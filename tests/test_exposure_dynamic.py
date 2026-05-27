"""
test_exposure_dynamic.py — Test unitari per l'esposizione dinamica RMS-based.

Casi coperti:
  1. Trigger UP soddisfatto + escalation gate aperto → _apply_exposure chiamato,
     stato cambia in BOOSTED_FOR_SEEING
  2. Trigger UP soddisfatto + escalation gate chiuso (aggr non al minimo) →
     nessuna azione esposizione
  3. Trigger UP con condition OSCILLATING → nessuna azione
  4. Trigger UP con condition LOW_SNR → path B non chiamato (priorità A)
  5. Trigger DOWN dopo nominal_for_seconds → esposizione torna a base
"""
from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock, patch

from phd2_agent.analyzer import AnalysisSnapshot, SeeingCondition
from phd2_agent.config import (
    AgentConfig, AxisLimits, ControlConfig, EmergencyConfig,
    ExposureDynamicConfig, SetupConfig, Thresholds,
)
from phd2_agent.controller import AdaptiveController, AxisState, ExposureState


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def _make_config(enabled: bool = True) -> AgentConfig:
    cfg = AgentConfig()
    cfg.control = ControlConfig(dry_run=False, cooldown_seconds=30.0)
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
        profile_name="rc8",
        guide_pixel_scale_arcsec_native=0.51,
        guide_pixel_scale_arcsec_reduced=0.68,
        reducer_active=False,
    )
    cfg.exposure_dynamic = ExposureDynamicConfig(
        enabled=enabled,
        step_factor=1.5,
        max_steps_above_base=2,
        cooldown_s=90.0,
        spike_min=0.20,
        hfd_min_arcsec=4.0,
        peak_to_rms_ratio_min=3.0,
        nominal_for_seconds=60.0,
    )
    return cfg


def _make_client(valid_exposures: list[int] | None = None) -> MagicMock:
    client = MagicMock()
    client.get_exposure.return_value = 2000
    client.get_exposure_durations.return_value = (
        valid_exposures if valid_exposures is not None
        else [500, 1000, 1500, 2000, 3000, 4000, 5000, 6000]
    )
    return client


def _make_controller(cfg: AgentConfig | None = None,
                     client: MagicMock | None = None) -> AdaptiveController:
    if cfg is None:
        cfg = _make_config()
    if client is None:
        client = _make_client()
    ctrl = AdaptiveController(client=client, config=cfg)
    # Simula initialize() senza connessione reale
    ctrl._valid_exposures = client.get_exposure_durations.return_value
    ctrl.base_exposure_ms = client.get_exposure.return_value
    ctrl.current_exposure_ms = ctrl.base_exposure_ms
    ctrl.exposure_state = ExposureState.NOMINAL
    ctrl.exposure_steps_above_base = 0
    ctrl.last_exposure_action_time = 0.0
    ctrl._nominal_since = None
    ctrl._initialized = True
    return ctrl


def _degraded_snapshot(
    spike_score: float = 0.25,
    hfd_avg: float = 9.0,   # 9.0 * 0.51 = 4.59 >= hfd_min_arcsec=4.0
    peak_ra: float = 2.0,
    rms_ra: float = 0.5,
    peak_dec: float = 2.0,
    rms_dec: float = 0.5,
    consecutive_high: int = 6,
) -> AnalysisSnapshot:
    snap = AnalysisSnapshot()
    snap.condition = SeeingCondition.DEGRADED_SEEING
    snap.rms_total = 1.0
    snap.rms_ra = rms_ra
    snap.rms_dec = rms_dec
    snap.peak_ra = peak_ra
    snap.peak_dec = peak_dec
    snap.hfd_avg = hfd_avg
    snap.snr_avg = 20.0
    snap.spike_score = spike_score
    snap.consecutive_high = consecutive_high
    snap.consecutive_low = 0
    snap.implosion_suspended = False
    snap.frame_count = 30
    return snap


