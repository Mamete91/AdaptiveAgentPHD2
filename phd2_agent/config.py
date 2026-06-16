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
    # §34 — accumulo baseline e popolamento dei campi di logging per OGNI guide-frame
    # (non solo sul tick interval_seconds). Corregge: (a) baseline lenta (contava i tick
    # da 10s -> ~30 min invece di ~6), (b) righe CSV fuori-tick con placeholder
    # (exposure_ms=0, diag_state=INSUFFICIENT) che gonfiavano l'"85% INSUFFICIENT".
    # Default true (shipped ON). A false: comportamento storico per-tick.
    per_frame_baseline: bool = True


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
    # §35 — riselezione stella all'aumento esposizione (Path B). Se, dopo che Path B
    # ha alzato l'esposizione, la stella corrente SATURA al nuovo tempo, riseleziona
    # proattivamente una stella non satura (entro pochi secondi, non i 300s del timer).
    # Default true (shipped ON). pathb_restar_settle_frames = quanti "frame" (× durata
    # esposizione) attendere che il nuovo tempo sia attivo prima del check.
    # pathb_restar_cooldown_s = anti-flapping fra riselezioni successive.
    restar_on_pathb_saturation: bool = True
    pathb_restar_settle_frames: int = 2
    pathb_restar_cooldown_s: float = 120.0


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

    # --- §33 — La baseline deve formarsi SEMPRE (prerequisito di P1) ---
    # Kill-switch dell'intero fix §33. A OFF: comportamento identico (baseline solo
    # da frame NOMINAL, mediana di tutti i campioni, gate rifiuto su valore assoluto,
    # nessun cap su rms_low). A ON (default): aggiunge il FALLBACK di formazione
    # (cosi' la baseline si forma anche nelle notti brutte, dove non esistono
    # baseline_window_frames frame NOMINAL), lo stimatore "miglior frazione", il cap
    # anti-inversione su rms_low e il rifiuto di fallback su instabilita'.
    # Valori PROVVISORI, da calibrare sui log multi-setup.
    baseline_always_form: bool = True
    # Fallback: se i baseline_window_frames campioni NOMINAL non si accumulano entro
    # questo numero di frame SNR-validi, la baseline si forma dalla finestra "tutti i
    # frame". Deve superare i frame tipici per riempire NOMINAL su una notte buona
    # (cosi' le notti buone restano sul percorso NOMINAL, nessuna regressione).
    baseline_fallback_frames: int = 180
    # Stimatore di fallback: mediana del MIGLIOR X% della finestra (la "miglior
    # prestazione raggiungibile nelle condizioni correnti", NON la mediana di tutto
    # che sovrastimerebbe).
    baseline_best_fraction: float = 0.33
    # Anti-inversione bande: rms_low <= ratio × rms_high (con baseline alta e rms_high
    # cappato a 1.00", impedisce rms_low > rms_high che romperebbe la logica).
    rms_low_high_ratio_max: float = 0.85
    # Rifiuto della baseline di FALLBACK (non su valore assoluto basso: una notte
    # brutta reale ha baseline alta ma legittima). Si rifiuta solo se la best fraction
    # e' instabile (CoV alto = transitorio/spazzatura) o oltre un tetto "guida
    # fondamentalmente rotta".
    baseline_fallback_max_cov: float = 0.50
    baseline_fallback_reject_arcsec: float = 4.0


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

    # --- §32 — Recupero MinMove nella banda morta (asimmetria leve §4) ---
    # Complemento speculare del satisfaction gate, sulla stessa ancora (mediana
    # baseline): §30 = "se rms <= mediana non spingere verso la reattivita'";
    # recupero = "se rms > mediana persistente nella banda morta, alza MinMove
    # verso la morbidezza". Corregge l'asimmetria storica (banda morta rms_low..
    # rms_high: MinMove scende su rms<rms_low ma risale solo su rms>rms_high, raro).
    # enabled=true di DEFAULT: e' la correzione di un comportamento base osservato
    # sul campo (v2.2/2.3/2.4), non una feature sperimentale. A OFF il comportamento
    # e' identico bit-per-bit alla v2.3. Floor minmove_min (0.15) NON toccato.
    minmove_recovery_enabled: bool = True
    # Corridoio di recupero: si alza MinMove finche' rms > mediana × questo fattore.
    minmove_recovery_factor: float = 1.0
    # Anti-windup: dopo K recuperi consecutivi senza calo dell'RMS ci si ferma
    # (RMS atmosferico, non correggibile dalle leve) -> niente windup verso minmove_max.
    recovery_no_progress_k: int = 3


