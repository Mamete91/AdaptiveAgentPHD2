"""
test_anello_aperto.py — §108, l'Agente durante una misura del Guiding Assistant.

Il flusso reale: NINA accende l'Agente all'avvio, PHD2 parte in parallelo, e il
Guiding Assistant lo si lancia DOPO. Cioe' esattamente il caso in cui l'Agente e'
gia' in funzione mentre PHD2 sospende l'uscita di guida.

Due danni, entrambi silenziosi:

  1. ad anello aperto la stella non viene corretta, quindi l'RMS che arriva e' il
     moto NON corretto — diversi arcosecondi. Ingerirlo avvelena la baseline di
     sessione (60 frame; una misura GA ne dura 120-150), il cap MinMove §51 che ne
     discende e la diagnosi. E il controller lo legge come degrado: ammorbidisce le
     leve o alza la posa NEL MEZZO della misura, falsando la caratterizzazione che
     si sta aspettando — il GA costruisce i propri filtri sulla posa d'avvio;
  2. la caratterizzazione appena conclusa non veniva mai vista, perche' §104 la
     leggeva solo al primo avvio del processo.

PHD2 annuncia entrambi i confini da solo: `GuideParamChange` con
`Name=MountGuidingEnabled` (event_server.cpp:3022).
"""
from __future__ import annotations

import datetime as dt
import unittest
from unittest.mock import MagicMock

from phd2_agent import ga_baseline as gb
from phd2_agent.config import (AgentConfig, AxisLimits, BandaNominaleConfig,
                               ControlConfig, GABaselineConfig, SetupConfig)
from phd2_agent.controller import AdaptiveController


def _export(ts: str, ra: float, dec: float, posa_s: int = 2) -> str:
    return "\n".join([
        "PHD Config 1",
        "/profile/2/name\t1\tCEM70 RC8",
        f"/profile/2/GA/{ts}/timestamp\t1\t{ts}",
        f"/profile/2/GA/{ts}/snr\t1\t64.9",
        f"/profile/2/GA/{ts}/exposure_time\t1\t{posa_s}s",
        f"/profile/2/GA/{ts}/elapsed_time\t1\t256s",
        f"/profile/2/GA/{ts}/sample_count\t1\t99",
        f"/profile/2/GA/{ts}/rec_ra_minmove\t1\t{ra:.6f}",
        f"/profile/2/GA/{ts}/rec_dec_minmove\t1\t{dec:.6f}",
        "/profile/2/scope/BacklashCompEnabled\t3\t1",
        "/profile/2/scope/DecBacklashPulse\t3\t130",
        "/profile/2/scope/DecBacklashCeiling\t3\t195",
    ])


def _ctrl(tmpfile) -> AdaptiveController:
    cfg = AgentConfig()
    cfg.control = ControlConfig(dry_run=True)
    ax = dict(aggr_min=35, aggr_max=100, aggr_step_down=5, aggr_step_up=2,
              minmove_min=0.15, minmove_max=1.20, minmove_step=0.05)
    cfg.ra = AxisLimits(**ax)
    cfg.dec = AxisLimits(**ax)
    cfg.setup = SetupConfig(profile_name="t", guide_pixel_scale_arcsec_native=0.508)
    cfg.banda = BandaNominaleConfig(enabled=True, minmove_px=0.20, aggr_punti=20.0)
    cfg.ga_baseline = GABaselineConfig()
    client = MagicMock()
    client.get_profile.return_value = {"id": 2, "name": "CEM70 RC8"}
    client.export_config_settings.return_value = str(tmpfile)
    c = AdaptiveController(client=client, config=cfg)
    c._initialized = True
    c.base_exposure_ms = 2000
    for a, aggr in ((c._ra, 70.0), (c._dec, 100.0)):   # default PHD2 per algoritmo
        a.aggr_param = "aggression"
        a.aggr_native_scale = 0.01
        a.minmove_param = "minMove"
        a.current_aggr = aggr
        a.current_minmove = 0.20
    return c


