"""
config.py - Caricamento e validazione di config.toml

Aggiornato per supportare:
  - Sezione [setup] con profile_name (multi-setup, baseline guardian)
  - emergency.saturation_timeout_s (timer stelle sature)
  - SetupConfig esteso con pixel scale nativo/ridotto e toggle reducer_active
"""
from __future__ import annotations

import logging

try:
    import tomllib          # Python 3.11+
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]  # Python 3.10

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SetupConfig:
    """Profilo setup ottico: pixel scale di guida (nativo/ridotto) e toggle riduttore."""
    profile_name: str = "default"
    guide_pixel_scale_arcsec_native:  float = 1.0
    guide_pixel_scale_arcsec_reduced: float = 1.0
    reducer_active: bool = False
    # Override runtime impostato da get_pixel_scale (NON parsato dal TOML).
    # None = scala sconosciuta da PHD2 -> usa i valori native/reduced del TOML.
    pixel_scale_override: Optional[float] = None

    @property
    def guide_pixel_scale_arcsec(self) -> float:
        """Pixel scale effettiva. Priorita': override runtime (da PHD2) > reduced/native (da TOML)."""
        if self.pixel_scale_override is not None:
            return self.pixel_scale_override
        return (self.guide_pixel_scale_arcsec_reduced
                if self.reducer_active
                else self.guide_pixel_scale_arcsec_native)


@dataclass
class PHD2Config:
    host: str = "localhost"
    port: int = 4400


@dataclass
class DashboardConfig:
    host: str = "0.0.0.0"
    port: int = 8080


@dataclass
class ControlConfig:
    dry_run: bool = True
    interval_seconds: float = 10.0
    window_frames: int = 30
    cooldown_seconds: float = 30.0


@dataclass
class Thresholds:
    rms_high: float = 0.80
    rms_low: float = 0.35
    snr_low: float = 10.0
    spike_ratio_high: float = 0.30
    consecutive_frames: int = 5


@dataclass
class EmergencyConfig:
    auto_recovery: bool = True
    max_exposure_ms: int = 5000
    find_star_delay: int = 10
    saturation_timeout_s: int = 300


@dataclass
class AxisLimits:
    # Range armonizzati RA/DEC (§24): piu' dinamica nei due estremi.
    aggr_min: float = 35.0
    aggr_max: float = 90.0
    aggr_step_down: float = 5.0
    aggr_step_up: float = 2.0
    minmove_min: float = 0.15
    minmove_max: float = 0.85
    minmove_step: float = 0.05


@dataclass
class LoggingConfig:
    csv_dir: str = "logs"
    log_level: str = "INFO"


@dataclass
class PHD2LogConfig:
    log_dir: str = ""
    output_dir: str = "phd2_log"
    auto_import: bool = True


@dataclass
class ExposureDynamicConfig:
    enabled: bool = False
    step_factor: float = 1.5
    max_steps_above_base: int = 2
    cooldown_s: float = 90.0
    spike_min: float = 0.25
    hfd_min_arcsec: float = 4.0
    peak_to_rms_ratio_min: float = 3.0
    nominal_for_seconds: float = 60.0


@dataclass
class AutoCalibrationConfig:
    """Auto-configurazione: pixel scale da PHD2 + soglie RMS da baseline misurata."""
    enabled: bool = False
    use_phd2_pixel_scale: bool = True
    rms_high_factor: float = 1.3   # cuscinetto sopra baseline (§25: 1.5 -> 1.3 protegge focali lunghe)
    rms_low_factor: float = 0.75
    baseline_window_frames: int = 60
    baseline_min_snr: float = 10.0
    # Clamp proporzionale del cap su rms_high (§23, sostituisce il clamp fisso §22):
    # cap_efficace = clamp(rms_high_max_factor * pixel_scale, rms_high_min_arcsec, rms_high_max_arcsec)
    rms_high_max_factor: float = 2.0     # k del cap proporzionale: cap = k * pixel_scale
    rms_high_min_arcsec: float = 0.70    # pavimento assoluto del cap (era 0.50 in §22)
    rms_high_max_arcsec: float = 1.00    # tetto assoluto del cap (§24: era 3.00 in §23; benchmark "guida pulita")
    # Floor su rms_low derivato:
    rms_low_min_arcsec: float = 0.25     # pavimento assoluto su rms_low
    # Gate di rifiuto baseline: reject se baseline > max(baseline_reject_min_arcsec, baseline_reject_factor * scale)
    baseline_reject_factor: float = 3.0
    baseline_reject_min_arcsec: float = 1.50
    # §25 — Refresh ciclico baseline (regola tightest-wins): l'Agente non concede
    # mai reattività al cielo che peggiora, ma si adatta quando migliora.
    refresh_enabled: bool = True
    refresh_interval_seconds: float = 1800.0     # 30 minuti
    refresh_only_if_tighter: bool = True


