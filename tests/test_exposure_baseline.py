"""
test_exposure_baseline.py — §95: la Base dell'esposizione si dichiara, non si eredita.

Origine, ricostruita dai log riga per riga.

  16/08 03:04  la stella di guida collassa, SNR 6.1 < 8. Path A alza l'esposizione
               2000 -> 4000 ms (salto unico, `base * 2`).
  16/08 03:0x  la sessione si interrompe di colpo. Quattro tentativi di ripristino
               trovano PHD2 gia' chiuso: il valore resta 4000 ms nel profilo.
  17/08 22:51  nuova sessione. La baseline orfana viene trovata ma scartata
               ("vecchia di 48.2 ore - skip restore"), e `base = get_exposure()`
               adotta i 4000 ms residui come riferimento della notte.
  17-18/08     con base 4000 e tetto 4000 l'Exposure Controller non puo' salire
               (e' al tetto) ne' scendere (il pavimento della discesa E' la base).
               Quattro ore, zero interventi sull'esposizione.

Il difetto non e' "4 secondi": e' che nessuno aveva scelto 4 secondi, e che una
volta li' il controller non aveva piu' gradi di liberta'. Questi test difendono
due invarianti distinte:

  1. la Base della sessione e' il valore DICHIARATO in configurazione, mai il
     residuo trovato in PHD2, mai quello scritto in un file di baseline;
  2. si sale e si scende a gradini — e 4000 ms resta raggiungibile in due passi,
     perche' non e' ancora dimostrato che 2/2.5 s guidino meglio di 4 s.
"""
from __future__ import annotations

import json
import pathlib
import tempfile
import time
import unittest
from unittest.mock import MagicMock

from phd2_agent.analyzer import AnalysisSnapshot, SeeingCondition
from phd2_agent.config import (
    AgentConfig, AxisLimits, ControlConfig, EmergencyConfig,
    ExposureDynamicConfig, SetupConfig, Thresholds, load_config,
)
from phd2_agent.controller import AdaptiveController, ExposureState


# Le esposizioni che PHD2 offre davvero sul setup di riferimento.
VALIDE = [500, 1000, 1500, 2000, 2500, 3000, 3500, 4000, 5000, 6000]


def _cfg(target_ms: int | None = 2000, cap_ms: int = 4000) -> AgentConfig:
    cfg = AgentConfig()
    cfg.control = ControlConfig(dry_run=False, cooldown_seconds=30.0)
    cfg.thresholds = Thresholds(rms_high=0.80, rms_low=0.35, snr_low=8.0,
                                spike_ratio_high=0.30, consecutive_frames=5)
    # Il tetto vero del rig: e' cio' che ha reso il salto `base * 2` definitivo.
    cfg.emergency = EmergencyConfig(auto_recovery=True, max_exposure_ms=cap_ms,
                                    find_star_delay=10, saturation_timeout_s=300)
    cfg.ra = AxisLimits(aggr_min=35, aggr_max=75, aggr_step_down=5, aggr_step_up=2,
                        minmove_min=0.15, minmove_max=0.80, minmove_step=0.05)
    cfg.dec = AxisLimits(aggr_min=30, aggr_max=70, aggr_step_down=5, aggr_step_up=2,
                         minmove_min=0.20, minmove_max=0.85, minmove_step=0.05)
    cfg.setup = SetupConfig(profile_name="rc8",
                            guide_pixel_scale_arcsec_native=0.508,
                            guide_pixel_scale_arcsec_reduced=0.68,
                            reducer_active=False)
    cfg.exposure_dynamic = ExposureDynamicConfig(
        enabled=True, target_exposure_ms=target_ms, snr_step_cooldown_s=45.0,
        step_factor=1.5, max_steps_above_base=2, cooldown_s=90.0,
    )
    return cfg


def _client(esposizione_in_phd2: int = 2000) -> MagicMock:
    c = MagicMock()
    c.get_exposure.return_value = esposizione_in_phd2
    c.get_exposure_durations.return_value = VALIDE
    return c


def _ctrl(cfg: AgentConfig, client: MagicMock) -> AdaptiveController:
    ctrl = AdaptiveController(client=client, config=cfg)
    ctrl._valid_exposures = VALIDE
    ctrl._initialized = True
    return ctrl


def _snap(snr: float, condition: SeeingCondition) -> AnalysisSnapshot:
    s = AnalysisSnapshot()
    s.condition = condition
    s.snr_avg = snr
    s.rms_total = 0.7
    s.frame_count = 30
    return s


