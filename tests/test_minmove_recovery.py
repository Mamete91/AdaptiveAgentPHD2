"""
test_minmove_recovery.py — Recupero MinMove nella banda morta (§32, asimmetria leve §4).

Verifica il ramo di recupero aggiunto alla catena CASO della v2.3 (attivo a motore
OFF e in GUARDIAN; sospeso in JITTER):
  - alza MinMove di minmove_step quando rms > mediana baseline nella banda morta,
    proseguendo OLTRE il valore iniziale fino a minmove_max (floor 0.15 intatto);
  - anti-windup: dopo recovery_no_progress_k recuperi senza calo RMS si ferma;
  - continua a recuperare finche' il softening riduce davvero l'RMS;
  - isteresi sulla mediana: tra rms_low e mediana nessuna leva si muove (no pompaggio);
  - CASO 1 / CASO 3 invariati; OFF = bit-identico; sospeso in JITTER.

Setup: rms_low=0.30 < mediana=0.50 < rms_high=1.20 -> banda morta ampia. rms=0.60
e' nella banda morta e sopra la mediana (recupero); rms=0.40 e' nella banda morta ma
sotto la mediana (zona di isteresi, fermo); rms=0.25 < rms_low (CASO 3).
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from phd2_agent.analyzer import AnalysisSnapshot, SeeingCondition
from phd2_agent.config import (
    AgentConfig, AxisLimits, ControlConfig, DiagnosticEngineConfig,
    LeverOptimizationConfig, SetupConfig, Thresholds,
)
from phd2_agent.controller import AdaptiveController, GuidingState


# --------------------------------------------------------------------------- #
#  Factory                                                                      #
# --------------------------------------------------------------------------- #

def _make_config(recovery_enabled=True, recovery_factor=1.0, no_progress_k=3,
                 consecutive_frames=3) -> AgentConfig:
    cfg = AgentConfig()
    cfg.control = ControlConfig(dry_run=True, cooldown_seconds=30.0)
    cfg.thresholds = Thresholds(
        rms_high=1.20, rms_low=0.30, snr_low=10.0,
        spike_ratio_high=0.30, consecutive_frames=consecutive_frames,
    )
    for axis in ("ra", "dec"):
        setattr(cfg, axis, AxisLimits(
            aggr_min=35, aggr_max=90, aggr_step_down=5, aggr_step_up=2,
            minmove_min=0.15, minmove_max=0.85, minmove_step=0.05,
        ))
    cfg.setup = SetupConfig(profile_name="test", guide_pixel_scale_arcsec_native=0.51)
    cfg.lever_optimization = LeverOptimizationConfig(
        enabled=True, target_factor=1.0,
        minmove_recovery_enabled=recovery_enabled,
        minmove_recovery_factor=recovery_factor,
        recovery_no_progress_k=no_progress_k,
        # §53: questi test coprono il ramo LEGACY §32 (soften/anti-windup), ora fallback.
        # Il recupero simmetrico bidirezionale ha i suoi test in test_recovery_symmetric.py.
        symmetric_recovery_enabled=False,
    )
    return cfg


def _make_controller(cfg: AgentConfig | None = None, mm0=0.40) -> AdaptiveController:
    if cfg is None:
        cfg = _make_config()
    ctrl = AdaptiveController(client=MagicMock(), config=cfg)
    ctrl._initialized = True
    ctrl.guiding_state = GuidingState.NORMAL
    ctrl._rms_baseline_value = 0.50          # mediana baseline (ancora del recupero)
    ctrl._rms_baseline_rejected = False
    for ax in (ctrl._ra, ctrl._dec):
        ax.aggr_param = "Aggressiveness"
        ax.minmove_param = "MinMove"
        ax.current_aggr = 70.0
        ax.current_minmove = mm0
        ax.last_action_time = 0.0             # cooldown abbondantemente scaduto
        ax.last_minmove_action_time = 0.0
    return ctrl


def _snap(rms_total=0.60, rms_axis=None) -> AnalysisSnapshot:
    s = AnalysisSnapshot()
    s.condition = SeeingCondition.NOMINAL
    s.frame_count = 30
    s.rms_total = rms_total
    s.rms_ra = rms_axis if rms_axis is not None else rms_total
    s.rms_dec = rms_axis if rms_axis is not None else rms_total
    return s


def _eval_ra(ctrl, rms, consec_high=0, consec_low=0,
             condition=SeeingCondition.NOMINAL):
    """Chiama direttamente _evaluate_axis su RA (senza i helper per-tick)."""
    return ctrl._evaluate_axis(
        ctrl._ra, ctrl.cfg.ra, rms, consec_high, consec_low, condition,
        _snap(rms_total=rms),
    )


def _tick(ctrl, rms_total, rms_axis=None, consec_high=0, consec_low=0,
          condition=SeeingCondition.NOMINAL):
    """Simula il flusso per-tick reale: update_recovery_state -> _evaluate_axis(RA)
    -> finalize_recovery_windup. Restituisce le azioni dell'asse RA."""
    snap = _snap(rms_total=rms_total, rms_axis=rms_axis)
    ctrl._update_recovery_state(snap)
    acts = ctrl._evaluate_axis(
        ctrl._ra, ctrl.cfg.ra, snap.rms_ra, consec_high, consec_low, condition, snap)
    ctrl._finalize_recovery_windup(snap)
    return acts