class TestRilettura(unittest.TestCase):
    """§108 — una caratterizzazione conclusa a sessione in corso va adottata."""

    def setUp(self):
        import tempfile
        import pathlib
        self.f = pathlib.Path(tempfile.mkdtemp()) / "phd2_settings.txt"
        self.f.write_text(_export("2026-06-12 22:33:35", 0.50, 0.70), encoding="utf-8")
        self.c = _ctrl(self.f)
        self.c._resolve_nominal()

    def test_parte_dalla_caratterizzazione_esistente(self):
        self.assertEqual(self.c._baseline.sorgente, "guide_assistant")
        self.assertAlmostEqual(self.c._nominal["ra"][1], 0.50)

    def test_nessuna_novita_non_cambia_nulla(self):
        self.assertFalse(self.c.ricontrolla_baseline_ga())
        self.assertAlmostEqual(self.c._nominal["ra"][1], 0.50)

    def test_caratterizzazione_nuova_viene_adottata(self):
        self.f.write_text(_export("2026-08-24 00:28:30", 0.6175, 0.95), encoding="utf-8")
        self.assertTrue(self.c.ricontrolla_baseline_ga())
        self.assertAlmostEqual(self.c._nominal["ra"][1], 0.6175)
        self.assertAlmostEqual(self.c._nominal["dec"][1], 0.95)

    def test_il_recinto_non_taglia_l_adozione(self):
        """Il valore nuovo dista 0.45 dal vecchio nominale: col recinto vecchio
        (+/-0.20) verrebbe limitato. L'ordine — nominale prima, scrittura poi — e'
        cio' che lo impedisce."""
        self.f.write_text(_export("2026-08-24 00:28:30", 0.95, 0.95), encoding="utf-8")
        self.c.ricontrolla_baseline_ga()
        self.assertAlmostEqual(self.c._ra.current_minmove, 0.95)

    def test_i_contatori_del_recupero_si_azzerano(self):
        """Le leve sono appena saltate: le finestre che le seguivano non descrivono
        piu' questo regime."""
        self.c._recovery_consec = 7
        self.c._recovery_anchor_rms = 0.9
        self.f.write_text(_export("2026-08-24 00:28:30", 0.6175, 0.95), encoding="utf-8")
        self.c.ricontrolla_baseline_ga()
        self.assertEqual(self.c._recovery_consec, 0)
        self.assertIsNone(self.c._recovery_anchor_rms)

    def test_caratterizzazione_a_posa_diversa_viene_adottata_lo_stesso(self):
        """§118 — PHD2 non scarta per posa diversa, e nemmeno noi. Verificato sulla
        sorgente: la posa del GA e' salvata solo per essere mostrata a schermo."""
        self.f.write_text(_export("2026-08-24 00:28:30", 0.6175, 0.95, posa_s=1),
                          encoding="utf-8")
        self.assertTrue(self.c.ricontrolla_baseline_ga())
        self.assertEqual(self.c._baseline.sorgente, "guide_assistant")
        self.assertAlmostEqual(self.c._nominal["ra"][1], 0.6175)

    def test_lettura_fallita_non_solleva(self):
        self.c.client.export_config_settings.side_effect = RuntimeError("PHD2 giu'")
        self.assertFalse(self.c.ricontrolla_baseline_ga())


