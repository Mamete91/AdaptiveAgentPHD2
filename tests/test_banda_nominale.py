"""
test_banda_nominale.py — §106, il recinto attorno al nominale.

Il nominale (§104) dice DA DOVE si parte; la banda dice QUANTO ci si puo'
allontanare. E' una regola, non un giudizio: nessuna diagnosi, nessuna confidenza,
si verifica con una sottrazione.

Nasce da una misura, non da un'intuizione. Nella sessione 22-23/8 il Guardian ha
prodotto **294 CONFIRM, 0 ATTENUATE, 0 BLOCK**, con la motivazione "diagnosi non
confidente -> CONFIRM (fail-safe)": nel 78% dei tick la diagnosi e' UNCERTAIN, e la
via di sicurezza e' l'unica percorsa. Il 24/8, con la stella persa per meta' notte,
l'aggressivita' RA e' comunque scesa da 70 al pavimento 35 e il MinMove e' salito
del 33% sopra il valore misurato: nessun componente aveva il compito di fermarli.

La semantica e' un CRICCHETTO, non una molla: un valore gia' fuori banda non viene
strattonato dentro — gli si impedisce solo di allontanarsi ancora.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from phd2_agent.config import (AgentConfig, AxisLimits, BandaNominaleConfig,
                               ControlConfig, SetupConfig)
from phd2_agent.controller import AdaptiveController


def _ctrl(banda=True, minmove_px=0.20, aggr_punti=20.0,
          nominale=(70.0, 0.6175)) -> AdaptiveController:
    """Controller con il nominale del GA reale del 24/08/2026 (RA 0.6175 / aggr 70)."""
    cfg = AgentConfig()
    cfg.control = ControlConfig(dry_run=True)
    ax = dict(aggr_min=35, aggr_max=100, aggr_step_down=5, aggr_step_up=2,
              minmove_min=0.15, minmove_max=1.20, minmove_step=0.05)
    cfg.ra = AxisLimits(**ax)
    cfg.dec = AxisLimits(**ax)
    cfg.setup = SetupConfig(profile_name="test", guide_pixel_scale_arcsec_native=0.508)
    cfg.banda = BandaNominaleConfig(enabled=banda, minmove_px=minmove_px,
                                    aggr_punti=aggr_punti)
    c = AdaptiveController(client=MagicMock(), config=cfg)
    c._initialized = True
    c._nominal = {"ra": nominale, "dec": nominale}
    for a in (c._ra, c._dec):
        a.aggr_param = "aggression"
        a.aggr_native_scale = 0.01
        a.minmove_param = "minMove"
        a.current_aggr = nominale[0]
        a.current_minmove = nominale[1]
    return c


class TestMinMove(unittest.TestCase):

    def test_dentro_la_banda_passa(self):
        c = _ctrl()
        # nominale 0.6175, banda +/-0.20 -> [0.4175, 0.8175]
        self.assertAlmostEqual(
            c._entro_la_banda(c._ra, 0.6175, 0.75, is_minmove=True), 0.75)

    def test_oltre_la_banda_viene_limitato(self):
        c = _ctrl()
        self.assertAlmostEqual(
            c._entro_la_banda(c._ra, 0.6175, 0.95, is_minmove=True), 0.8175)

    def test_il_caso_reale_del_24_agosto(self):
        """Il MinMove RA era arrivato a 0.818 partendo dal misurato 0.6175, in una
        notte con la stella persa per meta' del tempo."""
        c = _ctrl()
        limitato = c._entro_la_banda(c._ra, 0.768, 0.818, is_minmove=True)
        self.assertAlmostEqual(limitato, 0.8175)

    def test_verso_il_basso_stesso_limite(self):
        c = _ctrl()
        self.assertAlmostEqual(
            c._entro_la_banda(c._ra, 0.6175, 0.20, is_minmove=True), 0.4175)


class TestAggressivita(unittest.TestCase):
    """Il GA non caratterizza l'aggressivita': il nominale resta il default PHD2.
    Proprio per questo il recinto le serve di piu' — l'ancora e' meno solida."""

    def test_dentro_la_banda_passa(self):
        c = _ctrl()
        self.assertAlmostEqual(c._entro_la_banda(c._ra, 70.0, 60.0, is_minmove=False), 60.0)

    def test_il_caso_reale_del_24_agosto(self):
        """L'aggressivita' RA era scesa da 70 al pavimento 35: la banda la ferma a 50."""
        c = _ctrl()
        self.assertAlmostEqual(c._entro_la_banda(c._ra, 55.0, 35.0, is_minmove=False), 50.0)

    def test_verso_l_alto_stesso_limite(self):
        c = _ctrl()
        self.assertAlmostEqual(c._entro_la_banda(c._ra, 70.0, 100.0, is_minmove=False), 90.0)


class TestCricchettoNonMolla(unittest.TestCase):
    """Un valore gia' fuori banda non viene strattonato dentro."""

    def test_non_puo_allontanarsi_ancora(self):
        c = _ctrl()
        # gia' a 0.95, ben oltre il bordo 0.8175: la richiesta di salire e' fermata li'
        self.assertAlmostEqual(
            c._entro_la_banda(c._ra, 0.95, 1.10, is_minmove=True), 0.95)

    def test_puo_sempre_avvicinarsi(self):
        c = _ctrl()
        self.assertAlmostEqual(
            c._entro_la_banda(c._ra, 0.95, 0.90, is_minmove=True), 0.90)

    def test_puo_rientrare_del_tutto(self):
        c = _ctrl()
        self.assertAlmostEqual(
            c._entro_la_banda(c._ra, 0.95, 0.6175, is_minmove=True), 0.6175)

    def test_non_viene_tirato_dentro_da_solo(self):
        """Il valore fuori banda resta dov'e' finche' qualcuno non lo muove."""
        c = _ctrl()
        self.assertAlmostEqual(
            c._entro_la_banda(c._ra, 0.95, 0.95, is_minmove=True), 0.95)


