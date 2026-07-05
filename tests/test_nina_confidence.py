"""
test_nina_confidence.py — §46 N8: fusione confidence con la trasparenza NINA.

Verifica:
  • penalità PROPORZIONALE al calo % (dead-band -> lieve -> forte), monotòna;
  • seeing vero + velo lieve -> confidence scende di poco -> motore PUÒ ancora agire;
  • crollo trasparenza -> confidence sotto soglia -> motore si astiene;
  • SOLO sul SEEING: OVERCORRECTION/DRIFT NON modulati;
  • persistenza >= nina_persist_subs (singola posa non penalizza);
  • graceful / kill-switch (confidence_use_nina=false o provider None) = pre-§46;
  • fail-safe: NINA non aumenta MAI la confidence.
"""
from __future__ import annotations

import unittest

from phd2_agent.analyzer import AnalysisSnapshot, SeeingCondition
from phd2_agent.config import DiagnosticEngineConfig
from phd2_agent.diagnostic_engine import SeeingDiagnosticEngine, DiagnosisState


def _snap(rms_total=0.2, hfd_avg=2.0, jitter_rms=0.1, jitter_n=29,
          lag1_ra=0.0, lag1_dec=0.0, trend_ra=0.0, trend_dec=0.0,
          frame_count=30, condition=SeeingCondition.UNKNOWN) -> AnalysisSnapshot:
    s = AnalysisSnapshot()
    s.frame_count = frame_count
    s.rms_total = rms_total
    s.hfd_avg = hfd_avg
    s.jitter_rms = jitter_rms
    s.jitter_n = jitter_n
    s.lag1_ra = lag1_ra
    s.lag1_dec = lag1_dec
    s.trend_ra = trend_ra
    s.trend_dec = trend_dec
    s.condition = condition
    return s


def _engine(provider, **cfg_over):
    cfg_over.setdefault("confidence_use_nina", True)
    cfg = DiagnosticEngineConfig(enabled=True, mode="guardian", **cfg_over)
    eng = SeeingDiagnosticEngine(
        cfg,
        thresholds_provider=lambda: (0.8, 0.35),
        baseline_provider=lambda: None,
        transparency_provider=provider,
    )
    # forma jitter_ref con frame calmi
    for _ in range(max(2, cfg.refs_warmup_frames)):
        eng.classify(_snap(rms_total=0.2, jitter_rms=0.1, condition=SeeingCondition.NOMINAL))
    return eng


def _transp(deficit, confirmed=3, index=None, state="HAZE"):
    return lambda: {"deficit": deficit, "confirmed_subs": confirmed,
                    "index": (1.0 - deficit) if index is None else index, "state": state}


# SEEING snapshot: rms>rms_high, jitter alto, no oscillazione.
def _seeing():
    return _snap(rms_total=1.0, jitter_rms=0.3, hfd_avg=3.0)


_BASE_SEEING_CONF = 76   # 40 + 18*2 (hfd_gates=false -> 2 segnali)


class TestProportionalPenalty(unittest.TestCase):
    def test_deadband_light_moderate_strong_monotone(self):
        light = _engine(_transp(0.07)).classify(_seeing())     # dentro dead-band
        moderate = _engine(_transp(0.27)).classify(_seeing())
        strong = _engine(_transp(0.47)).classify(_seeing())    # oltre full_deficit
        self.assertEqual(light.confidence, _BASE_SEEING_CONF)   # penalità trascurabile
        self.assertLess(moderate.confidence, light.confidence)
        self.assertLess(strong.confidence, moderate.confidence)
        # tutte SEEING e calibrate
        for r in (light, moderate, strong):
            self.assertEqual(r.state, DiagnosisState.SEEING)
            self.assertTrue(r.confidence_calibrated)
        # forte -> penalità massima (40) -> 76-40=36
        self.assertEqual(strong.confidence, _BASE_SEEING_CONF - 40)


class TestSeeingPlusLightVeilStillActs(unittest.TestCase):
    def test_light_veil_keeps_above_gate(self):
        r = _engine(_transp(0.07)).classify(_seeing())
        self.assertEqual(r.state, DiagnosisState.SEEING)
        self.assertGreaterEqual(r.confidence, 60)   # guardian_min_confidence default


class TestTransparencyCollapseAbstains(unittest.TestCase):
    def test_collapse_drops_below_gate(self):
        r = _engine(_transp(0.47)).classify(_seeing())
        self.assertLess(r.confidence, 60)           # sotto il gate -> il motore si astiene


class TestOnlySeeingModulated(unittest.TestCase):
    def test_overcorrection_not_modulated(self):
        # lag-1 fortemente negativo -> OVERCORRECTION; provider con crollo forte.
        eng = _engine(_transp(0.47))
        r = eng.classify(_snap(rms_total=0.6, lag1_ra=-0.9, lag1_dec=-0.9, hfd_avg=2.0))
        self.assertEqual(r.state, DiagnosisState.OVERCORRECTION)
        self.assertFalse(r.confidence_calibrated)        # NINA non tocca
        self.assertNotIn("nina_penalty", r.metrics)

    def test_drift_not_modulated(self):
        eng = _engine(_transp(0.47))
        r = eng.classify(_snap(rms_total=0.6, lag1_ra=0.5, lag1_dec=0.5, trend_ra=0.1))
        self.assertEqual(r.state, DiagnosisState.DRIFT)
        self.assertFalse(r.confidence_calibrated)
        self.assertNotIn("nina_penalty", r.metrics)


class TestPersistence(unittest.TestCase):
    def test_single_sub_no_penalty(self):
        r = _engine(_transp(0.40, confirmed=1)).classify(_seeing())   # confermato 1 < 2
        self.assertEqual(r.confidence, _BASE_SEEING_CONF)
        self.assertTrue(r.confidence_calibrated)          # comunque calibrata (NINA fresca)

    def test_confirmed_applies(self):
        r = _engine(_transp(0.40, confirmed=2)).classify(_seeing())
        self.assertLess(r.confidence, _BASE_SEEING_CONF)


class TestGracefulAndKillSwitch(unittest.TestCase):
    def test_provider_none_is_pre_n8(self):
        r = _engine(lambda: None).classify(_seeing())
        self.assertEqual(r.confidence, _BASE_SEEING_CONF)
        self.assertFalse(r.confidence_calibrated)
        self.assertNotIn("nina_penalty", r.metrics)

    def test_kill_switch_off(self):
        r = _engine(_transp(0.47), confidence_use_nina=False).classify(_seeing())
        self.assertEqual(r.confidence, _BASE_SEEING_CONF)
        self.assertFalse(r.confidence_calibrated)


class TestFailSafeNeverRaises(unittest.TestCase):
    def test_penalty_never_increases_confidence(self):
        for d in (0.0, 0.07, 0.2, 0.27, 0.4, 0.47, 0.9):
            r = _engine(_transp(d)).classify(_seeing())
            self.assertLessEqual(r.confidence, _BASE_SEEING_CONF)


if __name__ == "__main__":
    unittest.main()
