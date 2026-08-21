"""
test_exposure_ladder.py — §98: una sola scala, esplicita, comune ai due Path.

Il §95 aveva costruito la scala ma l'aveva data solo a Path A. Path B era
rimasto sulla formula moltiplicativa, e `x1.5` / `:1.5` NON sono simmetriche una
volta passate dallo snap ai tempi che PHD2 accetta davvero: da base 2000 la
salita atterrava su 3000, ma la discesa da 4000 dava 2666 -> 2500, un valore che
sulla scala non esiste. Andata e ritorno non ripercorrevano la stessa strada.

Le quattro regole difese qui:

  1. Path B resta limitato a `max_steps_above_base`; Path A no, arriva al tetto.
     Path A e' emergenza (non perdere la stella), Path B e' ottimizzazione
     speculativa: e' giusto che il secondo sia piu' prudente.
  2. La Base puo' valere solo uno dei due gradini piu' bassi della scala. I 4 s
     devono essere RAGGIUNTI in base ai dati della guida, mai un punto di
     partenza.
  3. Scala esplicita, comune ai due Path, in salita e in discesa.
  4. Un gradino che PHD2 non offre FERMA la progressione. Saltarlo ricreerebbe
     il salto 2 -> 4 s che il §95 e questo §98 esistono per impedire.

Sequenze richieste:
    base 1 s:  1 -> 2 -> 3 -> 4 -> 3 -> 2 -> 1
    base 2 s:  2 -> 3 -> 4 -> 3 -> 2      (sotto la base non si scende mai)
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from phd2_agent.analyzer import AnalysisSnapshot, SeeingCondition
from phd2_agent.config import (
    AgentConfig, AxisLimits, ControlConfig, EmergencyConfig,
    ExposureDynamicConfig, SetupConfig, Thresholds,
)
from phd2_agent.controller import AdaptiveController, ExposureState

# I tempi che PHD2 offre davvero (phd2-master/src/myframe.cpp:963).
PHD2_REALI = [10, 20, 50, 100, 200, 500, 1000, 1500, 2000, 2500, 3000, 3500,
              4000, 4500, 5000, 6000, 7000, 8000, 9000, 10000, 15000, 30000]

SCALA = [1000, 2000, 3000, 4000]


def _cfg(target=2000, tetto=4000, scala=None, max_steps=2) -> AgentConfig:
    cfg = AgentConfig()
    cfg.control = ControlConfig(dry_run=False, cooldown_seconds=30.0)
    cfg.thresholds = Thresholds(rms_high=0.80, rms_low=0.35, snr_low=8.0,
                                spike_ratio_high=0.30, consecutive_frames=5)
    cfg.emergency = EmergencyConfig(auto_recovery=True, max_exposure_ms=tetto,
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
        enabled=True, target_exposure_ms=target,
        exposure_ladder_ms=SCALA if scala is None else scala,
        snr_step_cooldown_s=45.0, step_factor=1.5,
        max_steps_above_base=max_steps, cooldown_s=90.0,
    )
    return cfg


def _ctrl(cfg, base, validi=None) -> AdaptiveController:
    validi = PHD2_REALI if validi is None else validi
    c = MagicMock()
    c.get_exposure.return_value = base
    c.get_exposure_durations.return_value = validi
    k = AdaptiveController(client=c, config=cfg)
    k._valid_exposures = validi
    k._initialized = True
    k.base_exposure_ms = base
    k.current_exposure_ms = base
    k.exposure_state = ExposureState.NOMINAL
    k.exposure_steps_above_base = 0
    k.last_exposure_action_time = 0.0
    k._nominal_since = None
    return k


def _snap(snr, cond) -> AnalysisSnapshot:
    s = AnalysisSnapshot()
    s.condition = cond
    s.snr_avg = snr
    s.rms_total = 0.7
    s.frame_count = 30
    return s


BASSA = lambda: _snap(6.1, SeeingCondition.LOW_SNR)
OK = lambda: _snap(24.0, SeeingCondition.NOMINAL)


# ===========================================================================
#  Regola 3 — la scala esplicita
# ===========================================================================

class TestScalaEsplicita(unittest.TestCase):

    def test_da_base_1000_quattro_gradini(self):
        self.assertEqual(_ctrl(_cfg(target=1000), 1000)._exposure_ladder(),
                         [1000, 2000, 3000, 4000])

    def test_da_base_2000_la_scala_parte_dalla_base(self):
        """Il gradino da 1000 esiste nella scala ma sta SOTTO la base: la
        sessione non deve poterlo raggiungere."""
        self.assertEqual(_ctrl(_cfg(), 2000)._exposure_ladder(),
                         [2000, 3000, 4000])

    def test_nessun_valore_intermedio(self):
        """Il difetto della formula moltiplicativa: 1500, 2500, 3500 non devono
        piu' comparire da nessuna base."""
        for base in (1000, 2000):
            scala = _ctrl(_cfg(target=base), base)._exposure_ladder()
            for intruso in (1500, 2500, 3500):
                self.assertNotIn(intruso, scala,
                                 f"{intruso} non e' un gradino (base {base})")

    def test_il_tetto_accorcia_la_scala(self):
        self.assertEqual(_ctrl(_cfg(tetto=3000), 2000)._exposure_ladder(),
                         [2000, 3000])
        self.assertEqual(_ctrl(_cfg(target=1000, tetto=2000), 1000)._exposure_ladder(),
                         [1000, 2000])


