"""
test_sky_background_logging.py — §100: si registra cio' che il motore gia' calcola.

Origine. Analizzando la notte ciclica 21-22/8 ho dovuto ricostruire il
riferimento di trasparenza per via indiretta — `riferimento = stelle / indice`,
identita' valida solo se il fattore di fondo cielo vale 1 — e stabilire
l'influenza della Luna calcolando un'effemeride dalle coordinate
dell'osservatore. Entrambe le fatiche erano evitabili: il tracker **conosce
gia'** il fondo cielo misurato e il proprio riferimento, li usa a ogni posa per
calcolare l'indice, e non li scriveva da nessuna parte.

Cinque colonne, nessuna logica toccata. Rendono rispondibile la domanda che
separa la trasparenza da tutto il resto:

    stelle in calo + fondo cielo che SALE   -> diffusione, probabile velatura
    stelle in calo + fondo cielo COSTANTE   -> non e' trasparenza

Invariante difesa qui: le colonne esistono, sono POPOLATE con i valori veri del
tracker, e nessuna decisione le legge. E' la disciplina del §94 — prima si
misura in ombra, poi si decide — applicata a una misura che non serviva
nemmeno inventare.
"""
from __future__ import annotations

import csv as _csv
import tempfile
import unittest
from types import SimpleNamespace

from phd2_agent.logger import SessionLogger, _CSV_FIELDS
from phd2_agent.nina_indices import TransparencyTracker

NUOVE = ("bkg", "base_bkg", "base_stars", "base_stars_session_best", "ref_drift_pct")


class _Orologio:
    def __init__(self):
        self.t = 1_700_000_000.0

    def __call__(self):
        return self.t

    def avanza(self, minuti):
        self.t += minuti * 60.0


def _posa(stelle, fondo, filtro="L", target="NGC 6888"):
    return {"image": {"star_count": stelle, "median_adu": fondo, "filter": filtro,
                      "hfr": 3.0, "image_type": "LIGHT"},
            "context": {"target": target}}


def _snapshot():
    from phd2_agent.analyzer import AnalysisSnapshot, SeeingCondition
    s = AnalysisSnapshot()
    s.condition = SeeingCondition.NOMINAL
    s.rms_total = 0.7
    s.rms_ra = 0.5
    s.rms_dec = 0.4
    s.frame_count = 30
    return s


class TestColonneEsistono(unittest.TestCase):

    def test_le_cinque_colonne_sono_nello_schema(self):
        for c in NUOVE:
            self.assertIn(c, _CSV_FIELDS, f"colonna {c} assente")

    def test_stanno_col_gruppo_in_ombra_non_fra_le_decisioni(self):
        """Collocazione voluta: accanto alle altre colonne che nessuno legge
        (§94), prima della diagnosi. Non e' estetica — e' il confine fra cio'
        che si osserva e cio' che decide."""
        self.assertLess(_CSV_FIELDS.index("airmass"), _CSV_FIELDS.index("bkg"))
        self.assertLess(_CSV_FIELDS.index("ref_drift_pct"),
                        _CSV_FIELDS.index("diag_state"))

    def test_il_tracker_espone_il_riferimento_del_fondo(self):
        """`base_bkg` era una variabile locale: senza, `bkg_factor` resta
        ricavabile solo per inversione — impossibile quando l'indice satura
        a 1.00, che e' proprio il caso di una notte serena."""
        c = _Orologio()
        t = TransparencyTracker(enabled=True, now_fn=c)
        t.ingest(_posa(1400, 120.0))
        b = t.status_block()
        self.assertIn("base_bkg", b)
        self.assertIsNotNone(b["base_bkg"])


class TestColonnePopolate(unittest.TestCase):
    """Che esistano non basta: devono portare i numeri veri del tracker."""

    def _sessione(self, pose):
        c = _Orologio()
        t = TransparencyTracker(enabled=True, now_fn=c)
        for stelle, fondo in pose:
            t.ingest(_posa(stelle, fondo))
            c.avanza(3.0)
        with tempfile.TemporaryDirectory() as d:
            lg = SessionLogger(csv_dir=d)
            lg.bind_controller(SimpleNamespace(
                transparency_tracker=t,
                diagnostic_engine=None,
                cfg=SimpleNamespace(thresholds=SimpleNamespace(
                    rms_high=0.8, rms_low=0.35))))
            lg.log_snapshot(_snapshot(), [])
            lg.close()
            with open(lg._csv_path, encoding="utf-8") as fh:
                righe = list(_csv.DictReader(fh))
        return t.status_block(), righe[-1]

    def test_i_valori_scritti_sono_quelli_del_tracker(self):
        blocco, riga = self._sessione([(1400, 120.0)] * 3)
        self.assertEqual(float(riga["bkg"]), float(blocco["bkg"]))
        self.assertEqual(float(riga["base_stars"]), float(blocco["base_stars"]))
        self.assertEqual(float(riga["base_bkg"]), float(blocco["base_bkg"]))

    def test_il_caso_che_ha_motivato_tutto(self):
        """Stelle in calo: dal solo conteggio non si sa perche'. Con il fondo
        cielo accanto, la riga si interpreta da sola."""
        blocco, riga = self._sessione(
            [(1400, 120.0)] * 3 + [(900, 260.0)] * 3)   # stelle giu', fondo su
        self.assertGreater(float(riga["bkg"]), float(riga["base_bkg"]),
                           "il fondo e' salito sopra il proprio riferimento")
        self.assertLess(float(riga["base_stars"]), 1500)
        self.assertGreater(float(riga["base_stars"]), 900,
                           "il riferimento stelle non ha ancora inseguito il calo")

    def test_senza_tracker_le_colonne_restano_vuote_senza_rompere(self):
        """Chi non usa NINA non deve vedere un errore: colonne vuote."""
        with tempfile.TemporaryDirectory() as d:
            lg = SessionLogger(csv_dir=d)
            lg.bind_controller(SimpleNamespace(
                transparency_tracker=None, diagnostic_engine=None,
                cfg=SimpleNamespace(thresholds=SimpleNamespace(
                    rms_high=0.8, rms_low=0.35))))
            lg.log_snapshot(_snapshot(), [])
            lg.close()
            with open(lg._csv_path, encoding="utf-8") as fh:
                riga = list(_csv.DictReader(fh))[-1]
        for c in NUOVE:
            self.assertEqual(riga[c], "", f"{c} doveva restare vuota")


class TestNessunaDecisioneLeLegge(unittest.TestCase):
    """Il vincolo dichiarato: e' strumentazione, non algoritmo."""

    def test_il_controller_non_consuma_le_colonne_nuove(self):
        import inspect
        from phd2_agent import controller
        src = inspect.getsource(controller)
        for c in ("base_stars_session_best", "ref_drift_pct", "base_bkg"):
            self.assertNotIn(c, src,
                             f"{c} e' comparso nel controller: non deve decidere nulla")


if __name__ == "__main__":
    unittest.main()