@dataclass
class DiagnosticEngineConfig:
    """Seeing Diagnostic Engine (§31, Agente v2.4).

    Diagnosi causale del regime (SEEING / OVERCORRECTION / DRIFT / NOMINAL) da
    jitter + lag-1 + RMS + HFD + trend. `enabled=false` (default) => comportamento
    identico alla v2.3 (motore non istanziato). Quando enabled, `mode` sceglie tra
    `jitter` (motore unica autorita' su Aggr/MinMove, CASO 1/2/3 sospesi) e
    `guardian` (la v2.3 pilota; il motore conferma/attenua/blocca e micro-corregge).
    """
    enabled: bool = False          # DEFAULT spento = comportamento identico v2.3
    mode: str = "guardian"         # "jitter" | "guardian" (usato solo se enabled)
    # --- soglie diagnosi (relative alle reference EMA) ---
    min_frames: int = 30
    jitter_high_factor: float = 1.6
    hfd_high_factor: float = 1.25
    lag1_oscillation_thresh: float = -0.35
    trend_drift_min: float = 0.05
    ema_alpha: float = 0.1
    # --- azione (entrambe le modalita') ---
    act_min_confidence: int = 60
    outcome_window_frames: int = 15
    warmup_frames_after_switch: int = 10
    # --- guardian ---
    guardian_min_confidence: int = 60      # sotto questa confidence il review CONFERMA sempre
    guardian_attenuate_factor: float = 0.5 # ampiezza ridotta quando il review ATTENUA una mossa v2.3
    guardian_action_factor: float = 0.4    # ampiezza delle micro-correzioni proprie di guardian (vs step pieni)
    # --- UI ---
    allow_dashboard_mode_switch: bool = False


@dataclass
class AnalyzerConfig:
    """Analyzer (§36 — fix unità misura)."""
    # §36 — Le distanze di guida grezze da PHD2 (RADistanceRaw/DECDistanceRaw) sono in
    # PIXEL; le soglie/cap/reject sono in arcsec. Con questo flag l'ingest converte la
    # misura px→arcsec moltiplicando per la pixel-scale viva, così misura e soglie
    # combaciano su tutti i setup. Default true (SHIPPED ON): un fix di correttezza non
    # deve girare col bug. A false = comportamento buggato (misura in px), solo per A/B.
    convert_distance_to_arcsec: bool = True


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
    diagnostic_engine: DiagnosticEngineConfig = field(default_factory=DiagnosticEngineConfig)
    analyzer: AnalyzerConfig = field(default_factory=AnalyzerConfig)


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
        cfg.control.per_frame_baseline = bool(ctrl.get(
            "per_frame_baseline", cfg.control.per_frame_baseline))

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
            restar_on_pathb_saturation=bool(ed.get("restar_on_pathb_saturation", True)),
            pathb_restar_settle_frames=int(ed.get("pathb_restar_settle_frames", 2)),
            pathb_restar_cooldown_s=float(ed.get("pathb_restar_cooldown_s", 120.0)),
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
            baseline_always_form=bool(a.get("baseline_always_form", True)),
            baseline_fallback_frames=int(a.get("baseline_fallback_frames", 180)),
            baseline_best_fraction=float(a.get("baseline_best_fraction", 0.33)),
            rms_low_high_ratio_max=float(a.get("rms_low_high_ratio_max", 0.85)),
            baseline_fallback_max_cov=float(a.get("baseline_fallback_max_cov", 0.50)),
            baseline_fallback_reject_arcsec=float(a.get("baseline_fallback_reject_arcsec", 4.0)),
        )

    # §30 — Satisfaction gate (sezione opzionale; assente -> default dataclass)
    if "lever_optimization" in raw:
        lo = raw["lever_optimization"]
        cfg.lever_optimization = LeverOptimizationConfig(
            enabled=bool(lo.get("enabled", True)),
            target_factor=float(lo.get("target_factor", 1.0)),
            minmove_recovery_enabled=bool(lo.get("minmove_recovery_enabled", True)),
            minmove_recovery_factor=float(lo.get("minmove_recovery_factor", 1.0)),
            recovery_no_progress_k=int(lo.get("recovery_no_progress_k", 3)),
        )

    # §31 — Seeing Diagnostic Engine (sezione opzionale; assente -> default).
    # Validazione mode: valore ignoto -> fallback "guardian" con WARNING.
    if "diagnostic_engine" in raw:
        de = raw["diagnostic_engine"]
        mode = str(de.get("mode", "guardian"))
        if mode not in ("jitter", "guardian"):
            logger.warning("[diagnostic_engine] mode '%s' ignoto -> guardian", mode)
            mode = "guardian"
        cfg.diagnostic_engine = DiagnosticEngineConfig(
            enabled=bool(de.get("enabled", False)),
            mode=mode,
            min_frames=int(de.get("min_frames", 30)),
            jitter_high_factor=float(de.get("jitter_high_factor", 1.6)),
            hfd_high_factor=float(de.get("hfd_high_factor", 1.25)),
            lag1_oscillation_thresh=float(de.get("lag1_oscillation_thresh", -0.35)),
            trend_drift_min=float(de.get("trend_drift_min", 0.05)),
            ema_alpha=float(de.get("ema_alpha", 0.1)),
            act_min_confidence=int(de.get("act_min_confidence", 60)),
            outcome_window_frames=int(de.get("outcome_window_frames", 15)),
            warmup_frames_after_switch=int(de.get("warmup_frames_after_switch", 10)),
            guardian_min_confidence=int(de.get("guardian_min_confidence", 60)),
            guardian_attenuate_factor=float(de.get("guardian_attenuate_factor", 0.5)),
            guardian_action_factor=float(de.get("guardian_action_factor", 0.4)),
            allow_dashboard_mode_switch=bool(de.get("allow_dashboard_mode_switch", False)),
        )

    # §36 — Analyzer (sezione opzionale; assente -> default = conversione ATTIVA)
    if "analyzer" in raw:
        an = raw["analyzer"]
        cfg.analyzer = AnalyzerConfig(
            convert_distance_to_arcsec=bool(an.get("convert_distance_to_arcsec", True)),
        )

    return cfg
