"""
test_shadow_refs.py — §94: l'ancora di sessione NON insegue il degrado lento.

Origine: notte 2026-08-13/14 su Abell 61 (RC8 a piena focale, CEM70). Notte
riuscita — 23 pose su 23, zero stelle perse, RMS mediano 0.694" — ma con un
degrado lento confermato da cinque strumenti indipendenti mentre il Cigno
scendeva: RMS 0.634"->0.772", jitter +12%, N1 1.00->0.82, SNR di guida 66->48,
FWHM delle light 4.35"->4.75".

Il motore ha diagnosticato SEEING nel 2.9% dei frame, e nell'ultima ora — con
tutto al peggio — UNA volta. Non perche' il jitter non salisse, ma perche' il
suo riferimento saliva piu' in fretta (+17.5% contro +12%): il rapporto restava
piatto attorno a 1.2 e non sfiorava mai la soglia di 1.6.

Il cricchetto §66/§76-bis non cura questo, ed e' stato verificato col replay:
a emivita 25 minuti e cadenza 3 s, dopo 4 ore il riferimento ha colmato il
99.9% del divario. Quel cricchetto nasce per il crollo del 4/8 (SNR 70->22 in
quattro minuti) ed e' tarato su quella scala di tempi.

Invariante difesa qui: **l'ancora scende sul calmo e non risale mai**, cosi'
un degrado piu' lento di qualunque emivita resta comunque misurabile.
"""
from __future__ import annotations

import unittest

from phd2_agent.shadow_refs import ShadowRefs


class TestAncoraNonInsegue(unittest.TestCase):
    """Il cuore del §94, con i numeri veri della notte."""

    def test_degrado_lento_resta_visibile(self):
        """Quattro ore di peggioramento graduale: il rapporto jitter/ancora deve
        CRESCERE. Con il riferimento adattivo restava piatto e il degrado era
        invisibile al proprio metro."""
        s = ShadowRefs()
        # profilo reale della notte, ora per ora (jitter mediano misurato)
        orari = [0.792, 0.810, 0.835, 0.870, 0.896]
        rapporti = []
        for jitter in orari:
            for _ in range(1200):            # ~un'ora a cadenza di guida
                s.update(jitter, jitter * 0.85)
            rapporti.append(jitter / s.jitter_anchor)

        self.assertLess(rapporti[0], 1.10, "la prima ora e' il riferimento: rapporto ~1")
        self.assertGreater(rapporti[-1], 1.12,
                           f"dopo 4 ore il degrado deve essere visibile: {rapporti}")
        self.assertEqual(rapporti, sorted(rapporti),
                         f"il rapporto deve crescere in modo monotono: {rapporti}")

    def test_ancora_non_risale_mai(self):
        """L'invariante in una riga: nessuna sequenza di peggioramenti, per quanto
        lunga, puo' alzare l'ancora."""
        s = ShadowRefs()
        s.update(0.60, 0.60)
        base = s.jitter_anchor
        for _ in range(5000):
            s.update(1.80, 1.80)
        self.assertEqual(s.jitter_anchor, base,
                         "cinquemila frame peggiori non spostano l'ancora di un capello")

    def test_miglioramento_adottato_subito(self):
        """Verso il basso nessun freno: una notte che si calma davvero deve
        riportare l'ancora al nuovo livello (regola 1 del §66)."""
        s = ShadowRefs()
        s.update(1.00, 1.00)
        for _ in range(200):
            s.update(0.50, 0.50)
        self.assertLess(s.jitter_anchor, 0.55,
                        "il miglioramento e' informazione vera e si adotta")

    def test_un_istante_fortunato_non_trascina_l_ancora(self):
        """Il rischio dichiarato del meccanismo: dieci minuti eccezionalmente calmi
        non devono far leggere tutta la notte come degradata. L'EMA a 0.05 rende
        il singolo frame quasi ininfluente."""
        s = ShadowRefs()
        for _ in range(1000):
            s.update(0.80, 0.80)
        prima = s.jitter_anchor
        s.update(0.20, 0.20)                 # un frame anomalo
        self.assertGreater(s.jitter_anchor, prima * 0.95,
                           "un solo frame non puo' riscrivere il riferimento")


class TestRobustezza(unittest.TestCase):

    def test_valori_assenti_o_nulli_non_sporcano(self):
        """Un'ancora sporcata da uno zero non e' piu' un riferimento."""
        s = ShadowRefs()
        s.update(0.80, 0.80)
        atteso = s.jitter_anchor
        for cattivo in (None, 0.0, -1.0):
            s.update(cattivo, cattivo)
        self.assertEqual(s.jitter_anchor, atteso)

    def test_prima_di_qualsiasi_dato_e_none(self):
        """Mai un valore inventato: senza frame non c'e' ancora."""
        s = ShadowRefs()
        self.assertIsNone(s.jitter_anchor)
        self.assertIsNone(s.rms_anchor)
        self.assertIsNone(s.status_block()["jitter_anchor"])

    def test_le_due_ancore_sono_indipendenti(self):
        """Jitter e RMS misurano cose diverse e non devono contaminarsi."""
        s = ShadowRefs()
        s.update(1.00, 0.50)
        s.update(0.10, 5.00)
        for _ in range(300):
            s.update(0.10, 5.00)
        self.assertLess(s.jitter_anchor, 0.5, "il jitter e' sceso")
        self.assertLessEqual(s.rms_anchor, 0.50, "l'RMS no: non deve risalire")


if __name__ == "__main__":
    unittest.main()