class TestInterazioni(unittest.TestCase):

    def test_disabilitata_e_trasparente(self):
        c = _ctrl(banda=False)
        self.assertAlmostEqual(
            c._entro_la_banda(c._ra, 0.6175, 5.0, is_minmove=True), 5.0)

    def test_raggio_zero_e_trasparente(self):
        c = _ctrl(minmove_px=0.0)
        self.assertAlmostEqual(
            c._entro_la_banda(c._ra, 0.6175, 5.0, is_minmove=True), 5.0)

    def test_segue_il_nominale_non_una_costante(self):
        """Cambiando la caratterizzazione, il recinto si sposta con lei."""
        c = _ctrl(nominale=(100.0, 0.95))
        self.assertAlmostEqual(
            c._entro_la_banda(c._dec, 0.95, 1.30, is_minmove=True), 1.15)

    def test_apply_rispetta_la_banda(self):
        c = _ctrl()
        azione = c._apply(c._ra, c.cfg.ra, "minMove", 0.6175, 0.95,
                          "prova", is_minmove=True, softening_source="SEEING")
        self.assertAlmostEqual(azione.new_value, 0.8175)

    def test_apply_conserva_l_attribuzione_quando_ferma(self):
        """Se la banda annulla la richiesta, l'azione torna comunque con la sua
        sorgente: "proposto e fermato" e' un fatto che deve restare nei log."""
        c = _ctrl()
        azione = c._apply(c._ra, c.cfg.ra, "minMove", 0.8175, 0.90,
                          "prova", is_minmove=True, softening_source="SEEING")
        self.assertAlmostEqual(azione.new_value, 0.8175)
        self.assertEqual(azione.softening_source, "SEEING")
        self.assertIn("banda", azione.reason)

    def test_bypass_per_il_ripristino_utente(self):
        """Il ripristino dei valori salvati dell'utente deve poter uscire dalla
        banda: e' un ritorno alla sua configurazione, non un adattamento."""
        c = _ctrl()
        azione = c._apply(c._ra, c.cfg.ra, "minMove", 0.6175, 1.10,
                          "ripristino", is_minmove=True, bypass_banda=True)
        self.assertAlmostEqual(azione.new_value, 1.10)



class TestEscalationGate(unittest.TestCase):
    """§106 — il recinto NON deve chiudere l'escalation gate.

    Difetto trovato da Alessandro subito dopo la prima build: la saturazione delle
    leve si confrontava con i limiti STATICI (aggr_min 35, minmove_max 1.20), che
    con il recinto non sono piu' raggiungibili. Risultato: gate chiuso per sempre e
    Path B (aumento esposizione a seeing degradato) codice morto.
    """

    def _al_bordo(self, banda=True):
        c = _ctrl(banda=banda)
        c._ra.current_aggr = 50.0        # bordo del recinto (70 - 20)
        c._ra.current_minmove = 0.8175   # bordo del recinto (0.6175 + 0.20)
        c._ra.last_action_time = 0.0
        c._ra.last_minmove_action_time = 0.0
        return c

    def test_limiti_effettivi_seguono_il_recinto(self):
        c = _ctrl()
        aggr_min, mm_max = c._limiti_effettivi(c._ra, c.cfg.ra)
        self.assertAlmostEqual(aggr_min, 50.0)
        self.assertAlmostEqual(mm_max, 0.8175)

    def test_limiti_effettivi_senza_recinto_sono_quelli_statici(self):
        c = _ctrl(banda=False)
        aggr_min, mm_max = c._limiti_effettivi(c._ra, c.cfg.ra)
        self.assertAlmostEqual(aggr_min, 35.0)
        self.assertAlmostEqual(mm_max, 1.20)

    def test_gate_si_apre_al_bordo_del_recinto(self):
        """Il caso del 24/08: le leve erano finite proprio li'."""
        c = self._al_bordo()
        self.assertTrue(c._axis_levers_saturated(c._ra, c.cfg.ra))

    def test_gate_chiuso_se_le_leve_hanno_ancora_margine(self):
        c = self._al_bordo()
        c._ra.current_minmove = 0.70     # dentro il recinto
        self.assertFalse(c._axis_levers_saturated(c._ra, c.cfg.ra))

    def test_il_cap_adattivo_puo_stringere_ancora(self):
        """§51 — se il cap e' piu' stretto del recinto, e' lui a definire il bordo."""
        c = _ctrl()
        c._minmove_baseline_ema = 0.45        # cap_arcsec 0.36 -> cap_px ~0.71
        _, mm_max = c._limiti_effettivi(c._ra, c.cfg.ra)
        self.assertLess(mm_max, 0.8175)
        self.assertGreaterEqual(mm_max, c._nominal["ra"][1])   # mai sotto il nominale

if __name__ == "__main__":
    unittest.main()
