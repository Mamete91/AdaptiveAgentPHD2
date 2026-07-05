"""
test_oscillation_experiment.py — §47: esperimento outcome-first, ramo oscillazioni
disattivo (kill-switch reversibile) + strumentazione di attribuzione.

Verifica:
  • default off: OVERCORRECTION/lag-1 -> proposal None (stato informativo); micro None;
    contatore would-have-fired incrementa; CASO2-trend non riduce l'aggressività;
  • reversibile: oscillation_branch_enabled=true -> comportamento legacy;
  • SEEING-softening / §32 recovery / engine-micro INVARIATI (le loro azioni restano);
  • strumentazione: softening_source + minmove_arcsec su ogni azione.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from phd2_agent.analyzer import AnalysisSnapshot, SeeingCondition
from phd2_agent.config import (
    AgentConfig, AxisLimits, ControlConfig, DiagnosticEngineConfig,
    LeverOptimizationConfig, SetupConfig, Thresholds,
)
from phd2_agent.controller import AdaptiveController
from phd2_agent.diagnostic_engine import SeeingDiagnosticEngine, DiagnosisState, LeverProposal


# ---------------- engine-level ----------------

def _snap(rms_total=0.2, jitter_rms=0.1, lag1_ra=0.0, lag1_dec=0.0,
          condition=SeeingCondition.UNKNOWN) -> AnalysisSnapshot:
    s = AnalysisSnapshot()
    s.frame_count = 30
    s.rms_total = rms_total
    s.hfd_avg = 2.0
    s.jitter_rms = jitter_rms
    s.jitter_n = 29
    s.lag1_ra = lag1_ra
    s.lag1_dec = lag1_dec
    s.condition = condition
    return s


def _eng(**ov):
    cfg = DiagnosticEngineConfig(enabled=True, mode="guardian", **ov)
    e = SeeingDiagnosticEngine(cfg, lambda: (0.8, 0.35), lambda: None)
    for _ in range(max(2, cfg.refs_warmup_frames)):
        e.classify(_snap(rms_total=0.2, jitter_rms=0.1, condition=SeeingCondition.NOMINAL))
    return e


class TestEngineOscillationBranch(unittest.TestCase):
    def test_default_off_no_proposal_but_informative(self):
        e = _eng()   # default oscillation_branch_enabled=False
        r = e.classify(_snap(rms_total=0.6, lag1_ra=-0.9, lag1_dec=-0.9))
        self.assertEqual(r.state, DiagnosisState.OVERCORRECTION)   # stato informativo resta
        self.assertIsNone(r.proposal)                              # ma nessuna azione
        self.assertIsNone(e.micro_proposal())
        st = e.get_state()
        self.assertGreaterEqual(st["osc_would_fire"], 1)          # shadow conta
        self.assertFalse(st["oscillation_branch_enabled"])

    def test_would_fire_degraded_counts_when_rms_high(self):
        e = _eng()
        e.classify(_snap(rms_total=0.95, lag1_ra=-0.9, lag1_dec=-0.9))  # rms > rms_high 0.8
        self.assertGreaterEqual(e.get_state()["osc_would_fire_degraded"], 1)

    def test_reversible_on_legacy(self):
        e = _eng(oscillation_branch_enabled=True)
        r = e.classify(_snap(rms_total=0.6, lag1_ra=-0.9, lag1_dec=-0.9))
        self.assertEqual(r.state, DiagnosisState.OVERCORRECTION)
        self.assertEqual(r.proposal, LeverProposal(aggr=-1, minmove=0))
        self.assertEqual(e.micro_proposal(), LeverProposal(aggr=-1, minmove=0))
        self.assertEqual(e.get_state()["osc_would_fire"], 0)       # non in shadow


# ---------------- controller-level (CASO2 + attribuzione) ----------------

def _ctrl(osc=False) -> AdaptiveController:
    cfg = AgentConfig()
    cfg.control = ControlConfig(dry_run=True, cooldown_seconds=30.0)
    cfg.thresholds = Thresholds(rms_high=0.80, rms_low=0.35, snr_low=10.0,
                                spike_ratio_high=0.30, consecutive_frames=5)
    ax = dict(aggr_min=35, aggr_max=100, aggr_step_down=5, aggr_step_up=2,
              minmove_min=0.15, minmove_max=0.85, minmove_step=0.05)
    cfg.ra = AxisLimits(**ax)
    cfg.dec = AxisLimits(**ax)
    cfg.setup = SetupConfig(profile_name="test", guide_pixel_scale_arcsec_native=0.5)
    cfg.lever_optimization = LeverOptimizationConfig(enabled=True, target_factor=1.0)
    cfg.diagnostic_engine = DiagnosticEngineConfig(enabled=False, oscillation_branch_enabled=osc)
    ctrl = AdaptiveController(client=MagicMock(), config=cfg)
    ctrl._initialized = True
    for a in (ctrl._ra, ctrl._dec):
        a.aggr_param = "Aggressiveness"
        a.minmove_param = "MinMove"
        a.current_aggr = 70.0
        a.current_minmove = 0.40
        a.last_action_time = 0.0
        a.last_minmove_action_time = 0.0
    ctrl._rms_baseline_value = 0.5
    ctrl._rms_baseline_rejected = False
    return ctrl


def _csnap(condition=SeeingCondition.NOMINAL) -> AnalysisSnapshot:
    s = AnalysisSnapshot()
    s.condition = condition
    s.frame_count = 30
    return s


def _eval(ctrl, rms, consec_high=0, consec_low=0, condition=SeeingCondition.NOMINAL):
    return ctrl._evaluate_axis(ctrl._ra, ctrl.cfg.ra, rms, consec_high, consec_low,
                               condition, _csnap(condition))


class TestCaso2Gated(unittest.TestCase):
    def test_caso2_off_no_action(self):
        ctrl = _ctrl(osc=False)
        actions = _eval(ctrl, rms=0.5, condition=SeeingCondition.OSCILLATING)
        self.assertEqual(actions, [])                  # oscillazione non riduce l'aggr
        self.assertEqual(ctrl._ra.current_aggr, 70.0)

    def test_caso2_on_reduces_aggr(self):
        ctrl = _ctrl(osc=True)
        actions = _eval(ctrl, rms=0.5, condition=SeeingCondition.OSCILLATING)
        self.assertGreater(len(actions), 0)
        self.assertEqual(ctrl._ra.current_aggr, 65.0)  # 70 - step_down 5
        self.assertEqual(actions[0].softening_source, "oscillation")


class TestSofteningSourcesInvariant(unittest.TestCase):
    def test_seeing_softening_still_acts_and_tagged(self):
        ctrl = _ctrl(osc=False)   # ramo oscillazioni off NON tocca il SEEING-softening
        actions = _eval(ctrl, rms=1.5, consec_high=6,
                        condition=SeeingCondition.DEGRADED_SEEING)
        self.assertGreater(len(actions), 0)
        srcs = {a.softening_source for a in actions}
        self.assertEqual(srcs, {"SEEING"})
        mm = [a for a in actions if a.param == "MinMove"]
        self.assertTrue(mm and mm[0].minmove_arcsec is not None)
        self.assertAlmostEqual(mm[0].minmove_arcsec, round(mm[0].new_value * 0.5, 3))

    def test_recovery_still_acts_and_tagged(self):
        ctrl = _ctrl(osc=False)
        ctrl._recovery_consec = 5
        ctrl._recovery_blocked = False
        actions = _eval(ctrl, rms=0.6, condition=SeeingCondition.NOMINAL)  # banda morta, > mediana 0.5
        srcs = {a.softening_source for a in actions}
        self.assertIn("minmove_recovery_§32", srcs)


if __name__ == "__main__":
    unittest.main()