_SNR_BASSA = lambda: _snap(6.1, SeeingCondition.LOW_SNR)      # il valore del 16/8
_SNR_OK = lambda: _snap(24.0, SeeingCondition.NOMINAL)


# ===========================================================================
#  1. La Base e' dichiarata
# ===========================================================================

class TestBaseDichiarata(unittest.TestCase):

    def test_il_residuo_di_phd2_non_diventa_la_base(self):
        """Il caso del 17/08: PHD2 aperto con 4000 ms lasciati li' dalla notte
        prima. Prima l'Agente li adottava; ora li corregge."""
        c = _client(esposizione_in_phd2=4000)
        ctrl = _ctrl(_cfg(target_ms=2000), c)

        ctrl._reconcile_base_exposure(full=True)

        self.assertEqual(ctrl.base_exposure_ms, 2000,
                         "la base e' il riferimento dichiarato, non cio' che si trova")
        self.assertEqual(ctrl.current_exposure_ms, 2000)
        c.set_exposure.assert_called_once_with(2000)

    def test_phd2_gia_allineato_nessun_comando_inutile(self):
        c = _client(esposizione_in_phd2=2000)
        ctrl = _ctrl(_cfg(target_ms=2000), c)

        ctrl._reconcile_base_exposure(full=True)

        self.assertEqual(ctrl.base_exposure_ms, 2000)
        c.set_exposure.assert_not_called()

    def test_il_riaggancio_non_rinegozia_la_base(self):
        """La notte 17-18/8 ha visto 11 initialize(). Se la base si ricontratta a
        ogni ripartenza della guida, un gradino conquistato diventa il nuovo
        pavimento e la discesa non torna piu' a 2 s."""
        c = _client(esposizione_in_phd2=3000)      # siamo su un gradino
        ctrl = _ctrl(_cfg(target_ms=2000), c)
        ctrl.base_exposure_ms = 2000
        ctrl.current_exposure_ms = 3000

        ctrl._reconcile_base_exposure(full=False)

        self.assertEqual(ctrl.base_exposure_ms, 2000, "la base di sessione non si tocca")
        self.assertEqual(ctrl.current_exposure_ms, 3000, "ma si prende atto del gradino")
        c.set_exposure.assert_not_called()

    def test_senza_target_resta_il_comportamento_storico(self):
        """Chi non vuole che l'Agente tocchi l'esposizione toglie la riga e
        ritrova esattamente il comportamento di prima."""
        c = _client(esposizione_in_phd2=4000)
        ctrl = _ctrl(_cfg(target_ms=None), c)

        ctrl._reconcile_base_exposure(full=True)

        self.assertEqual(ctrl.base_exposure_ms, 4000)
        c.set_exposure.assert_not_called()

    def test_una_base_non_ammessa_viene_rifiutata_senza_degradare(self):
        """§98 — 2600 ms non e' un gradino della scala, e la Base puo' valere solo
        uno dei due piu' bassi: i 4 s si raggiungono, non ci si parte.

        Prima questo test documentava lo snap al tempo PHD2 piu' vicino (2500).
        Non e' piu' la regola, e soprattutto 2500 era proprio uno di quei valori
        intermedi che la scala esplicita elimina. Qui si segue la catena vera —
        TOML, loader, controller, scala — perche' il punto non e' solo che il
        valore venga corretto, ma che a valle non resti **nessuna degradazione
        silenziosa**: con una base fuori scala la progressione ricadrebbe sul
        vecchio passo moltiplicativo e i gradini intermedi tornerebbero.
        """
        with tempfile.TemporaryDirectory() as d:
            toml = pathlib.Path(d) / "config.toml"
            toml.write_text(
                "[exposure_dynamic]\n"
                "enabled = true\n"
                "target_exposure_ms = 2600\n"
                "exposure_ladder_ms = [1000, 2000, 3000, 4000]\n",
                encoding="utf-8")

            # 1) il rifiuto e' esplicito, non silenzioso
            with self.assertLogs("phd2_agent.config", level="ERROR") as log:
                cfg = load_config(str(toml))
            self.assertIn("NON AMMESSO", "\n".join(log.output))
            self.assertEqual(cfg.exposure_dynamic.target_exposure_ms, 2000,
                             "ripiego su un gradino ammesso, non su 2500")

            # 2) a valle non resta traccia del valore non ammesso
            c = _client(esposizione_in_phd2=1000)
            ctrl = _ctrl(cfg, c)
            ctrl._reconcile_base_exposure(full=True)

            self.assertEqual(ctrl.base_exposure_ms, 2000)
            scala = ctrl._exposure_ladder()
            self.assertEqual(scala, [2000, 3000, 4000])
            for intruso in (2500, 3500):
                self.assertNotIn(intruso, scala,
                                 "un gradino intermedio qui significa che la "
                                 "progressione e' tornata al passo moltiplicativo")

    def test_target_oltre_il_tetto_viene_limitato(self):
        c = _client(esposizione_in_phd2=1000)
        ctrl = _ctrl(_cfg(target_ms=6000, cap_ms=4000), c)

        ctrl._reconcile_base_exposure(full=True)

        self.assertLessEqual(ctrl.base_exposure_ms, 4000)

    def test_se_phd2_rifiuta_il_comando_la_base_resta_dichiarata(self):
        """La base e' un riferimento, non una misura: se il comando fallisce lo
        dice il log, ma l'Agente non torna a ragionare sul valore residuo."""
        c = _client(esposizione_in_phd2=4000)
        c.set_exposure.side_effect = RuntimeError("PHD2 non risponde")
        ctrl = _ctrl(_cfg(target_ms=2000), c)

        ctrl._reconcile_base_exposure(full=True)

        self.assertEqual(ctrl.base_exposure_ms, 2000)

    def test_baseline_salvata_non_reintroduce_il_valore_ereditato(self):
        """Terzo vettore di eredita': il file di baseline del 16/8 contiene
        base_exposure_ms=4000, perche' era la base in cui l'Agente credeva."""
        c = _client(esposizione_in_phd2=4000)
        ctrl = _ctrl(_cfg(target_ms=2000), c)
        ctrl.base_exposure_ms = 2000

        with tempfile.TemporaryDirectory() as d:
            ctrl.baseline_path = pathlib.Path(d) / "baseline.json"
            ctrl.baseline_path.write_text(json.dumps({
                "version": 3, "setup_id": ctrl._baseline_setup_id, "saved_at": time.time(),
                "base_exposure_ms": 4000, "current_exposure_ms": 4000,
                "exposure_state": "BOOSTED_FOR_SNR", "exposure_steps_above_base": 0,
                "ra": {}, "dec": {},
            }), encoding="utf-8")
            ctrl.restore_baseline(source="orphan_recovery")

        self.assertEqual(ctrl.base_exposure_ms, 2000)
        self.assertEqual(ctrl.current_exposure_ms, 2000)
        c.set_exposure.assert_called_with(2000)