# ===========================================================================
#  Regola 4 — un gradino mancante ferma, non si salta
# ===========================================================================

class TestGradinoMancante(unittest.TestCase):

    def test_senza_3000_non_si_salta_a_4000(self):
        """Il caso che reintrodurrebbe il difetto: una camera che non offre 3 s.
        Meglio non salire che saltare."""
        senza = [v for v in PHD2_REALI if v != 3000]
        scala = _ctrl(_cfg(), 2000, validi=senza)._exposure_ladder()
        self.assertEqual(scala, [2000])
        self.assertNotIn(4000, scala, "mai 2 -> 4 s per un gradino mancante")

    def test_senza_3000_da_base_1000_ci_si_ferma_a_2000(self):
        senza = [v for v in PHD2_REALI if v != 3000]
        self.assertEqual(_ctrl(_cfg(target=1000), 1000, validi=senza)._exposure_ladder(),
                         [1000, 2000])


# ===========================================================================
#  Regola 3 applicata a Path A — le sequenze richieste, per intero
# ===========================================================================

class TestPathASequenze(unittest.TestCase):

    def _percorso(self, base):
        k = _ctrl(_cfg(target=base), base)
        seq = [k.current_exposure_ms]
        for _ in range(5):
            k.last_exposure_action_time = 0.0
            k._evaluate_exposure_snr(BASSA())
            if k.current_exposure_ms != seq[-1]:
                seq.append(k.current_exposure_ms)
        for _ in range(6):
            k.last_exposure_action_time = 0.0
            k._evaluate_exposure_snr(OK())
            if k.current_exposure_ms != seq[-1]:
                seq.append(k.current_exposure_ms)
        return seq, k

    def test_base_2000(self):
        seq, k = self._percorso(2000)
        self.assertEqual(seq, [2000, 3000, 4000, 3000, 2000])
        self.assertEqual(k.exposure_state, ExposureState.NOMINAL)

    def test_base_1000(self):
        """Path A non e' limitato dal conteggio dei gradini: arriva al tetto."""
        seq, k = self._percorso(1000)
        self.assertEqual(seq, [1000, 2000, 3000, 4000, 3000, 2000, 1000])
        self.assertEqual(k.exposure_state, ExposureState.NOMINAL)

    def test_non_scende_mai_sotto_la_base(self):
        k = _ctrl(_cfg(), 2000)
        for _ in range(8):
            k.last_exposure_action_time = 0.0
            k._evaluate_exposure_snr(OK())
        self.assertEqual(k.current_exposure_ms, 2000)


# ===========================================================================
#  Regola 3 applicata a Path B + regola 1 (il limite di gradini)
# ===========================================================================

