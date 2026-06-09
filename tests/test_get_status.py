"""
test_get_status.py — Verifica che get_status() esponga i nuovi blocchi §21.

Casi coperti:
  1. Blocco 'exposure' ha cooldown_residuo_s e cooldown_total_s
  2. Blocco 'escalation_gate' presente con chiavi enabled / ra / dec
  3. escalation_gate.ra e .dec sono bool
  4. cooldown_residuo_s <= cooldown_total_s
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from phd2_agent.config import (
    AgentConfig, AxisLimits, ControlConfig, EmergencyConfig,
    ExposureDynamicConfig, SetupConfig, Thresholds,
)
from phd2_agent.controller import AdaptiveController


def _make_controller() -> AdaptiveController:
    cfg = AgentConfig()
    cfg.control = ControlConfig(dry_run=True, cooldown_seconds=30.0)
    cfg.thresholds = Thresholds(
        rms_high=0.80, rms_low=0.35, snr_low=10.0,
        spike_ratio_high=0.30, consecutive_frames=5,
    )
    cfg.emergency = EmergencyConfig(
        auto_recovery=True, max_exposure_ms=6000,
        find_star_delay=10, saturation_timeout_s=300,
    )
    cfg.ra = AxisLimits(
        aggr_min=35, aggr_max=75,
        aggr_step_down=5, aggr_step_up=2,
        minmove_min=0.15, minmove_max=0.80, minmove_step=0.05,
    )
    cfg.dec = AxisLimits(
        aggr_min=30, aggr_max=70,
        aggr_step_down=5, aggr_step_up=2,
        minmove_min=0.20, minmove_max=0.85, minmove_step=0.05,
    )
    cfg.setup = SetupConfig(
        profile_name="test",
        guide_pixel_scale_arcsec_native=0.51,
        guide_pixel_scale_arcsec_reduced=0.68,
        reducer_active=False,
    )
    cfg.exposure_dynamic = ExposureDynamicConfig(
        enabled=True,
        step_factor=1.5,
        max_steps_above_base=2,
        cooldown_s=90.0,
        spike_min=0.20,
        hfd_min_arcsec=4.0,
        peak_to_rms_ratio_min=3.0,
        nominal_for_seconds=60.0,
    )
    client = MagicMock()
    ctrl = AdaptiveController(client=client, config=cfg)
    ctrl.base_exposure_ms = 2000
    ctrl.current_exposure_ms = 2000
    ctrl.last_exposure_action_time = 0.0
    return ctrl


class TestGetStatusNewFields(unittest.TestCase):

    def setUp(self):
        self.ctrl = _make_controller()
        self.status = self.ctrl.get_status()

    def test_exposure_has_cooldown_total(self):
        exp = self.status['exposure']
        self.assertIn('cooldown_total_s', exp)
        self.assertEqual(exp['cooldown_total_s'], 90.0)

    def test_exposure_has_cooldown_residuo(self):
        exp = self.status['exposure']
        self.assertIn('cooldown_residuo_s', exp)
        # Fresh controller: last_exposure_action_time = 0.0, so residuo = 0
        self.assertEqual(exp['cooldown_residuo_s'], 0.0)

    def test_cooldown_residuo_lte_total(self):
        exp = self.status['exposure']
        self.assertLessEqual(exp['cooldown_residuo_s'], exp['cooldown_total_s'])

    def test_escalation_gate_present(self):
        self.assertIn('escalation_gate', self.status)

    def test_escalation_gate_keys(self):
        gate = self.status['escalation_gate']
        self.assertIn('enabled', gate)
        self.assertIn('ra', gate)
        self.assertIn('dec', gate)

    def test_escalation_gate_enabled_is_bool(self):
        gate = self.status['escalation_gate']
        self.assertIsInstance(gate['enabled'], bool)

    def test_escalation_gate_axes_are_bool(self):
        gate = self.status['escalation_gate']
        self.assertIsInstance(gate['ra'], bool)
        self.assertIsInstance(gate['dec'], bool)

    def test_escalation_gate_fresh_controller_not_saturated(self):
        # Fresh controller has aggr and minmove at baseline — not yet saturated
        gate = self.status['escalation_gate']
        # ra.current_aggr defaults to 0 which is <= aggr_min + 1 (36), but
        # minmove defaults to 0 which is < minmove_max - step (0.75), so False
        self.assertFalse(gate['ra'])
        self.assertFalse(gate['dec'])

    def test_diagnostic_engine_block_present_when_off(self):
        # §31 — il blocco diagnostic_engine è presente anche a motore spento
        # (default), nella forma minima {enabled:false, mode, allow_...}.
        self.assertIn('diagnostic_engine', self.status)
        de = self.status['diagnostic_engine']
        self.assertFalse(de['enabled'])
        self.assertEqual(de['mode'], 'guardian')
        self.assertIn('allow_dashboard_mode_switch', de)


if __name__ == '__main__':
    unittest.main()
