"""
test_context_columns.py — §101 (Stadio A): ogni riga dice a chi appartiene.

Il modello di trasparenza e' indicizzato per `(target, filtro)` — e' la chiave di
`_stars_by_filter`, `_ref_stars_by_filter`, `_best_stars_by_filter`. Ma il CSV
non registrava nessuna delle due: quarantaquattro colonne di misure di cui non
si sapeva a chi appartenessero.

Non e' un difetto teorico. Per ricostruire la notte ciclica 21-22/8 (sequenza
O H S R G B L, tre cicli) ho dovuto parsare il log di NINA e riallineare a mano
i blocchi filtro con il CSV dell'Agente. Il replay del modello di memoria — a
cui le linee guida ci impegnano — era **impossibile dal solo CSV**.

Costo zero: `status_block()` esponeva gia' entrambe.

Nota sull'invariante. Per il §100 il test difensivo era "questi nomi non
compaiono nel controller". Qui **non si applica**: `target` e `filter` sono
concetti interni legittimi, il tracker ci costruisce sopra le proprie chiavi.
L'invariante vero e' un altro, ed e' quello verificato qui sotto: le colonne
sono un **passaggio diretto** di cio' che il tracker dichiara, senza
trasformazioni, e la loro assenza non rompe nulla.
"""
from __future__ import annotations

import csv as _csv
import tempfile
import unittest
from collections import defaultdict
from types import SimpleNamespace

from phd2_agent.logger import SessionLogger, _CSV_FIELDS
from phd2_agent.nina_indices import TransparencyTracker


class _Orologio:
    def __init__(self):
        self.t = 1_700_000_000.0

    def __call__(self):
        return self.t

    def avanza(self, minuti):
        self.t += minuti * 60.0


def _posa(stelle, filtro, target="NGC 6888", fondo=120.0):
    return {"image": {"star_count": stelle, "median_adu": fondo, "filter": filtro,
                      "hfr": 3.0, "image_type": "LIGHT"},
            "context": {"target": target}}


def _snapshot(tracker=None):
    """Riproduce il percorso vero: `star_count` arriva al CSV dallo SNAPSHOT
    (il controller lo copia da `_nina_shadow_block()`, controller.py:1228),
    mentre target/filter/bkg li legge il logger direttamente dal tracker.
    Due strade per la stessa sorgente: il banco di prova deve rispettarle."""
    from phd2_agent.analyzer import AnalysisSnapshot, SeeingCondition
    s = AnalysisSnapshot()
    s.condition = SeeingCondition.NOMINAL
    s.rms_total = 0.7
    s.frame_count = 30
    if tracker is not None:
        b = tracker.status_block()
        s.star_count = b.get("star_count")
        s.hfr_nina = b.get("hfr")
        s.airmass = b.get("airmass")
    return s


def _logger(d, tracker):
    lg = SessionLogger(csv_dir=d)
    lg.bind_controller(SimpleNamespace(
        transparency_tracker=tracker, diagnostic_engine=None,
        cfg=SimpleNamespace(thresholds=SimpleNamespace(rms_high=0.8, rms_low=0.35))))
    return lg


class TestColonneDiContesto(unittest.TestCase):

    def test_esistono(self):
        for c in ("target", "filter"):
            self.assertIn(c, _CSV_FIELDS, f"colonna {c} assente")

    def test_precedono_le_misure_che_indicizzano(self):
        """Collocazione voluta: il blocco si legge come 'questo target, con
        questo filtro, ha misurato questi valori'."""
        for misura in ("star_count", "bkg", "base_stars", "hfr_nina"):
            self.assertLess(_CSV_FIELDS.index("target"), _CSV_FIELDS.index(misura))
            self.assertLess(_CSV_FIELDS.index("filter"), _CSV_FIELDS.index(misura))

    def test_riportano_esattamente_cio_che_il_tracker_dichiara(self):
        c = _Orologio()
        t = TransparencyTracker(enabled=True, now_fn=c)
        t.ingest(_posa(1400, "L"))
        with tempfile.TemporaryDirectory() as d:
            lg = _logger(d, t)
            lg.log_snapshot(_snapshot(t), [])
            lg.close()
            with open(lg._csv_path, encoding="utf-8") as fh:
                riga = list(_csv.DictReader(fh))[-1]
        b = t.status_block()
        self.assertEqual(riga["target"], b["target"])
        self.assertEqual(riga["filter"], b["filter"])

    def test_senza_tracker_restano_vuote_senza_rompere(self):
        with tempfile.TemporaryDirectory() as d:
            lg = _logger(d, None)
            lg.log_snapshot(_snapshot(), [])
            lg.close()
            with open(lg._csv_path, encoding="utf-8") as fh:
                riga = list(_csv.DictReader(fh))[-1]
        self.assertEqual(riga["target"], "")
        self.assertEqual(riga["filter"], "")


class TestIlReplayDiventaPossibile(unittest.TestCase):
    """Il motivo per cui il §101 esiste, riprodotto in piccolo."""

    def test_dal_solo_csv_si_ricostruisce_la_serie_per_filtro(self):
        """Sequenza ciclica come quella reale: senza `filter` nel CSV questa
        ricostruzione richiedeva il log di NINA. Ora basta il CSV."""
        c = _Orologio()
        t = TransparencyTracker(enabled=True, now_fn=c)
        stelle = {"O": 579, "H": 436, "S": 682, "R": 1189,
                  "G": 1250, "B": 1149, "L": 1402}
        with tempfile.TemporaryDirectory() as d:
            lg = _logger(d, t)
            for ciclo in range(2):
                for filtro in ["O", "H", "S", "R", "G", "B", "L"]:
                    t.ingest(_posa(stelle[filtro], filtro))
                    lg.log_snapshot(_snapshot(t), [])
                    c.avanza(15.0)
            lg.close()
            with open(lg._csv_path, encoding="utf-8") as fh:
                righe = list(_csv.DictReader(fh))

        serie = defaultdict(list)
        for r in righe:
            if r["filter"]:
                serie[(r["target"], r["filter"])].append(float(r["star_count"] or 0))

        self.assertEqual(len(serie), 7, "una serie per filtro, tutte sotto lo stesso target")
        for filtro, atteso in stelle.items():
            v = serie[("NGC 6888", filtro)]
            self.assertEqual(len(v), 2, f"{filtro}: due visite, una per ciclo")
            self.assertEqual(v[0], atteso, f"{filtro}: il conteggio e' quello di quel filtro")

    def test_il_cambio_target_e_visibile_nella_riga(self):
        """Il target e' l'altra meta' della chiave: un campo nuovo deve
        distinguersi, altrimenti le sue misure finirebbero nella serie del
        campo precedente."""
        c = _Orologio()
        t = TransparencyTracker(enabled=True, now_fn=c)
        with tempfile.TemporaryDirectory() as d:
            lg = _logger(d, t)
            t.ingest(_posa(1400, "L", target="NGC 6888"))
            lg.log_snapshot(_snapshot(t), [])
            c.avanza(20.0)
            t.ingest(_posa(900, "L", target="Abell 61"))
            lg.log_snapshot(_snapshot(t), [])
            lg.close()
            with open(lg._csv_path, encoding="utf-8") as fh:
                righe = list(_csv.DictReader(fh))

        targets = [r["target"] for r in righe if r["target"]]
        self.assertEqual(targets[0], "NGC 6888")
        self.assertEqual(targets[-1], "Abell 61")


if __name__ == "__main__":
    unittest.main()
