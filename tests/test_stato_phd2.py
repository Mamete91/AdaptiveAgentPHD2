"""
test_stato_phd2.py — §124: lo stato di PHD2 si ricava dagli eventi.

IL DIFETTO, osservato dal vivo il 03/10/2026 sul Minix100 con la 3.0.0 in
sessione: PHD2 rispondeva `get_app_state() == "Guiding"`, l'Agente riportava
`app_state: Stopped`, `sospeso: True`, `baseline_progress: 0/60`. Non aveva
ingerito un solo fotogramma in tutta la serata.

LA CAUSA, verificata sulla sorgente di PHD2. `ev_app_state()` compare in due
punti di `event_server.cpp`:
  * riga 541 — nel saluto al client che si connette;
  * riga 2953 — dentro `NotifyAppState()`, che **non e' chiamata da nessuna
    parte** nel sorgente.
Quindi PHD2 manda `AppState` UNA VOLTA SOLA, alla connessione. I cambi di stato
successivi li annuncia con eventi specifici (StartGuiding, GuidingStopped,
Paused, LoopingExposures, StartCalibration).

Il §110 aveva legato `sospeso` ad `app_state`. Avviando l'Agente PRIMA della
guida — cioe' sempre, visto che NINA lo accende e PHD2 guida dopo — lo stato
restava "Stopped" per tutta la notte e il gate sospendeva l'Agente dall'inizio
alla fine.

Questi test fissano l'invariante: lo stato deve seguire gli eventi che PHD2
EMETTE DAVVERO, non quello che manda una volta e poi dimentica.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from phd2_agent.config import AgentConfig, ControlConfig, SetupConfig
from phd2_agent.controller import AdaptiveController


def _ctrl(app_state="Stopped"):
    cfg = AgentConfig()
    cfg.control = ControlConfig(dry_run=True)
    cfg.setup = SetupConfig(profile_name="t", guide_pixel_scale_arcsec_native=0.508)
    c = AdaptiveController(client=MagicMock(), config=cfg)
    c.app_state = app_state
    c.anello_aperto = False
    c.in_calibrazione = False
    c._phd2_connesso = True
    c._phd2_calibrato = True
    return c


class TestStatoDagliEventi(unittest.TestCase):
    """`_stato_phd2` e' la via principale: gli eventi che PHD2 emette davvero."""

    def setUp(self):
        from main import _stato_phd2
        self.set = _stato_phd2

    def test_la_guida_parte_e_l_agente_si_sveglia(self):
        """Lo scenario del difetto: connesso da fermo, poi la guida parte."""
        c = _ctrl("Stopped")
        self.assertTrue(c.sospeso, "di partenza e' sospeso, ed e' giusto")
        self.set(c, "Guiding", "annuncio StartGuiding")
        self.assertEqual(c.app_state, "Guiding")
        self.assertFalse(c.sospeso, "deve svegliarsi: PHD2 sta guidando")

    def test_il_guide_step_rimette_in_riga_uno_stato_perso(self):
        """Rete di sicurezza: se StartGuiding si perde, il primo GuideStep basta."""
        c = _ctrl("Stopped")
        self.set(c, "Guiding", "arrivato un GuideStep")
        self.assertFalse(c.sospeso)

    def test_la_guida_si_ferma_e_l_agente_si_ferma(self):
        c = _ctrl("Guiding")
        self.assertFalse(c.sospeso)
        self.set(c, "Stopped", "guida fermata")
        self.assertTrue(c.sospeso)

    def test_tutte_le_transizioni_che_phd2_annuncia(self):
        attesi = {
            "Guiding": False,      # sta guidando -> l'Agente lavora
            "LostLock": False,     # guida che ha perso la stella: e' sempre guida
            "Stopped": True,
            "Paused": True,
            "Looping": True,
            "Calibrating": True,
        }
        for stato, deve_sospendere in attesi.items():
            with self.subTest(stato=stato):
                c = _ctrl("Guiding")
                self.set(c, stato, "prova")
                self.assertEqual(c.sospeso, deve_sospendere)

    def test_niente_controller_niente_danni(self):
        self.set(None, "Guiding", "prova")          # non deve sollevare

    def test_stato_vuoto_ignorato(self):
        c = _ctrl("Guiding")
        self.set(c, "", "prova")
        self.assertEqual(c.app_state, "Guiding")


class TestReteDiSicurezzaNelSondaggio(unittest.TestCase):
    """Il sondaggio del §122 rimette in riga lo stato se un evento si perde."""

    def test_il_sondaggio_corregge_uno_stato_rimasto_indietro(self):
        c = _ctrl("Stopped")
        c.client.get_connected.return_value = True
        c.client.get_calibrated.return_value = True
        c.client.get_app_state.return_value = "Guiding"
        c._fase_ultimo_poll = 0.0
        c._aggiorna_fase_phd2()
        self.assertEqual(c.app_state, "Guiding")
        self.assertFalse(c.sospeso)

    def test_solo_una_stringa_viene_accettata(self):
        """Un mock, o una risposta malformata, e' 'vero' e passerebbe: finirebbe
        nel gate di controllo un valore che non e' uno stato. (Ci sono cascato
        scrivendo questa stessa correzione: un test e' andato in errore.)"""
        c = _ctrl("Guiding")
        c.client.get_connected.return_value = True
        c.client.get_calibrated.return_value = True
        c.client.get_app_state.return_value = MagicMock()      # non e' una stringa
        c._fase_ultimo_poll = 0.0
        c._aggiorna_fase_phd2()
        self.assertEqual(c.app_state, "Guiding", "lo stato non deve essere inquinato")

    def test_phd2_muto_non_cambia_niente(self):
        c = _ctrl("Guiding")
        c.client.get_connected.return_value = True
        c.client.get_calibrated.return_value = True
        c.client.get_app_state.side_effect = RuntimeError("PHD2 giu'")
        c._fase_ultimo_poll = 0.0
        c._aggiorna_fase_phd2()
        self.assertEqual(c.app_state, "Guiding")


class TestLaFaseSegue(unittest.TestCase):
    """§122 — la fase mostrata in dashboard dipende dallo stesso stato."""

    def test_da_pronto_a_guida_quando_la_guida_parte(self):
        from main import _stato_phd2
        c = _ctrl("Stopped")
        self.assertTrue(c.fase.startswith("pronto"))
        _stato_phd2(c, "Guiding", "prova")
        self.assertTrue(c.fase.startswith("guida"))


if __name__ == "__main__":
    unittest.main()
