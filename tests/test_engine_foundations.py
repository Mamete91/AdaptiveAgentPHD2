"""
test_engine_foundations.py — §50 INIT ai valori standard PHD2 + §51 cap MinMove adattivo.
"""
from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock

from phd2_agent.analyzer import AnalysisSnapshot, SeeingCondition
from phd2_agent.config import (
    AgentConfig, AxisLimits, ControlConfig, MinMoveCapConfig, SetupConfig, Thresholds,
    LeverOptimizationConfig,
)
from phd2_agent.controller import AdaptiveController


def _ctrl(init_std=True, cap_enabled=True, scale=0.5) -> AdaptiveController:
    cfg = AgentConfig()
    cfg.control = ControlConfig(dry_run=True, cooldown_seconds=30.0,
                                init_to_phd2_standard=init_std)
    cfg.thresholds = Thresholds(rms_high=0.80, rms_low=0.35, snr_low=10.0,
                                spike_ratio_high=0.30, consecutive_frames=5)
    ax = dict(aggr_min=35, aggr_max=100, aggr_step_down=5, aggr_step_up=2,
              minmove_min=0.15, minmove_max=0.85, minmove_step=0.05)
    cfg.ra = AxisLimits(**ax)
    cfg.dec = AxisLimits(**ax)
    cfg.setup = SetupConfig(profile_name="test", guide_pixel_scale_arcsec_native=scale)
    cfg.lever_optimization = LeverOptimizationConfig(enabled=True, target_factor=1.0)
    cfg.minmove_cap = MinMoveCapConfig(enabled=cap_enabled, baseline_factor=0.8,
                                       imaging_ceiling_arcsec=2.0, filter_tau_minutes=18.0)
    ctrl = AdaptiveController(client=MagicMock(), config=cfg)
    ctrl._initialized = True
    for a in (ctrl._ra, ctrl._dec):
        a.aggr_param = "aggression"       # famiglia Hysteresis/Resist Switch (fractional)
        a.aggr_native_scale = 0.01
        a.minmove_param = "minMove"
        a.current_aggr = 50.0
        a.current_minmove = 0.50
        a.last_action_time = 0.0
        a.last_minmove_action_time = 0.0
    ctrl._rms_baseline_value = 0.5
    ctrl._rms_baseline_rejected = False
    return ctrl


# ---------------- §50 INIT ai valori standard ----------------

class TestInitStandard(unittest.TestCase):
    def test_applies_standard_values(self):
        ctrl = _ctrl(init_std=True)
        ctrl._init_to_phd2_standard()
        self.assertEqual(ctrl._ra.current_aggr, 70.0)      # RA Hysteresis
        self.assertEqual(ctrl._ra.current_minmove, 0.20)
        self.assertEqual(ctrl._dec.current_aggr, 100.0)    # DEC Resist Switch
        self.assertEqual(ctrl._dec.current_minmove, 0.20)

    def test_skips_nonstandard_algorithm(self):
        ctrl = _ctrl(init_std=True)
        ctrl._ra.aggr_native_scale = 1.0   # Lowpass2 'aggressiveness' 0-100 (scala diversa)
        ctrl._init_to_phd2_standard()
        self.assertEqual(ctrl._ra.current_aggr, 50.0)      # SALTATO (nessun valore a scala sbagliata)
        self.assertEqual(ctrl._ra.current_minmove, 0.50)
        self.assertEqual(ctrl._dec.current_aggr, 100.0)    # DEC (standard) applicato comunque

    def test_killswitch_off_inherits(self):
        ctrl = _ctrl(init_std=False)
        ctrl._init_to_phd2_standard()
        self.assertEqual(ctrl._ra.current_aggr, 50.0)      # eredita i valori correnti
        self.assertEqual(ctrl._ra.current_minmove, 0.50)


# ---------------- §51 cap MinMove adattivo ----------------

