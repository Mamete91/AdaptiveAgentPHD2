"""
test_cielo_guida.py — §126: la guida giudica il cielo (lato Agente: la MISURA).

Decisione dell'operatore del 04/10/2026, dopo la forense della notte 3-4/10:
la camera di guida e' l'unico giudice del cielo, in entrambi i versi; la camera
di ripresa resta informativa. Prima di firmare l'operatore ha chiesto che la
guida NON dichiari UNSAFE a torto durante calibrazione, Guide Assistant e
autofocus. Il rapporto del 04/10 (RAPPORTO_GUIDA_SOLA_2026-10-04.md) ha trovato
cosa andava corretto; questi test fissano ogni correzione su un caso reale:

  * 3-4/10   — N1 a 0.457 per una posa allungata, guida a SNR ~65: nessun degrado.
  * 2/10     — UNSAFE "guida non osservabile" nel Guide Assistant: l'Agente
               scartava i GuideStep senza segnare che erano arrivati.
  * 24/8     — UNSAFE durante una calibrazione da uno stato rimasto congelato.
  * 10/8     — UN frame perso, 126 buoni dopo, e UNSAFE: la stella persa restava
               appiccicata finche' l'RMS non usciva dalla banda neutra.
  * 4/8      — 93.5% di frame saturi: canale "non pronto" a cielo sereno.
  * 3/10     — dopo l'autofocus una stella nuova al 60% del metro della vecchia.

L'Agente MISURA; la decisione resta nel plugin (SafetyDecisionEngine).
"""
from __future__ import annotations

import queue
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from main import _event_loop
from phd2_agent.config import GuideHealthConfig, RecoveryHintConfig
from phd2_agent.guide_health import GuideHealthTracker
from phd2_agent.recovery_hint import RecoveryHintTracker


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class _State:
    """Provider dello stato N1 della camera di ripresa (ormai solo telemetria)."""

    def __init__(self, state="CLEAR") -> None:
        self.state = state

    def __call__(self):
        return (self.state, None)


def _cielo(clock, state=None, **kw) -> RecoveryHintTracker:
    return RecoveryHintTracker(RecoveryHintConfig(**kw),
                               now_fn=clock)


def _feed(t, c, snr, seconds, step=3.0) -> None:
    """Frame di guida a cadenza ~3 s per `seconds`."""
    for _ in range(int(seconds / step)):
        t.update(snr)
        c.advance(step)


# ============================================================ il giudice ======
class TestLaCameraNonGiudicaPiu(unittest.TestCase):

    def test_notte_3_4_ottobre(self):
        """00:24:37 — N1 a 0.457 (HAZE) per una posa con stelle allungate; la stella
        di guida fra 64.85 e 66.26 contro un riferimento di 65.5. Nessun degrado:
        il cielo, per la guida, era sereno — ed era vero."""
        c, st = _Clock(), _State("CLEAR")
        t = _cielo(c, st)
        _feed(t, c, 65.5, 1800)
        st.state = "HAZE"
        _feed(t, c, 66.0, 600)
        b = t.status_block()
        self.assertFalse(b["degrading"])
        self.assertEqual(b["sky_state"], "CLEAR")
        self.assertTrue(b["sky_ok"])

    def test_il_degrado_si_vede_qualunque_cosa_dica_n1(self):
        """Prima del §126 il degrado si cercava solo a N1 CLEAR. Oggi conta la guida."""
        c = _Clock()
        t = _cielo(c, _State("CLOUD"))
        _feed(t, c, 70.0, 900)
        _feed(t, c, 20.0, 200)
        b = t.status_block()
        self.assertTrue(b["degrading"])
        self.assertEqual(b["sky_state"], "DEGRADED")
        self.assertFalse(b["sky_ok"])


class TestStatoDelCielo(unittest.TestCase):
    """DEGRADED entra col degrado (50% per 90 s), esce col recupero (80% per 60 s)."""

    def _degradato(self):
        c = _Clock()
        t = _cielo(c)
        _feed(t, c, 70.0, 900)
        _feed(t, c, 20.0, 200)
        self.assertEqual(t.status_block()["sky_state"], "DEGRADED")
        return t, c

    def test_tra_le_due_soglie_lo_stato_non_cambia(self):
        """45 e' sopra il 50% di 70 (il degrado rientra) ma sotto l'80%: il cielo
        resta DEGRADED e non c'e' evidenza di sereno. E' l'isteresi."""
        t, c = self._degradato()
        _feed(t, c, 45.0, 600)
        b = t.status_block()
        self.assertFalse(b["degrading"])
        self.assertEqual(b["sky_state"], "DEGRADED")
        self.assertFalse(b["sky_ok"])

    def test_si_torna_sereni_con_il_recupero_sostenuto(self):
        t, c = self._degradato()
        _feed(t, c, 65.0, 90)
        b = t.status_block()
        self.assertEqual(b["sky_state"], "CLEAR")
        self.assertTrue(b["sky_ok"])

    def test_un_picco_non_basta(self):
        t, c = self._degradato()
        _feed(t, c, 65.0, 9)
        _feed(t, c, 20.0, 30)
        self.assertEqual(t.status_block()["sky_state"], "DEGRADED")


class TestRiferimentoCongelato(unittest.TestCase):
    """Con la guida unico giudice il metro non deve seguire il cielo verso il basso."""

    def test_la_velatura_lunga_non_erode_il_metro(self):
        """Senza congelamento, a SNR 45 su 70 il riferimento (emivita 25 min)
        scenderebbe fino a far sembrare sereno il cielo velato in ~35 minuti."""
        c = _Clock()
        t = _cielo(c)
        _feed(t, c, 70.0, 900)
        _feed(t, c, 20.0, 200)
        _feed(t, c, 45.0, 45 * 60)
        b = t.status_block()
        self.assertGreater(b["snr_ref"], 65.0)
        self.assertTrue(b["snr_ref_frozen"])
        self.assertEqual(b["sky_state"], "DEGRADED")
        self.assertFalse(b["sky_ok"])

    def test_il_congelamento_ha_un_tetto(self):
        """Oltre il tetto il degrado stabile e' la nuova normalita' (stesso
        principio del §66 per N1): il riferimento riprende a scendere."""
        c = _Clock()
        t = _cielo(c, snr_ref_freeze_max_min=10.0)
        _feed(t, c, 70.0, 900)
        _feed(t, c, 20.0, 200)
        _feed(t, c, 45.0, 60 * 60)
        b = t.status_block()
        self.assertFalse(b["snr_ref_frozen"])
        self.assertLess(b["snr_ref"], 55.0)

    def test_a_cielo_sereno_il_metro_scende_piano(self):
        """Fuori dal degrado nulla cambia rispetto al §76-bis."""
        c = _Clock()
        t = _cielo(c)
        _feed(t, c, 70.0, 900)
        self.assertFalse(t.status_block()["snr_ref_frozen"])


class TestFasiCieche(unittest.TestCase):
    """Guida ferma, calibrazione, anello aperto: niente flag accesi su dati che non arrivano."""

    def test_sospendi_spegne_i_flag_ma_tiene_il_metro(self):
        c = _Clock()
        t = _cielo(c)
        _feed(t, c, 70.0, 900)
        _feed(t, c, 20.0, 200)
        self.assertTrue(t.status_block()["degrading"])
        t.sospendi("calibrazione")
        b = t.status_block()
        self.assertFalse(b["degrading"], "il plugin non deve contare un degrado congelato")
        self.assertFalse(b["sky_ok"])
        self.assertGreater(b["snr_ref"], 65.0, "la stella e' la stessa: il metro resta")

    def test_nessun_tempo_fantasma_dopo_la_sospensione(self):
        c = _Clock()
        t = _cielo(c)
        _feed(t, c, 70.0, 900)
        t.sospendi("guida fermata")
        c.advance(600)
        t.update(70.0)
        self.assertEqual(t.status_block()["accumulator_s"], 0.0)


