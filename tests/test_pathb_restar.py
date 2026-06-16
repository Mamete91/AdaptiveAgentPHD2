"""
test_pathb_restar.py — Riselezione stella all'aumento esposizione Path B (§35).

Verifica:
  - star_finder.find_best_star(prefer_unsaturated=True) scarta i blob saturi;
  - controller._evaluate_pathb_restar: riseleziona SOLO se la stella satura al nuovo
    tempo, dopo il settle, rispettando cooldown (anti-flapping) e stato di guida;
  - kill-switch OFF -> nessuna azione (resta solo il timer 300s).
"""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from phd2_agent.analyzer import AnalysisSnapshot, SeeingCondition
from phd2_agent.config import (
    AgentConfig, ControlConfig, ExposureDynamicConfig, SetupConfig, Thresholds,
)
from phd2_agent.controller import AdaptiveController, GuidingState
from phd2_agent.star_finder import find_best_star


# --------------------------------------------------------------------------- #
#  Helper: scrive un FITS float32 minimale con un singolo blob                  #
# --------------------------------------------------------------------------- #

def _write_fits_f32(path: str, arr: np.ndarray) -> None:
    h, w = arr.shape
    cards = [
        "SIMPLE  =                    T",
        "BITPIX  =                  -32",
        "NAXIS   =                    2",
        "NAXIS1  = " + str(w).rjust(20),
        "NAXIS2  = " + str(h).rjust(20),
        "END",
    ]
    header = "".join(c.ljust(80) for c in cards)
    header = header + " " * ((2880 - (len(header) % 2880)) % 2880)
    with open(path, "wb") as f:
        f.write(header.encode("ascii"))
        f.write(arr.astype(">f4").tobytes())


