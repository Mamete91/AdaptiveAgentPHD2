"""
test_recovery_symmetric.py — §53 recupero SIMMETRICO guidato dall'esito (banda morta
bidirezionale). Chiude l'asimmetria allargamento/recupero: aggr + MinMove rientrano
verso lo standard §50 quando la guida è stabile, con outcome gate.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from phd2_agent.analyzer import AnalysisSnapshot, SeeingCondition
from phd2_agent.config import (
    AgentConfig, AxisLimits, ControlConfig, LeverOptimizationConfig,
    MinMoveCapConfig, SetupConfig, Thresholds,
)
from phd2_agent.controller import AdaptiveController, GuidingState


def _ctrl(symmetric=True, mm0=0.40, aggr0=40.0, k=3, window=2) -> AdaptiveController:
    cfg = AgentConfig()
    cfg.control = ControlConfig(dry_run=True, cooldown_seconds=0.0)
    cfg.thresholds = Thresholds(rms_high=1.20, rms_low=0.30, snr_low=10.0,
                                spike_ratio_high=0.30, consecutive_frames=3)
    for axis in ("ra", "dec"):
        setattr(cfg, axis, AxisLimits(aggr_min=35, aggr_max=100, aggr_step_down=5,
                                      aggr_step_up=2, minmove_min=0.15, minmove_max=0.85,
                                      minmove_step=0.05))
    cfg.setup = SetupConfig(profile_name="test", guide_pixel_scale_arcsec_native=0.5)
    cfg.lever_optimization = LeverOptimizationConfig(
        enabled=True, target_factor=1.0, minmove_recovery_enabled=True,
        minmove_recovery_factor=1.0, recovery_no_progress_k=k,
        symmetric_recovery_enabled=symmetric, recovery_stiffen_aggression=True,
        recovery_outcome_window_frames=window, recovery_outcome_tolerance_factor=1.05)
    cfg.minmove_cap = MinMoveCapConfig(enabled=False)   # isola il recupero dal cap §51
    ctrl = AdaptiveController(client=MagicMock(), config=cfg)
    ctrl._initialized = True
    ctrl.guiding_state = GuidingState.NORMAL
    ctrl._rms_baseline_value = 0.50            # àncora soglia recupero (mediana)
    ctrl._rms_baseline_rejected = False
    for ax in (ctrl._ra, ctrl._dec):
        ax.aggr_param = "aggression"
        ax.aggr_native_scale = 0.01            # famiglia Hysteresis/Resist Switch (§50 valido)
        ax.minmove_param = "minMove"
        ax.current_aggr = aggr0
        ax.current_minmove = mm0
        ax.last_action_time = 0.0
        ax.last_minmove_action_time = 0.0
    return ctrl


def _snap(rms, condition=SeeingCondition.NOMINAL):
    s = AnalysisSnapshot()
    s.condition = condition
    s.frame_count = 30
    s.rms_total = rms
    s.rms_ra = rms
    s.rms_dec = rms
    return s


def _tick(ctrl, rms, condition=SeeingCondition.NOMINAL):
    """Flusso per-tick reale: update_recovery_state -> RA -> DEC -> finalize."""
    s = _snap(rms, condition)
    ctrl._update_recovery_state(s)
    acts = ctrl._evaluate_axis(ctrl._ra, ctrl.cfg.ra, s.rms_ra, 0, 0, condition, s)
    acts += ctrl._evaluate_axis(ctrl._dec, ctrl.cfg.dec, s.rms_dec, 0, 0, condition, s)
    ctrl._finalize_recovery_windup(s)
    return acts


class TestStiffenPreferred(unittest.TestCase):
    def test_softened_stable_stiffens(self):
        # 1. banda morta + leve morbide + RMS stabile poco sopra baseline -> STIFFEN.
        ctrl = _ctrl(mm0=0.40, aggr0=40.0)
        for _ in range(6):
            _tick(ctrl, 0.60)   # > soglia 0.50, stabile
        self.assertGreater(ctrl._ra.current_aggr, 40.0)     # aggr risalito
        self.assertLess(ctrl._ra.current_minmove, 0.40)     # minmove abbassato
        self.assertEqual(ctrl.get_status()["recovery"]["direction"], "stiffen")

    def test_aggression_recovers(self):
        # 2. regressione dell'asimmetria: aggr al pavimento risale verso il nominale §50.
        ctrl = _ctrl(mm0=0.20, aggr0=35.0)   # minmove al nominale, aggr al floor
        for _ in range(6):
            _tick(ctrl, 0.60)
        self.assertGreater(ctrl._ra.current_aggr, 35.0)     # PRIMA restava inchiodato
        self.assertGreater(ctrl._dec.current_aggr, 35.0)

    def test_no_soften_action_in_stiffen_tick(self):
        # 7. anti-flapping: nello stesso tick niente stiffen+soften sull'asse.
        ctrl = _ctrl(mm0=0.40, aggr0=40.0)
        for _ in range(3):
            _tick(ctrl, 0.60)
        acts = _tick(ctrl, 0.60)
        reasons = " ".join(a.reason for a in acts)
        self.assertNotIn("alzo MinMove", reasons)           # nessun ammorbidimento
        self.assertTrue("irrigidisco" in reasons or "abbasso MinMove" in reasons)


class TestOutcomeGate(unittest.TestCase):
    def test_stiffen_stop_on_worse_rms(self):
        # 3. irrigidimento che peggiora l'RMS oltre tolleranza -> STOP + stiffen_blocked.
        ctrl = _ctrl(window=2)
        ctrl._recovery_direction = "stiffen"
        ctrl._recovery_anchor_rms = 0.50
        ctrl._recovery_actions_since_anchor = 1     # +1 nel finalize -> 2 >= window
        ctrl._recovery_applied_this_tick = True
        ctrl._finalize_recovery_windup(_snap(0.60))  # 0.60 > 0.50×1.05=0.525 -> STOP
        self.assertTrue(ctrl._recovery_stiffen_blocked)

    def test_stiffen_keep_on_holding_rms(self):
        ctrl = _ctrl(window=2)
        ctrl._recovery_direction = "stiffen"
        ctrl._recovery_anchor_rms = 0.50
        ctrl._recovery_actions_since_anchor = 1
        ctrl._recovery_applied_this_tick = True
        ctrl._finalize_recovery_windup(_snap(0.51))  # <= 0.525 -> KEEP, ri-ancora
        self.assertFalse(ctrl._recovery_stiffen_blocked)
        self.assertAlmostEqual(ctrl._recovery_anchor_rms, 0.51, places=3)

    def test_soften_fallback_after_stiffen_blocked(self):
        # 3 (fallback): dopo il blocco dell'irrigidimento il verso diventa soften.
        ctrl = _ctrl(mm0=0.40, aggr0=40.0)
        ctrl._recovery_stiffen_blocked = True
        ctrl._update_recovery_state(_snap(0.60))     # softened+stabile ma stiffen_blocked
        self.assertEqual(ctrl._recovery_direction, "soften")


class TestBoundsAndGates(unittest.TestCase):
    def test_never_exceeds_standard(self):
        # 4. aggr non supera il nominale §50; MinMove non scende sotto il nominale.
        ctrl = _ctrl(mm0=0.22, aggr0=69.0)
        for _ in range(10):
            _tick(ctrl, 0.60)
        self.assertLessEqual(ctrl._ra.current_aggr, 70.0 + 1e-9)
        self.assertGreaterEqual(ctrl._ra.current_minmove, 0.20 - 1e-9)
        self.assertAlmostEqual(ctrl._ra.current_aggr, 70.0, places=3)
        self.assertAlmostEqual(ctrl._ra.current_minmove, 0.20, places=3)

    def test_satisfied_no_action(self):
        # 5. guida soddisfatta (rms <= target §30) -> nessuna azione.
        ctrl = _ctrl(mm0=0.40, aggr0=40.0)
        acts = []
        for _ in range(5):
            acts += _tick(ctrl, 0.40)   # <= soglia 0.50
        self.assertEqual(acts, [])
        self.assertEqual(ctrl._ra.current_aggr, 40.0)
        self.assertEqual(ctrl._ra.current_minmove, 0.40)

    def test_killswitch_off_legacy_soften(self):
        # 6. symmetric off -> comportamento §32 legacy (MinMove sale, aggr intatto).
        ctrl = _ctrl(symmetric=False, mm0=0.40, aggr0=40.0)
        for _ in range(4):
            _tick(ctrl, 0.60)
        self.assertGreater(ctrl._ra.current_minmove, 0.40)   # soften (legacy)
        self.assertEqual(ctrl._ra.current_aggr, 40.0)        # aggr NON toccato


if __name__ == "__main__":
    unittest.main()