class TestRisincronizzazione(unittest.TestCase):
    """Se l'operatore preme Applica mentre l'Agente gira, PHD2 cambia sotto i suoi
    piedi: senza risincronizzazione il delta della modifica dopo sarebbe falso."""

    def setUp(self):
        import tempfile
        import pathlib
        f = pathlib.Path(tempfile.mkdtemp()) / "s.txt"
        f.write_text(_export("2026-08-24 00:28:30", 0.6175, 0.95), encoding="utf-8")
        self.c = _ctrl(f)

    def test_allinea_il_minmove_cambiato_da_fuori(self):
        self.c.client.probe_algo_params.return_value = {
            "ra": {"minMove": 0.62, "aggression": 0.70},
            "dec": {"minMove": 0.95, "aggression": 1.00}}
        self.assertTrue(self.c.risincronizza_leve())
        self.assertAlmostEqual(self.c._ra.current_minmove, 0.62)
        self.assertAlmostEqual(self.c._dec.current_minmove, 0.95)

    def test_allinea_l_aggressivita_riportandola_in_scala(self):
        self.c.client.probe_algo_params.return_value = {
            "ra": {"minMove": 0.20, "aggression": 0.55},   # nativa 0-1
            "dec": {"minMove": 0.20, "aggression": 1.00}}
        self.assertTrue(self.c.risincronizza_leve())
        self.assertAlmostEqual(self.c._ra.current_aggr, 55.0)

    def test_nessuna_differenza_nessun_cambiamento(self):
        self.c.client.probe_algo_params.return_value = {
            "ra": {"minMove": 0.20, "aggression": 0.70},
            "dec": {"minMove": 0.20, "aggression": 1.00}}
        self.assertFalse(self.c.risincronizza_leve())

    def test_errore_di_lettura_non_solleva(self):
        self.c.client.probe_algo_params.side_effect = RuntimeError("giu'")
        self.assertFalse(self.c.risincronizza_leve())


class TestStatoIniziale(unittest.TestCase):

    def test_di_default_l_anello_e_chiuso(self):
        import tempfile
        import pathlib
        f = pathlib.Path(tempfile.mkdtemp()) / "s.txt"
        f.write_text(_export("2026-08-24 00:28:30", 0.6175, 0.95), encoding="utf-8")
        c = _ctrl(f)
        self.assertIs(c.anello_aperto, False,
                      "deve essere un bool VERO: su un MagicMock un attributo non "
                      "definito e' truthy e bloccherebbe ogni frame")

    def test_lo_stato_e_su_status(self):
        import tempfile
        import pathlib
        f = pathlib.Path(tempfile.mkdtemp()) / "s.txt"
        f.write_text(_export("2026-08-24 00:28:30", 0.6175, 0.95), encoding="utf-8")
        c = _ctrl(f)
        c.anello_aperto = True
        self.assertTrue(c.get_status()["anello_aperto"])


class TestCausaResetPreserva(unittest.TestCase):
    """L'anello aperto non tocca l'atmosfera: i riferimenti di calma restano."""

    def test_anello_aperto_preserva_i_riferimenti(self):
        from phd2_agent import diagnostic_engine as de
        self.assertIn("anello_aperto", de._PRESERVE_CAUSES)



