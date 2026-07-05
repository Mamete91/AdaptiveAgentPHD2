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
        # rms_high_factor: default §25 (1.3) - non specificato di proposito
        rms_low_factor=0.75,
        baseline_window_frames=window,
        baseline_min_snr=10.0,
        # clamp proporzionale / reject / floor / refresh: default
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
        # §25 (f=1.3): rms_high = 1.3 * 0.50 = 0.65 ; rms_low = 0.75 * 0.50 = 0.375
        self.assertAlmostEqual(ctrl.cfg.thresholds.rms_high, 0.65)
        self.assertAlmostEqual(ctrl.cfg.thresholds.rms_low, 0.375)
        self.assertAlmostEqual(ctrl.analyzer.rms_high, 0.65)
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
        """Scala finissima 0.30, baseline 0.30 → cap_prop 0.60 → floor 0.70; derived 1.3*0.30=0.39 sotto cap."""
        ctrl = _make_controller(cfg=_make_config(window=5))
        _finalize_with(ctrl, scale=0.30, baseline=0.30)
        self.assertAlmostEqual(ctrl._rms_high_cap_value, 0.70, places=3)
        self.assertAlmostEqual(ctrl.cfg.thresholds.rms_high, 0.39, places=3)  # §25: 1.3*0.30
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
        # §25 (f=1.3): rms_high = 1.3*0.25 = 0.325 (cap 1.0 non vincolante)
        self.assertAlmostEqual(ctrl.cfg.thresholds.rms_high, 0.325, places=3)


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
        self.assertAlmostEqual(ctrl.cfg.thresholds.rms_high, 0.39, places=3)  # §25: 1.3*0.30


# ===========================================================================
# §25 — Refresh ciclico baseline (tightest-wins) + rms_high_factor 1.3
# ===========================================================================

import time


def _start_refresh(ctrl, new_baseline: float, n: int = 5) -> None:
    """Simula l'inizio di un ciclo di refresh con N campioni della nuova baseline,
    senza dipendere dal timer reale: imposta il flag in_progress e popola samples,
    poi chiama _finalize_rms_baseline come farebbe _update_rms_baseline a finestra piena."""
    ctrl._baseline_refresh_in_progress = True
    ctrl._rms_baseline_done = False
    ctrl._rms_baseline_samples = [new_baseline] * n
    ctrl._finalize_rms_baseline()


class TestRefreshTightestWins(unittest.TestCase):

    def test_apply_when_tighter(self):
        """Baseline corrente 0.6 → nuova 0.4: applicata, soglie ristrette."""
        ctrl = _make_controller(cfg=_make_config(window=5))
        _finalize_with(ctrl, scale=0.51, baseline=0.6)        # corrente
        prev_high = ctrl.cfg.thresholds.rms_high

        _start_refresh(ctrl, new_baseline=0.4)
        self.assertEqual(ctrl._last_refresh_action, "applicato")
        self.assertAlmostEqual(ctrl._last_refresh_baseline, 0.4)
        self.assertAlmostEqual(ctrl._rms_baseline_value, 0.4)
        self.assertFalse(ctrl._baseline_refresh_in_progress)
        # Nuova rms_high = 1.3 * 0.4 = 0.52 (sotto cap 1.00) → strettamente minore della precedente
        self.assertAlmostEqual(ctrl.cfg.thresholds.rms_high, 0.52, places=3)
        self.assertLess(ctrl.cfg.thresholds.rms_high, prev_high)

    def test_reject_when_worse(self):
        """Baseline corrente 0.5 → nuova 0.8 (peggiore): rifiutata, soglie e baseline correnti preservate."""
        ctrl = _make_controller(cfg=_make_config(window=5))
        _finalize_with(ctrl, scale=0.51, baseline=0.5)
        prev_high = ctrl.cfg.thresholds.rms_high
        prev_low = ctrl.cfg.thresholds.rms_low
        prev_baseline = ctrl._rms_baseline_value

        _start_refresh(ctrl, new_baseline=0.8)
        self.assertEqual(ctrl._last_refresh_action, "rifiutato")
        self.assertAlmostEqual(ctrl._last_refresh_baseline, 0.8)
        self.assertFalse(ctrl._baseline_refresh_in_progress)
        self.assertAlmostEqual(ctrl._rms_baseline_value, prev_baseline)   # baseline corrente preservata
        self.assertAlmostEqual(ctrl.cfg.thresholds.rms_high, prev_high)
        self.assertAlmostEqual(ctrl.cfg.thresholds.rms_low, prev_low)
        # Il timer riparte: _baseline_finalize_time aggiornato a "adesso"
        self.assertIsNotNone(ctrl._baseline_finalize_time)

    def test_reject_when_equal(self):
        """Baseline uguale (new == current): regola new >= current → rifiutata."""
        ctrl = _make_controller(cfg=_make_config(window=5))
        _finalize_with(ctrl, scale=0.51, baseline=0.5)
        prev_high = ctrl.cfg.thresholds.rms_high

        _start_refresh(ctrl, new_baseline=0.5)
        self.assertEqual(ctrl._last_refresh_action, "rifiutato")
        self.assertAlmostEqual(ctrl.cfg.thresholds.rms_high, prev_high)