class TestMinMoveCap(unittest.TestCase):
    def test_guiding_term_wins(self):
        ctrl = _ctrl(scale=0.5)
        ctrl._minmove_baseline_ema = 0.5                    # k*0.5=0.4 < ceiling 2.0
        cap_px = ctrl._minmove_cap_px()
        self.assertAlmostEqual(ctrl._minmove_cap_info["cap_arcsec"], 0.4, places=3)
        self.assertAlmostEqual(cap_px, 0.8, places=3)       # 0.4 / 0.5
        self.assertEqual(ctrl._minmove_cap_info["winning"], "guiding")

    def test_imaging_ceiling_wins(self):
        ctrl = _ctrl(scale=0.5)
        ctrl._minmove_baseline_ema = 5.0                    # k*5=4.0 > ceiling 2.0
        cap_px = ctrl._minmove_cap_px()
        self.assertAlmostEqual(ctrl._minmove_cap_info["cap_arcsec"], 2.0, places=3)
        self.assertAlmostEqual(cap_px, 4.0, places=3)       # 2.0 / 0.5
        self.assertEqual(ctrl._minmove_cap_info["winning"], "imaging")

    def test_cap_clamps_minmove_up(self):
        ctrl = _ctrl(scale=0.5)
        ctrl._minmove_baseline_ema = 0.5                    # cap_px 0.8
        self.assertAlmostEqual(ctrl._cap_minmove_up(0.85, ctrl.cfg.ra), 0.8, places=3)
        self.assertAlmostEqual(ctrl._cap_minmove_up(0.6, ctrl.cfg.ra), 0.6, places=3)  # sotto il cap: invariato

    def test_floor_wins_over_tiny_cap(self):
        ctrl = _ctrl(scale=0.5)
        ctrl._minmove_baseline_ema = 0.05                   # cap_arcsec 0.04 -> cap_px 0.08 < floor 0.15
        self.assertAlmostEqual(ctrl._cap_minmove_up(0.5, ctrl.cfg.ra), 0.15, places=3)

    def test_fallback_disabled(self):
        ctrl = _ctrl(cap_enabled=False)
        ctrl._minmove_baseline_ema = 0.5
        self.assertIsNone(ctrl._minmove_cap_px())
        self.assertEqual(ctrl._cap_minmove_up(0.85, ctrl.cfg.ra), 0.85)   # legacy

    def test_fallback_ema_not_ready(self):
        ctrl = _ctrl()                                       # ema None
        self.assertIsNone(ctrl._minmove_cap_px())
        self.assertEqual(ctrl._cap_minmove_up(0.85, ctrl.cfg.ra), 0.85)

    def test_ema_seeds_then_tracks_slowly(self):
        ctrl = _ctrl()
        ctrl._rms_baseline_value = 0.5
        ctrl._update_minmove_baseline_filter()
        self.assertEqual(ctrl._minmove_baseline_ema, 0.5)    # seed
        # baseline sale a 1.0; dopo ~1h (>> tau 18min) l'EMA si è mossa quasi del tutto
        ctrl._rms_baseline_value = 1.0
        ctrl._minmove_baseline_ema_t = time.monotonic() - 3600.0
        ctrl._update_minmove_baseline_filter()
        self.assertGreater(ctrl._minmove_baseline_ema, 0.9)
        self.assertLess(ctrl._minmove_baseline_ema, 1.0)

    def test_uses_filtered_not_instant(self):
        # Il cap usa l'EMA, NON il valore istantaneo _rms_baseline_value.
        ctrl = _ctrl(scale=0.5)
        ctrl._minmove_baseline_ema = 0.5                    # filtrato
        ctrl._rms_baseline_value = 3.0                      # istantaneo (spike) — ignorato dal cap
        self.assertAlmostEqual(ctrl._minmove_cap_px(), 0.8, places=3)   # usa 0.5 (EMA), non 3.0

    def test_clamping_active_flag(self):
        ctrl = _ctrl(scale=0.5)
        ctrl._minmove_baseline_ema = 0.5                    # cap_px 0.8
        # nessun taglio ancora
        self.assertFalse(ctrl.get_status()["minmove_cap"]["clamping_active"])
        # richiesta sotto il cap -> nessun taglio
        ctrl._cap_minmove_up(0.6, ctrl.cfg.ra)
        self.assertFalse(ctrl.get_status()["minmove_cap"]["clamping_active"])
        # MinMove che COINCIDE col cap ma senza salita oltre -> nessun taglio
        ctrl._cap_minmove_up(0.8, ctrl.cfg.ra)
        self.assertFalse(ctrl.get_status()["minmove_cap"]["clamping_active"])
        # richiesta OLTRE il cap -> taglio -> ACTIVE
        ctrl._cap_minmove_up(0.85, ctrl.cfg.ra)
        self.assertTrue(ctrl.get_status()["minmove_cap"]["clamping_active"])

    def test_caso1_minmove_up_respects_cap(self):
        ctrl = _ctrl(scale=0.5)
        ctrl._minmove_baseline_ema = 0.5                    # cap_px 0.8
        ctrl._ra.current_minmove = 0.78                     # +step 0.05 = 0.83 > cap 0.8
        s = AnalysisSnapshot(); s.condition = SeeingCondition.DEGRADED_SEEING; s.frame_count = 30
        ctrl._evaluate_axis(ctrl._ra, ctrl.cfg.ra, 1.5, 6, 0,
                            SeeingCondition.DEGRADED_SEEING, s)
        self.assertLessEqual(ctrl._ra.current_minmove, 0.8 + 1e-9)   # cap ha limitato la salita
        self.assertAlmostEqual(ctrl._ra.current_minmove, 0.8, places=3)


if __name__ == "__main__":
    unittest.main()
