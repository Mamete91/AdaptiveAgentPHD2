"""
test_ancoraggio.py — §120: la baseline si calcola dal pavimento del GA.

Il difetto di partenza: la baseline era l'RMS che l'Agente osservava guidando,
cioe' il RISULTATO del proprio lavoro. Se guidava male saliva, e le soglie
salivano con lei — un metro che si allunga insieme a cio' che deve misurare.

Il pavimento del Guiding Assistant e' misurato ad anello APERTO: non contiene
niente di cio' che l'Agente ha fatto. Da li':

    baseline = pavimento_di_stanotte  (+)  contributo_del_rig

dove il primo cambia ogni sera e lo misura il GA, e il secondo e' una proprieta'
del setup che l'Agente si impara da solo.
"""
from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest.mock import MagicMock

from phd2_agent import ancoraggio
from phd2_agent.config import AgentConfig, ControlConfig, SetupConfig
from phd2_agent.controller import AdaptiveController
from phd2_agent.ga_baseline import Baseline


# ===========================================================================
#  Le funzioni pure
# ===========================================================================

class TestDecomposizione(unittest.TestCase):

    def test_scorpora_il_rig_dal_pavimento(self):
        # 0.75" osservati su un pavimento di 0.51" -> rig 0.55"
        self.assertAlmostEqual(ancoraggio.contributo_rig(0.75, 0.51), 0.5500, places=3)

    def test_e_il_giro_torna(self):
        rig = ancoraggio.contributo_rig(0.75, 0.51)
        self.assertAlmostEqual(ancoraggio.baseline_prevista(0.51, rig), 0.75, places=6)

    def test_guidato_sotto_il_pavimento_non_produce_campione(self):
        """Succede per davvero: il GA si esegue a declinazione 0 (~45 gradi di
        altezza) e se poi si riprende allo zenit il seeing e' migliore. Non e' un
        errore, e' geometria — ma non e' nemmeno un campione utilizzabile."""
        self.assertIsNone(ancoraggio.contributo_rig(0.40, 0.51))

    def test_nemmeno_appena_sopra(self):
        # entro il 2% i due sono indistinguibili: niente campione
        self.assertIsNone(ancoraggio.contributo_rig(0.515, 0.51))

    def test_ingressi_mancanti(self):
        self.assertIsNone(ancoraggio.contributo_rig(0.75, None))
        self.assertIsNone(ancoraggio.contributo_rig(None, 0.51))
        self.assertIsNone(ancoraggio.baseline_prevista(0.51, None))


class TestTetto(unittest.TestCase):
    """Il tetto su rms_high. Il vecchio `clamp(2 x scala, 0.70, 1.00)` valeva
    1.00" per QUALUNQUE scala >= 0.5"/px — cioe' per tutti."""

    FATT, MIN, MAX = 2.0, 0.70, 1.00

    def test_senza_previsione_resta_la_formula_vecchia(self):
        for scala in (0.51, 0.75, 1.05, 2.55, 3.60):
            with self.subTest(scala=scala):
                cap, ancorato = ancoraggio.cap_ancorato(None, scala, self.FATT,
                                                        self.MIN, self.MAX)
                self.assertFalse(ancorato)
                self.assertEqual(cap, 1.00)

    def test_con_la_previsione_il_tetto_assoluto_sparisce(self):
        cap, ancorato = ancoraggio.cap_ancorato(1.50, 2.55, self.FATT, self.MIN, self.MAX)
        self.assertTrue(ancorato)
        self.assertAlmostEqual(cap, 3.00)          # non piu' troncato a 1.00"

    def test_il_tetto_non_scende_mai_sotto_la_previsione(self):
        """L'errore che avevo fatto ancorandolo al solo pavimento: con pavimento
        0.26" e rig 0.55" il tetto veniva 0.52", cioe' SOTTO la baseline prevista
        di 0.61" — allarme permanente dall'altro lato."""
        for prevista in (0.30, 0.61, 1.00, 1.50, 2.40):
            with self.subTest(prevista=prevista):
                cap, _ = ancoraggio.cap_ancorato(prevista, 0.51, self.FATT,
                                                 self.MIN, self.MAX)
                self.assertGreater(cap, prevista)

    def test_continuita_sul_rig_di_riferimento(self):
        """Sul CEM70+RC8 (pavimento 0.51", rig 0.55" -> prevista 0.75") il tetto
        viene 1.50": piu' largo dell'1.00" di prima, ma la soglia derivata
        (1.3 x 0.75 = 0.98") resta sotto, quindi il comportamento non cambia."""
        cap, _ = ancoraggio.cap_ancorato(0.75, 0.508, self.FATT, self.MIN, self.MAX)
        self.assertAlmostEqual(cap, 1.50)
        self.assertLess(1.3 * 0.75, cap)