class TestCoperturaCompleta(unittest.TestCase):
    """Ad anello aperto NESSUN percorso deve arrivare ad agire su PHD2.

    Verifica di COMPORTAMENTO, non di testo: il loop viene fatto girare davvero con
    l'anello aperto e si controlla che ingest e evaluate non vengano mai chiamati.
    Il giro di controllo aveva trovato un percorso scoperto — il timer di saturazione
    chiama `evaluate` a intervalli, fuori dai rami GuideStep/StarLost, e da li' si
    arriva a cambiare la posa o a riselezionare la stella: proprio le due cose che
    falserebbero la misura del Guiding Assistant.
    """

    def _giro(self, sospeso: bool, evento: dict, *, calibrazione: bool = False):
        import queue
        import threading
        from unittest.mock import patch
        from types import SimpleNamespace
        from main import _event_loop
        from tests.test_event_loop_wiring import _snapshot

        stop = threading.Event()
        client = MagicMock()
        client.event_queue = queue.Queue()
        client.event_queue.put(evento)
        client.connected = True

        snap = _snapshot()
        analyzer = MagicMock()
        analyzer.is_ready = True
        analyzer.ingest_guide_step.return_value = snap
        analyzer.ingest_star_lost.return_value = snap
        analyzer.last_snapshot = snap

        controller = MagicMock()
        controller.cfg = SimpleNamespace(
            setup=SimpleNamespace(guide_pixel_scale_arcsec=1.0),
            analyzer=SimpleNamespace(convert_distance_to_arcsec=True))
        controller.saturated_lock_since = None
        controller.evaluate.return_value = []
        controller._current_diag = None
        # Coerenti fra loro, come sul controller vero: `sospeso` e' la proprieta'
        # che i gate leggono, e su un MagicMock va impostata ESPLICITAMENTE —
        # altrimenti e' truthy e scarta ogni frame (ci sono cascato scrivendo
        # questo stesso test).
        controller.anello_aperto = sospeso and not calibrazione
        controller.in_calibrazione = calibrazione
        controller.sospeso = sospeso

        logger = MagicMock()
        # con l'anello aperto non si logga: il timer ferma comunque il giro
        threading.Timer(0.4, stop.set).start()
        logger.log_snapshot.side_effect = lambda *a, **k: stop.set()

        with patch("server.sync_broadcast", lambda msg: None):
            _event_loop(client=client, analyzer=analyzer, controller=controller,
                        session_logger=logger, stop_event=stop, eval_interval=0.0,
                        monitor_only=False, recovery_hint_tracker=MagicMock())
        return controller, logger

    def test_guide_step_ad_anello_aperto_non_agisce(self):
        from tests.test_event_loop_wiring import _guide_step
        c, lg = self._giro(True, _guide_step())
        c.ingest_frame.assert_not_called()
        c.evaluate.assert_not_called()
        lg.log_snapshot.assert_not_called()

    def test_guide_step_ad_anello_chiuso_agisce(self):
        """Controprova: senza la sospensione il giro fa tutto il suo lavoro."""
        from tests.test_event_loop_wiring import _guide_step
        c, lg = self._giro(False, _guide_step())
        c.ingest_frame.assert_called_once()
        c.evaluate.assert_called_once()
        lg.log_snapshot.assert_called_once()

    def test_star_lost_in_calibrazione_non_valuta(self):
        """§109 — il caso della notte 23-24/8: `StarLost` arriva anche durante la
        calibrazione (guider.cpp:1337) e portava a `find_star`, che lato PHD2 non ha
        guardia di stato e sposterebbe la lock position nel mezzo della misura."""
        c, _ = self._giro(True, {"Event": "StarLost", "Status": "low SNR"},
                          calibrazione=True)
        c.evaluate.assert_not_called()

    def test_guide_step_in_calibrazione_non_ingerisce(self):
        from tests.test_event_loop_wiring import _guide_step
        c, _ = self._giro(True, _guide_step(), calibrazione=True)
        c.ingest_frame.assert_not_called()

    def test_star_lost_ad_anello_aperto_non_valuta(self):
        """`evaluate` da qui puo' chiamare find_star, che riselezionerebbe la
        stella nel mezzo della misura."""
        c, _ = self._giro(True, {"Event": "StarLost", "Status": "low SNR"})
        c.evaluate.assert_not_called()

    def test_rilettura_prima_dell_init_non_fa_nulla(self):
        import tempfile
        import pathlib
        f = pathlib.Path(tempfile.mkdtemp()) / "s.txt"
        f.write_text(_export("2026-08-24 00:28:30", 0.6175, 0.95), encoding="utf-8")
        c = _ctrl(f)
        c._initialized = False
        self.assertFalse(c.ricontrolla_baseline_ga())