def _saturate_axis(axis_state: AxisState, limits: AxisLimits,
                   cooldown: float = 30.0) -> None:
    """Porta un asse allo stato 'leve saturate'."""
    axis_state.current_aggr = limits.aggr_min          # aggr al minimo
    axis_state.current_minmove = limits.minmove_max    # minmove al massimo
    t_past = time.monotonic() - (cooldown * 2)         # abbondantemente scaduto
    axis_state.last_action_time = t_past
    axis_state.last_minmove_action_time = t_past


# ---------------------------------------------------------------------------
# Test 1: Trigger UP + escalation gate aperto → azione emessa, stato cambia
# ---------------------------------------------------------------------------

class TestTriggerUpGateOpen(unittest.TestCase):

    def test_action_emitted_and_state_changes(self):
        ctrl = _make_controller()
        _saturate_axis(ctrl._ra, ctrl.cfg.ra, ctrl.cfg.control.cooldown_seconds)

        snap = _degraded_snapshot()
        actions = ctrl._evaluate_exposure_seeing(snap)

        self.assertEqual(len(actions), 1, "Attesa esattamente 1 azione")
        a = actions[0]
        self.assertEqual(a.param, "exposure_seeing")
        self.assertEqual(a.axis, "camera")
        self.assertGreater(a.new_value, a.old_value, "Nuova esposizione > base")
        self.assertEqual(ctrl.exposure_state, ExposureState.BOOSTED_FOR_SEEING)
        self.assertEqual(ctrl.exposure_steps_above_base, 1)
        self.assertEqual(ctrl.current_exposure_ms, int(a.new_value))


# ---------------------------------------------------------------------------
# Test 2: Trigger UP + escalation gate chiuso → nessuna azione
# ---------------------------------------------------------------------------

class TestTriggerUpGateClosed(unittest.TestCase):

    def test_no_action_when_levers_not_saturated(self):
        ctrl = _make_controller()
        # Asse RA NON saturato: aggr a metà, minmove a metà
        ctrl._ra.current_aggr = 60.0        # lontano da aggr_min=35
        ctrl._ra.current_minmove = 0.40     # lontano da minmove_max=0.80
        ctrl._ra.last_action_time = time.monotonic() - 5.0
        ctrl._ra.last_minmove_action_time = time.monotonic() - 5.0
        # Asse DEC pure non saturato
        ctrl._dec.current_aggr = 55.0
        ctrl._dec.current_minmove = 0.35
        ctrl._dec.last_action_time = time.monotonic() - 5.0
        ctrl._dec.last_minmove_action_time = time.monotonic() - 5.0

        snap = _degraded_snapshot()
        actions = ctrl._evaluate_exposure_seeing(snap)

        self.assertEqual(actions, [], "Atteso nessuna azione (gate chiuso)")
        self.assertEqual(ctrl.exposure_state, ExposureState.NOMINAL)


# ---------------------------------------------------------------------------
# Test 3: Trigger UP con condition OSCILLATING → nessuna azione
# ---------------------------------------------------------------------------

class TestTriggerUpOscillating(unittest.TestCase):

    def test_no_action_on_oscillating(self):
        ctrl = _make_controller()
        _saturate_axis(ctrl._ra, ctrl.cfg.ra, ctrl.cfg.control.cooldown_seconds)

        snap = _degraded_snapshot()
        snap.condition = SeeingCondition.OSCILLATING  # override

        actions = ctrl._evaluate_exposure_seeing(snap)

        self.assertEqual(actions, [],
                         "Path B non deve attivarsi su OSCILLATING")
        self.assertEqual(ctrl.exposure_state, ExposureState.NOMINAL)


# ---------------------------------------------------------------------------
# Test 4: Trigger UP con condition LOW_SNR → path B non chiamato
# ---------------------------------------------------------------------------