class TestStorico(unittest.TestCase):

    def setUp(self):
        self.f = pathlib.Path(tempfile.mkdtemp()) / "rig.json"
        self.s = ancoraggio.StoricoRig(self.f, massimo_campioni=5).carica()

    def test_vuoto_non_ha_valore(self):
        self.assertIsNone(self.s.valore("setup-1"))

    def test_mediana_non_minimo(self):
        """La mediana e' deliberata: col MINIMO basterebbe una notte in cui si e'
        ripreso piu' in alto del GA per incollare la costante troppo in basso."""
        for v in (0.55, 0.52, 0.90, 0.58, 0.56):
            self.s.aggiungi("setup-1", v)
        self.assertAlmostEqual(self.s.valore("setup-1"), 0.56)   # non 0.52

    def test_tiene_solo_gli_ultimi_n(self):
        for v in (1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6):
            self.s.aggiungi("setup-1", v)
        self.assertEqual(len(self.s.campioni("setup-1")), 5)
        self.assertNotIn(1.0, self.s.campioni("setup-1"))

    def test_setup_separati(self):
        self.s.aggiungi("setup-1", 0.55)
        self.s.aggiungi("setup-2", 1.40)
        self.assertAlmostEqual(self.s.valore("setup-1"), 0.55)
        self.assertAlmostEqual(self.s.valore("setup-2"), 1.40)

    def test_sopravvive_al_riavvio(self):
        self.s.aggiungi("setup-1", 0.55)
        self.assertAlmostEqual(
            ancoraggio.StoricoRig(self.f).carica().valore("setup-1"), 0.55)

    def test_file_corrotto_non_esplode(self):
        self.f.write_text("{non json", encoding="utf-8")
        self.assertIsNone(ancoraggio.StoricoRig(self.f).carica().valore("setup-1"))


# ===========================================================================
#  Il controller
# ===========================================================================

def _ctrl(scala, pavimento_arcsec, store):
    cfg = AgentConfig()
    cfg.control = ControlConfig(dry_run=True)
    cfg.setup = SetupConfig(profile_name="t", guide_pixel_scale_arcsec_native=scala)
    cfg.auto_calibration.enabled = True
    c = AdaptiveController(client=MagicMock(), config=cfg)
    c._storico_rig = ancoraggio.StoricoRig(store, massimo_campioni=5).carica()
    c._baseline_setup_id = "setup-prova"
    if pavimento_arcsec is not None:
        c._baseline = Baseline(70.0, 0.6, 100.0, 0.9, "guide_assistant", "x",
                               pavimento_totale_arcsec=pavimento_arcsec)
    return c