class TestRefreshTrigger(unittest.TestCase):

    def test_disabled_does_not_start(self):
        """Con refresh_enabled=False, _maybe_start_refresh è no-op anche con timer scaduto."""
        cfg = _make_config(window=5)
        cfg.auto_calibration.refresh_enabled = False
        ctrl = _make_controller(cfg=cfg)
        _finalize_with(ctrl, scale=0.51, baseline=0.5)
        # Forza il timer scaduto
        ctrl._baseline_finalize_time = time.monotonic() - 1e6
        ctrl._maybe_start_refresh()
        self.assertFalse(ctrl._baseline_refresh_in_progress)
        self.assertTrue(ctrl._rms_baseline_done)   # la baseline corrente resta "done"

    def test_enabled_starts_on_elapsed_timer(self):
        """Con refresh_enabled=True e timer scaduto, _maybe_start_refresh riapre la raccolta."""
        cfg = _make_config(window=5)
        cfg.auto_calibration.refresh_interval_seconds = 1.0
        # §44: il refresh ciclico §25 è la modalità LEGACY (opt-in); va disattivato il
        # tracker continuo bidirezionale per esercitarlo.
        cfg.auto_calibration.baseline_track_bidirectional = False
        ctrl = _make_controller(cfg=cfg)
        _finalize_with(ctrl, scale=0.51, baseline=0.5)
        ctrl._baseline_finalize_time = time.monotonic() - 5.0   # 5s fa, oltre soglia 1s
        ctrl._maybe_start_refresh()
        self.assertTrue(ctrl._baseline_refresh_in_progress)
        self.assertFalse(ctrl._rms_baseline_done)
        self.assertEqual(len(ctrl._rms_baseline_samples), 0)


class TestRefreshAndRejectGate(unittest.TestCase):

    def test_refresh_with_reject_gate(self):
        """Durante refresh, baseline che supera il gate §23 → refresh esito 'rifiutato'.
        Soglie correnti e baseline corrente preservate (NON aggiornate dal rigetto)."""
        ctrl = _make_controller(cfg=_make_config(window=5))
        _finalize_with(ctrl, scale=0.51, baseline=0.5)
        prev_high = ctrl.cfg.thresholds.rms_high
        prev_baseline = ctrl._rms_baseline_value

        # 1.6" a scala 0.51 → reject = max(1.5, 1.53) = 1.53 < 1.6 → gate scatta
        _start_refresh(ctrl, new_baseline=1.6)
        self.assertEqual(ctrl._last_refresh_action, "rifiutato")
        self.assertAlmostEqual(ctrl._last_refresh_baseline, 1.6)
        self.assertTrue(ctrl._rms_baseline_rejected)
        self.assertFalse(ctrl._baseline_refresh_in_progress)
        # Soglie e baseline corrente PRESERVATE
        self.assertAlmostEqual(ctrl.cfg.thresholds.rms_high, prev_high)
        self.assertAlmostEqual(ctrl._rms_baseline_value, prev_baseline)


class TestRefreshStatus(unittest.TestCase):

    def test_status_fields_after_finalize(self):
        """Dopo il primo finalize, /status espone refresh_seconds_to_next e nessun refresh in corso."""
        cfg = _make_config(window=5)
        cfg.auto_calibration.refresh_interval_seconds = 1800.0
        ctrl = _make_controller(cfg=cfg)
        _finalize_with(ctrl, scale=0.51, baseline=0.5)

        ac = ctrl.get_status()["auto_calibration"]
        self.assertTrue(ac["refresh_enabled"])
        self.assertEqual(ac["refresh_interval_seconds"], 1800.0)
        self.assertFalse(ac["refresh_in_progress"])
        self.assertIsNone(ac["refresh_progress"])
        self.assertIsNotNone(ac["refresh_seconds_to_next"])
        # Subito dopo finalize, secondi rimanenti ~ intervallo (entro tolleranza)
        self.assertGreater(ac["refresh_seconds_to_next"], 1700.0)
        self.assertLessEqual(ac["refresh_seconds_to_next"], 1800.0)

    def test_status_fields_during_refresh(self):
        """Durante refresh, refresh_in_progress True e refresh_progress popolato."""
        cfg = _make_config(window=10)
        # §44: refresh ciclico §25 = modalità legacy (opt-in).
        cfg.auto_calibration.baseline_track_bidirectional = False
        ctrl = _make_controller(cfg=cfg)
        _finalize_with(ctrl, scale=0.51, baseline=0.5, n=10)
        # Forza l'inizio di un refresh manualmente
        ctrl._baseline_finalize_time = time.monotonic() - 1e6
        ctrl._maybe_start_refresh()
        # Aggiungi 3 campioni (su finestra 10) per simulare raccolta in corso
        ctrl._rms_baseline_samples = [0.4, 0.45, 0.5]

        ac = ctrl.get_status()["auto_calibration"]
        self.assertTrue(ac["refresh_in_progress"])
        self.assertEqual(ac["refresh_progress"], "3/10")
        self.assertIsNone(ac["refresh_seconds_to_next"])   # None mentre in corso