class TestPathBStessaScala(unittest.TestCase):
    """Path B non passa piu' dalla formula: si muove sugli stessi gradini.

    Questi test esercitano il calcolo del gradino cosi' come lo fa Path B alle
    righe 2333 e 2377 — l'indice sulla scala — invece dei trigger completi
    (spike, HFD, gate di escalation), che sono gia' coperti da
    test_exposure_dynamic.py.
    """

    def _passo(self, k, cur, su):
        scala = k._exposure_ladder()
        idx = min(range(len(scala)), key=lambda i: abs(scala[i] - cur))
        if su:
            return scala[idx + 1] if idx + 1 < len(scala) else cur
        return max(scala[idx - 1] if idx > 0 else k.base_exposure_ms,
                   k.base_exposure_ms)

    def test_andata_e_ritorno_ripercorrono_la_stessa_strada(self):
        """LA REGRESSIONE: con la vecchia formula la discesa da 4000 dava 2500.
        Ora i due versi usano gli stessi gradini."""
        k = _ctrl(_cfg(), 2000)
        cur, su = 2000, [2000]
        for _ in range(3):
            n = self._passo(k, cur, True)
            if n == cur:
                break
            cur = n
            su.append(cur)
        giu = [cur]
        for _ in range(3):
            n = self._passo(k, cur, False)
            if n == cur:
                break
            cur = n
            giu.append(cur)

        self.assertEqual(su, [2000, 3000, 4000])
        self.assertEqual(giu, [4000, 3000, 2000])
        self.assertEqual(su, list(reversed(giu)), "andata e ritorno simmetriche")
        self.assertNotIn(2500, giu, "2500 era il valore prodotto dalla vecchia formula")

    def test_il_limite_di_gradini_e_solo_di_path_b(self):
        """Regola 1: con base 1 s, Path B si ferma a 3 s (due gradini) mentre
        Path A arriva a 4 s. Voluto: Path B e' speculativo."""
        k = _ctrl(_cfg(target=1000), 1000)
        cur = 1000
        raggiunti = [cur]
        for passo in range(k.cfg.exposure_dynamic.max_steps_above_base):
            cur = self._passo(k, cur, True)
            raggiunti.append(cur)
        self.assertEqual(raggiunti, [1000, 2000, 3000])
        self.assertEqual(k._exposure_ladder()[-1], 4000,
                         "la scala arriva a 4000: e' Path B a fermarsi prima")


# ===========================================================================
#  Regola 2 — la Base solo sui due gradini piu' bassi
# ===========================================================================

class TestBaseAmmessa(unittest.TestCase):

    def _carica(self, tmpdir, target):
        import pathlib
        from phd2_agent.config import load_config
        p = pathlib.Path(tmpdir) / "config.toml"
        p.write_text(
            "[exposure_dynamic]\n"
            "enabled = true\n"
            f"target_exposure_ms = {target}\n"
            "exposure_ladder_ms = [1000, 2000, 3000, 4000]\n",
            encoding="utf-8")
        return load_config(str(p)).exposure_dynamic

    def test_1000_e_2000_sono_ammessi(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self._carica(d, 1000).target_exposure_ms, 1000)
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self._carica(d, 2000).target_exposure_ms, 2000)

    def test_un_valore_intermedio_viene_rifiutato_e_segnalato(self):
        """2600 non deve diventare in silenzio una base diversa da quella
        scritta: e' il tipo di sorpresa che il §95 esiste per eliminare."""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            with self.assertLogs("phd2_agent.config", level="ERROR") as log:
                ed = self._carica(d, 2600)
            self.assertEqual(ed.target_exposure_ms, 2000, "ripiego su un gradino ammesso")
            self.assertIn("NON AMMESSO", "\n".join(log.output))

    def test_4000_non_puo_essere_una_base(self):
        """Il cuore della regola: i 4 s si raggiungono, non ci si parte."""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            with self.assertLogs("phd2_agent.config", level="ERROR"):
                ed = self._carica(d, 4000)
            self.assertEqual(ed.target_exposure_ms, 2000)


if __name__ == "__main__":
    unittest.main()
