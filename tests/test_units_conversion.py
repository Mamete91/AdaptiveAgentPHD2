"""
test_units_conversion.py — FIX unità: misura px→arcsec all'ingest (§36).

PHD2 fornisce RADistanceRaw/DECDistanceRaw in PIXEL; le soglie sono in arcsec.
ingest_guide_step(event, pixel_scale) converte la misura grezza in arcsec (× scala).
Verifiche: conversione corretta a varie scale, identità a 1.0 (e di default), una sola
moltiplicazione (linearità), il jitter eredita arcsec, parsing del kill-switch.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from phd2_agent.analyzer import StatisticsAnalyzer
from phd2_agent.config import load_config


def _step(ra, dec=0.0, snr=30.0, hfd=2.0) -> dict:
    return {"RADistanceRaw": ra, "DECDistanceRaw": dec, "SNR": snr, "HFD": hfd}


def _rms_after(scale, ra=2.0, n=3):
    an = StatisticsAnalyzer(window_size=30)
    snap = None
    for _ in range(n):
        snap = an.ingest_guide_step(_step(ra), pixel_scale=scale)
    return snap


class TestUnitsConversion(unittest.TestCase):

    def test_scale_rc8_051(self):
        self.assertAlmostEqual(_rms_after(0.51).rms_ra, 1.02, places=4)   # 2.0px × 0.51

    def test_scale_askar_158(self):
        self.assertAlmostEqual(_rms_after(1.58).rms_ra, 3.16, places=4)   # 2.0px × 1.58

    def test_scale_identity_10(self):
        self.assertAlmostEqual(_rms_after(1.0).rms_ra, 2.0, places=4)     # invariato

    def test_default_scale_is_identity(self):
        # Senza pixel_scale -> default 1.0 -> px grezzi (retrocompat dei test esistenti).
        an = StatisticsAnalyzer(window_size=30)
        snap = None
        for _ in range(3):
            snap = an.ingest_guide_step(_step(2.0))
        self.assertAlmostEqual(snap.rms_ra, 2.0, places=4)

    def test_single_conversion_is_linear(self):
        # rms(scale=0.5) deve essere esattamente rms(scale=1.0) × 0.5 (una sola × scala).
        full = _rms_after(1.0, ra=1.0).rms_ra
        half = _rms_after(0.5, ra=1.0).rms_ra
        self.assertAlmostEqual(half, full * 0.5, places=6)

    def test_jitter_inherits_arcsec(self):
        an = StatisticsAnalyzer(window_size=30)
        snap = None
        for v in (0.0, 1.0, 0.0, 1.0, 0.0):
            snap = an.ingest_guide_step(_step(v), pixel_scale=2.0)
        # ogni step = 1px × 2.0 = 2.0" -> jitter_rms = 2.0 (eredita arcsec, niente doppioni)
        self.assertAlmostEqual(snap.jitter_rms, 2.0, places=6)

    def test_runtime_scale_change(self):
        # La scala e' per-chiamata (viva): cambiandola cambia la conversione.
        an = StatisticsAnalyzer(window_size=30)
        s1 = an.ingest_guide_step(_step(2.0), pixel_scale=0.51)
        s2 = an.ingest_guide_step(_step(2.0), pixel_scale=1.58)
        # l'ultimo frame e' 3.16; la finestra contiene 1.02 e 3.16
        self.assertAlmostEqual(s2.peak_ra, 3.16, places=4)


class TestAnalyzerConfigParsing(unittest.TestCase):

    def test_default_on_when_section_absent(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.toml"
            p.write_text("[thresholds]\nrms_high = 1.2\n", encoding="utf-8")
            cfg = load_config(p)
        self.assertTrue(cfg.analyzer.convert_distance_to_arcsec)   # shipped/ default ON

    def test_parse_off(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.toml"
            p.write_text("[analyzer]\nconvert_distance_to_arcsec = false\n", encoding="utf-8")
            cfg = load_config(p)
        self.assertFalse(cfg.analyzer.convert_distance_to_arcsec)


if __name__ == "__main__":
    unittest.main()