# --------------------------------------------------------------------------- #
#  1. Recupero in banda morta: sale di step, oltre l'iniziale, fino a max       #
# --------------------------------------------------------------------------- #

class TestRecoveryRises(unittest.TestCase):

    def test_step_up_past_initial_capped_at_max(self):
        ctrl = _make_controller(mm0=0.40)
        ctrl._recovery_consec = 5            # trigger gia' maturo (>= consecutive_frames 3)
        # Un passo: 0.40 -> 0.45 (rms 0.60 nella banda morta e sopra mediana 0.50)
        acts = _eval_ra(ctrl, rms=0.60)
        self.assertEqual(len(acts), 1)
        self.assertEqual(acts[0].param, "MinMove")
        self.assertAlmostEqual(ctrl._ra.current_minmove, 0.45, places=4)
        # Prosegue OLTRE il valore iniziale, fino a minmove_max
        for _ in range(20):
            _eval_ra(ctrl, rms=0.60)
        self.assertAlmostEqual(ctrl._ra.current_minmove, 0.85, places=4)  # cap minmove_max
        # Al cap, nessuna ulteriore azione (new == old)
        self.assertEqual(_eval_ra(ctrl, rms=0.60), [])

    def test_no_recovery_below_consecutive(self):
        ctrl = _make_controller()
        ctrl._recovery_consec = 2            # < consecutive_frames 3
        self.assertEqual(_eval_ra(ctrl, rms=0.60), [])
        self.assertAlmostEqual(ctrl._ra.current_minmove, 0.40, places=4)


# --------------------------------------------------------------------------- #
#  1b. Anti-windup: K recuperi senza calo RMS -> stop (no windup a minmove_max) #
# --------------------------------------------------------------------------- #

class TestAntiWindup(unittest.TestCase):

    def test_blocks_after_k_without_progress(self):
        ctrl = _make_controller(mm0=0.40, cfg=_make_config(no_progress_k=3))
        # RMS costante 0.60 (mai cala): il softening non aiuta -> deve fermarsi.
        for _ in range(12):
            _tick(ctrl, rms_total=0.60)
        self.assertTrue(ctrl._recovery_blocked)
        # 3 recuperi (k) applicati: 0.40 -> 0.55, poi congelato (NON corre a 0.85).
        self.assertAlmostEqual(ctrl._ra.current_minmove, 0.55, places=4)
        self.assertLess(ctrl._ra.current_minmove, ctrl.cfg.ra.minmove_max)

    def test_continues_while_rms_drops(self):
        ctrl = _make_controller(mm0=0.40, cfg=_make_config(no_progress_k=3))
        # RMS cala di 0.02/tick ma resta sopra la soglia 0.50: il softening aiuta,
        # l'anti-windup ri-ancora e il recupero prosegue.
        for rms in (0.70, 0.68, 0.66, 0.64, 0.62, 0.60, 0.58, 0.56, 0.54, 0.52):
            _tick(ctrl, rms_total=rms)
        self.assertFalse(ctrl._recovery_blocked)
        # Recuperi a partire dal 3° tick (consec>=3): 8 step -> 0.40 + 8*0.05 = 0.80
        self.assertAlmostEqual(ctrl._ra.current_minmove, 0.80, places=4)

    def test_run_resets_when_rms_back_in_corridor(self):
        ctrl = _make_controller()
        for _ in range(5):
            _tick(ctrl, rms_total=0.60)      # costruisce consec + (eventuale) blocco
        self.assertGreaterEqual(ctrl._recovery_consec, 5)
        _tick(ctrl, rms_total=0.45)          # rientro nel corridoio (<= soglia 0.50)
        self.assertEqual(ctrl._recovery_consec, 0)
        self.assertFalse(ctrl._recovery_blocked)
        self.assertIsNone(ctrl._recovery_anchor_rms)


# --------------------------------------------------------------------------- #
#  2. Niente pompaggio: zona di isteresi tra rms_low e mediana -> fermo          #
# --------------------------------------------------------------------------- #

