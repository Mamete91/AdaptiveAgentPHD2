"""
test_auto_calibration.py — Test unitari per l'auto-configurazione:
  - pixel scale di guida letta da PHD2 (con fallback TOML / null-safe)
  - soglie RMS adattive derivate da una baseline misurata
  - invalidazione baseline su cambio pixel scale
  - retrocompatibilità del parsing (sezione [auto_calibration] assente)

Casi coperti (1..9 come da specifica feature):
  1. Pixel scale da PHD2 valida → override applicato, source "phd2"
  2. Fallback su null → override None, property = valore TOML
  3. Feature OFF → override sempre None
  4. client.get_pixel_scale null-safe (None o eccezione → None, nessun crash)
  5. Baseline happy path → rms_high/rms_low derivati (cfg.thresholds E analyzer)
  6. Baseline ignora frame cattivi (SNR basso / implosion / DEGRADED)
  7. Clamp su rms_high derivato
  8. Invalidazione baseline su cambio pixel scale
  9. Retrocompatibilità parsing (sezione assente → default OFF)
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from phd2_agent.analyzer import AnalysisSnapshot, SeeingCondition, StatisticsAnalyzer
from phd2_agent.client import PHD2Client
from phd2_agent.config import (
    AgentConfig, AutoCalibrationConfig, AxisLimits, ControlConfig,
    EmergencyConfig, ExposureDynamicConfig, SetupConfig, Thresholds, load_config,
)
from phd2_agent.controller import AdaptiveController


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def _make_config(ac_enabled: bool = True, window: int = 5) -> AgentConfig:
    cfg = AgentConfig()
    cfg.control = ControlConfig(dry_run=True, cooldown_seconds=30.0)
    cfg.thresholds = Thresholds(
        rms_high=1.20, rms_low=0.60, snr_low=8.0,
        spike_ratio_high=0.30, consecutive_frames=5,
    )
    cfg.emergency = EmergencyConfig(
        auto_recovery=True, max_exposure_ms=4000,
        find_star_delay=10, saturation_timeout_s=300,
    )
    cfg.ra = AxisLimits()
    cfg.dec = AxisLimits()
    cfg.setup = SetupConfig(
        profile_name="auto",
        guide_pixel_scale_arcsec_native=0.51,
        guide_pixel_scale_arcsec_reduced=0.68,
        reducer_active=False,
    )
    cfg.exposure_dynamic = ExposureDynamicConfig(enabled=False)
    cfg.auto_calibration = AutoCalibrationConfig(
        enabled=ac_enabled,
        use_phd2_pixel_scale=True,
        rms_high_factor=1.5,
        rms_low_factor=0.75,
        baseline_window_frames=window,
        baseline_min_snr=10.0,
        # clamp proporzionale / reject / floor: default §23 (max_factor=2.0,
        # min=0.70, max=3.00, rms_low_min=0.25, reject_factor=3.0, reject_min=1.50)
    )
    return cfg


def _finalize_with(ctrl, scale: float, baseline: float, n: int = 5) -> None:
    """Helper §23: imposta la pixel scale efficace e una baseline deterministica
    (mediana == baseline), poi finalizza la calibrazione."""
    ctrl.cfg.setup.pixel_scale_override = scale
    ctrl._rms_baseline_samples = [baseline] * n
    ctrl._finalize_rms_baseline()


def _make_controller(cfg: AgentConfig | None = None,
                     pixel_scale=None) -> AdaptiveController:
    if cfg is None:
        cfg = _make_config()
    client = MagicMock()
    client.get_pixel_scale.return_value = pixel_scale
    analyzer = StatisticsAnalyzer(
        window_size=cfg.control.window_frames,
        rms_high=cfg.thresholds.rms_high,
        rms_low=cfg.thresholds.rms_low,
        snr_low=cfg.thresholds.snr_low,
    )
    ctrl = AdaptiveController(client=client, config=cfg, analyzer=analyzer)
    ctrl._initialized = True
    return ctrl


def _nominal_snap(rms_total: float, snr: float = 20.0) -> AnalysisSnapshot:
    snap = AnalysisSnapshot()
    snap.condition = SeeingCondition.NOMINAL
    snap.rms_total = rms_total
    snap.snr_avg = snr
    snap.implosion_detected = False
    snap.frame_count = 30
    return snap


# ---------------------------------------------------------------------------
# 1. Pixel scale da PHD2 valida
# ---------------------------------------------------------------------------

class TestPixelScaleFromPhd2(unittest.TestCase):

    def test_valid_scale_applied(self):
        ctrl = _make_controller(pixel_scale=1.03)
        ctrl._apply_pixel_scale_from_phd2("init")
        self.assertAlmostEqual(ctrl.cfg.setup.pixel_scale_override, 1.03)
        self.assertAlmostEqual(ctrl.cfg.setup.guide_pixel_scale_arcsec, 1.03)
        status = ctrl.get_status()
        self.assertEqual(status["auto_calibration"]["pixel_scale_source"], "phd2")
        self.assertAlmostEqual(status["auto_calibration"]["pixel_scale_arcsec"], 1.03)


# ---------------------------------------------------------------------------
# 2. Fallback su null → property = valore TOML
# ---------------------------------------------------------------------------

class TestPixelScaleNullFallback(unittest.TestCase):

    def test_null_falls_back_to_toml(self):
        ctrl = _make_controller(pixel_scale=None)
        ctrl._apply_pixel_scale_from_phd2("init")
        self.assertIsNone(ctrl.cfg.setup.pixel_scale_override)
        # native = 0.51 (reducer_active=False)
        self.assertAlmostEqual(ctrl.cfg.setup.guide_pixel_scale_arcsec, 0.51)
        status = ctrl.get_status()
        self.assertEqual(status["auto_calibration"]["pixel_scale_source"], "toml")


# ---------------------------------------------------------------------------
# 3. Feature OFF → override sempre None
# ---------------------------------------------------------------------------

class TestPixelScaleFeatureOff(unittest.TestCase):

    def test_feature_off_no_override(self):
        cfg = _make_config(ac_enabled=False)
        ctrl = _make_controller(cfg=cfg, pixel_scale=1.03)
        ctrl._apply_pixel_scale_from_phd2("init")
        self.assertIsNone(ctrl.cfg.setup.pixel_scale_override)
        self.assertAlmostEqual(ctrl.cfg.setup.guide_pixel_scale_arcsec, 0.51)
        # Con feature OFF il client non deve nemmeno essere interrogato
        ctrl.client.get_pixel_scale.assert_not_called()


# ---------------------------------------------------------------------------
# 4. client.get_pixel_scale null-safe
# ---------------------------------------------------------------------------

class TestClientNullSafe(unittest.TestCase):

    def test_returns_none_on_null(self):
        client = PHD2Client()
        client.call = MagicMock(return_value=None)
        self.assertIsNone(client.get_pixel_scale())

    def test_returns_none_on_exception(self):
        client = PHD2Client()
        client.call = MagicMock(side_effect=TimeoutError("no answer"))
        self.assertIsNone(client.get_pixel_scale())

    def test_returns_float_on_value(self):
        client = PHD2Client()
        client.call = MagicMock(return_value=1.23)
        self.assertAlmostEqual(client.get_pixel_scale(), 1.23)


# ---------------------------------------------------------------------------
# 5. Baseline happy path
# ---------------------------------------------------------------------------

class TestBaselineHappyPath(unittest.TestCase):

    def test_thresholds_derived_from_median(self):
        cfg = _make_config(window=5)
        ctrl = _make_controller(cfg=cfg)
        rms_values = [0.40, 0.50, 0.60, 0.50, 0.50]  # mediana = 0.50
        for v in rms_values:
            ctrl._update_rms_baseline(_nominal_snap(v))
        self.assertTrue(ctrl._rms_baseline_done)
        self.assertAlmostEqual(ctrl._rms_baseline_value, 0.50)
        # rms_high = clamp(1.5 * 0.50 = 0.75) → 0.75 ; rms_low = 0.75 * 0.50 = 0.375
        self.assertAlmostEqual(ctrl.cfg.thresholds.rms_high, 0.75)
        self.assertAlmostEqual(ctrl.cfg.thresholds.rms_low, 0.375)
        self.assertAlmostEqual(ctrl.analyzer.rms_high, 0.75)
        self.assertAlmostEqual(ctrl.analyzer.rms_low, 0.375)


# ---------------------------------------------------------------------------
# 6. Baseline ignora frame cattivi
# ---------------------------------------------------------------------------

class TestBaselineIgnoresBadFrames(unittest.TestCase):

    def test_bad_frames_not_sampled(self):
        cfg = _make_config(window=5)
        ctrl = _make_controller(cfg=cfg)

        # SNR sotto soglia
        low_snr = _nominal_snap(0.5, snr=5.0)
        ctrl._update_rms_baseline(low_snr)

        # Implosion
        implosion = _nominal_snap(0.5, snr=20.0)
        implosion.implosion_detected = True
        ctrl._update_rms_baseline(implosion)

        # Condizione degradata
        degraded = _nominal_snap(0.5, snr=20.0)
        degraded.condition = SeeingCondition.DEGRADED_SEEING
        ctrl._update_rms_baseline(degraded)

        self.assertEqual(len(ctrl._rms_baseline_samples), 0)
        self.assertFalse(ctrl._rms_baseline_done)


# ---------------------------------------------------------------------------
# 8. Invalidazione baseline su cambio pixel scale
# ---------------------------------------------------------------------------

class TestBaselineInvalidationOnScaleChange(unittest.TestCase):

    def test_scale_change_resets_baseline(self):
        cfg = _make_config(window=3)
        ctrl = _make_controller(cfg=cfg, pixel_scale=0.51)
        # Prima lettura: prev None → nessuna invalidazione
        ctrl._apply_pixel_scale_from_phd2("init")
        for _ in range(3):
            ctrl._update_rms_baseline(_nominal_snap(0.6))
        self.assertTrue(ctrl._rms_baseline_done)

        # Cambio scala reale → invalidazione
        ctrl.client.get_pixel_scale.return_value = 0.68
        ctrl._apply_pixel_scale_from_phd2("resume")
        self.assertFalse(ctrl._rms_baseline_done)
        self.assertIsNone(ctrl._rms_baseline_value)
        self.assertEqual(len(ctrl._rms_baseline_samples), 0)

    def test_same_scale_keeps_baseline(self):
        cfg = _make_config(window=3)
        ctrl = _make_controller(cfg=cfg, pixel_scale=0.51)
        ctrl._apply_pixel_scale_from_phd2("init")
        for _ in range(3):
            ctrl._update_rms_baseline(_nominal_snap(0.6))
        self.assertTrue(ctrl._rms_baseline_done)
        # Riconnessione a scala invariata → baseline preservata
        ctrl._apply_pixel_scale_from_phd2("resume")
        self.assertTrue(ctrl._rms_baseline_done)


# ---------------------------------------------------------------------------
# 9. Retrocompatibilità parsing
# ---------------------------------------------------------------------------

class TestParsingRetrocompat(unittest.TestCase):

    def test_missing_section_defaults_off(self):
        toml = (
            "[setup]\n"
            'profile_name = "x"\n'
            "[thresholds]\n"
            "rms_high = 0.8\n"
        )
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.toml"
            p.write_text(toml, encoding="utf-8")
            cfg = load_config(p)
        self.assertIsInstance(cfg.auto_calibration, AutoCalibrationConfig)
        self.assertFalse(cfg.auto_calibration.enabled)
        # default sani
        self.assertTrue(cfg.auto_calibration.use_phd2_pixel_scale)
        self.assertEqual(cfg.auto_calibration.baseline_window_frames, 60)


# ===========================================================================
# §23 — Clamp proporzionale alla pixel scale + gate di rifiuto baseline
# ===========================================================================

class TestProportionalCap(unittest.TestCase):

    def test_cap_rc8(self):
        """RC8: scala 0.51, baseline 0.8 → cap_prop 1.02 → ceiling 1.00 (§24); derived 1.20 → cap attivo."""
        ctrl = _make_controller(cfg=_make_config(window=5))
        _finalize_with(ctrl, scale=0.51, baseline=0.8)
        self.assertAlmostEqual(ctrl.cfg.thresholds.rms_high, 1.00, places=3)
        self.assertTrue(ctrl._rms_high_cap_active)
        self.assertAlmostEqual(ctrl._rms_high_cap_value, 1.00, places=3)
        self.assertFalse(ctrl._rms_baseline_rejected)
        # rms_low = max(0.25, 0.75*0.8=0.6) = 0.6
        self.assertAlmostEqual(ctrl.cfg.thresholds.rms_low, 0.6, places=3)

    def test_cap_askar_ceiling(self):
        """Askar: scala 1.58, baseline 1.4 → cap_prop 3.16 → ceiling 1.00 (§24); derived 2.10 → cap attivo."""
        ctrl = _make_controller(cfg=_make_config(window=5))
        _finalize_with(ctrl, scale=1.58, baseline=1.4)
        self.assertAlmostEqual(ctrl._rms_high_cap_value, 1.00, places=3)
        self.assertAlmostEqual(ctrl.cfg.thresholds.rms_high, 1.00, places=3)
        self.assertTrue(ctrl._rms_high_cap_active)  # derived 2.10 > cap 1.00

    def test_cap_floor_fine_scale(self):
        """Scala finissima 0.30, baseline 0.30 → cap_prop 0.60 → floor 0.70; derived 0.45 sotto cap."""
        ctrl = _make_controller(cfg=_make_config(window=5))
        _finalize_with(ctrl, scale=0.30, baseline=0.30)
        self.assertAlmostEqual(ctrl._rms_high_cap_value, 0.70, places=3)
        self.assertAlmostEqual(ctrl.cfg.thresholds.rms_high, 0.45, places=3)
        self.assertFalse(ctrl._rms_high_cap_active)
        self.assertFalse(ctrl._rms_baseline_rejected)


class TestBaselineReject(unittest.TestCase):

    def test_reject_rc8(self):
        """RC8: scala 0.51, baseline 1.6 → reject 1.53 < 1.6 → rifiutata, soglie invariate."""
        ctrl = _make_controller(cfg=_make_config(window=5))
        prev_high = ctrl.cfg.thresholds.rms_high
        prev_low = ctrl.cfg.thresholds.rms_low
        _finalize_with(ctrl, scale=0.51, baseline=1.6)
        self.assertTrue(ctrl._rms_baseline_rejected)
        self.assertTrue(ctrl._rms_baseline_done)
        self.assertFalse(ctrl._rms_high_cap_active)
        self.assertAlmostEqual(ctrl.cfg.thresholds.rms_high, prev_high)
        self.assertAlmostEqual(ctrl.cfg.thresholds.rms_low, prev_low)

    def test_reject_absolute_floor_dominates(self):
        """Scala finissima 0.20, baseline 1.6 → reject = max(1.5, 0.6) = 1.5 < 1.6 → rifiutata."""
        ctrl = _make_controller(cfg=_make_config(window=5))
        prev_high = ctrl.cfg.thresholds.rms_high
        _finalize_with(ctrl, scale=0.20, baseline=1.6)
        self.assertTrue(ctrl._rms_baseline_rejected)
        self.assertAlmostEqual(ctrl.cfg.thresholds.rms_high, prev_high)

    def test_accept_borderline(self):
        """RC8: scala 0.51, baseline 1.5 → reject 1.53 > 1.5 → accettata; cap 1.00 attivo (§24)."""
        ctrl = _make_controller(cfg=_make_config(window=5))
        _finalize_with(ctrl, scale=0.51, baseline=1.5)
        self.assertFalse(ctrl._rms_baseline_rejected)
        self.assertAlmostEqual(ctrl.cfg.thresholds.rms_high, 1.00, places=3)
        self.assertTrue(ctrl._rms_high_cap_active)  # derived 2.25 > cap 1.00


class TestRmsLowFloor(unittest.TestCase):

    def test_rms_low_floor(self):
        """Scala 1.0, baseline 0.25 → derived_low 0.1875 → floor 0.25."""
        ctrl = _make_controller(cfg=_make_config(window=5))
        _finalize_with(ctrl, scale=1.0, baseline=0.25)
        self.assertFalse(ctrl._rms_baseline_rejected)
        self.assertAlmostEqual(ctrl.cfg.thresholds.rms_low, 0.25, places=3)
        # rms_high = derived 1.5*0.25=0.375 (cap 2.0 non vincolante)
        self.assertAlmostEqual(ctrl.cfg.thresholds.rms_high, 0.375, places=3)


class TestStateResetOnInvalidation(unittest.TestCase):

    def test_invalidation_resets_new_flags(self):
        """Dopo finalize con cap attivo, _invalidate azzera tutti i flag §23."""
        ctrl = _make_controller(cfg=_make_config(window=5))
        _finalize_with(ctrl, scale=0.51, baseline=0.8)  # cap attivo
        self.assertTrue(ctrl._rms_high_cap_active)
        self.assertIsNotNone(ctrl._rms_high_cap_value)

        ctrl._invalidate_rms_baseline("test")
        self.assertFalse(ctrl._rms_baseline_done)
        self.assertFalse(ctrl._rms_baseline_rejected)
        self.assertFalse(ctrl._rms_high_cap_active)
        self.assertIsNone(ctrl._rms_high_cap_value)
        self.assertIsNone(ctrl._rms_baseline_value)
        self.assertEqual(len(ctrl._rms_baseline_samples), 0)


# ===========================================================================
# §24 — Cap globale a 1.00" + (verifica) pavimento proporzionale a scala fine
# ===========================================================================

class TestGlobalCeiling(unittest.TestCase):

    def test_cap_1_on_all_setups(self):
        """Stessa baseline 0.8 su scale diverse → cap sempre 1.00" (§24).
        Era 1.02 / 2.06 / 3.00 in §23; ora il tetto assoluto domina."""
        for scale in (0.51, 1.03, 1.58, 1.93):  # RC8, Tecnosky, Askar, cercatore 400mm
            ctrl = _make_controller(cfg=_make_config(window=5))
            _finalize_with(ctrl, scale=scale, baseline=0.8)
            self.assertFalse(ctrl._rms_baseline_rejected,
                             f"scala {scale}: baseline 0.8 non deve essere rifiutata")
            self.assertAlmostEqual(ctrl._rms_high_cap_value, 1.00, places=3,
                                   msg=f"scala {scale}: cap atteso 1.00")
            self.assertAlmostEqual(ctrl.cfg.thresholds.rms_high, 1.00, places=3,
                                   msg=f"scala {scale}: rms_high atteso 1.00")
            self.assertTrue(ctrl._rms_high_cap_active,
                            f"scala {scale}: cap deve risultare attivo (derived 1.2 > 1.00)")

    def test_proportional_floor_prevails_fine_scale(self):
        """Scala finissima 0.30: cap_prop 0.60 → pavimento 0.70; il tetto globale 1.00 NON si applica."""
        ctrl = _make_controller(cfg=_make_config(window=5))
        _finalize_with(ctrl, scale=0.30, baseline=0.30)
        self.assertAlmostEqual(ctrl._rms_high_cap_value, 0.70, places=3)
        self.assertLess(ctrl._rms_high_cap_value, 1.00)
        self.assertAlmostEqual(ctrl.cfg.thresholds.rms_high, 0.45, places=3)


if __name__ == "__main__":
    unittest.main()