class TestNuovaStella(unittest.TestCase):

    def test_stella_piu_debole_dopo_l_autofocus(self):
        """3/10 22:55 — dopo l'autofocus PHD2 sceglie una stella con SNR 37-39
        contro il riferimento 65.5 della precedente. Col metro vecchio il sereno
        non si conferma mai (soglia 52.4); col metro nuovo si'."""
        c = _Clock()
        t = _cielo(c)
        _feed(t, c, 65.5, 1800)
        t.reset_stella("StarSelected")
        _feed(t, c, 38.0, 600)
        b = t.status_block()
        self.assertFalse(b["degrading"])
        self.assertTrue(b["sky_ok"])
        self.assertAlmostEqual(b["snr_ref"], 38.0, delta=1.0)
        self.assertTrue(b["ref_reset_reason"].startswith("StarSelected"))

    def test_senza_reset_la_stella_debole_bloccherebbe_il_sereno(self):
        """Controprova del caso precedente: e' il reset a fare la differenza."""
        c = _Clock()
        t = _cielo(c)
        _feed(t, c, 65.5, 1800)
        _feed(t, c, 38.0, 120)
        self.assertFalse(t.status_block()["sky_ok"])


# ======================================================== la stella persa ======
def _canale(clock, **kw) -> GuideHealthTracker:
    return GuideHealthTracker(GuideHealthConfig(**kw), now_fn=clock)


class TestStellaPersaDagliEventi(unittest.TestCase):

    def test_un_frame_perso_non_resta_appiccicato(self):
        """10/8 — un solo frame perso alle 22:32:03, poi 126 frame buoni, e UNSAFE
        alle 22:34:55. Qui il primo GuideStep chiude la perdita."""
        c = _Clock()
        g = _canale(c)
        g.set_guiding_expected(True, "test")
        g.on_guide_step({})
        c.advance(3)
        g.on_star_lost({})
        self.assertTrue(g.status_block()["star_lost"])
        c.advance(3)
        g.on_guide_step({})
        b = g.status_block()
        self.assertFalse(b["star_lost"])
        self.assertEqual(b["star_lost_s"], 0.0)
        self.assertTrue(b["star_tracked"])

    def test_la_perdita_continua_si_misura_in_secondi(self):
        c = _Clock()
        g = _canale(c)
        g.set_guiding_expected(True, "test")
        for _ in range(70):
            g.on_star_lost({})
            c.advance(3)
        b = g.status_block()
        self.assertTrue(b["star_lost"])
        self.assertAlmostEqual(b["star_lost_s"], 210.0, delta=0.5)
        self.assertFalse(b["star_tracked"])

    def test_la_ripartenza_della_guida_azzera_la_perdita(self):
        c = _Clock()
        g = _canale(c)
        g.set_guiding_expected(True, "test")
        g.on_star_lost({})
        g.set_guiding_expected(False, "guida fermata")
        c.advance(60)
        g.set_guiding_expected(True, "guida ripartita")
        b = g.status_block()
        self.assertFalse(b["star_lost"])
        self.assertEqual(b["star_lost_s"], 0.0)

    def test_tracciata_vuol_dire_un_frame_recente(self):
        c = _Clock()
        g = _canale(c)
        g.set_guiding_expected(True, "test")
        g.on_guide_step({})
        c.advance(30)
        self.assertFalse(g.status_block()["star_tracked"])

    def test_un_passo_di_calibrazione_riuscito_chiude_la_perdita(self):
        """Il passo "Calibrating" arriva solo a stella trovata: se la stella era
        persa prima della calibrazione, si rivede qui e l'allarme si spegne."""
        c = _Clock()
        g = _canale(c)
        g.set_guiding_expected(True, "test")
        g.on_star_lost({})
        g.set_guiding_expected(False, "calibrazione")
        c.advance(20)
        self.assertTrue(g.status_block()["star_lost"])
        g.on_calibration_step({"step": 1})
        self.assertFalse(g.status_block()["star_lost"])

    def test_a_guida_ferma_la_perdita_non_si_congela(self):
        """Fail-safe: se la guida si ferma mentre la stella e' persa e nessuno la
        rivede, la perdita continua a contare (il plugin dichiarera' UNSAFE).
        Congelarla renderebbe cieco il monitor proprio con le nubi."""
        c = _Clock()
        g = _canale(c)
        g.set_guiding_expected(True, "test")
        g.on_star_lost({})
        g.set_guiding_expected(False, "guida fermata")
        c.advance(200)
        b = g.status_block()
        self.assertTrue(b["star_lost"])
        self.assertGreaterEqual(b["star_lost_s"], 200.0)

    def test_nuova_stella_azzera_lo_stato(self):
        c = _Clock()
        g = _canale(c)
        g.set_guiding_expected(True, "test")
        g.on_star_lost({})
        g.reset_stella("StarSelected")
        self.assertFalse(g.status_block()["star_lost"])


class TestSaturazione(unittest.TestCase):

    def test_la_stella_satura_non_rende_il_canale_non_pronto(self):
        """4/8, 23:23-23:42 — il 93.5% dei frame era saturo: il canale risultava
        "non pronto" in 81 interrogazioni su 106, a cielo sereno."""
        c = _Clock()
        g = _canale(c)
        g.set_guiding_expected(True, "test")
        for _ in range(40):
            g.on_guide_step({"ErrorCode": 1})
            c.advance(3)
        b = g.status_block()
        self.assertTrue(b["channel_ready"], b["channel_not_ready_reasons"])
        self.assertEqual(b["star_errors_recent"], 0)
        self.assertGreater(b["star_saturated_recent"], 30)

    def test_gli_altri_errori_contano_ancora(self):
        c = _Clock()
        g = _canale(c)
        g.set_guiding_expected(True, "test")
        for _ in range(40):
            g.on_guide_step({"ErrorCode": 7})      # MASSCHANGE
            c.advance(3)
        b = g.status_block()
        self.assertFalse(b["channel_ready"])
        self.assertGreater(b["star_errors_recent"], 2)


class TestEsitoAssestamento(unittest.TestCase):

    def test_settle_fallito_registrato(self):
        c = _Clock()
        g = _canale(c)
        g.on_settle_done(1, "timed-out waiting for guider to become active")
        b = g.status_block()
        self.assertEqual(b["last_settle_status"], 1)
        self.assertIn("timed-out", b["last_settle_error"])

    def test_settle_riuscito(self):
        c = _Clock()
        g = _canale(c)
        g.on_settle_done(0, "")
        b = g.status_block()
        self.assertEqual(b["last_settle_status"], 0)
        self.assertIsNone(b["last_settle_error"])


# ===================================================== cablaggio degli eventi ==
class _CodaCheFinisce(queue.Queue):
    """Consegna gli eventi e, finiti quelli, ferma il loop."""

    def __init__(self, eventi, stop) -> None:
        super().__init__()
        for e in eventi:
            self.put(e)
        self._stop = stop

    def get(self, block=True, timeout=None):
        try:
            return super().get(block=False)
        except queue.Empty:
            self._stop.set()
            raise