class TestStatoDiPHD2(unittest.TestCase):
    """§110 — l'Agente agisce solo quando PHD2 sta davvero guidando.

    E' una condizione POSITIVA, non una lista di eccezioni: copre anche gli stati
    che non abbiamo enumerato (Manual Guide, Star Cross, strumenti futuri) senza
    doverli rincorrere uno per uno.
    """

    def _c(self):
        import tempfile
        import pathlib
        f = pathlib.Path(tempfile.mkdtemp()) / "s.txt"
        f.write_text(_export("2026-08-24 00:28:30", 0.6175, 0.95), encoding="utf-8")
        return _ctrl(f)

    def test_guiding_non_sospende(self):
        c = self._c()
        c.app_state = "Guiding"
        self.assertFalse(c.sospeso)

    def test_lostlock_non_sospende(self):
        """PHD2 sta guidando e ha perso la stella: e' una condizione di guida, non
        un'altra attivita'. L'Agente deve poter reagire."""
        c = self._c()
        c.app_state = "LostLock"
        self.assertFalse(c.sospeso)

    def test_gli_altri_stati_sospendono(self):
        c = self._c()
        for stato in ("Stopped", "Selected", "Calibrating", "Paused", "Looping"):
            with self.subTest(stato=stato):
                c.app_state = stato
                self.assertTrue(c.sospeso, stato)

    def test_stato_sconosciuto_non_sospende(self):
        """`None` significa "non l'abbiamo ancora ricevuto". Non si sospende su
        un'ignoranza: si sospende su un fatto."""
        c = self._c()
        c.app_state = None
        self.assertFalse(c.sospeso)

    def test_uno_stato_futuro_sospende(self):
        """Il valore della condizione positiva: uno stato che oggi non esiste
        sospende comunque, senza che nessuno debba prevederlo."""
        c = self._c()
        c.app_state = "QualcosaCheNonEsisteAncora"
        self.assertTrue(c.sospeso)

    def test_anello_aperto_prevale_su_guiding(self):
        """Durante il Guiding Assistant PHD2 resta in "Guiding": e' l'uscita
        sospesa a fare la differenza."""
        c = self._c()
        c.app_state = "Guiding"
        c.anello_aperto = True
        self.assertTrue(c.sospeso)

if __name__ == "__main__":
    unittest.main()


# ===========================================================================
#  §114 — dopo un GA a sessione avviata, anche la posa segue la misura
# ===========================================================================

def _export_con_deriva(ts: str, ra: float, dec: float, posa_s: int = 2) -> str:
    """Come `_export`, ma con i campi numerici da cui si ricava l'intervallo.

    deriva di picco 0.35 px/s, rms passa-alto 0.45 px:
        drift_exp = ceil((0.45/0.35)/0.5)*0.5 = 1.5  ->  intervallo 1.5-3.5 s
        limite-deriva = MinMove/0.35            ->  con 0.6175 = 1.76 s
    Il gradino piu' vicino al limite dentro l'intervallo e' 2000 ms.
    """
    return _export(ts, ra, dec, posa_s) + "\n" + "\n".join([
        f"/profile/2/GA/{ts}/ra_peak_drift_rate\t1\t0.350000 px/s",
        f"/profile/2/GA/{ts}/ra_hpf_rms\t1\t0.450000 px",
    ])