@dataclass
class LeverOptimizationConfig:
    """Satisfaction gate sul ramo guida-ottima (§30, Agente v2.3).

    Quando il gate è attivo e l'RMS dell'asse è gia' <= mediana baseline ×
    target_factor, il ramo di ottimizzazione del CASO 3 di _evaluate_axis
    NON spinge le leve verso la reattività (Aggr UP / MinMove DOWN). Le leve
    restano al loro valore corrente finche' il regime resta "guida ottima".
    Se l'RMS risale sopra la soglia, il gate rilascia automaticamente le leve
    e il CASO 3 torna a operare come da v2.2.

    Il gate NON modifica CASO 1 (degradato) ne' CASO 2 (oscillazione): l'asimmetria
    e' intenzionale. Quando il seeing peggiora, le leve continuano ad ammorbidirsi
    fino all'eventuale apertura dell'escalation gate (§19).
    """
    enabled: bool = True
    # Fattore moltiplicativo sulla mediana baseline. 1.0 = "ferma se RMS <= mediana".
    # 0.9 = piu' conservativo (ferma anche prima). 1.1 = piu' permissivo (lascia
    # esplorare un po' anche sopra mediana).
    target_factor: float = 1.0


@dataclass
class AgentConfig:
    setup: SetupConfig = field(default_factory=SetupConfig)
    phd2: PHD2Config = field(default_factory=PHD2Config)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)
    control: ControlConfig = field(default_factory=ControlConfig)
    thresholds: Thresholds = field(default_factory=Thresholds)
    emergency: EmergencyConfig = field(default_factory=EmergencyConfig)
    ra: AxisLimits = field(default_factory=AxisLimits)
    dec: AxisLimits = field(default_factory=AxisLimits)   # §24: RA/DEC armonizzati
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    phd2_log: PHD2LogConfig = field(default_factory=PHD2LogConfig)
    exposure_dynamic: ExposureDynamicConfig = field(default_factory=ExposureDynamicConfig)
    auto_calibration: AutoCalibrationConfig = field(default_factory=AutoCalibrationConfig)
    lever_optimization: LeverOptimizationConfig = field(default_factory=LeverOptimizationConfig)