def _gira(eventi, *, sospeso=False, app_state="Guiding", anello_aperto=False):
    """Il VERO _event_loop con un GuideHealthTracker vero e un sensore del cielo finto."""
    stop = threading.Event()
    client = MagicMock()
    client.connected = True
    client.event_queue = _CodaCheFinisce(eventi, stop)

    snap = SimpleNamespace(rms_ra=0.5, rms_dec=0.4, rms_total=0.64, snr_avg=42.0,
                           condition=SimpleNamespace(name="NORMAL"),
                           condition_description="ok", evaluated=False)
    analyzer = MagicMock()
    analyzer.is_ready = True
    analyzer.ingest_guide_step.return_value = snap

    controller = MagicMock()
    controller.cfg = SimpleNamespace(
        setup=SimpleNamespace(guide_pixel_scale_arcsec=1.0),
        analyzer=SimpleNamespace(convert_distance_to_arcsec=True))
    controller.saturated_lock_since = None
    controller.evaluate.return_value = []
    controller._current_diag = None
    controller.anello_aperto = anello_aperto
    controller.in_calibrazione = False
    controller.sospeso = sospeso
    controller.app_state = app_state

    c = _Clock()
    g = _canale(c)
    g.set_guiding_expected(True, "sessione di prova")
    cielo = MagicMock()
    with patch("server.sync_broadcast", lambda msg: None):
        _event_loop(client=client, analyzer=analyzer, controller=controller,
                    session_logger=MagicMock(), stop_event=stop,
                    eval_interval=0.0, monitor_only=False,
                    recovery_hint_tracker=cielo, guide_health=g)
    return g, cielo, c, controller


class TestCablaggio(unittest.TestCase):

    def test_guide_step_ad_anello_aperto_aggiorna_l_orologio(self):
        """2/10 23:13:42 — il GuideStep del Guide Assistant arrivava ma l'Agente lo
        scartava prima di segnarlo: canale "muto" e UNSAFE. Ora l'orologio del
        canale si aggiorna prima di ogni filtro."""
        stop = threading.Event()
        c = _Clock()
        g = _canale(c)
        g.set_guiding_expected(True, "test")
        c.advance(120)
        self.assertGreater(g.status_block()["frame_age_s"], 100)
        client = MagicMock()
        client.connected = True
        client.event_queue = _CodaCheFinisce([{"Event": "GuideStep",
                                               "Timestamp": time.time()}], stop)
        controller = MagicMock()
        controller.sospeso = True
        controller.app_state = "Guiding"
        with patch("server.sync_broadcast", lambda msg: None):
            _event_loop(client=client, analyzer=MagicMock(), controller=controller,
                        session_logger=MagicMock(), stop_event=stop,
                        eval_interval=0.0, monitor_only=False,
                        recovery_hint_tracker=None, guide_health=g)
        self.assertEqual(g.status_block()["frame_age_s"], 0.0)
        controller.ingest_frame.assert_not_called()   # il motore resta fermo (§108)

    def test_calibrazione_spegne_l_attesa_e_sospende(self):
        g, cielo, _, _ = _gira([{"Event": "StartCalibration"}])
        self.assertFalse(g.status_block()["guiding_expected"])
        cielo.sospendi.assert_called_once_with("calibrazione")

    def test_guida_fermata_sospende(self):
        g, cielo, _, _ = _gira([{"Event": "GuidingStopped"}])
        self.assertFalse(g.status_block()["guiding_expected"])
        cielo.sospendi.assert_called_once_with("guida fermata")

    def test_guide_assistant_spegne_e_riaccende_l_attesa(self):
        g, cielo, _, _ = _gira([{"Event": "GuideParamChange",
                                 "Name": "MountGuidingEnabled", "Value": False}])
        self.assertFalse(g.status_block()["guiding_expected"])
        cielo.sospendi.assert_called_once_with("anello aperto")

        g, _, _, _ = _gira([{"Event": "GuideParamChange",
                             "Name": "MountGuidingEnabled", "Value": True}],
                           anello_aperto=True)
        self.assertTrue(g.status_block()["guiding_expected"])

    def test_fine_misura_a_guida_ferma_non_riaccende(self):
        g, _, _, _ = _gira([{"Event": "GuideParamChange",
                             "Name": "MountGuidingEnabled", "Value": True}],
                           anello_aperto=True, app_state="Stopped")
        # l'attesa era vera all'avvio del test: non deve essere RIACCESA da qui,
        # ma nemmeno spenta (non e' questo evento a dirlo).
        self.assertTrue(g.status_block()["guiding_expected"])

    def test_nuova_stella_azzera_metro_e_stato(self):
        g, cielo, _, _ = _gira([{"Event": "AppState", "State": "Guiding"},
                                {"Event": "StarSelected", "X": 100.0, "Y": 200.0}])
        cielo.reset_stella.assert_called_once_with("StarSelected")
        self.assertFalse(g.status_block()["star_lost"])

    def test_passo_di_calibrazione_cablato(self):
        g, _, _, _ = _gira([{"Event": "StarLost"}, {"Event": "Calibrating", "step": 3}])
        self.assertFalse(g.status_block()["star_lost"])

    def test_settle_fallito_registrato_dal_loop(self):
        g, _, _, _ = _gira([{"Event": "SettleDone", "Status": 1,
                             "Error": "timed-out waiting for guider to become active"}])
        self.assertEqual(g.status_block()["last_settle_status"], 1)

    def test_un_osservatore_che_esplode_non_ferma_il_loop(self):
        """§63 — il sensore del cielo e' passivo: un suo errore non abbatte il loop."""
        stop = threading.Event()
        client = MagicMock()
        client.connected = True
        client.event_queue = _CodaCheFinisce([{"Event": "GuidingStopped"},
                                              {"Event": "StartCalibration"}], stop)
        cielo = MagicMock()
        cielo.sospendi.side_effect = RuntimeError("boom")
        controller = MagicMock()
        controller.in_calibrazione = False
        with patch("server.sync_broadcast", lambda msg: None):
            _event_loop(client=client, analyzer=MagicMock(), controller=controller,
                        session_logger=MagicMock(), stop_event=stop,
                        eval_interval=0.0, monitor_only=False,
                        recovery_hint_tracker=cielo, guide_health=None)
        self.assertEqual(cielo.sospendi.call_count, 2)


# ====================================================== §126-bis: seconda tornata
class TestSogliaDiSereno(unittest.TestCase):

    def test_stella_debole_torna_serena(self):
        """Stella con sereno a SNR 22: la nube la porta a 9 (degrado), poi torna a 22.
        Con la soglia max(25, 80%) il sereno non si confermava MAI."""
        c = _Clock()
        t = _cielo(c)
        _feed(t, c, 22.0, 900)
        _feed(t, c, 9.0, 200)
        self.assertEqual(t.status_block()["sky_state"], "DEGRADED")
        _feed(t, c, 22.0, 120)
        b = t.status_block()
        self.assertTrue(b["sky_ok"])
        self.assertEqual(b["sky_state"], "CLEAR")


class TestCongelamentoBis(unittest.TestCase):

    def test_il_tetto_vale_anche_sotto_la_meta(self):
        """3/10 22:36 — guasto della camera di guida: SNR 15-18 contro 74. Prima il
        ramo 'degrado in corso' veniva prima del tetto e il metro restava fermo per
        sempre. Ora oltre il tetto il metro scende e l'UNSAFE puo' rientrare."""
        c = _Clock()
        t = _cielo(c, snr_ref_freeze_max_min=10.0)
        _feed(t, c, 74.0, 900)
        _feed(t, c, 17.0, 60 * 60)          # 10 min congelato, poi 50 min di rilascio
        b = t.status_block()
        self.assertFalse(b["snr_ref_frozen"])
        self.assertLess(b["snr_ref"], 35.0)

    def test_velo_al_65_per_cento_non_erode_il_metro(self):
        """Simulazione della verifica: velo al 65% per 60 minuti. Prima il metro
        scendeva da 65 a 46.6 e il 'sereno' si confermava con SNR 42."""
        c = _Clock()
        t = _cielo(c)
        _feed(t, c, 65.0, 900)
        _feed(t, c, 42.0, 60 * 60)
        b = t.status_block()
        self.assertGreater(b["snr_ref"], 60.0)
        self.assertTrue(b["sotto_il_sereno"])
        self.assertFalse(b["sky_ok"])

    def test_il_sereno_confermato_chiude_il_degrado_residuo(self):
        """Prima il flag di degrado restava acceso fino a 90 s dopo il ritorno della
        SNR e il plugin continuava a contare verso un UNSAFE a nube passata."""
        c = _Clock()
        t = _cielo(c)
        _feed(t, c, 70.0, 900)
        _feed(t, c, 20.0, 120)
        self.assertTrue(t.status_block()["degrading"])
        _feed(t, c, 70.0, 63)
        b = t.status_block()
        self.assertTrue(b["sky_ok"])
        self.assertFalse(b["degrading"])