class TestHysteresisNoPumping(unittest.TestCase):

    def test_hysteresis_band_no_action(self):
        ctrl = _make_controller()
        ctrl._recovery_consec = 5
        # rms 0.40: > rms_low 0.30 (no CASO 3) e < mediana 0.50 (no recupero) -> fermo
        self.assertEqual(_eval_ra(ctrl, rms=0.40, consec_low=6), [])
        self.assertAlmostEqual(ctrl._ra.current_minmove, 0.40, places=4)

    def test_counter_only_grows_above_threshold(self):
        ctrl = _make_controller()
        for _ in range(4):
            _tick(ctrl, rms_total=0.60)      # sopra soglia -> incrementa
        self.assertEqual(ctrl._recovery_consec, 4)
        _tick(ctrl, rms_total=0.40)          # in isteresi (<= soglia) -> reset
        self.assertEqual(ctrl._recovery_consec, 0)


# --------------------------------------------------------------------------- #
#  3-4. CASO 3 / CASO 1 invariati                                               #
# --------------------------------------------------------------------------- #

class TestCasiUnchanged(unittest.TestCase):

    def test_caso3_minmove_down_unchanged(self):
        # Baseline None -> gate §30 inattivo E recupero indisponibile: CASO 3 legacy.
        ctrl = _make_controller()
        ctrl._rms_baseline_value = None
        acts = _eval_ra(ctrl, rms=0.25, consec_low=6)   # < rms_low 0.30 -> CASO 3
        self.assertGreater(len(acts), 0)
        self.assertAlmostEqual(ctrl._ra.current_minmove, 0.35, places=4)  # 0.40 - step
        self.assertEqual(ctrl._ra.current_aggr, 72.0)                     # aggr UP

    def test_caso1_unchanged(self):
        ctrl = _make_controller()
        acts = _eval_ra(ctrl, rms=1.5, consec_high=6,
                        condition=SeeingCondition.DEGRADED_SEEING)   # > rms_high 1.20
        self.assertGreater(len(acts), 0)
        self.assertEqual(ctrl._ra.current_aggr, 65.0)                    # aggr DOWN
        self.assertAlmostEqual(ctrl._ra.current_minmove, 0.45, places=4)  # CASO 1 minmove UP


# --------------------------------------------------------------------------- #
#  5. Switch OFF = bit-identico (nessun recupero)                               #
# --------------------------------------------------------------------------- #

class TestOffBitIdentical(unittest.TestCase):

    def test_disabled_no_recovery(self):
        ctrl = _make_controller(cfg=_make_config(recovery_enabled=False))
        ctrl._recovery_consec = 5
        # Stesso scenario che con ON recupererebbe: con OFF -> nessuna azione, leva ferma
        self.assertEqual(_eval_ra(ctrl, rms=0.60), [])
        self.assertAlmostEqual(ctrl._ra.current_minmove, 0.40, places=4)

    def test_enabled_would_act_same_scenario(self):
        ctrl = _make_controller(cfg=_make_config(recovery_enabled=True))
        ctrl._recovery_consec = 5
        self.assertEqual(len(_eval_ra(ctrl, rms=0.60)), 1)   # controprova: ON agisce


# --------------------------------------------------------------------------- #
#  6. Floor: il recupero parte da 0.15 e sale, mai sotto il floor               #
# --------------------------------------------------------------------------- #

class TestFloor(unittest.TestCase):

    def test_starts_at_floor_and_rises(self):
        ctrl = _make_controller(mm0=0.15)
        ctrl._recovery_consec = 5
        _eval_ra(ctrl, rms=0.60)
        self.assertAlmostEqual(ctrl._ra.current_minmove, 0.20, places=4)  # 0.15 + step
        self.assertGreaterEqual(ctrl._ra.current_minmove, ctrl.cfg.ra.minmove_min)


# --------------------------------------------------------------------------- #
#  Sospeso in JITTER (la catena CASO non gira -> nessun recupero)                #
# --------------------------------------------------------------------------- #

class TestSuspendedInJitter(unittest.TestCase):

    def test_no_recovery_in_jitter_mode(self):
        cfg = _make_config()
        cfg.diagnostic_engine = DiagnosticEngineConfig(enabled=True, mode="jitter")
        ctrl = _make_controller(cfg=cfg)
        ctrl.diagnostic_engine = ctrl._make_diagnostic_engine()
        ctrl._recovery_consec = 5
        # In jitter _evaluate_axis ritorna [] in testa (CASO sospesi) -> nessun recupero
        self.assertEqual(_eval_ra(ctrl, rms=0.60), [])
        self.assertAlmostEqual(ctrl._ra.current_minmove, 0.40, places=4)


if __name__ == "__main__":
    unittest.main()