def load_config(path: str | Path = "config.toml") -> AgentConfig:
    """Carica config.toml e ritorna un oggetto AgentConfig tipizzato."""
    p = Path(path)
    if not p.exists():
        return AgentConfig()

    with open(p, "rb") as f:
        raw = tomllib.load(f)

    cfg = AgentConfig()

    # Setup
    if "setup" in raw:
        s = raw["setup"]
        cfg.setup = SetupConfig(
            profile_name=str(s.get("profile_name", "")),
            guide_pixel_scale_arcsec_native=float(s.get("guide_pixel_scale_arcsec_native", 1.0)),
            guide_pixel_scale_arcsec_reduced=float(s.get("guide_pixel_scale_arcsec_reduced", 1.0)),
            reducer_active=bool(s.get("reducer_active", False)),
        )

    # PHD2
    if "phd2" in raw:
        phd2 = raw["phd2"]
        cfg.phd2.host = phd2.get("host", cfg.phd2.host)
        cfg.phd2.port = phd2.get("port", cfg.phd2.port)

    # Dashboard
    if "dashboard" in raw:
        dash = raw["dashboard"]
        cfg.dashboard.host = dash.get("host", cfg.dashboard.host)
        cfg.dashboard.port = dash.get("port", cfg.dashboard.port)

    # Control
    if "control" in raw:
        ctrl = raw["control"]
        cfg.control.dry_run = ctrl.get("dry_run", cfg.control.dry_run)
        cfg.control.interval_seconds = ctrl.get(
            "interval_seconds", cfg.control.interval_seconds)
        cfg.control.window_frames = ctrl.get(
            "window_frames", cfg.control.window_frames)
        cfg.control.cooldown_seconds = ctrl.get(
            "cooldown_seconds", cfg.control.cooldown_seconds)

    # Thresholds
    th_dict = raw.get("thresholds", {})
    cfg.thresholds = Thresholds(
        rms_high=float(th_dict.get("rms_high", 0.80)),
        rms_low=float(th_dict.get("rms_low", 0.35)),
        snr_low=float(th_dict.get("snr_low", 10.0)),
        spike_ratio_high=float(th_dict.get("spike_ratio_high", 0.30)),
        consecutive_frames=int(th_dict.get("consecutive_frames", 5)),
    )

    # Emergency
    em_dict = raw.get("emergency", {})
    cfg.emergency = EmergencyConfig(
        auto_recovery=bool(em_dict.get("auto_recovery", True)),
        max_exposure_ms=int(em_dict.get("max_exposure_ms", 5000)),
        find_star_delay=int(em_dict.get("find_star_delay", 10)),
        saturation_timeout_s=int(em_dict.get("saturation_timeout_s", 300)),
    )

    # Axis limits
    if "limits" in raw:
        for axis_key, target in [("ra", cfg.ra), ("dec", cfg.dec)]:
            if axis_key in raw["limits"]:
                ax = raw["limits"][axis_key]
                target.aggr_min = ax.get("aggr_min", target.aggr_min)
                target.aggr_max = ax.get("aggr_max", target.aggr_max)
                target.aggr_step_down = ax.get(
                    "aggr_step_down", target.aggr_step_down)
                target.aggr_step_up = ax.get("aggr_step_up", target.aggr_step_up)
                target.minmove_min = ax.get("minmove_min", target.minmove_min)
                target.minmove_max = ax.get("minmove_max", target.minmove_max)
                target.minmove_step = ax.get("minmove_step", target.minmove_step)

    # Logging
    if "logging" in raw:
        lg = raw["logging"]
        cfg.logging.csv_dir = lg.get("csv_dir", cfg.logging.csv_dir)
        cfg.logging.log_level = lg.get("log_level", cfg.logging.log_level)

    # PHD2 log import
    if "phd2_log" in raw:
        pl = raw["phd2_log"]
        cfg.phd2_log.log_dir = pl.get("log_dir", cfg.phd2_log.log_dir)
        cfg.phd2_log.output_dir = pl.get("output_dir", cfg.phd2_log.output_dir)
        cfg.phd2_log.auto_import = bool(pl.get("auto_import", cfg.phd2_log.auto_import))

    # Exposure dynamic (sezione opzionale — default se mancante per retrocompatibilità)
    if "exposure_dynamic" in raw:
        ed = raw["exposure_dynamic"]
        if "guide_pixel_scale_arcsec" in ed:
            logger.debug(
                "Campo legacy `guide_pixel_scale_arcsec` in [exposure_dynamic] ignorato "
                "— usare [setup]"
            )
        cfg.exposure_dynamic = ExposureDynamicConfig(
            enabled=bool(ed.get("enabled", False)),
            step_factor=float(ed.get("step_factor", 1.5)),
            max_steps_above_base=int(ed.get("max_steps_above_base", 2)),
            cooldown_s=float(ed.get("cooldown_s", 90.0)),
            spike_min=float(ed.get("spike_min", 0.25)),
            hfd_min_arcsec=float(ed.get("hfd_min_arcsec", 4.0)),
            peak_to_rms_ratio_min=float(ed.get("peak_to_rms_ratio_min", 3.0)),
            nominal_for_seconds=float(ed.get("nominal_for_seconds", 60.0)),
        )

    # Auto-calibration (sezione opzionale — default se mancante per retrocompatibilita')
    if "auto_calibration" in raw:
        a = raw["auto_calibration"]
        cfg.auto_calibration = AutoCalibrationConfig(
            enabled=bool(a.get("enabled", False)),
            use_phd2_pixel_scale=bool(a.get("use_phd2_pixel_scale", True)),
            rms_high_factor=float(a.get("rms_high_factor", 1.3)),
            rms_low_factor=float(a.get("rms_low_factor", 0.75)),
            baseline_window_frames=int(a.get("baseline_window_frames", 60)),
            baseline_min_snr=float(a.get("baseline_min_snr", 10.0)),
            rms_high_max_factor=float(a.get("rms_high_max_factor", 2.0)),
            rms_high_min_arcsec=float(a.get("rms_high_min_arcsec", 0.70)),
            rms_high_max_arcsec=float(a.get("rms_high_max_arcsec", 1.00)),
            rms_low_min_arcsec=float(a.get("rms_low_min_arcsec", 0.25)),
            baseline_reject_factor=float(a.get("baseline_reject_factor", 3.0)),
            baseline_reject_min_arcsec=float(a.get("baseline_reject_min_arcsec", 1.50)),
            refresh_enabled=bool(a.get("refresh_enabled", True)),
            refresh_interval_seconds=float(a.get("refresh_interval_seconds", 1800.0)),
            refresh_only_if_tighter=bool(a.get("refresh_only_if_tighter", True)),
        )

    # §30 — Satisfaction gate (sezione opzionale; assente -> default dataclass)
    if "lever_optimization" in raw:
        lo = raw["lever_optimization"]
        cfg.lever_optimization = LeverOptimizationConfig(
            enabled=bool(lo.get("enabled", True)),
            target_factor=float(lo.get("target_factor", 1.0)),
        )

    return cfg
