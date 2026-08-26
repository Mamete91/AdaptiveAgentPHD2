"""
test_fasi.py — §122: in quale punto della serata siamo.

Il banner prima diceva "Misura in corso" ogni volta che PHD2 non stava guidando —
compreso `Stopped`, cioe' PHD2 aperto senza periferiche collegate. Annunciava una
misura che non esisteva.

La causa: `sospeso` e' un ottimo GATE di controllo (non toccare niente se non si
sta guidando) ma un pessimo DESCRITTORE. Confondeva "non sto guidando" con "sto
misurando".

Adesso l'Agente chiede a PHD2 due cose che sapeva gia' rispondere e che non gli
avevamo mai chiesto — `get_connected` e `get_calibrated` — e ne ricava la fase.

La catena della serata e' imposta da PHD2, non da noi:
  * la guida non parte senza calibrazione (`guider.cpp`, BeginCalibration);
  * il pulsante Inizia dell'Assistente resta grigio finche' la guida non e' attiva
    (`guiding_assistant.cpp:1738`: `m_start->Enable(pGuider->IsGuiding())`).
Quindi: calibri -> guidi -> solo allora l'Assistente si accende.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from phd2_agent.config import AgentConfig, ControlConfig, SetupConfig
from phd2_agent.controller import AdaptiveController
from phd2_agent.ga_baseline import Baseline


def _ctrl(*, connesso=True, calibrato=True, app_state="Stopped",
          sorgente=None, di_stanotte=False):
    cfg = AgentConfig()
    cfg.control = ControlConfig(dry_run=True)
    cfg.setup = SetupConfig(profile_name="t", guide_pixel_scale_arcsec_native=0.508)
    c = AdaptiveController(client=MagicMock(), config=cfg)
    c._phd2_connesso = connesso
    c._phd2_calibrato = calibrato
    c.app_state = app_state
    c.anello_aperto = False
    c.in_calibrazione = False
    if sorgente:
        c._baseline = Baseline(70.0, 0.6175, 100.0, 0.95, sorgente, "x",
                               ga_di_stanotte=di_stanotte)
    return c


class TestFasiPrimaDellaGuida(unittest.TestCase):

    def test_niente_periferiche(self):
        """Il caso delle schermate: PHD2 aperto, niente collegato. Prima diceva
        'Misura in corso'."""
        self.assertEqual(_ctrl(connesso=False).fase, "non_connesso")

    def test_collegato_ma_non_calibrato(self):
        self.assertEqual(_ctrl(calibrato=False).fase, "non_calibrato")

    def test_pronto_senza_nessuna_caratterizzazione(self):
        self.assertEqual(_ctrl().fase, "pronto_senza_ga")

    def test_pronto_con_caratterizzazione_vecchia(self):
        c = _ctrl(sorgente="guide_assistant", di_stanotte=False)
        self.assertEqual(c.fase, "pronto_ga_vecchio")

    def test_pronto_con_caratterizzazione_di_stanotte(self):
        c = _ctrl(sorgente="guide_assistant", di_stanotte=True)
        self.assertEqual(c.fase, "pronto_ga_stanotte")

    def test_la_formula_non_e_una_caratterizzazione(self):
        c = _ctrl(sorgente="formula_phd2", di_stanotte=True)
        self.assertEqual(c.fase, "pronto_senza_ga")


class TestFasiDurantePHD2AlLavoro(unittest.TestCase):

    def test_calibrazione_vince_su_tutto(self):
        c = _ctrl(connesso=False, calibrato=False)
        c.in_calibrazione = True
        self.assertEqual(c.fase, "calibrazione")

    def test_anello_aperto_e_la_misura(self):
        c = _ctrl(sorgente="guide_assistant", di_stanotte=True)
        c.anello_aperto = True
        self.assertEqual(c.fase, "misura")

    def test_la_calibrazione_precede_la_misura(self):
        c = _ctrl()
        c.in_calibrazione = True
        c.anello_aperto = True
        self.assertEqual(c.fase, "calibrazione")


class TestFasiDuranteLaGuida(unittest.TestCase):

    def test_guida_con_misura_di_stanotte(self):
        c = _ctrl(app_state="Guiding", sorgente="guide_assistant", di_stanotte=True)
        self.assertEqual(c.fase, "guida_ok")

    def test_guida_con_misura_vecchia(self):
        c = _ctrl(app_state="Guiding", sorgente="guide_assistant", di_stanotte=False)
        self.assertEqual(c.fase, "guida_ga_vecchio")

    def test_guida_su_valori_stimati(self):
        c = _ctrl(app_state="Guiding", sorgente="formula_phd2")
        self.assertEqual(c.fase, "guida_stimata")

    def test_stella_persa_conta_come_guida(self):
        """LostLock e' la guida che ha perso la stella, non un'altra fase: la
        taratura in vigore e' sempre quella."""
        c = _ctrl(app_state="LostLock", sorgente="guide_assistant", di_stanotte=True)
        self.assertEqual(c.fase, "guida_ok")


class TestInterrogazioneDiPHD2(unittest.TestCase):

    def test_le_due_domande_vengono_fatte(self):
        c = _ctrl()
        c.client.get_connected.return_value = True
        c.client.get_calibrated.return_value = False
        c._fase_ultimo_poll = 0.0
        c._aggiorna_fase_phd2()
        c.client.get_connected.assert_called_once()
        c.client.get_calibrated.assert_called_once()
        self.assertIs(c._phd2_calibrato, False)

    def test_il_ttl_evita_di_martellare_phd2(self):
        c = _ctrl()
        c.client.get_connected.return_value = True
        c.client.get_calibrated.return_value = True
        c._fase_ultimo_poll = 0.0
        c._aggiorna_fase_phd2()
        c._aggiorna_fase_phd2()          # subito dopo: non deve richiedere
        self.assertEqual(c.client.get_connected.call_count, 1)

    def test_phd2_muto_lascia_l_ultimo_valore_noto(self):
        """Meglio la fase di un attimo fa che una dichiarata sull'ignoranza."""
        c = _ctrl(connesso=True)
        c.client.get_connected.side_effect = RuntimeError("PHD2 giu'")
        c.client.get_calibrated.side_effect = RuntimeError("PHD2 giu'")
        c._fase_ultimo_poll = 0.0
        c._aggiorna_fase_phd2()
        self.assertIs(c._phd2_connesso, True)

    def test_la_fase_arriva_alla_dashboard(self):
        c = _ctrl(connesso=False)
        c.client.get_connected.return_value = False
        c.client.get_calibrated.return_value = False
        self.assertEqual(c.get_status()["fase"], "non_connesso")


if __name__ == "__main__":
    unittest.main()