def _img_with_blob(peak: float, size: int = 60, blob: int = 10, bg: float = 1000.0) -> np.ndarray:
    arr = np.full((size, size), bg, dtype=np.float64)
    c = size // 2
    arr[c - blob // 2:c + blob // 2, c - blob // 2:c + blob // 2] = peak
    return arr


# --------------------------------------------------------------------------- #
#  1. find_best_star(prefer_unsaturated) — unit test sul FITS reale            #
# --------------------------------------------------------------------------- #

class TestFindBestStarPreferUnsaturated(unittest.TestCase):

    def test_saturated_only_field_returns_none_when_prefer_unsaturated(self):
        with tempfile.TemporaryDirectory() as d:
            p = str(Path(d) / "sat.fits")
            _write_fits_f32(p, _img_with_blob(65000))      # > 60000 = saturo
            cx, cy, info = find_best_star(p)
            self.assertIsNotNone(cx)
            self.assertTrue(info["is_saturated"])
            ncx, ncy, _ = find_best_star(p, prefer_unsaturated=True)
            self.assertIsNone(ncx)                          # nessuna stella NON satura

    def test_unsaturated_field_returned_in_both_modes(self):
        with tempfile.TemporaryDirectory() as d:
            p = str(Path(d) / "clean.fits")
            _write_fits_f32(p, _img_with_blob(40000))      # < 60000 = non saturo
            cx, cy, info = find_best_star(p)
            self.assertIsNotNone(cx)
            self.assertFalse(info["is_saturated"])
            ncx, ncy, _ = find_best_star(p, prefer_unsaturated=True)
            self.assertIsNotNone(ncx)                       # param non esclude le non sature


# --------------------------------------------------------------------------- #
#  Factory controller per i test di riselezione                                #
# --------------------------------------------------------------------------- #

def _make_ctrl(restar=True, cooldown=120.0) -> AdaptiveController:
    cfg = AgentConfig()
    cfg.control = ControlConfig(dry_run=True)
    cfg.setup = SetupConfig(profile_name="rc8", guide_pixel_scale_arcsec_native=0.508)
    cfg.thresholds = Thresholds()
    cfg.exposure_dynamic = ExposureDynamicConfig(
        enabled=True, restar_on_pathb_saturation=restar,
        pathb_restar_settle_frames=2, pathb_restar_cooldown_s=cooldown,
    )
    ctrl = AdaptiveController(client=MagicMock(), config=cfg)
    ctrl._initialized = True
    ctrl.guiding_state = GuidingState.NORMAL
    ctrl.dry_run = False
    ctrl.base_exposure_ms = 1000
    ctrl.current_exposure_ms = 2000
    return ctrl


def _snap() -> AnalysisSnapshot:
    s = AnalysisSnapshot()
    s.condition = SeeingCondition.DEGRADED_SEEING
    return s


# --------------------------------------------------------------------------- #
#  2-7. controller._evaluate_pathb_restar                                       #
# --------------------------------------------------------------------------- #

class TestPathBRestar(unittest.TestCase):

    def _arm(self, ctrl, due_in=-1.0, last=0.0):
        """Mette il restar in stato 'pronto' (pending + settle scaduto)."""
        ctrl._pathb_restar_pending = True
        ctrl._pathb_restar_due = time.monotonic() + due_in
        ctrl._pathb_restar_last_time = last

    def test_reselects_when_saturated(self):
        ctrl = _make_ctrl(restar=True)
        self._arm(ctrl)
        ctrl.client.save_image.return_value = "x.fits"
        with patch("phd2_agent.star_finder.find_best_star") as fbs, \
                patch("phd2_agent.controller.os.path.exists", return_value=True):
            fbs.side_effect = [
                (100.0, 100.0, {"is_saturated": True, "peak_adu": 65000}),   # corrente: satura
                (50.0, 50.0, {"is_saturated": False, "peak_adu": 42000}),    # alternativa non satura
            ]
            acts = ctrl._evaluate_pathb_restar(_snap())
        ctrl.client.set_lock_position.assert_called_once_with(50.0, 50.0)
        self.assertTrue(acts and acts[0].param == "pathb_restar")
        self.assertFalse(ctrl._pathb_restar_pending)

    def test_no_reselection_when_not_saturated(self):
        ctrl = _make_ctrl(restar=True)
        self._arm(ctrl)
        ctrl.client.save_image.return_value = "x.fits"
        with patch("phd2_agent.star_finder.find_best_star") as fbs, \
                patch("phd2_agent.controller.os.path.exists", return_value=True):
            fbs.side_effect = [(100.0, 100.0, {"is_saturated": False, "peak_adu": 30000})]
            ctrl._evaluate_pathb_restar(_snap())
        ctrl.client.set_lock_position.assert_not_called()

    def test_no_action_before_settle(self):
        ctrl = _make_ctrl(restar=True)
        self._arm(ctrl, due_in=+100.0)             # settle non ancora scaduto
        acts = ctrl._evaluate_pathb_restar(_snap())
        self.assertEqual(acts, [])
        self.assertTrue(ctrl._pathb_restar_pending)  # resta pending
        ctrl.client.save_image.assert_not_called()

    def test_kill_switch_off(self):
        ctrl = _make_ctrl(restar=False)
        self._arm(ctrl)
        acts = ctrl._evaluate_pathb_restar(_snap())
        self.assertEqual(acts, [])
        ctrl.client.save_image.assert_not_called()

    def test_cooldown_blocks_reselection(self):
        ctrl = _make_ctrl(restar=True, cooldown=300.0)
        self._arm(ctrl, last=time.monotonic())     # riselezione recentissima
        acts = ctrl._evaluate_pathb_restar(_snap())
        self.assertEqual(acts, [])
        ctrl.client.save_image.assert_not_called()

    def test_not_reselect_when_guiding_invalid(self):
        ctrl = _make_ctrl(restar=True)
        self._arm(ctrl)
        ctrl.guiding_state = GuidingState.STAR_LOST
        acts = ctrl._evaluate_pathb_restar(_snap())
        self.assertEqual(acts, [])
        ctrl.client.save_image.assert_not_called()

    def test_no_unsaturated_alternative_falls_back_to_timer(self):
        ctrl = _make_ctrl(restar=True)
        self._arm(ctrl)
        ctrl.client.save_image.return_value = "x.fits"
        with patch("phd2_agent.star_finder.find_best_star") as fbs, \
                patch("phd2_agent.controller.os.path.exists", return_value=True):
            fbs.side_effect = [
                (100.0, 100.0, {"is_saturated": True, "peak_adu": 65000}),   # satura
                (None, None, {"is_saturated": False, "peak_adu": 0}),        # nessuna alternativa
            ]
            ctrl._evaluate_pathb_restar(_snap())
        ctrl.client.set_lock_position.assert_not_called()
        self.assertIsNotNone(ctrl.saturated_lock_since)   # rete timer 300s armata


if __name__ == "__main__":
    unittest.main()