class TestPosaDopoIlGA(unittest.TestCase):
    """Il flusso reale: NINA accende l'Agente, PHD2 parte, il GA si esegue DOPO.

    Fino al §113 la posa veniva decisa in `initialize()`, quando la misura nuova
    non esisteva ancora: alla fine del GA l'Agente adottava il MinMove nuovo ma
    restava sulla posa vecchia, che l'operatore doveva correggere a mano.
    """

    SCALA = [500, 1000, 1500, 2000, 2500, 3000, 3500, 4000, 5000, 6000]

    def _prepara(self, posa_in_phd2: int, base: int = 2000):
        import pathlib
        import tempfile
        self.f = pathlib.Path(tempfile.mkdtemp()) / "phd2_settings.txt"
        # Caratterizzazione vecchia, senza i campi della deriva.
        self.f.write_text(_export("2026-06-12 22:33:35", 0.50, 0.70), encoding="utf-8")
        c = _ctrl(self.f)
        c._valid_exposures = self.SCALA
        c.base_exposure_ms = base
        c.current_exposure_ms = base
        c.client.get_exposure.return_value = posa_in_phd2
        c._resolve_nominal()
        return c

    def _arriva_il_ga(self, c):
        self.f.write_text(_export_con_deriva("2026-08-24 00:28:30", 0.6175, 0.95),
                          encoding="utf-8")
        return c.ricontrolla_baseline_ga()

    def test_la_posa_non_avallata_viene_portata_al_valore_misurato(self):
        c = self._prepara(posa_in_phd2=4000)
        self.assertTrue(self._arriva_il_ga(c))
        c.client.set_exposure.assert_called_once_with(2000)
        self.assertEqual(c.base_exposure_ms, 2000)
        self.assertEqual(c.current_exposure_ms, 2000)

    def test_la_posa_avallata_diventa_la_base_senza_toccare_phd2(self):
        # 3000 e' dentro l'intervallo 1.5-3.5 misurato: scelta informata, e il
        # §113 la rispetta — PHD2 non viene toccato.
        c = self._prepara(posa_in_phd2=3000)
        self._arriva_il_ga(c)
        c.client.set_exposure.assert_not_called()
        self.assertEqual(c.base_exposure_ms, 3000)

    def test_scegliere_un_altra_posa_nell_intervallo_non_costa_la_misura(self):
        """§118 — la tensione trovata dal §116 e' sparita, e non con un compromesso.

        Il §116 aveva trovato che il §113 ("dentro l'intervallo la posa la scegli
        tu") e `richiedi_posa_uguale` si tiravano per la giacca, e vinceva la
        seconda: si finiva alla formula. Poi la verifica sulla sorgente di PHD2 ha
        mostrato che la seconda regola non era di PHD2 — era nostra. Adesso la posa
        resta la tua E il MinMove misurato resta in vigore, con una nota.
        """
        c = self._prepara(posa_in_phd2=3000)
        adottata = self._arriva_il_ga(c)
        self.assertEqual(c.base_exposure_ms, 3000)          # la tua scelta resta
        self.assertTrue(adottata)                           # e la misura pure
        self.assertEqual(c._baseline.sorgente, "guide_assistant")
        self.assertAlmostEqual(c._nominal["ra"][1], 0.6175)
        self.assertTrue([a for a in c._baseline.avvisi if "il valore si usa" in a])

    def test_la_posa_gia_giusta_non_produce_nessun_comando(self):
        c = self._prepara(posa_in_phd2=2000)
        self._arriva_il_ga(c)
        c.client.set_exposure.assert_not_called()
        self.assertEqual(c.base_exposure_ms, 2000)

    def test_un_boost_ereditato_si_richiude(self):
        """La base e' stata ridefinita: il boost non ha piu' un riferimento a cui
        tornare, e lo stato deve tornare NOMINAL."""
        from phd2_agent.controller import ExposureState
        c = self._prepara(posa_in_phd2=4000)
        c.exposure_state = ExposureState.BOOSTED_FOR_SNR
        self._arriva_il_ga(c)
        self.assertEqual(c.exposure_state, ExposureState.NOMINAL)

    def test_se_phd2_rifiuta_il_comando_la_base_non_si_muove(self):
        c = self._prepara(posa_in_phd2=4000)
        c.client.set_exposure.side_effect = RuntimeError("PHD2 occupato")
        with self.assertLogs("phd2_agent.controller", level="ERROR"):
            self._arriva_il_ga(c)
        # Senza la scrittura, cambiare la base significherebbe credere a una
        # posa che PHD2 non ha.
        self.assertEqual(c.base_exposure_ms, 2000)

    def test_senza_campi_di_deriva_la_posa_non_si_tocca(self):
        """Caratterizzazione nuova ma senza raccomandazione utilizzabile: non e'
        un motivo per riscrivere la posa a meta' sessione."""
        c = self._prepara(posa_in_phd2=4000)
        self.f.write_text(_export("2026-08-24 00:28:30", 0.6175, 0.95),
                          encoding="utf-8")
        self.assertTrue(c.ricontrolla_baseline_ga())
        c.client.set_exposure.assert_not_called()
        self.assertEqual(c.base_exposure_ms, 2000)

    def test_il_minmove_viene_adottato_lo_stesso(self):
        """La posa e' un'aggiunta, non un sostituto: il §108 continua a valere."""
        c = self._prepara(posa_in_phd2=4000)
        self._arriva_il_ga(c)
        self.assertAlmostEqual(c._nominal["ra"][1], 0.6175)
        self.assertAlmostEqual(c._nominal["dec"][1], 0.95)