class TestSoglieAncorate(unittest.TestCase):

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())

    def test_prima_notte_usa_l_osservata_e_impara(self):
        c = _ctrl(0.508, 0.51, self.tmp / "a.json")
        d = c._apply_derived_thresholds(0.75)
        self.assertEqual(d["baseline_usata"], 0.75)
        self.assertFalse(c._ancoraggio_stato["ancorata"])
        c._impara_contributo_rig(0.75)
        self.assertAlmostEqual(c._storico_rig.valore("setup-prova"), 0.55, places=2)

    def test_seconda_notte_la_baseline_si_calcola(self):
        s = self.tmp / "b.json"
        _ctrl(0.508, 0.51, s)._impara_contributo_rig(0.75)
        c = _ctrl(0.508, 0.26, s)          # cielo migliore stanotte
        d = c._apply_derived_thresholds(0.75)
        self.assertTrue(c._ancoraggio_stato["ancorata"])
        self.assertAlmostEqual(d["baseline_usata"], 0.61, places=2)
        # e le soglie si stringono invece di restare incollate al vecchio tetto
        self.assertAlmostEqual(d["new_high"], 0.79, places=2)

    def test_senza_ga_niente_cambia(self):
        c = _ctrl(0.508, None, self.tmp / "c.json")
        d = c._apply_derived_thresholds(0.75)
        self.assertEqual(d["baseline_usata"], 0.75)
        self.assertFalse(d["cap_da_pavimento"])
        self.assertEqual(d["cap_efficace"], 1.00)

    def test_il_cercatore_non_e_piu_in_allarme_permanente(self):
        """Il caso che si rompeva: scala 2.55"/px, guida fisiologica a 1.50".
        Prima: rms_high 1.00" e rms_low 0.85", ENTRAMBE sotto la baseline."""
        s = self.tmp / "d.json"
        _ctrl(2.55, 1.20, s)._impara_contributo_rig(1.50)
        c = _ctrl(2.55, 1.20, s)
        d = c._apply_derived_thresholds(1.50)
        self.assertGreater(d["new_high"], 1.50)     # sopra la prestazione normale
        self.assertLess(d["new_low"], 1.50)         # e la banda la contiene
        self.assertGreater(d["cap_efficace"], 1.00)

    def test_una_notte_con_la_guida_rotta_resta_riconosciuta(self):
        """La protezione del tetto non si perde: 3.00" non deve diventare la
        nuova normalita'."""
        s = self.tmp / "e.json"
        _ctrl(0.508, 0.51, s)._impara_contributo_rig(0.75)
        c = _ctrl(0.508, 0.51, s)
        d = c._apply_derived_thresholds(3.00)
        self.assertLess(d["new_high"], 3.00)
        self.assertFalse(c._ancoraggio_stato["ancorata"])   # divergenza rilevata

    def test_la_divergenza_fa_vincere_l_osservata(self):
        s = self.tmp / "f.json"
        _ctrl(0.508, 0.51, s)._impara_contributo_rig(0.75)
        c = _ctrl(0.508, 0.51, s)
        with self.assertLogs("phd2_agent.controller", level="WARNING"):
            d = c._apply_derived_thresholds(3.00)
        self.assertEqual(d["baseline_usata"], 3.00)
        self.assertIn("divergenza", c._ancoraggio_stato["motivo"])

    def test_interruttore_spento_comportamento_di_ieri(self):
        s = self.tmp / "g.json"
        _ctrl(0.508, 0.51, s)._impara_contributo_rig(0.75)
        c = _ctrl(0.508, 0.26, s)
        c.cfg.auto_calibration.ancoraggio_ga_enabled = False
        d = c._apply_derived_thresholds(0.75)
        self.assertEqual(d["baseline_usata"], 0.75)
        self.assertEqual(d["cap_efficace"], 1.00)

    def test_niente_campione_se_si_guida_sotto_il_pavimento(self):
        c = _ctrl(0.508, 0.51, self.tmp / "h.json")
        with self.assertLogs("phd2_agent.controller", level="INFO"):
            c._impara_contributo_rig(0.40)
        self.assertIsNone(c._storico_rig.valore("setup-prova"))


if __name__ == "__main__":
    unittest.main()