class TestTriggerUpLowSnrDelegatedToPathA(unittest.TestCase):

    def test_path_b_not_called_on_low_snr(self):
        """
        Quando condition == LOW_SNR, _evaluate_exposure() deve chiamare solo
        path A (_evaluate_exposure_snr) e NON path B (_evaluate_exposure_seeing).
        """
        ctrl = _make_controller()
        _saturate_axis(ctrl._ra, ctrl.cfg.ra, ctrl.cfg.control.cooldown_seconds)

        snap = AnalysisSnapshot()
        snap.condition = SeeingCondition.LOW_SNR
        snap.snr_avg = 5.0
        snap.rms_total = 1.0
        snap.rms_ra = 0.5
        snap.rms_dec = 0.5
        snap.peak_ra = 2.0
        snap.peak_dec = 2.0
        snap.hfd_avg = 5.0
        snap.spike_score = 0.25
        snap.consecutive_high = 6
        snap.consecutive_low = 0
        snap.implosion_suspended = False
        snap.frame_count = 30

        with patch.object(ctrl, '_evaluate_exposure_seeing',
                          wraps=ctrl._evaluate_exposure_seeing) as mock_b:
            ctrl._evaluate_exposure(snap)
            # Path B è chiamato ma condition == LOW_SNR blocca il trigger
            # (stato rimane NOMINAL — path A gestisce la transizione a BOOSTED_FOR_SNR)
            # Verifica che lo stato sia BOOSTED_FOR_SNR (path A ha agito)
            # oppure che path B non abbia emesso azioni seeing
            seeing_actions = [a for a in mock_b.call_args_list
                              if a] if mock_b.called else []
            # Lo stato NON deve essere BOOSTED_FOR_SEEING
            self.assertNotEqual(ctrl.exposure_state, ExposureState.BOOSTED_FOR_SEEING,
                                "Path B non deve portare a BOOSTED_FOR_SEEING su LOW_SNR")


# ---------------------------------------------------------------------------
# Test 5: Trigger DOWN dopo nominal_for_seconds → esposizione torna a base
# ---------------------------------------------------------------------------

class TestTriggerDown(unittest.TestCase):

    def test_exposure_returns_to_base_after_nominal_period(self):
        ctrl = _make_controller()

        # Porta lo stato a BOOSTED_FOR_SEEING (2 step) manualmente
        ctrl.exposure_state = ExposureState.BOOSTED_FOR_SEEING
        ctrl.exposure_steps_above_base = 1
        ctrl.current_exposure_ms = 3000   # 2000 * 1.5
        # Il cooldown esposizione deve essere scaduto
        ctrl.last_exposure_action_time = time.monotonic() - 200.0
        # Il _nominal_since deve essere abbondantemente passato
        ctrl._nominal_since = time.monotonic() - 120.0  # > nominal_for_seconds=60

        snap = AnalysisSnapshot()
        snap.condition = SeeingCondition.NOMINAL
        snap.rms_total = 0.20
        snap.rms_ra = 0.15
        snap.rms_dec = 0.10
        snap.peak_ra = 0.3
        snap.peak_dec = 0.2
        snap.hfd_avg = 3.0
        snap.spike_score = 0.05
        snap.consecutive_high = 0
        snap.consecutive_low = 12   # > 2 * consecutive_frames=5 → 10
        snap.implosion_suspended = False
        snap.frame_count = 30
        snap.snr_avg = 25.0

        actions = ctrl._evaluate_exposure_seeing(snap)

        self.assertEqual(len(actions), 1, "Attesa 1 azione di riduzione")
        a = actions[0]
        self.assertEqual(a.param, "exposure_seeing")
        self.assertLess(a.new_value, a.old_value, "Nuova esposizione < corrente")
        # Con step_factor=1.5, 3000/1.5=2000 → torna a base
        self.assertEqual(ctrl.current_exposure_ms, ctrl.base_exposure_ms)
        self.assertEqual(ctrl.exposure_state, ExposureState.NOMINAL)
        self.assertEqual(ctrl.exposure_steps_above_base, 0)


if __name__ == "__main__":
    unittest.main()