class TestStellaNuovaBis(unittest.TestCase):

    def test_a_cielo_non_confermato_si_eredita_il_metro(self):
        """3/8 23:39 — stella nuova sotto le nubi a SNR 16-23 contro il metro 73
        (22-31%): per il metro vecchio e' una nube, lo si tiene. Senza, il 'sereno' si
        confermava a SNR 43 mentre l'autofocus vedeva 0-6 stelle."""
        c = _Clock()
        t = _cielo(c)
        _feed(t, c, 64.0, 900)
        _feed(t, c, 20.0, 200)                      # nube: DEGRADED
        t.sospendi("guida fermata")
        t.reset_stella("StarSelected")
        _feed(t, c, 14.0, 300)
        _feed(t, c, 43.0, 90)
        b = t.status_block()
        self.assertTrue(b["ref_ereditato"])
        self.assertGreater(b["snr_ref"], 55.0)
        self.assertFalse(b["sky_ok"], "43 non e' l'80% del sereno della stella di prima")

    def test_stella_nuova_sopra_la_meta_si_reimpara_anche_a_cielo_non_confermato(self):
        """19/7 02:53 — stella persa dalle 02:41 (nubi, nessun degrado misurato:
        solo frame persi), guida ripartita dopo ~10 minuti su una stella al 66% del
        metro vecchio; le pose vere avevano l'84-100% delle stelle: era sereno.
        Tenere il metro vecchio dava UNSAFE fino a fine notte."""
        c = _Clock()
        t = _cielo(c)
        _feed(t, c, 70.8, 900)
        for _ in range(200):                        # 10 minuti di stella persa
            c.advance(3)
            t.on_star_lost()
        t.sospendi("guida fermata")
        t.reset_stella("StarSelected")
        _feed(t, c, 46.7, 120)
        b = t.status_block()
        self.assertFalse(b["ref_ereditato"])
        self.assertAlmostEqual(b["snr_ref"], 46.7, delta=1.0)
        self.assertTrue(b["sky_ok"])

    def test_selezioni_ripetute_non_perdono_il_metro_in_sospeso(self):
        c = _Clock()
        t = _cielo(c)
        _feed(t, c, 64.0, 900)
        _feed(t, c, 20.0, 200)
        t.reset_stella("StarSelected")
        t.reset_stella("StarSelected")
        t.reset_stella("StarSelected")
        _feed(t, c, 16.0, 60)
        b = t.status_block()
        self.assertTrue(b["ref_ereditato"])
        self.assertGreater(b["snr_ref"], 55.0)

    def test_a_tetto_scaduto_il_metro_ereditato_si_reimpara(self):
        c = _Clock()
        t = _cielo(c, snr_ref_freeze_max_min=10.0)
        _feed(t, c, 64.0, 900)
        _feed(t, c, 20.0, 200)
        t.reset_stella("StarSelected")
        _feed(t, c, 20.0, 15 * 60)
        b = t.status_block()
        self.assertFalse(b["ref_ereditato"])
        self.assertLess(b["snr_ref"], 30.0)

    def test_a_cielo_confermato_si_reimpara_anche_dopo_lo_stop(self):
        """3/10 22:53 — autofocus a cielo sereno: stop, nuova stella piu' debole.
        Il giudizio 'sereno' sopravvive allo stop e il metro si reimpara."""
        c = _Clock()
        t = _cielo(c)
        _feed(t, c, 65.5, 1800)
        t.sospendi("guida fermata")
        t.reset_stella("StarSelected")
        _feed(t, c, 38.0, 300)
        b = t.status_block()
        self.assertFalse(b["ref_ereditato"])
        self.assertAlmostEqual(b["snr_ref"], 38.0, delta=1.0)
        self.assertTrue(b["sky_ok"])

    def test_la_stella_persa_non_e_sereno(self):
        c = _Clock()
        t = _cielo(c)
        _feed(t, c, 65.0, 900)
        self.assertTrue(t.status_block()["sky_ok"])
        for _ in range(15):
            c.advance(3)
            t.on_star_lost()
        self.assertFalse(t.status_block()["sky_ok"])