# ===========================================================================
#  2. Path A sale e scende a gradini
# ===========================================================================

class TestPathAProgressiva(unittest.TestCase):

    def _pronto(self, target=2000, cap=4000, corrente=None,
                stato=ExposureState.NOMINAL):
        ctrl = _ctrl(_cfg(target_ms=target, cap_ms=cap), _client(target))
        ctrl.base_exposure_ms = target
        ctrl.current_exposure_ms = corrente if corrente is not None else target
        ctrl.exposure_state = stato
        ctrl.exposure_steps_above_base = 0
        ctrl.last_exposure_action_time = 0.0    # cooldown scaduto
        ctrl._nominal_since = None
        return ctrl

    def test_un_solo_gradino_non_il_salto_al_tetto(self):
        """Il cuore della correzione: 2000 -> 3000, non 2000 -> 4000."""
        ctrl = self._pronto()

        azioni = ctrl._evaluate_exposure_snr(_SNR_BASSA())

        self.assertEqual(len(azioni), 1)
        self.assertEqual(ctrl.current_exposure_ms, 3000)
        self.assertEqual(ctrl.exposure_state, ExposureState.BOOSTED_FOR_SNR)

    def test_quattro_secondi_restano_raggiungibili(self):
        """Nessuna regola qui penalizza le pose lunghe: se la SNR resta bassa,
        il secondo gradino porta a 4000 ms. Cambia la strada, non la meta."""
        ctrl = self._pronto()
        ctrl._evaluate_exposure_snr(_SNR_BASSA())
        ctrl.last_exposure_action_time = 0.0        # passa il cooldown

        ctrl._evaluate_exposure_snr(_SNR_BASSA())

        self.assertEqual(ctrl.current_exposure_ms, 4000)
        self.assertEqual(ctrl.exposure_state, ExposureState.BOOSTED_FOR_SNR)

    def test_il_cooldown_impedisce_due_gradini_di_fila(self):
        """Il cambio di posa azzera analyzer e motore diagnostico: il gradino
        successivo va deciso su dati nuovi, non sul transitorio."""
        ctrl = self._pronto()
        ctrl._evaluate_exposure_snr(_SNR_BASSA())
        primo = ctrl.current_exposure_ms

        azioni = ctrl._evaluate_exposure_snr(_SNR_BASSA())   # subito dopo

        self.assertEqual(azioni, [])
        self.assertEqual(ctrl.current_exposure_ms, primo)

    def test_al_tetto_nessuna_azione_e_lo_stato_resta_boosted(self):
        """Serve che resti BOOSTED: e' da li' che parte la discesa."""
        ctrl = self._pronto(corrente=4000, stato=ExposureState.BOOSTED_FOR_SNR)

        azioni = ctrl._evaluate_exposure_snr(_SNR_BASSA())

        self.assertEqual(azioni, [])
        self.assertEqual(ctrl.current_exposure_ms, 4000)
        self.assertEqual(ctrl.exposure_state, ExposureState.BOOSTED_FOR_SNR)

    def test_la_discesa_e_simmetrica(self):
        """4000 -> 3000 -> 2000, non un tuffo unico."""
        ctrl = self._pronto(corrente=4000, stato=ExposureState.BOOSTED_FOR_SNR)

        ctrl._evaluate_exposure_snr(_SNR_OK())
        self.assertEqual(ctrl.current_exposure_ms, 3000)
        self.assertEqual(ctrl.exposure_state, ExposureState.BOOSTED_FOR_SNR,
                         "a meta' strada la discesa non e' finita")

        ctrl.last_exposure_action_time = 0.0
        ctrl._evaluate_exposure_snr(_SNR_OK())
        self.assertEqual(ctrl.current_exposure_ms, 2000)
        self.assertEqual(ctrl.exposure_state, ExposureState.NOMINAL)

    def test_la_discesa_non_scende_mai_sotto_la_base(self):
        ctrl = self._pronto(corrente=3000, stato=ExposureState.BOOSTED_FOR_SNR)

        for _ in range(6):
            ctrl.last_exposure_action_time = 0.0
            ctrl._evaluate_exposure_snr(_SNR_OK())

        self.assertEqual(ctrl.current_exposure_ms, 2000)
        self.assertEqual(ctrl.exposure_state, ExposureState.NOMINAL)

    def test_stato_boosted_ma_gia_alla_base_si_richiude_da_solo(self):
        """Difesa contro lo stato incoerente: BOOSTED senza esposizione sopra la
        base bloccherebbe Path B, che gira solo quando Path A non e' attivo."""
        ctrl = self._pronto(corrente=2000, stato=ExposureState.BOOSTED_FOR_SNR)

        ctrl._evaluate_exposure_snr(_SNR_OK())

        self.assertEqual(ctrl.exposure_state, ExposureState.NOMINAL)


