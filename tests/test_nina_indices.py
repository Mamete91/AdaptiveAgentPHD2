"""
test_nina_indices.py — §45 N1: Transparency Index (Layer-2).

Verifica il principio anti soglie-assolute:
  • calo % RAPIDO del conteggio stelle vs riferimento del campo -> HAZE/CLOUD;
  • livello BASSO ma STABILE (campo povero) -> resta CLEAR (NON deve scattare);
  • cambio filtro -> riferimento si ri-forma (per-filtro);
  • confirmed_subs (trend) sale sui cali consecutivi, si azzera al recupero;
  • disabilitato / senza star detection -> graceful (None).
"""
from __future__ import annotations

import unittest

from phd2_agent.nina_indices import TransparencyTracker


def _payload(stars, filt="L", bkg=1000.0):
    img = {"star_count": stars, "filter": filt}
    if bkg is not None:
        img["median_adu"] = bkg
    return {"schema_version": 1, "source": "nina-plugin", "image": img}


def _tracker(**ov):
    return TransparencyTracker(
        enabled=ov.get("enabled", True),
        baseline_window_subs=ov.get("baseline_window_subs", 12),
        base_best_fraction=ov.get("base_best_fraction", 0.5),
        clear_above=ov.get("clear_above", 0.8),
        cloud_below=ov.get("cloud_below", 0.5),
        hysteresis=ov.get("hysteresis", 0.05),
        deadband_deficit=ov.get("deadband_deficit", 0.10),
    )


class TestStableLowFieldStaysClear(unittest.TestCase):
    def test_poor_but_stable_field_is_clear(self):
        # Campo povero (60 stelle) ma STABILE: l'assoluto è basso, ma relativo ~1 -> CLEAR.
        t = _tracker()
        for _ in range(12):
            t.ingest(_payload(60))
        b = t.status_block()
        self.assertEqual(b["state"], "CLEAR")
        self.assertGreaterEqual(b["index"], 0.95)
        self.assertEqual(t.confidence_input()["confirmed_subs"], 0)


class TestRapidDropTriggersHazeOrCloud(unittest.TestCase):
    def test_rapid_relative_drop(self):
        # Cielo limpido a 150, poi crollo rapido: il riferimento rolling-high "ricorda"
        # il limpido recente -> deficit alto -> stato peggiore di CLEAR.
        t = _tracker()
        for _ in range(10):
            t.ingest(_payload(150))
        self.assertEqual(t.status_block()["state"], "CLEAR")
        t.ingest(_payload(75))   # -50% vs riferimento ~150
        b = t.status_block()
        self.assertNotEqual(b["state"], "CLEAR")
        self.assertLessEqual(b["index"], 0.55)
        self.assertGreater(b["deficit_pct"], 40.0)

    def test_strong_sustained_drop_reaches_cloud(self):
        t = _tracker()
        for _ in range(10):
            t.ingest(_payload(150))
        for _ in range(3):
            t.ingest(_payload(55))   # ~-63% sostenuto
        self.assertEqual(t.status_block()["state"], "CLOUD")


class TestConfirmedSubsTrend(unittest.TestCase):
    def test_confirmed_increments_then_resets(self):
        t = _tracker()
        for _ in range(10):
            t.ingest(_payload(150))
        self.assertEqual(t.confidence_input()["confirmed_subs"], 0)
        t.ingest(_payload(90))    # -40% > deadband
        t.ingest(_payload(95))    # ancora sotto
        self.assertGreaterEqual(t.confidence_input()["confirmed_subs"], 2)
        t.ingest(_payload(150))   # recupero -> azzera
        self.assertEqual(t.confidence_input()["confirmed_subs"], 0)

    def test_single_anomalous_sub_does_not_persist(self):
        t = _tracker()
        for _ in range(10):
            t.ingest(_payload(150))
        t.ingest(_payload(80))    # singola posa anomala
        self.assertEqual(t.confidence_input()["confirmed_subs"], 1)   # 1, non >=2
        t.ingest(_payload(150))   # subito recuperato
        self.assertEqual(t.confidence_input()["confirmed_subs"], 0)


class TestFilterChangeReformsReference(unittest.TestCase):
    def test_filter_change_uses_own_window(self):
        t = _tracker()
        for _ in range(10):
            t.ingest(_payload(150, filt="L"))      # L: cielo ricco
        # Cambio filtro a R con conteggio naturalmente più basso (60): finestra propria
        # -> NON deve essere letto come crollo di trasparenza.
        t.ingest(_payload(60, filt="R"))
        b = t.status_block()
        self.assertEqual(b["filter"], "R")
        self.assertEqual(b["state"], "CLEAR")        # relativo al proprio filtro
        self.assertGreaterEqual(b["index"], 0.95)


class TestGraceful(unittest.TestCase):
    def test_disabled_is_noop(self):
        t = _tracker(enabled=False)
        t.ingest(_payload(150))
        self.assertIsNone(t.confidence_input())
        self.assertFalse(t.status_block()["available"])

    def test_no_star_count_ignored(self):
        t = _tracker()
        t.ingest({"schema_version": 1, "image": {"hfr": 2.0, "filter": "L"}})  # niente star_count
        self.assertIsNone(t.confidence_input())

    def test_no_data_yet(self):
        t = _tracker()
        self.assertIsNone(t.confidence_input())
        b = t.status_block()
        self.assertFalse(b["available"])
        self.assertIsNone(b["index"])


if __name__ == "__main__":
    unittest.main()