class TestCambioStellaQuater(unittest.TestCase):
    """§126-quater — revisione finale: le ripartenze della sonda di guida fanno
    riselezionare la stella SOTTO LE NUBI."""

    def test_la_nube_si_trasporta_su_una_stella_piu_luminosa(self):
        """Nube vera (DEGRADED), poi si dirada al 60% (sotto il sereno, sopra la
        meta'): l'UNSAFE resta e la sonda fa Stop+Start; PHD2 sceglie una stella 1.5
        volte piu' luminosa. Senza trasporto il metro rinasceva al livello della nube
        e il sereno si 'confermava' coperto."""
        c = _Clock()
        t = _cielo(c)
        _feed(t, c, 60.0, 900)
        _feed(t, c, 15.0, 200)                      # nube: DEGRADED
        _feed(t, c, 36.0, 300)                      # si dirada al 60%
        self.assertEqual(t.status_block()["sky_state"], "DEGRADED")
        t.sospendi("guida fermata")
        c.advance(60)                               # Stop+Start della sonda
        t.reset_stella("StarSelected")
        _feed(t, c, 54.0, 180)                      # stella nuova x1.5, stessa nube
        b = t.status_block()
        self.assertAlmostEqual(b["snr_ref"], 90.0, delta=2.0)
        self.assertFalse(b["sky_ok"], "la nube resta una nube")
        self.assertIn("trasportato", b["ref_reset_reason"])

    def test_a_cielo_sereno_non_si_trasporta(self):
        """§126-quinquies, rigioco del 17/8 02:53: cielo sereno, stella vecchia al 75%
        del suo metro (§126-sexies: per la posa scesa da 4 a 2.5 s alle 02:38:05, non
        per rumore). Trasportando il metro saliva da 43.3 a 52 e UNSAFE fino a fine
        notte: fra stelle diverse a cielo sereno si reimpara."""
        c = _Clock()
        t = _cielo(c)
        _feed(t, c, 43.3, 900)
        _feed(t, c, 32.6, 10)                       # una posa bassa
        self.assertEqual(t.status_block()["sky_state"], "CLEAR")
        t.sospendi("guida fermata")
        c.advance(80)
        t.reset_stella("LockPositionSet")
        _feed(t, c, 39.3, 3)
        b = t.status_block()
        self.assertAlmostEqual(b["snr_ref"], 39.3, delta=0.5)
        self.assertNotIn("trasportato", b["ref_reset_reason"])
        _feed(t, c, 35.0, 600)                      # la stella nuova al suo livello
        _feed(t, c, 20.0, 240)                      # il calo breve delle 03:22
        _feed(t, c, 33.0, 300)
        b = t.status_block()
        self.assertEqual(b["sky_state"], "CLEAR")
        self.assertTrue(b["sky_ok"])

    def test_a_cielo_degradato_la_stella_nuova_debole_eredita(self):
        """Nube al 30% (DEGRADED), ripartenza tardiva su una stella a SNR 25: per il
        metro vecchio (60) e' una nube, si eredita."""
        c = _Clock()
        t = _cielo(c)
        _feed(t, c, 60.0, 900)
        _feed(t, c, 18.0, 300)
        t.sospendi("guida fermata")
        c.advance(600)
        t.reset_stella("StarSelected")
        _feed(t, c, 25.0, 180)
        b = t.status_block()
        self.assertTrue(b["ref_ereditato"])
        self.assertFalse(b["sky_ok"])

    def test_limite_dichiarato_stella_piu_luminosa_sotto_la_nube(self):
        """AG-5, limite ACCETTATO: nube al 30%, ripartenza tardiva (nessun dato
        recente da trasportare) su una stella 2.2 volte piu' luminosa, al 66% del
        metro vecchio. Con la sola SNR e' indistinguibile da una stella piu' debole a
        cielo sereno (19/7 02:53, 3/10 dopo il guasto): si reimpara. Meglio qualche
        posa sotto la nube che una notte ferma a cielo sereno."""
        c = _Clock()
        t = _cielo(c)
        _feed(t, c, 60.0, 900)
        _feed(t, c, 18.0, 300)
        self.assertEqual(t.status_block()["sky_state"], "DEGRADED")
        t.sospendi("guida fermata")
        c.advance(600)                              # ripartenza tardiva: niente ponte
        t.reset_stella("StarSelected")
        _feed(t, c, 39.6, 180)
        b = t.status_block()
        self.assertFalse(b["ref_ereditato"])
        self.assertAlmostEqual(b["snr_ref"], 39.6, delta=1.0)

    def test_il_tetto_dell_eredita_parte_dal_cambio(self):
        """AG-3: dopo 90 minuti di nubi una ripartenza su un'altra stella NON deve far
        reimparare subito il metro sotto le stesse nubi."""
        c = _Clock()
        t = _cielo(c)
        _feed(t, c, 60.0, 900)
        _feed(t, c, 12.0, 88 * 60)
        t.sospendi("guida fermata")
        c.advance(600)
        t.reset_stella("StarSelected")
        _feed(t, c, 14.0, 10 * 60)
        b = t.status_block()
        self.assertTrue(b["ref_ereditato"])
        self.assertFalse(b["sky_ok"])

    def test_il_sereno_confermato_non_sopravvive_a_una_stella_persa(self):
        """AG-1/N1 (16/8 03:01): autofocus partito a cielo sereno, nube durante
        l'autofocus, stella nuova a SNR 6 contro 60.8: prima si reimparava."""
        c = _Clock()
        t = _cielo(c)
        _feed(t, c, 60.8, 900)
        t.sospendi("guida fermata")
        c.advance(240)
        t.reset_stella("StarSelected")
        _feed(t, c, 6.1, 180)
        b = t.status_block()
        self.assertTrue(b["ref_ereditato"])
        self.assertGreater(b["snr_ref"], 55.0)


