"""
test_per_frame_baseline.py — Cadenza loop / baseline reale / pulizia logging (§34).

Verifica il fix sulla cadenza: la baseline e il popolamento dei campi di logging
avvengono per OGNI guide-frame (controller.ingest_frame), non solo sul tick
interval_seconds (controller.evaluate). Conseguenze attese:
  - la baseline si forma contando i guide-frame reali (kill-switch ON);
  - exposure_ms e diag_state (ultimo valido) popolati sulle righe fuori-tick;
  - evaluate() marca snapshot.evaluated=True (il tick vero);
  - kill-switch OFF -> ingest_frame e' no-op (comportamento storico per-tick).
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from phd2_agent.analyzer import AnalysisSnapshot, SeeingCondition
from phd2_agent.config import (
    AgentConfig, AutoCalibrationConfig, ControlConfig, SetupConfig, Thresholds,
)
from phd2_agent.controller import AdaptiveController, GuidingState


def _make_ctrl(per_frame=True, **ac) -> AdaptiveController:
    cfg = AgentConfig()
    cfg.control = ControlConfig(dry_run=True, interval_seconds=10.0,
                                per_frame_baseline=per_frame)
    cfg.setup = SetupConfig(profile_name="rc8", guide_pixel_scale_arcsec_native=0.508)
    cfg.thresholds = Thresholds(rms_high=1.20, rms_low=0.60)
    acfg = dict(enabled=True, baseline_window_frames=10, baseline_min_snr=10.0,
                baseline_fallback_frames=30, refresh_enabled=False)
    acfg.update(ac)
    cfg.auto_calibration = AutoCalibrationConfig(**acfg)
    ctrl = AdaptiveController(client=MagicMock(), config=cfg)
    ctrl._initialized = True
    ctrl.base_exposure_ms = 2000
    ctrl.current_exposure_ms = 2000
    return ctrl


def _snap(rms=0.5, cond=SeeingCondition.NOMINAL, snr=20.0) -> AnalysisSnapshot:
    s = AnalysisSnapshot()
    s.rms_total = rms
    s.condition = cond
    s.snr_avg = snr
    s.frame_count = 30
    return s


class TestPerFrameBaseline(unittest.TestCase):

    def test_ingest_frame_accumulates_baseline_per_frame(self):
        ctrl = _make_ctrl(per_frame=True)
        for _ in range(10):                       # 10 frame NOMINAL = finestra piena
            ctrl.ingest_frame(_snap(0.5, SeeingCondition.NOMINAL))
        self.assertEqual(ctrl._rms_baseline_value, 0.5)   # baseline formata PER-FRAME

    def test_off_ingest_frame_is_noop(self):
        ctrl = _make_ctrl(per_frame=False)
        for _ in range(20):
            ctrl.ingest_frame(_snap(0.5, SeeingCondition.NOMINAL))
        self.assertIsNone(ctrl._rms_baseline_value)        # nessun accumulo (no-op)

    def test_ingest_frame_populates_exposure_ms(self):
        ctrl = _make_ctrl(per_frame=True)
        s = _snap(0.7, SeeingCondition.UNKNOWN)
        self.assertEqual(s.exposure_ms, 0)                 # default placeholder
        ctrl.ingest_frame(s)
        self.assertEqual(s.exposure_ms, 2000)              # esposizione reale popolata

    def test_ingest_frame_populates_last_valid_diag(self):
        ctrl = _make_ctrl(per_frame=True)
        ctrl._current_diag = SimpleNamespace(
            state=SimpleNamespace(name="OVERCORRECTION"), confidence=88)
        s = _snap(0.7, SeeingCondition.UNKNOWN)
        self.assertEqual(s.diag_state, "INSUFFICIENT_DATA")   # placeholder di default
        ctrl.ingest_frame(s)
        self.assertEqual(s.diag_state, "OVERCORRECTION")      # ultimo esito valido
        self.assertEqual(s.diag_confidence, 88)

    def test_evaluate_marks_evaluated_true(self):
        ctrl = _make_ctrl(per_frame=True)
        ctrl.guiding_state = GuidingState.NORMAL
        s = _snap(0.5, SeeingCondition.NOMINAL)
        self.assertFalse(s.evaluated)
        ctrl.evaluate(s)
        self.assertTrue(s.evaluated)                       # il tick vero e' marcato

    def test_off_baseline_still_forms_via_evaluate(self):
        # Kill-switch OFF: la baseline si accumula nel percorso storico (evaluate/tick).
        ctrl = _make_ctrl(per_frame=False)
        ctrl.guiding_state = GuidingState.NORMAL
        for _ in range(10):
            ctrl.evaluate(_snap(0.5, SeeingCondition.NOMINAL))
        self.assertEqual(ctrl._rms_baseline_value, 0.5)


if __name__ == "__main__":
    unittest.main()
