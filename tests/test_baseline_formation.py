"""
test_baseline_formation.py — La baseline deve formarsi SEMPRE (§33, prerequisito P1).

Verifica il fix sul campionamento della baseline auto-calibrata:
  - notte BUONA: percorso NOMINAL invariato (nessuna regressione);
  - notte BRUTTA (no 60 frame NOMINAL): la baseline si forma via FALLBACK dalla
    finestra 'tutti i frame', stimatore best-fraction;
  - CAP su rms_high invariato (1.00"); cap ANTI-INVERSIONE su rms_low (rms_low < rms_high);
  - rifiuto di fallback su INSTABILITA' (CoV alto) o tetto "guida rotta", non su
    valore assoluto basso;
  - kill-switch OFF -> comportamento identico (solo NOMINAL, nessun fallback);
  - parsing TOML retrocompatibile.

Setup: RC8 0.508"/px -> cap rms_high efficace = 1.00". window=10, fallback=30 (veloci).
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from phd2_agent.analyzer import AnalysisSnapshot, SeeingCondition
from phd2_agent.config import (
    AgentConfig, AutoCalibrationConfig, ControlConfig, SetupConfig, Thresholds,
    load_config,
)
from phd2_agent.controller import AdaptiveController


def _make_ctrl(**ac_over) -> AdaptiveController:
    cfg = AgentConfig()
    cfg.control = ControlConfig(dry_run=True)
    cfg.setup = SetupConfig(profile_name="rc8", guide_pixel_scale_arcsec_native=0.508)
    cfg.thresholds = Thresholds(rms_high=1.20, rms_low=0.60)
    ac = dict(enabled=True, baseline_window_frames=10, baseline_min_snr=10.0,
              baseline_fallback_frames=30, refresh_enabled=False)
    ac.update(ac_over)
    cfg.auto_calibration = AutoCalibrationConfig(**ac)
    ctrl = AdaptiveController(client=MagicMock(), config=cfg)
    ctrl._initialized = True
    return ctrl


def _snap(rms, cond=SeeingCondition.NOMINAL, snr=20.0, implosion=False) -> AnalysisSnapshot:
    s = AnalysisSnapshot()
    s.rms_total = rms
    s.condition = cond
    s.snr_avg = snr
    s.implosion_detected = implosion
    return s


def _feed(ctrl, n, rms, cond, snr=20.0) -> None:
    for _ in range(n):
        ctrl._update_rms_baseline(_snap(rms, cond, snr))


def _feed_each(ctrl, rms_list, cond, snr=20.0) -> None:
    for rms in rms_list:
        ctrl._update_rms_baseline(_snap(rms, cond, snr))


# --------------------------------------------------------------------------- #
#  1. Notte BUONA: percorso NOMINAL invariato (nessuna regressione)             #
# --------------------------------------------------------------------------- #

class TestGoodNightNominalPath(unittest.TestCase):

    def test_nominal_forms_as_before(self):
        ctrl = _make_ctrl()
        _feed(ctrl, 10, 0.5, SeeingCondition.NOMINAL)   # riempie la finestra NOMINAL
        self.assertEqual(ctrl._rms_baseline_value, 0.5)
        self.assertFalse(ctrl._rms_baseline_rejected)
        self.assertTrue(ctrl._rms_baseline_done)
        # rms_high = min(cap 1.00, 1.3*0.5=0.65) = 0.65 ; rms_low = 0.75*0.5 = 0.375
        self.assertAlmostEqual(ctrl.cfg.thresholds.rms_high, 0.65, places=4)
        self.assertAlmostEqual(ctrl.cfg.thresholds.rms_low, 0.375, places=4)


# --------------------------------------------------------------------------- #
#  2. Notte BRUTTA: la baseline si forma via FALLBACK (il fix)                  #
# --------------------------------------------------------------------------- #

class TestBadNightFallbackForms(unittest.TestCase):

    def test_fallback_forms_with_high_stable_rms(self):
        ctrl = _make_ctrl()
        _feed(ctrl, 30, 2.0, SeeingCondition.DEGRADED_SEEING)   # nessun NOMINAL, 30 frame
        self.assertIsNotNone(ctrl._rms_baseline_value)          # baseline FORMATA (vs None oggi)
        self.assertFalse(ctrl._rms_baseline_rejected)
        self.assertAlmostEqual(ctrl._rms_baseline_value, 2.0, places=4)  # best-fraction stabile
        # CAP invariato: rms_high resta 1.00 (1.3*2.0 >> 1.00)
        self.assertAlmostEqual(ctrl.cfg.thresholds.rms_high, 1.00, places=4)
        self.assertTrue(ctrl._rms_high_cap_active)

    def test_no_fallback_when_below_fallback_frames(self):
        ctrl = _make_ctrl()
        _feed(ctrl, 25, 1.5, SeeingCondition.DEGRADED_SEEING)   # 25 < fallback 30
        self.assertIsNone(ctrl._rms_baseline_value)
        self.assertFalse(ctrl._rms_baseline_done)


# --------------------------------------------------------------------------- #
#  3. Anti-inversione: rms_low SEMPRE sotto rms_high                            #
# --------------------------------------------------------------------------- #

class TestAntiInversion(unittest.TestCase):

    def test_rms_low_capped_below_rms_high(self):
        ctrl = _make_ctrl()
        _feed(ctrl, 30, 2.0, SeeingCondition.DEGRADED_SEEING)   # baseline 2.0
        # Senza cap: rms_low = 0.75*2.0 = 1.5 > rms_high 1.0 (inversione). Con cap:
        # rms_low = 1.0 * 0.85 = 0.85 < 1.0.
        self.assertAlmostEqual(ctrl.cfg.thresholds.rms_low, 0.85, places=4)
        self.assertLess(ctrl.cfg.thresholds.rms_low, ctrl.cfg.thresholds.rms_high)


# --------------------------------------------------------------------------- #
#  4. Stimatore best-fraction: prende il MEGLIO, non la mediana di tutto        #
# --------------------------------------------------------------------------- #

class TestBestFractionEstimator(unittest.TestCase):

    def test_picks_best_not_median_of_all(self):
        ctrl = _make_ctrl()
        # 15 frame a 1.0 + 15 a 3.0: mediana-di-tutto = 2.0; best 33% = solo gli 1.0.
        _feed_each(ctrl, [1.0] * 15 + [3.0] * 15, SeeingCondition.DEGRADED_SEEING)
        self.assertIsNotNone(ctrl._rms_baseline_value)
        self.assertAlmostEqual(ctrl._rms_baseline_value, 1.0, places=4)   # best, non 2.0


# --------------------------------------------------------------------------- #
#  5. Rifiuto fallback su INSTABILITA' (CoV alto) e su tetto "guida rotta"      #
# --------------------------------------------------------------------------- #

class TestFallbackReject(unittest.TestCase):

    def test_reject_on_instability(self):
        ctrl = _make_ctrl()
        # Pochi frame ottimi tra spazzatura -> best fraction instabile (CoV alto).
        _feed_each(ctrl, [0.3] * 5 + [5.0] * 25, SeeingCondition.DEGRADED_SEEING)
        self.assertTrue(ctrl._rms_baseline_rejected)
        # Soglie NON modificate (restano ai valori TOML correnti)
        self.assertAlmostEqual(ctrl.cfg.thresholds.rms_high, 1.20, places=4)

    def test_reject_on_broken_ceiling(self):
        ctrl = _make_ctrl(baseline_fallback_reject_arcsec=4.0)
        _feed(ctrl, 30, 5.0, SeeingCondition.DEGRADED_SEEING)   # stabile ma 5.0 > 4.0
        self.assertTrue(ctrl._rms_baseline_rejected)

    def test_high_but_stable_is_accepted(self):
        ctrl = _make_ctrl(baseline_fallback_reject_arcsec=4.0)
        _feed(ctrl, 30, 1.77, SeeingCondition.DEGRADED_SEEING)  # notte brutta reale
        self.assertFalse(ctrl._rms_baseline_rejected)
        self.assertIsNotNone(ctrl._rms_baseline_value)


# --------------------------------------------------------------------------- #
#  6. Kill-switch OFF = comportamento identico (nessun fallback)               #
# --------------------------------------------------------------------------- #

class TestKillSwitchOff(unittest.TestCase):

    def test_off_no_fallback_then_nominal_still_works(self):
        ctrl = _make_ctrl(baseline_always_form=False)
        _feed(ctrl, 50, 1.8, SeeingCondition.DEGRADED_SEEING)   # notte brutta
        self.assertIsNone(ctrl._rms_baseline_value)             # nessun fallback (come oggi)
        self.assertFalse(ctrl._rms_baseline_done)
        _feed(ctrl, 10, 0.5, SeeingCondition.NOMINAL)           # poi cielo buono
        self.assertEqual(ctrl._rms_baseline_value, 0.5)         # NOMINAL path invariato


# --------------------------------------------------------------------------- #
#  7. SNR basso non campiona (gate SNR invariato)                              #
# --------------------------------------------------------------------------- #

class TestSnrGate(unittest.TestCase):

    def test_low_snr_not_sampled(self):
        ctrl = _make_ctrl()
        _feed(ctrl, 40, 1.5, SeeingCondition.DEGRADED_SEEING, snr=5.0)  # SNR < 10
        self.assertIsNone(ctrl._rms_baseline_value)
        self.assertEqual(ctrl._baseline_frames_seen, 0)


# --------------------------------------------------------------------------- #
#  8. Parsing TOML retrocompatibile                                            #
# --------------------------------------------------------------------------- #

class TestTomlRetrocompat(unittest.TestCase):

    def test_missing_keys_defaults(self):
        toml = "[auto_calibration]\nenabled = true\n"
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.toml"
            p.write_text(toml, encoding="utf-8")
            cfg = load_config(p)
        ac = cfg.auto_calibration
        self.assertTrue(ac.baseline_always_form)
        self.assertEqual(ac.baseline_fallback_frames, 180)
        self.assertAlmostEqual(ac.baseline_best_fraction, 0.33)
        self.assertAlmostEqual(ac.rms_low_high_ratio_max, 0.85)

    def test_keys_parsed(self):
        toml = ("[auto_calibration]\nenabled = true\n"
                "baseline_always_form = false\nbaseline_best_fraction = 0.25\n")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.toml"
            p.write_text(toml, encoding="utf-8")
            cfg = load_config(p)
        self.assertFalse(cfg.auto_calibration.baseline_always_form)
        self.assertAlmostEqual(cfg.auto_calibration.baseline_best_fraction, 0.25)


if __name__ == "__main__":
    unittest.main()