class TestMemoriaSuDisco(unittest.TestCase):

    def test_il_giudizio_sopravvive_al_riavvio(self):
        """Riavvio dell'Agente sotto una nube: prima il primo frame fissava il metro
        al cielo coperto e l'UNSAFE tornava SAFE sotto le stesse nubi."""
        import tempfile, os
        with tempfile.TemporaryDirectory() as d:
            f = pathlib_path(os.path.join(d, "cielo.json"))
            c = _Clock()
            t = RecoveryHintTracker(RecoveryHintConfig(), now_fn=c, stato_file=f)
            t.posizione_stella(812.0, 433.0)
            _feed(t, c, 65.0, 900)
            _feed(t, c, 26.0, 300)
            self.assertEqual(t.status_block()["sky_state"], "DEGRADED")
            c.advance(120)
            t2 = RecoveryHintTracker(RecoveryHintConfig(), now_fn=c, stato_file=f)
            t2.conferma_memoria((814.0, 431.0), 15.0)   # il saluto di PHD2: stessa stella
            _feed(t2, c, 26.0, 120)
            b = t2.status_block()
            self.assertEqual(b["sky_state"], "DEGRADED")
            self.assertGreater(b["snr_ref"], 55.0)
            self.assertFalse(b["sky_ok"])

    def test_la_memoria_di_un_altra_stella_si_scarta(self):
        """Revisione finale (AG-4): la memoria descrive UNA stella. PHD2 riaperto senza
        stella nel saluto, o con un'altra stella (altro setup, simulatore): si scarta."""
        import tempfile, os
        with tempfile.TemporaryDirectory() as d:
            f = pathlib_path(os.path.join(d, "cielo.json"))
            c = _Clock()
            t = RecoveryHintTracker(RecoveryHintConfig(), now_fn=c, stato_file=f)
            t.posizione_stella(812.0, 433.0)
            _feed(t, c, 120.0, 900)
            for posizione in (None, (200.0, 900.0)):
                t2 = RecoveryHintTracker(RecoveryHintConfig(), now_fn=c, stato_file=f)
                t2.conferma_memoria(posizione, 15.0)
                self.assertIsNone(t2.status_block()["snr_ref"], posizione)

    def test_uno_stato_vecchio_si_ignora(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as d:
            f = pathlib_path(os.path.join(d, "cielo.json"))
            c = _Clock()
            t = RecoveryHintTracker(RecoveryHintConfig(), now_fn=c, stato_file=f)
            _feed(t, c, 65.0, 900)
            c.advance(3 * 3600)
            t2 = RecoveryHintTracker(RecoveryHintConfig(), now_fn=c, stato_file=f)
            t2.conferma_memoria(None, 15.0)
            self.assertIsNone(t2.status_block()["snr_ref"])

    def test_un_file_rovinato_non_ferma_nulla(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as d:
            f = pathlib_path(os.path.join(d, "cielo.json"))
            f.write_text("{non e' json", encoding="utf-8")
            t = RecoveryHintTracker(RecoveryHintConfig(), now_fn=_Clock(), stato_file=f)
            self.assertIsNone(t.status_block()["snr_ref"])


class TestCanaleBis(unittest.TestCase):

    def test_il_looping_non_rende_tracciata_la_stella(self):
        """PHD2 in looping senza stella manda solo LoopingExposures: prima rendevano
        'tracciata' una stella che non c'era."""
        c = _Clock()
        g = _canale(c)
        g.set_guiding_expected(True, "test")
        g.on_guide_step({})
        g.set_guiding_expected(False, "guida fermata")
        c.advance(60)
        for _ in range(10):
            g.on_looping_exposure({"ErrorCode": 6})
            c.advance(3)
        self.assertFalse(g.status_block()["star_tracked"])

    def test_ripartenza_fallita_conta_come_stella_persa(self):
        """La guida doveva ripartire e non e' ripartita: il monitor non deve
        restare SAFE mentre NINA espone senza guida."""
        c = _Clock()
        g = _canale(c)
        g.set_guiding_expected(True, "test")
        g.on_guide_step({})
        g.set_guiding_expected(False, "guida fermata")
        c.advance(60)
        g.on_settle_done(1, "failed to find a suitable guide star")
        c.advance(200)
        b = g.status_block()
        self.assertTrue(b["star_lost"])
        self.assertTrue(b["guide_restart_failed"])
        self.assertGreaterEqual(b["star_lost_s"], 200.0)

    def test_un_fallimento_insieme_allo_stop_e_un_annullamento(self):
        """PHD2 manda GuidingStopped e subito il SettleDone di annullamento: anche se il
        testo non e' quello atteso, non e' una ripartenza fallita."""
        c = _Clock()
        g = _canale(c)
        g.set_guiding_expected(True, "test")
        g.on_guide_step({})
        g.set_guiding_expected(False, "guida fermata")
        g.on_settle_done(1, "settling failed")
        self.assertFalse(g.status_block()["star_lost"])

    def test_lo_stop_volontario_non_e_una_ripartenza_fallita(self):
        c = _Clock()
        g = _canale(c)
        g.set_guiding_expected(True, "test")
        g.on_guide_step({})
        g.set_guiding_expected(False, "guida fermata")
        g.on_settle_done(1, "Guiding stopped")
        self.assertFalse(g.status_block()["star_lost"])

    def test_timeout_di_assestamento_a_guida_attiva_non_conta(self):
        c = _Clock()
        g = _canale(c)
        g.set_guiding_expected(True, "test")
        g.on_guide_step({})
        g.on_settle_done(1, "timed-out waiting for guider to settle")
        self.assertFalse(g.status_block()["star_lost"])

    def test_la_ripartenza_riuscita_azzera(self):
        c = _Clock()
        g = _canale(c)
        g.set_guiding_expected(False, "guida fermata")
        g.on_settle_done(1, "failed to find a suitable guide star")
        g.set_guiding_expected(True, "guida avviata")
        b = g.status_block()
        self.assertFalse(b["star_lost"])
        self.assertFalse(b["guide_restart_failed"])


class TestCablaggioBis(unittest.TestCase):

    def test_lo_starselected_del_saluto_non_e_una_stella_nuova(self):
        """Alla connessione PHD2 rimanda uno StarSelected (event_server.cpp) prima
        di AppState: e' la stella gia' in uso."""
        _, cielo, _, _ = _gira([{"Event": "StarSelected", "X": 100.0, "Y": 200.0},
                                {"Event": "AppState", "State": "Guiding"}])
        cielo.reset_stella.assert_not_called()

    def test_stessa_stella_dopo_il_saluto(self):
        _, cielo, _, _ = _gira([{"Event": "StarSelected", "X": 100.0, "Y": 200.0},
                                {"Event": "AppState", "State": "Guiding"},
                                {"Event": "StarSelected", "X": 104.0, "Y": 203.0}])
        cielo.reset_stella.assert_not_called()

    def test_stella_lontana_e_un_altra_stella(self):
        _, cielo, _, _ = _gira([{"Event": "AppState", "State": "Guiding"},
                                {"Event": "StarSelected", "X": 100.0, "Y": 200.0},
                                {"Event": "StarSelected", "X": 600.0, "Y": 420.0}])
        self.assertEqual(cielo.reset_stella.call_count, 2)

    def test_il_dither_non_cambia_stella_il_salto_si(self):
        """Fine Guiding Assistant con multistar: PHD2 cambia stella senza StarSelected
        (2/10 23:19:25). Il dither (4 px sul Minix) resta sotto la soglia. Il primo
        lock senza posizione precedente E' una selezione (§126-quater: PHD2 manda
        sempre LockPositionSet prima di StarSelected)."""
        _, cielo, _, _ = _gira([{"Event": "AppState", "State": "Guiding"},
                                {"Event": "LockPositionSet", "X": 1025.9, "Y": 555.9},
                                {"Event": "LockPositionSet", "X": 1029.0, "Y": 558.0},
                                {"Event": "LockPositionSet", "X": 1589.7, "Y": 422.4}])
        self.assertEqual(cielo.reset_stella.call_count, 2)

    def test_lock_poi_starselected_alla_stessa_posizione_e_una_sola_selezione(self):
        """L'ordine vero di PHD2 dopo un riavvio di PHD2 (saluto senza stella)."""
        _, cielo, _, _ = _gira([{"Event": "AppState", "State": "Stopped"},
                                {"Event": "LockPositionSet", "X": 640.0, "Y": 300.0},
                                {"Event": "StarSelected", "X": 640.0, "Y": 300.0}])
        self.assertEqual(cielo.reset_stella.call_count, 1)

    def test_dopo_la_calibrazione_il_lock_non_e_un_cambio(self):
        _, cielo, _, _ = _gira([{"Event": "AppState", "State": "Guiding"},
                                {"Event": "StarSelected", "X": 100.0, "Y": 100.0},
                                {"Event": "StartCalibration"},
                                {"Event": "CalibrationComplete"},
                                {"Event": "LockPositionSet", "X": 160.0, "Y": 100.0},
                                {"Event": "StartGuiding"}])
        self.assertEqual(cielo.reset_stella.call_count, 1, "solo la selezione iniziale")

    def test_calibrazione_fallita_e_stella_nuova_si_riconosce(self):
        _, cielo, _, _ = _gira([{"Event": "AppState", "State": "Guiding"},
                                {"Event": "StarSelected", "X": 100.0, "Y": 100.0},
                                {"Event": "StartCalibration"},
                                {"Event": "CalibrationFailed"},
                                {"Event": "LockPositionSet", "X": 700.0, "Y": 500.0},
                                {"Event": "StarSelected", "X": 700.0, "Y": 500.0}])
        self.assertEqual(cielo.reset_stella.call_count, 2)

    def test_la_stella_persa_arriva_al_sensore_del_cielo(self):
        _, cielo, _, _ = _gira([{"Event": "StarLost"}])
        cielo.on_star_lost.assert_called_once_with()

    def test_monitor_only_alimenta_il_sensore_del_cielo(self):
        stop = threading.Event()
        client = MagicMock()
        client.connected = True
        client.event_queue = _CodaCheFinisce([{"Event": "GuideStep",
                                               "Timestamp": time.time()}], stop)
        snap = SimpleNamespace(rms_ra=0.5, rms_dec=0.4, rms_total=0.64, snr_avg=42.0,
                               condition=SimpleNamespace(name="NORMAL"),
                               condition_description="ok", evaluated=False)
        analyzer = MagicMock()
        analyzer.is_ready = True
        analyzer.ingest_guide_step.return_value = snap
        controller = MagicMock()
        controller.cfg = SimpleNamespace(
            setup=SimpleNamespace(guide_pixel_scale_arcsec=1.0),
            analyzer=SimpleNamespace(convert_distance_to_arcsec=True))
        controller.sospeso = False
        controller.saturated_lock_since = None
        controller._current_diag = None
        cielo = MagicMock()
        with patch("server.sync_broadcast", lambda msg: None):
            _event_loop(client=client, analyzer=analyzer, controller=controller,
                        session_logger=MagicMock(), stop_event=stop,
                        eval_interval=0.0, monitor_only=True,
                        recovery_hint_tracker=cielo, guide_health=None)
        cielo.update.assert_called_once_with(42.0)
        controller.evaluate.assert_not_called()


class TestPHD2ClientBis(unittest.TestCase):

    def test_get_guide_output_enabled_esiste(self):
        """La rete di sicurezza del §108 lo chiamava, ma il metodo mancava."""
        from phd2_agent.client import PHD2Client
        c = PHD2Client.__new__(PHD2Client)
        c.call = MagicMock(return_value=False)
        self.assertIs(c.get_guide_output_enabled(), False)
        c.call.assert_called_once_with("get_guide_output_enabled")


class TestGiudicePronto(unittest.TestCase):

    def test_pronto_solo_con_sensore_e_canale(self):
        import server
        vecchio = server._recovery_hint_tracker
        try:
            server._recovery_hint_tracker = _cielo(_Clock())
            self.assertTrue(server._con_giudice_pronto({"enabled": True}, {"enabled": True})["giudice_pronto"])
            self.assertFalse(server._con_giudice_pronto({"enabled": True}, {"enabled": False})["giudice_pronto"])
            self.assertFalse(server._con_giudice_pronto({"enabled": False}, {"enabled": True})["giudice_pronto"])
            server._recovery_hint_tracker = None
            self.assertFalse(server._con_giudice_pronto({"enabled": True}, {"enabled": True})["giudice_pronto"])
        finally:
            server._recovery_hint_tracker = vecchio


# ================================================ §126-sexies: conferma lunga e posa
class _Monitor:
    """Provider dello stato del monitor del plugin: True = UNSAFE, False = SAFE,
    None = non si sa (nessun plugin, stato stantio, giudice camera)."""

    def __init__(self, valore=None) -> None:
        self.valore = valore

    def __call__(self):
        return self.valore


def _cielo_m(clock, monitor, **kw) -> RecoveryHintTracker:
    return RecoveryHintTracker(RecoveryHintConfig(**kw), now_fn=clock, unsafe_provider=monitor)


class TestConfermaLunga(unittest.TestCase):
    """Dopo un cambio di stella o di posa avvenuto mentre il monitor e' UNSAFE il
    sereno deve durare 5 minuti, non 1: con la sola SNR una stella piu' luminosa
    sotto la nube sembra una stella normale a cielo sereno."""

    def _dopo_la_ripartenza_in_unsafe(self):
        c = _Clock()
        m = _Monitor(None)
        t = _cielo_m(c, m)
        _feed(t, c, 60.0, 900)                      # sereno: riferimento 60
        _feed(t, c, 18.0, 300)                      # nube al 30%: DEGRADED
        self.assertEqual(t.status_block()["sky_state"], "DEGRADED")
        m.valore = True                             # il monitor e' UNSAFE
        t.sospendi("guida fermata")                 # la sonda ferma la guida...
        c.advance(600)                              # ...e la fa ripartire tardi
        t.reset_stella("StarSelected")
        return t, c, m

    def test_stella_piu_luminosa_dopo_la_ripartenza_in_unsafe(self):
        """Il limite 1 dichiarato al §126: stella 2.2 volte piu' luminosa sotto la
        stessa nube, al 66% del metro vecchio -> si reimpara. Prima bastava un
        minuto per il SAFE sotto la nube; ora ne servono cinque."""
        t, c, _ = self._dopo_la_ripartenza_in_unsafe()
        _feed(t, c, 39.6, 120)
        b = t.status_block()
        self.assertFalse(b["sky_ok"], "un minuto non basta dopo un cambio in UNSAFE")
        self.assertTrue(b["conferma_lunga"])
        self.assertEqual(b["sustained_target_s"], 300.0)
        self.assertTrue(b["sereno_in_conferma"])
        self.assertIn("StarSelected", b["conferma_lunga_motivo"])
        _feed(t, c, 39.6, 200)
        b = t.status_block()
        self.assertTrue(b["sky_ok"])
        self.assertFalse(b["conferma_lunga"])
        self.assertEqual(b["sustained_target_s"], 60.0)
        self.assertFalse(b["sereno_in_conferma"])

    def test_cambio_a_monitor_safe_basta_un_minuto(self):
        """3/10 22:55 — stella piu' debole dopo l'autofocus a cielo sereno: niente
        UNSAFE in corso, la conferma resta di un minuto."""
        c = _Clock()
        t = _cielo_m(c, _Monitor(False))
        _feed(t, c, 60.0, 900)
        t.sospendi("guida fermata")
        c.advance(60)
        t.reset_stella("StarSelected")
        _feed(t, c, 40.0, 90)
        b = t.status_block()
        self.assertTrue(b["sky_ok"])
        self.assertFalse(b["conferma_lunga"])

    def test_senza_notizie_dal_monitor_niente_cambia(self):
        """Nessun plugin, stato stantio o giudice camera: come prima."""
        c = _Clock()
        t = _cielo_m(c, _Monitor(None))
        _feed(t, c, 60.0, 900)
        _feed(t, c, 18.0, 300)
        t.sospendi("guida fermata")
        c.advance(600)
        t.reset_stella("StarSelected")
        _feed(t, c, 39.6, 90)
        self.assertTrue(t.status_block()["sky_ok"])

    def test_il_monitor_tornato_safe_chiude_la_conferma_lunga(self):
        """Il monitor torna SAFE per un'altra via (ricollegato): la conferma lunga non
        ha piu' un UNSAFE da chiudere."""
        t, c, m = self._dopo_la_ripartenza_in_unsafe()
        _feed(t, c, 39.6, 30)
        self.assertTrue(t.status_block()["conferma_lunga"])
        m.valore = False
        _feed(t, c, 39.6, 60)
        b = t.status_block()
        self.assertFalse(b["conferma_lunga"])
        self.assertTrue(b["sky_ok"])

    def test_un_provider_guasto_vale_non_so(self):
        def guasto():
            raise RuntimeError("boom")
        c = _Clock()
        t = _cielo_m(c, guasto)
        _feed(t, c, 60.0, 300)
        t.reset_stella("StarSelected")
        _feed(t, c, 40.0, 90)
        b = t.status_block()
        self.assertFalse(b["conferma_lunga"])
        self.assertTrue(b["sky_ok"])

    def test_anche_il_cambio_di_posa_in_unsafe_chiede_cinque_minuti(self):
        c = _Clock()
        m = _Monitor(None)
        t = _cielo_m(c, m)
        _feed(t, c, 60.0, 900)
        m.valore = True
        t.cambio_posa("posa di guida 2000 ms -> 3000 ms")
        c.advance(20)
        _feed(t, c, 73.0, 120)
        b = t.status_block()
        self.assertTrue(b["conferma_lunga"])
        self.assertIn("posa", b["conferma_lunga_motivo"])
        self.assertFalse(b["sky_ok"])

    def test_lo_stato_del_monitor_arriva_dallo_store_del_plugin(self):
        """Il provider vero: lo stato che il plugin pubblica su /nina/safety."""
        from phd2_agent.safety_state import SafetyStateStore
        c = _Clock()
        s = SafetyStateStore(staleness_seconds=45.0, now_fn=c)
        t = _cielo_m(c, s.monitor_in_unsafe)
        _feed(t, c, 60.0, 300)
        s.update("UNSAFE", cause="CLOUD", judge="GUIDE")
        t.reset_stella("StarSelected")
        self.assertTrue(t.status_block()["conferma_lunga"])


class TestMonitorInUnsafe(unittest.TestCase):
    """SafetyStateStore.monitor_in_unsafe: True/False solo con notizie fresche da un
    monitor collegato che usa la guida come giudice."""

    def setUp(self):
        from phd2_agent.safety_state import SafetyStateStore
        self.c = _Clock()
        self.s = SafetyStateStore(staleness_seconds=45.0, now_fn=self.c)

    def test_nessuna_notizia(self):
        self.assertIsNone(self.s.monitor_in_unsafe())

    def test_unsafe_e_safe_con_la_guida_giudice(self):
        self.s.update("UNSAFE", cause="STAR_LOST", judge="GUIDE")
        self.assertIs(self.s.monitor_in_unsafe(), True)
        self.s.update("SAFE", judge="GUIDE")
        self.assertIs(self.s.monitor_in_unsafe(), False)

    def test_giudice_camera_o_plugin_vecchio(self):
        self.s.update("UNSAFE", cause="CLOUD", judge="CAMERA")
        self.assertIsNone(self.s.monitor_in_unsafe())
        self.s.update("UNSAFE", cause="CLOUD")              # plugin fino al 1.13
        self.assertIsNone(self.s.monitor_in_unsafe())

    def test_monitor_scollegato_o_notizia_stantia(self):
        self.s.update("UNSAFE", judge="GUIDE", connected=False)
        self.assertIsNone(self.s.monitor_in_unsafe())
        self.s.update("UNSAFE", judge="GUIDE")
        self.c.advance(60)
        self.assertIsNone(self.s.monitor_in_unsafe())

    def test_finestra_del_meridiano_conta_lo_stato_interno(self):
        self.s.update("MERIDIAN_PROTECTION", judge="GUIDE", internal_safe=False)
        self.assertIs(self.s.monitor_in_unsafe(), True)
        self.s.update("MERIDIAN_PROTECTION", judge="GUIDE", internal_safe=True)
        self.assertIs(self.s.monitor_in_unsafe(), False)
        self.s.update("MERIDIAN_PROTECTION", judge="GUIDE")
        self.assertIsNone(self.s.monitor_in_unsafe())


class TestCambioPosa(unittest.TestCase):
    """Il cambio della posa di guida si tratta come un cambio di stella; essendo la
    stessa stella, il riferimento si riscala con il rapporto misurato."""

    def test_posa_accorciata_a_cielo_sereno_si_riscala(self):
        """17/8 03:20:45 — posa da 4 s a 1 s: la SNR scende a circa la meta' con il
        cielo invariato. Il riferimento segue la posa: nessuna nube."""
        c = _Clock()
        t = _cielo(c)
        _feed(t, c, 38.0, 900)
        t.cambio_posa("posa di guida 4000 ms -> 1000 ms")
        c.advance(20)                               # l'analizzatore si riempie
        _feed(t, c, 19.0, 300)
        b = t.status_block()
        self.assertAlmostEqual(b["snr_ref"], 19.0, delta=0.5)
        self.assertIn("trasportato", b["ref_reset_reason"])
        self.assertFalse(b["degrading"])
        self.assertEqual(b["sky_state"], "CLEAR")
        self.assertTrue(b["sky_ok"])

    def test_senza_il_cambio_di_posa_sembrava_una_nube(self):
        """Lo stesso caso con il codice di prima (nessun cambio_posa): degrado."""
        c = _Clock()
        t = _cielo(c)
        _feed(t, c, 38.0, 900)
        c.advance(20)
        _feed(t, c, 19.0, 300)
        self.assertTrue(t.status_block()["degrading"])

    def test_posa_allungata_riscala_subito(self):
        c = _Clock()
        t = _cielo(c)
        _feed(t, c, 40.0, 900)
        t.cambio_posa("posa di guida 1000 ms -> 4000 ms")
        c.advance(30)
        _feed(t, c, 80.0, 30)
        self.assertAlmostEqual(t.status_block()["snr_ref"], 80.0, delta=1.0)
        _feed(t, c, 30.0, 150)                      # nube al 37% con la posa nuova
        self.assertTrue(t.status_block()["degrading"])

    def test_posa_poi_stella_nuova_non_trasporta_a_cielo_sereno(self):
        """Cambio di posa e, prima del primo dato, una stella nuova: il confronto e'
        fra due stelle diverse e a cielo sereno si reimpara (§126-quinquies)."""
        c = _Clock()
        t = _cielo(c)
        _feed(t, c, 40.0, 900)
        t.cambio_posa("posa di guida 2000 ms -> 3000 ms")
        t.reset_stella("StarSelected")
        c.advance(20)
        _feed(t, c, 55.0, 30)
        b = t.status_block()
        self.assertAlmostEqual(b["snr_ref"], 55.0, delta=0.5)
        self.assertNotIn("trasportato", b["ref_reset_reason"])

    def test_sotto_una_nube_fitta_si_eredita(self):
        """L'Agente alza la posa con la SNR sotto 8 (Path A): l'ultimo dato e' sotto la
        meta' del metro, il rapporto non e' credibile e si tiene il metro vecchio."""
        c = _Clock()
        t = _cielo(c)
        _feed(t, c, 60.0, 900)
        _feed(t, c, 7.0, 200)
        t.cambio_posa("posa di guida 2000 ms -> 3000 ms")
        c.advance(30)
        _feed(t, c, 8.5, 60)
        b = t.status_block()
        self.assertTrue(b["ref_ereditato"])
        self.assertAlmostEqual(b["snr_ref"], 60.0, delta=1.0)
        self.assertEqual(b["sky_state"], "DEGRADED")


def _gira_posa(eventi):
    """Il VERO _event_loop con analizzatore, controller e sensore del cielo finti."""
    stop = threading.Event()
    client = MagicMock()
    client.connected = True
    client.event_queue = _CodaCheFinisce(eventi, stop)
    analyzer = MagicMock()
    analyzer.is_ready = False
    controller = MagicMock()
    controller.anello_aperto = False
    controller.sospeso = False
    controller.app_state = "Guiding"
    cielo = MagicMock()
    with patch("server.sync_broadcast", lambda msg: None):
        _event_loop(client=client, analyzer=analyzer, controller=controller,
                    session_logger=MagicMock(), stop_event=stop,
                    eval_interval=0.0, monitor_only=False,
                    recovery_hint_tracker=cielo, guide_health=None)
    return cielo, analyzer, controller


def _posa(valore):
    return {"Event": "GuideParamChange", "Name": "Exposure", "Value": valore}


class TestCablaggioPosa(unittest.TestCase):

    def test_il_cambio_di_posa_azzera_le_statistiche_e_avvisa_il_cielo(self):
        cielo, analyzer, controller = _gira_posa([_posa("2000 ms")])
        cielo.cambio_posa.assert_called_once_with("posa di guida ? -> 2000 ms")
        analyzer.reset.assert_called_once()
        controller.diagnostic_engine.reset.assert_called_once_with("exposure_change")

    def test_la_stessa_posa_non_e_un_cambio(self):
        cielo, _, _ = _gira_posa([_posa("2000 ms"), _posa("2000 ms")])
        self.assertEqual(cielo.cambio_posa.call_count, 1)

    def test_posa_con_vardelay(self):
        cielo, _, _ = _gira_posa([_posa("2000 ms"),
                                  _posa("4000 ms, VarDelay (short = 1000 ms, long = 2000 ms)")])
        cielo.cambio_posa.assert_called_with("posa di guida 2000 ms -> 4000 ms")

    def test_posa_numerica(self):
        cielo, _, _ = _gira_posa([_posa(2500)])
        cielo.cambio_posa.assert_called_once_with("posa di guida ? -> 2500 ms")

    def test_posa_automatica_avvisa(self):
        with self.assertLogs("phd2_agent.main", level="WARNING") as cm:
            cielo, _, _ = _gira_posa([_posa("2000 ms"),
                                      _posa("Auto (min = 1000 ms, max = 5000 ms, SNR = 20.00)")])
        cielo.cambio_posa.assert_called_with("posa di guida 2000 ms -> Auto")
        self.assertTrue(any("AUTOMATICA" in r for r in cm.output))

    def test_valore_incomprensibile_ignorato(self):
        cielo, analyzer, _ = _gira_posa([_posa("boh")])
        cielo.cambio_posa.assert_not_called()
        analyzer.reset.assert_not_called()

    def test_leggi_posa(self):
        from main import _leggi_posa
        self.assertEqual(_leggi_posa("2000 ms"), 2000)
        self.assertEqual(_leggi_posa("4000 ms, VarDelay (short = 1000 ms, long = 2000 ms)"), 4000)
        self.assertEqual(_leggi_posa("Auto (min = 1000 ms, max = 5000 ms, SNR = 20.00)"), "auto")
        self.assertEqual(_leggi_posa(3000), 3000)
        self.assertIsNone(_leggi_posa(True))
        self.assertIsNone(_leggi_posa(0))
        self.assertIsNone(_leggi_posa(""))
        self.assertIsNone(_leggi_posa(None))


def pathlib_path(s):
    import pathlib
    return pathlib.Path(s)


if __name__ == "__main__":
    unittest.main()