# ===========================================================================
#  3. Lo scenario completo, come si e' svolto davvero
# ===========================================================================

class TestScenarioNotte17(unittest.TestCase):

    def test_con_la_base_dichiarata_il_controller_non_si_paralizza(self):
        """Riproduzione della notte 17-18/8: PHD2 aperto a 4000 ms, tetto 4000.

        Prima: base = 4000 = tetto, il controller non poteva ne' salire ne'
        scendere. Ora la base torna a 2000 e restano due gradini di margine
        sopra e nessun pavimento sotto i piedi."""
        c = _client(esposizione_in_phd2=4000)
        ctrl = _ctrl(_cfg(target_ms=2000, cap_ms=4000), c)

        ctrl._reconcile_base_exposure(full=True)
        self.assertEqual(ctrl.base_exposure_ms, 2000)

        ctrl.last_exposure_action_time = 0.0
        salita = []
        for _ in range(4):
            ctrl._evaluate_exposure_snr(_SNR_BASSA())
            ctrl.last_exposure_action_time = 0.0
            salita.append(ctrl.current_exposure_ms)

        self.assertEqual(salita[:2], [3000, 4000],
                         "due gradini fino al tetto, uno per volta")
        self.assertEqual(salita[-1], 4000, "e poi si ferma al tetto")

        discesa = []
        for _ in range(4):
            ctrl._evaluate_exposure_snr(_SNR_OK())
            ctrl.last_exposure_action_time = 0.0
            discesa.append(ctrl.current_exposure_ms)

        self.assertEqual(discesa[:2], [3000, 2000], "e si torna giu' allo stesso modo")
        self.assertEqual(ctrl.exposure_state, ExposureState.NOMINAL)


if __name__ == "__main__":
    unittest.main()