class TestBaselineContinuousBidirectional(unittest.TestCase):
    """§44 — baseline a rinnovo continuo e bidirezionale (CAP §24 mantenuto)."""

    @staticmethod
    def _snap(rms: float, snr: float = 20.0) -> AnalysisSnapshot:
        s = AnalysisSnapshot()
        s.rms_total = rms
        s.snr_avg = snr
        s.condition = SeeingCondition.NOMINAL
        return s

    def test_worsening_raises_baseline_under_cap(self):
        # Default bidirezionale ON. Baseline iniziale 0.50 -> rms_high 0.65 (1.3x, sotto cap 1.00).
        cfg = _make_config(window=5)   # scale 0.51 -> cap efficace = 1.00
        ctrl = _make_controller(cfg=cfg)
        self.assertTrue(ctrl.cfg.auto_calibration.baseline_track_bidirectional)
        _finalize_with(ctrl, scale=0.51, baseline=0.50, n=5)
        high0 = ctrl.cfg.thresholds.rms_high
        self.assertAlmostEqual(high0, 0.65, places=3)
        self.assertFalse(ctrl._rms_high_cap_active)
        # Seeing peggiora: feed di 5 frame a RMS 0.65 (sotto il cap) via il percorso reale.
        for _ in range(5):
            ctrl._update_rms_baseline(self._snap(0.65))
        # La baseline è SALITA -> rms_high sale (1.3 x 0.65 = 0.845), cap non attivo.
        self.assertGreater(ctrl.cfg.thresholds.rms_high, high0)
        self.assertAlmostEqual(ctrl._rms_baseline_value, 0.65, places=3)
        self.assertAlmostEqual(ctrl.cfg.thresholds.rms_high, 0.845, places=3)
        self.assertFalse(ctrl._rms_high_cap_active)

    def test_improving_tightens_baseline(self):
        cfg = _make_config(window=5)
        ctrl = _make_controller(cfg=cfg)
        _finalize_with(ctrl, scale=0.51, baseline=0.65, n=5)
        high0 = ctrl.cfg.thresholds.rms_high          # 0.845
        ctrl._rms_rolling.extend([0.40] * 5)
        ctrl._continuous_track_baseline()
        self.assertLess(ctrl.cfg.thresholds.rms_high, high0)
        self.assertAlmostEqual(ctrl._rms_baseline_value, 0.40, places=3)

    def test_cap_still_effective_in_continuous(self):
        # §44 NON tocca il CAP §24: con baseline alta il tetto morde ancora.
        cfg = _make_config(window=5)
        ctrl = _make_controller(cfg=cfg)
        _finalize_with(ctrl, scale=0.51, baseline=0.50, n=5)   # cap efficace 1.00
        ctrl._rms_rolling.extend([0.90] * 5)                   # 1.3x0.90 = 1.17 > 1.00
        ctrl._continuous_track_baseline()
        self.assertAlmostEqual(ctrl.cfg.thresholds.rms_high, 1.00, places=3)
        self.assertTrue(ctrl._rms_high_cap_active)

    def test_reject_gate_backstop_in_continuous(self):
        # Baseline assurda oltre §23 (reject = max(1.5, 3x0.51=1.53)) -> nessun update.
        cfg = _make_config(window=5)
        ctrl = _make_controller(cfg=cfg)
        _finalize_with(ctrl, scale=0.51, baseline=0.50, n=5)
        high0 = ctrl.cfg.thresholds.rms_high
        base0 = ctrl._rms_baseline_value
        ctrl._rms_rolling.extend([1.60] * 5)                   # 1.60 > 1.53 -> rifiutata
        ctrl._continuous_track_baseline()
        self.assertAlmostEqual(ctrl.cfg.thresholds.rms_high, high0)   # soglie correnti mantenute
        self.assertAlmostEqual(ctrl._rms_baseline_value, base0)

    def test_killswitch_off_restores_legacy(self):
        # baseline_track_bidirectional=false -> il tracker continuo NON gira: dopo la
        # formazione, feed di frame peggiori non muove le soglie (comportamento legacy §25).
        cfg = _make_config(window=5)
        cfg.auto_calibration.baseline_track_bidirectional = False
        ctrl = _make_controller(cfg=cfg)
        _finalize_with(ctrl, scale=0.51, baseline=0.50, n=5)
        high0 = ctrl.cfg.thresholds.rms_high
        for _ in range(10):
            ctrl._update_rms_baseline(self._snap(0.90))
        self.assertAlmostEqual(ctrl.cfg.thresholds.rms_high, high0)   # invariato
        self.assertEqual(len(ctrl._rms_rolling), 0)                   # rolling non alimentato


if __name__ == "__main__":
    unittest.main()
