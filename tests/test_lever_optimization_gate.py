"""
test_lever_optimization_gate.py — Satisfaction gate sul ramo "guida ottima" (§30, v2.3).

Verifica che il gate stateless nel CASO 3 di _evaluate_axis:
  - blocchi l'ottimizzazione quando RMS <= mediana baseline × target_factor;
  - lasci passare il CASO 3 legacy quando RMS è sopra il target;
  - sia disattivabile (enabled=false) e in fallback su baseline None / rifiutata;
  - NON interferisca con CASO 1 (degradato);
  - abbia parsing TOML retrocompatibile (sezione assente -> default).

Nota di setup: per far cadere gli scenari DENTRO il CASO 3 serve rms < rms_low.
Si usa quindi rms_low = 0.6 > mediana = 0.5, così sia "rms 0.45" (gate attivo)
sia "rms 0.55" (gate inattivo) entrano nel ramo CASO 3.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from phd2_agent.analyzer import AnalysisSnapshot, SeeingCondition
from phd2_agent.config import (
    AgentConfig, AxisLimits, ControlConfig, LeverOptimizationConfig,
    SetupConfig, Thresholds, load_config,
)
from phd2_agent.controller import AdaptiveController


# ---------------------------------------------------------------------------
# Factory locale: rms_low alto (0.6) > mediana (0.5) per fit nel CASO 3.
# ---------------------------------------------------------------------------

def _make_config(gate_enabled: bool = True, target_factor: float = 1.0) -> AgentConfig:
    cfg = AgentConfig()
    cfg.control = ControlConfig(dry_run=True, cooldown_seconds=30.0)
    cfg.thresholds = Thresholds(
        rms_high=1.20, rms_low=0.60, snr_low=10.0,
        spike_ratio_high=0.30, consecutive_frames=5,
    )
    cfg.ra = AxisLimits(
        aggr_min=35, aggr_max=90, aggr_step_down=5, aggr_step_up=2,
        minmove_min=0.15, minmove_max=0.85, minmove_step=0.05,
    )
    cfg.dec = AxisLimits(
        aggr_min=35, aggr_max=90, aggr_step_down=5, aggr_step_up=2,
        minmove_min=0.15, minmove_max=0.85, minmove_step=0.05,
    )
    cfg.setup = SetupConfig(profile_name="test",
                            guide_pixel_scale_arcsec_native=0.51)
    cfg.lever_optimization = LeverOptimizationConfig(
        enabled=gate_enabled, target_factor=target_factor,
    )
    return cfg


def _make_controller(cfg: AgentConfig | None = None) -> AdaptiveController:
    if cfg is None:
        cfg = _make_config()
    ctrl = AdaptiveController(client=MagicMock(), config=cfg)
    ctrl._initialized = True
    # Asse RA pronto: param noti, leve a metà corsa, cooldown scaduti.
    for ax in (ctrl._ra, ctrl._dec):
        ax.aggr_param = "Aggressiveness"
        ax.minmove_param = "MinMove"
        ax.current_aggr = 70.0
        ax.current_minmove = 0.40
        ax.last_action_time = 0.0          # epoch -> cooldown abbondantemente scaduto
        ax.last_minmove_action_time = 0.0
    return ctrl


def _snap() -> AnalysisSnapshot:
    s = AnalysisSnapshot()
    s.condition = SeeingCondition.NOMINAL
    s.frame_count = 30
    return s


def _eval_ra(ctrl, rms, consec_low=6, consec_high=0, condition=SeeingCondition.NOMINAL):
    return ctrl._evaluate_axis(
        ctrl._ra, ctrl.cfg.ra, rms, consec_high, consec_low, condition, _snap(),
    )


# ---------------------------------------------------------------------------
# 1. Gate attivo blocca il CASO 3
# ---------------------------------------------------------------------------

class TestGateBlocksOptimization(unittest.TestCase):

    def test_gate_active_no_actions(self):
        ctrl = _make_controller()
        ctrl._rms_baseline_value = 0.5          # mediana
        ctrl._rms_baseline_rejected = False
        # rms 0.45 < rms_low 0.6 (entra in CASO 3) e <= mediana 0.5 (gate scatta)
        actions = _eval_ra(ctrl, rms=0.45)
        self.assertEqual(actions, [], "Gate attivo: nessuna azione di ottimizzazione")
        # Leve invariate
        self.assertEqual(ctrl._ra.current_aggr, 70.0)
        self.assertEqual(ctrl._ra.current_minmove, 0.40)


# ---------------------------------------------------------------------------
# 2. Gate inattivo (RMS sopra mediana) -> CASO 3 legacy emette azioni
# ---------------------------------------------------------------------------

class TestGateInactiveLegacyRuns(unittest.TestCase):

    def test_rms_above_median_emits_actions(self):
        ctrl = _make_controller()
        ctrl._rms_baseline_value = 0.5
        ctrl._rms_baseline_rejected = False
        # rms 0.55: < rms_low 0.6 (CASO 3) ma > mediana 0.5 (gate non scatta)
        actions = _eval_ra(ctrl, rms=0.55)
        self.assertGreater(len(actions), 0, "Gate inattivo: CASO 3 legacy deve agire")
        params = {a.param for a in actions}
        self.assertIn("Aggressiveness", params)
        self.assertEqual(ctrl._ra.current_aggr, 72.0)   # 70 + step_up 2 (UP)


# ---------------------------------------------------------------------------
# 3. enabled=false disabilita il gate
# ---------------------------------------------------------------------------

class TestGateDisabled(unittest.TestCase):

    def test_disabled_runs_legacy(self):
        ctrl = _make_controller(_make_config(gate_enabled=False))
        ctrl._rms_baseline_value = 0.5
        ctrl._rms_baseline_rejected = False
        # rms 0.45 <= mediana: con gate ON sarebbe bloccato; con OFF deve agire
        actions = _eval_ra(ctrl, rms=0.45)
        self.assertGreater(len(actions), 0, "Gate OFF: comportamento v2.2 legacy")
        self.assertEqual(ctrl._ra.current_aggr, 72.0)


# ---------------------------------------------------------------------------
# 4. Baseline non finalizzata (None) -> fallback legacy
# ---------------------------------------------------------------------------

class TestBaselineNone(unittest.TestCase):

    def test_baseline_none_runs_legacy(self):
        ctrl = _make_controller()
        ctrl._rms_baseline_value = None         # warm-up
        actions = _eval_ra(ctrl, rms=0.45)
        self.assertGreater(len(actions), 0, "Baseline None: nessun target, CASO 3 legacy")


# ---------------------------------------------------------------------------
# 5. Baseline rifiutata (§23) -> fallback legacy
# ---------------------------------------------------------------------------

class TestBaselineRejected(unittest.TestCase):

    def test_baseline_rejected_runs_legacy(self):
        ctrl = _make_controller()
        ctrl._rms_baseline_value = 0.5
        ctrl._rms_baseline_rejected = True      # §23: mediana non rappresentativa
        actions = _eval_ra(ctrl, rms=0.40)
        self.assertGreater(len(actions), 0, "Baseline rifiutata: gate non scatta")


# ---------------------------------------------------------------------------
# 6. CASO 1 (degradato) invariato dal gate
# ---------------------------------------------------------------------------

class TestCaso1Untouched(unittest.TestCase):

    def test_degraded_emits_softening_actions(self):
        ctrl = _make_controller()
        ctrl._rms_baseline_value = 0.5          # gate ON ma non riguarda CASO 1
        ctrl._rms_baseline_rejected = False
        # rms 1.5 > rms_high 1.2, consec_high alto -> CASO 1
        actions = _eval_ra(ctrl, rms=1.5, consec_low=0, consec_high=6,
                           condition=SeeingCondition.DEGRADED_SEEING)
        self.assertGreater(len(actions), 0, "CASO 1 deve agire (aggr DOWN / minmove UP)")
        self.assertEqual(ctrl._ra.current_aggr, 65.0)   # 70 - step_down 5 (DOWN)


# ---------------------------------------------------------------------------
# 7. Retrocompat TOML: sezione assente -> default
# ---------------------------------------------------------------------------

class TestTomlRetrocompat(unittest.TestCase):

    def test_missing_section_defaults(self):
        toml = "[thresholds]\nrms_high = 1.2\n"
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.toml"
            p.write_text(toml, encoding="utf-8")
            cfg = load_config(p)
        self.assertIsInstance(cfg.lever_optimization, LeverOptimizationConfig)
        self.assertTrue(cfg.lever_optimization.enabled)
        self.assertEqual(cfg.lever_optimization.target_factor, 1.0)

    def test_section_parsed(self):
        toml = "[lever_optimization]\nenabled = false\ntarget_factor = 0.9\n"
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.toml"
            p.write_text(toml, encoding="utf-8")
            cfg = load_config(p)
        self.assertFalse(cfg.lever_optimization.enabled)
        self.assertAlmostEqual(cfg.lever_optimization.target_factor, 0.9)


if __name__ == "__main__":
    unittest.main()
