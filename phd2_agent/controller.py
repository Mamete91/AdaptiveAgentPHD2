"""
controller.py - Macchina a stati adattiva per il controllo dei parametri PHD2.

Implementa una logica deterministica con guardrail di sicurezza:

  STATO: NORMAL --> DEGRADED --> CRITICAL
           ^                         |
           +-------- RECOVERING -----+

Il controller opera con un cooldown minimo tra modifiche successive
per evitare oscillazioni nella regolazione stessa.

PATCH APPLICATE rispetto alla versione originale:
  - Fix import os mancante (era runtime bug nel ramo AI Star Finder LIVE,
    rimosso in §75: la selezione stella e' competenza di PHD2)
  - MinMove dinamico (ora rispetta i range del config)
  - Baseline Guardian: save/restore baseline.json + orphan recovery
  - Saturation Timer: dopo 300s su stella satura forza re-scan find_star
  - find_best_star ora ritorna (cx, cy, info_dict)
  - Espressione ternaria ambigua riscritta in forma esplicita
  - _AGGR_ALIASES e _MINMOVE_ALIASES convertiti da set a tuple ordinata:
    fix bug non deterministico dove "hysteresis" (param 0-1) poteva essere
    selezionato prima di "aggression" (0-100) sull'algoritmo Hysteresis.
    Verificato sul sorgente PHD2 (guide_algorithm_hysteresis.cpp).
"""
from __future__ import annotations

import csv
import json
import logging
import math
import os
import statistics
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum, auto
from pathlib import Path
from typing import Optional

from .analyzer import AnalysisSnapshot, SeeingCondition, StatisticsAnalyzer
from .client import PHD2Client, PHD2RPCError
from .config import AgentConfig, AxisLimits, ExposureDynamicConfig
from .diagnostic_engine import GuardianVerdict, SeeingDiagnosticEngine

logger = logging.getLogger(__name__)

# §32 — Recupero MinMove: tolleranza di "calo RMS" per l'anti-windup. NON e' un
# parametro di taratura ma una guardia contro il rumore della misura: l'RMS su
# finestra deve scendere di piu' di questo (arcsec) perche' il softening conti come
# progresso. Sotto questa soglia il calo e' indistinguibile dal rumore.
_RECOVERY_PROGRESS_EPS = 0.01


def _utc_now_iso() -> str:
    """Timestamp UTC ISO-8601 con suffisso Z (formato dei record experimental_*.jsonl)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class GuidingState(Enum):
    NORMAL = auto()
    DEGRADED = auto()
    CRITICAL = auto()
    RECOVERING = auto()
    STAR_LOST = auto()
    INACTIVE = auto()


class ExposureState(Enum):
    NOMINAL              = auto()  # esposizione = base
    BOOSTED_FOR_SNR      = auto()  # path A: LOW_SNR (logica esistente)
    BOOSTED_FOR_SEEING   = auto()  # path B: RMS-based (nuova feature)


@dataclass
class AxisState:
    """Stato interno del controller per un singolo asse."""
    axis: str
    current_aggr: float = 70.0       # sempre in scala config (0-100)
    current_minmove: float = 0.15
    last_action_time: float = 0.0
    last_minmove_action_time: float = 0.0
    last_action_desc: str = ""
    param_names: list[str] = field(default_factory=list)
    aggr_param: Optional[str] = None
    minmove_param: Optional[str] = None
    # 0.01 per algoritmi PHD2 che usano scala 0-1 (Hysteresis, ResistSwitch)
    # 1.0  per algoritmi che usano scala 0-100 (Lowpass2, ecc.)
    aggr_native_scale: float = 1.0


@dataclass
class ControlAction:
    """Descrive un'azione intrapresa (o che sarebbe stata intrapresa in DRY_RUN)."""
    timestamp: float
    axis: str
    param: str
    old_value: float
    new_value: float
    reason: str
    dry_run: bool
    # §47 — attribuzione: chi ha generato il softening + MinMove efficace in arcsec.
    softening_source: str = "other"   # SEEING | minmove_recovery_§32 | guardian_micro | oscillation | optimization | other
    minmove_arcsec: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "axis": self.axis,
            "param": self.param,
            "old_value": round(self.old_value, 3),
            "new_value": round(self.new_value, 3),
            "reason": self.reason,
            "dry_run": self.dry_run,
            "softening_source": self.softening_source,
            "minmove_arcsec": self.minmove_arcsec,
        }

    def __str__(self) -> str:
        mode = "[TEST]" if self.dry_run else "[LIVE]"
        return (
            f"{mode} {self.axis.upper()} {self.param}: "
            f"{self.old_value:.3f} -> {self.new_value:.3f}  -  {self.reason}"
        )


# Nomi parametro aggressività ordinati per priorità (tuple, non set).
# Ordine critico: "hysteresis" rimosso — è un parametro distinto nell'algo
# Hysteresis (range 0.0-1.0) e NON va confuso con "aggression" (range 0-100).
# Verificato sul sorgente PHD2 (event_server.cpp + guide_algorithm_*.cpp).
_AGGR_ALIASES = (
    "aggression",              # Hysteresis, Resist Switch (sorgente PHD2)
    "aggressiveness",          # Lowpass2 (sorgente PHD2)
    "Aggressiveness",          # variante legacy
    "Aggression",              # variante legacy
    "PPEC_Aggressiveness",     # Predictive PEC
)

# Parametri che PHD2 espone in scala 0-1 (NON 0-100).
# Verificato su guide_algorithm_hysteresis.cpp e guide_algorithm_resistswitch.cpp.
_AGGR_FRACTIONAL_PARAMS = frozenset({"aggression", "Aggression"})

# §50 — valori standard PHD2 all'INIT (aggr in scala config 0-100, minmove in px/arcsec):
#   RA  (Hysteresis):     Aggressiveness 70  (native 0.70), MinMove 0.20
#   DEC (Resist Switch):  Aggressiveness 100 (native 1.00), MinMove 0.20
_STANDARD_INIT = {"ra": (70.0, 0.20), "dec": (100.0, 0.20)}
# Scala nativa frazionaria (0-1) = famiglia 'aggression' (Hysteresis / Resist Switch).
# È il discriminante di sicurezza: i default 70/100 hanno senso solo su questa scala.
_FRACTIONAL_AGGR_SCALE = 0.01

# §0-bis — persistenza (s) del flag clamping_active dopo un taglio del cap MinMove:
# anti-flicker per il badge ACTIVE (il clamp si valuta solo sui tick di softening).
_MINMOVE_CLAMP_PERSIST_S = 90.0

# §53 — soglia (arcsec) oltre cui l'RMS è considerato "in salita" nella finestra recente
# (pre-gate del recupero simmetrico: non irrigidire mentre l'RMS sta chiaramente salendo).
_RMS_RISING_EPS = 0.02

# §47 — attribuzione del softening: mappa il "caso" v2.3 alla sorgente leggibile.
_CASO_TO_SOURCE = {
    "CASO1": "SEEING",                  # seeing-softening (aggr giù / MinMove su)
    "CASO2": "oscillation",             # ramo oscillazioni (disattivo di default §47)
    "CASO3": "optimization",            # guida ottima (aggr su / MinMove giù) — non softening
    "RECOVERY": "minmove_recovery_§32",  # §32 recupero MinMove nella banda morta
}


def _aggr_native_scale(param_name: str) -> float:
    """Ritorna 0.01 se il parametro PHD2 usa scala 0-1, 1.0 se usa 0-100."""
    return 0.01 if param_name in _AGGR_FRACTIONAL_PARAMS else 1.0


# Nome ufficiale PHD2 per MinMove è "minMove" (camelCase) in tutti gli algoritmi.
_MINMOVE_ALIASES = (
    "minMove",                 # nome ufficiale in tutti gli algoritmi PHD2
    "MinMove",                 # variante legacy
    "min_move",
    "Min Move",
    "Minimum Move",
)

# find_star backoff — evita flood di chiamate su camera crashata (USB disconnect)
_FIND_STAR_SLOW_THRESHOLD = 5    # fallimenti consecutivi → tier slow (ogni 30s)
_FIND_STAR_SUSP_THRESHOLD = 10   # fallimenti consecutivi → sospeso (solo log ogni 60s)
_FIND_STAR_SLOW_INTERVAL  = 30.0 # secondi tra tentativi nel tier slow
_FIND_STAR_SUSP_INTERVAL  = 60.0 # secondi tra log alert nel tier sospeso


class AdaptiveController:
    """Valuta gli snapshot dell'Analyzer e decide se/come modificare PHD2."""

    def __init__(self, client: PHD2Client, config: AgentConfig,
                 analyzer: StatisticsAnalyzer | None = None):
        self.client = client
        self.cfg = config
        self.dry_run = config.control.dry_run

        self.guiding_state = GuidingState.INACTIVE
        self.action_history: list[ControlAction] = []
        # §63 — osservabilità del ciclo motore (dashboard: "raccolta dati" /
        # "valuta senza intervenire" / "ultimo intervento"): tick di valutazione
        # VERI (evaluated=True) contati e datati. Senza questo, un motore sano ma
        # quieto è indistinguibile da un motore fermo (lezione della validazione).
        self.eval_count = 0
        self.last_eval_ts: float | None = None

        self._ra = AxisState("ra")
        self._dec = AxisState("dec")

        self._initialized = False
        # §56 — flag di PROCESSO: True dopo il primo initialize() riuscito, mai resettato
        # da mark_uninitialized() (che governa solo la sessione-guida). Distingue il primo
        # avvio del processo (orphan-check + save_baseline + INIT §50) dai ri-init di
        # ripartenza guida (ri-aggancio leggero, leve preservate).
        self._process_initialized = False

        # Riferimento all'analyzer per reset post-cambio esposizione
        self.analyzer: Optional[StatisticsAnalyzer] = analyzer

        # --- Seeing Diagnostic Engine (§31, Agente v2.4) ---
        # Istanziato in initialize() solo se cfg.diagnostic_engine.enabled (default
        # spento => None => comportamento identico v2.3). session_logger e' duck-typed:
        # collegato da main.py per scrivere experimental_*.jsonl (no import circolare).
        self.diagnostic_engine: Optional[SeeingDiagnosticEngine] = None
        self.session_logger = None
        # §45/§46 — telemetria NINA Layer-1 (store) + indici Layer-2 (transparency tracker).
        # Collegati da main.py (duck-typed). None => motore PHD2-only (graceful, pre-N8).
        self.nina_store = None
        self.transparency_tracker = None
        # §47 — breakdown sorgenti di softening della sessione (per /status + dashboard).
        self._softening_source_counts: dict[str, int] = {}
        self._diag_last_state = None
        self._current_diag = None                 # ultimo DiagnosisResult di classify()
        self._warmup_frames_left = 0
        self._outcome_pending: Optional[dict] = None
        self._last_outcome: Optional[dict] = None
        self._diag_pre_buffer: list[dict] = []    # media pre-azione (esclusi i warmup)
        self._diag_last_action = {"ra": 0.0, "dec": 0.0}   # cooldown per-asse azioni motore

        # Emergency state
        self.base_exposure_ms: Optional[int] = None
        self.current_exposure_ms: Optional[int] = None
        self.exposure_state: ExposureState = ExposureState.NOMINAL
        self.exposure_steps_above_base: int = 0
        self.last_exposure_action_time: float = 0.0
        self._nominal_since: Optional[float] = None
        self._valid_exposures: list[int] = []
        self._auto_exposure_warned: bool = False
        self.star_lost_since: Optional[float] = None
        self._find_star_failures: int = 0
        self._find_star_last_attempt: float = 0.0

        # Saturation timer state
        self.saturated_lock_since: Optional[float] = None
        self.last_saturation_info: Optional[dict] = None

        # §35 — riselezione stella post-aumento esposizione Path B (vedi
        # _evaluate_pathb_restar). `_pathb_restar_due` = istante (monotonic) dopo cui
        # fare il check (settle del nuovo tempo); `_pathb_restar_last_time` = ultima
        # riselezione, per l'anti-flapping.
        self._pathb_restar_pending: bool = False
        self._pathb_restar_due: float = 0.0
        self._pathb_restar_last_time: float = 0.0

        # Baseline Guardian
        self.baseline_path = Path("baseline.json")
        # ID setup per identificare baseline cross-setup. Se in config c'e' un
        # campo [setup] profile_name lo usiamo, altrimenti "default".
        self._baseline_setup_id = self._read_setup_id_from_config()

        # CSV log periodi satura per post-mortem PixInsight
        self._saturation_csv_dir = Path(config.logging.csv_dir)

        # Auto-calibrazione soglie RMS (baseline misurata sul campo).
        # Stato inizializzato SOLO qui: initialize()/reinitialize() non lo azzerano,
        # cosi' una riconnessione a pixel scale invariata non ricomincia la misura.
        self._rms_baseline_samples: list[float] = []
        # §33 — baseline sempre formata: finestra rolling di TUTTI i frame SNR-validi
        # (per il fallback quando NOMINAL non si riempie) + contatore frame visti.
        self._rms_baseline_all_samples: deque[float] = deque(
            maxlen=max(1, config.auto_calibration.baseline_fallback_frames))
        self._baseline_frames_seen: int = 0
        # §44 — finestra mobile per il tracker continuo/bidirezionale (post-formazione).
        # Ampiezza = baseline_window_frames; alimentata dai frame SNR-validi.
        self._rms_rolling: deque[float] = deque(
            maxlen=max(1, config.auto_calibration.baseline_window_frames))
        # §51 — EMA temporale della baseline §44 (riferimento del cap MinMove adattivo).
        # Segue la baseline su ~decine di minuti (filter_tau_minutes) senza inseguire le
        # fluttuazioni. Fallback: None -> nessun cap adattivo (MinMove limitato solo da minmove_max).
        self._minmove_baseline_ema: Optional[float] = None
        self._minmove_baseline_ema_t: Optional[float] = None
        self._minmove_cap_info: Optional[dict] = None   # ultimo cap (per /status)
        # §51/dashboard — clamping_active: il cap ha TAGLIATO una richiesta MinMove-up
        # (requested > cap). Persistenza anti-flicker: resta true fino a questo istante.
        self._minmove_clamp_active_until: float = 0.0
        self._rms_baseline_value: Optional[float] = None
        self._rms_baseline_done: bool = False
        # §23: gate di rifiuto + clamp proporzionale
        self._rms_baseline_rejected: bool = False
        self._rms_high_cap_active: bool = False
        self._rms_high_cap_value: Optional[float] = None
        # §25: refresh ciclico baseline (tightest-wins)
        self._baseline_finalize_time: Optional[float] = None  # time.monotonic() dell'ultima applicazione
        self._baseline_refresh_in_progress: bool = False
        self._last_refresh_action: Optional[str] = None       # "applicato" / "rifiutato" / None
        self._last_refresh_baseline: Optional[float] = None   # baseline misurata nell'ultimo refresh

        # §32 — Recupero MinMove nella banda morta (asimmetria leve §4). Stato globale
        # (su rms_total): contatore consecutivo del trigger + anti-windup puro-RMS.
        # Valutato una volta per tick (vedi _update_recovery_state/_finalize_recovery_windup).
        self._recovery_consec: int = 0                       # tick consecutivi rms_total > soglia
        self._recovery_anchor_rms: Optional[float] = None    # rms_total all'inizio del run di recupero
        self._recovery_actions_since_anchor: int = 0         # recuperi applicati dall'ultimo anchor
        self._recovery_blocked: bool = False                 # anti-windup: softening sospeso
        self._recovery_applied_this_tick: bool = False       # flag per il bookkeeping per-tick
        # §53 — recupero simmetrico: verso del run corrente ("stiffen"/"soften"/None) e
        # blocco specifico dell'irrigidimento (l'esito ha provato che serviva ammorbidire).
        self._recovery_direction: Optional[str] = None
        self._recovery_stiffen_blocked: bool = False
        self._rms_recent: deque[float] = deque(
            maxlen=max(2, config.lever_optimization.recovery_outcome_window_frames))

    def _read_setup_id_from_config(self) -> str:
        """Estrae profile_name dal config se presente, altrimenti default."""
        try:
            setup_cfg = getattr(self.cfg, "setup", None)
            if setup_cfg is not None:
                name = getattr(setup_cfg, "profile_name", None)
                if name:
                    return str(name)
        except Exception:
            pass
        return "default"

    # ------------------------------------------------------------------ #
    #  Inizializzazione                                                   #
    # ------------------------------------------------------------------ #

    def initialize(self) -> bool:
        """
        Legge i parametri attuali da PHD2 e scopre i nomi parametro
        dell'algoritmo. Da chiamare dopo connessione e quando PHD2 e' Guiding.

        §56 — due modalita':
        - PRIMO init del processo (o kill-switch full_reinit_on_restart): init PIENO —
          orphan-check (recovery da crash di un processo precedente), save_baseline
          (cattura dei valori utente) e INIT §50 ai valori standard.
        - Ri-init di sessione (ripartenza guida: autofocus/filtro/ricentraggio):
          ri-aggancio LEGGERO — ri-legge params/esposizioni/pixel-scale (l'agente resta
          veritiero rispetto a PHD2) ma NON tocca le leve ne' la baseline: la convergenza
          costruita nella corsa precedente e' preservata.
        """
        first_init = not self._process_initialized
        full = first_init or self.cfg.control.full_reinit_on_restart
        try:
            # Step 1: orphan baseline check (SOLO primo init del processo: una
            # baseline.json preesistente e' di un processo precedente crashato.
            # Sui ri-init il file esiste perche' l'abbiamo scritto NOI -> non e' orfano).
            if full:
                self._check_orphan_baseline()

            self._valid_exposures = self.client.get_exposure_durations()
            self.base_exposure_ms = self.client.get_exposure()
            self.current_exposure_ms = self.base_exposure_ms

            # Controllo euristico Auto Exposure: se il valore letto non è nella
            # lista valida, PHD2 potrebbe avere Auto Exposure attivo.
            if (self.cfg.exposure_dynamic.enabled
                    and self._valid_exposures
                    and self.base_exposure_ms not in self._valid_exposures
                    and not self._auto_exposure_warned):
                logger.warning(
                    "ATTENZIONE: esposizione corrente (%s ms) non in lista valida "
                    "%s... — PHD2 Auto Exposure probabilmente attiva. "
                    "L'esposizione dinamica RMS-based (path B) è disabilitata. "
                    "Disabilitare Auto Exposure in PHD2 "
                    "(Brain → Camera → Use Auto Exposure).",
                    self.base_exposure_ms, self._valid_exposures[:5],
                )
                self._auto_exposure_warned = True

            self.exposure_state = ExposureState.NOMINAL
            self.exposure_steps_above_base = 0
            self.last_exposure_action_time = 0.0
            self._nominal_since = None
            self.star_lost_since = None
            self._find_star_failures = 0
            self._find_star_last_attempt = 0.0
            self.saturated_lock_since = None
            self.last_saturation_info = None

            params = self.client.probe_algo_params()
            self._setup_axis(self._ra, params.get("ra", {}), self.cfg.ra)
            self._setup_axis(self._dec, params.get("dec", {}), self.cfg.dec)
            self._initialized = True

            # Auto-scala: legge la pixel scale reale da PHD2 (fallback TOML).
            # initialize() e' invocato a init, su StartGuiding, AppState->Guiding e
            # riconnessione: il caso null a freddo si auto-corregge quando la camera
            # e' connessa. La baseline RMS NON viene toccata qui (solo su cambio scala).
            self._apply_pixel_scale_from_phd2("init")

            # §31 — Seeing Diagnostic Engine: istanziato solo se abilitato in config.
            # Spento (default) => self.diagnostic_engine resta None => v2.3 pura.
            self._init_diagnostic_engine()

            # Step 2 + §50: SOLO al primo init del processo (o kill-switch §56).
            # Sui ri-init di sessione le leve correnti (convergenza della corsa
            # precedente) restano intatte e la baseline utente non viene sovrascritta.
            if full:
                # salva baseline DOPO aver letto i parametri puliti
                self.save_baseline()

                # §50 — INIT ai valori standard PHD2 (stato iniziale NOTO): DOPO la
                # calibrazione (params letti) e save_baseline (valori utente salvati per il
                # restore), PRIMA della formazione baseline. Al primo init di un nuovo
                # processo il Baseline Guardian ha già ripristinato i valori utente
                # (orphan restore) prima di questo punto → non si perde nulla.
                self._init_to_phd2_standard()
            else:
                logger.info(
                    "Ri-aggancio guida (ripartenza sessione) — leve preservate: "
                    "RA aggr=%.1f minmove=%.3f | DEC aggr=%.1f minmove=%.3f",
                    self._ra.current_aggr, self._ra.current_minmove,
                    self._dec.current_aggr, self._dec.current_minmove,
                )

            logger.info(
                "Setup: profile=%s, guide_pixel_scale=%.2f arcsec/px "
                "(reducer_active=%s, native=%.2f, reduced=%.2f)",
                self.cfg.setup.profile_name,
                self.cfg.setup.guide_pixel_scale_arcsec,
                self.cfg.setup.reducer_active,
                self.cfg.setup.guide_pixel_scale_arcsec_native,
                self.cfg.setup.guide_pixel_scale_arcsec_reduced,
            )
            logger.info(
                "Controller inizializzato. Base Exposure: %dms | "
                "RA: aggr=%.1f minmove=%.3f | Dec: aggr=%.1f minmove=%.3f",
                self.base_exposure_ms or 0,
                self._ra.current_aggr, self._ra.current_minmove,
                self._dec.current_aggr, self._dec.current_minmove,
            )
            self._process_initialized = True   # §56 — primo init del processo completato
            return True
        except Exception as e:
            logger.error("Impossibile inizializzare il controller: %s", e)
            return False

    def _setup_axis(self, axis_state: AxisState,
                    params: dict[str, float],
                    limits: AxisLimits) -> None:
        axis_state.param_names = list(params.keys())

        for alias in _AGGR_ALIASES:
            if alias in params:
                axis_state.aggr_param = alias
                scale = _aggr_native_scale(alias)
                axis_state.aggr_native_scale = scale
                # Converti a scala config (0-100) per aritmetica uniforme con i limiti
                axis_state.current_aggr = params[alias] / scale
                break

        for alias in _MINMOVE_ALIASES:
            if alias in params:
                axis_state.minmove_param = alias
                axis_state.current_minmove = params[alias]
                break

        logger.info(
            "Asse %s: aggr_param=%s (%.1f -> config %.1f), minmove_param=%s (%.3f) | tutti: %s",
            axis_state.axis,
            axis_state.aggr_param,
            axis_state.current_aggr * axis_state.aggr_native_scale,  # valore PHD2 nativo
            axis_state.current_aggr,                                  # valore config (0-100)
            axis_state.minmove_param,
            axis_state.current_minmove,
            axis_state.param_names,
        )

    def _init_to_phd2_standard(self) -> None:
        """§50 — porta le leve ai valori standard PHD2 all'inizio guida (stato iniziale
        NOTO). Algoritmo-aware: applica SOLO se l'asse usa la scala frazionaria 'aggression'
        (Hysteresis/Resist Switch, native 0.01); altrimenti NON forza valori a scala sbagliata
        → WARNING + skip di quell'asse (fail-safe). Rispetta dry_run (via _apply)."""
        if not self.cfg.control.init_to_phd2_standard:
            return
        for axis_state, limits in ((self._ra, self.cfg.ra), (self._dec, self.cfg.dec)):
            std_aggr, std_mm = _STANDARD_INIT[axis_state.axis]
            if (not axis_state.aggr_param
                    or axis_state.aggr_native_scale != _FRACTIONAL_AGGR_SCALE):
                logger.warning(
                    "[init-std] Asse %s: algoritmo non standard (aggr_param=%s, native_scale=%.2f, "
                    "params=%s) → INIT ai valori standard SALTATO (nessun valore a scala sbagliata).",
                    axis_state.axis.upper(), axis_state.aggr_param,
                    axis_state.aggr_native_scale, axis_state.param_names,
                )
                continue
            if axis_state.aggr_param and std_aggr != axis_state.current_aggr:
                self._apply(axis_state, limits, axis_state.aggr_param,
                            axis_state.current_aggr, std_aggr,
                            f"[init-std] {axis_state.axis.upper()} Aggressiveness → {std_aggr:.0f} "
                            f"(standard PHD2, native {std_aggr * axis_state.aggr_native_scale:.2f})",
                            softening_source="init_standard")
                axis_state.current_aggr = std_aggr
            if axis_state.minmove_param and std_mm != axis_state.current_minmove:
                self._apply(axis_state, limits, axis_state.minmove_param,
                            axis_state.current_minmove, std_mm,
                            f"[init-std] {axis_state.axis.upper()} MinMove → {std_mm:.2f} (standard PHD2)",
                            is_minmove=True, softening_source="init_standard")
                axis_state.current_minmove = std_mm
            logger.info("[init-std] Asse %s ai valori standard: aggr=%.0f (native %.2f) minmove=%.2f",
                        axis_state.axis.upper(), std_aggr,
                        std_aggr * axis_state.aggr_native_scale, std_mm)

    def reinitialize(self) -> None:
        """Re-bootstrap COMPLETO esplicito (es. dopo cambio profilo utente): a differenza
        dei ri-init di sessione (§56, leggeri), qui si ripete l'init pieno — restore dei
        valori utente dalla baseline, ri-cattura della baseline, INIT §50."""
        self._initialized = False
        self._process_initialized = False   # §56 — forza il percorso primo-init
        self.initialize()

    # ------------------------------------------------------------------ #
    #  Seeing Diagnostic Engine (§31) — fabbrica e modalita'              #
    # ------------------------------------------------------------------ #

    def _make_diagnostic_engine(self) -> SeeingDiagnosticEngine:
        """Crea il motore con i provider verso lo stato runtime del controller:
        thresholds efficaci (post auto-cal §22-25) e mediana baseline (§30)."""
        return SeeingDiagnosticEngine(
            self.cfg.diagnostic_engine,
            thresholds_provider=lambda: (self.cfg.thresholds.rms_high,
                                         self.cfg.thresholds.rms_low),
            baseline_provider=lambda: (self._rms_baseline_value
                                       if not self._rms_baseline_rejected else None),
            transparency_provider=self._nina_confidence_input,   # §46 N8
        )

    def _nina_confidence_input(self) -> Optional[dict]:
        """§46 — input trasparenza per il motore. Graceful: None (nessuna modulazione)
        se la feature è off, store/tracker non collegati, o telemetria NON fresca (la
        freschezza è single-source nello store §43, adattiva alla posa)."""
        if not self.cfg.diagnostic_engine.confidence_use_nina:
            return None
        store = self.nina_store
        tracker = self.transparency_tracker
        if store is None or tracker is None:
            return None
        try:
            if not store.is_fresh:
                return None
            return tracker.confidence_input()
        except Exception:
            return None

    def _init_diagnostic_engine(self) -> None:
        """Istanzia (o dismette) il motore in base a cfg.diagnostic_engine.enabled.
        Se gia' istanziato e ancora abilitato lo conserva (mantiene le reference EMA)."""
        de = self.cfg.diagnostic_engine
        if de.enabled:
            if self.diagnostic_engine is None:
                self.diagnostic_engine = self._make_diagnostic_engine()
            logger.info("[diagnostic_engine] motore ATTIVO — mode=%s", de.mode)
        else:
            self.diagnostic_engine = None

    def _engine_owns_levers(self) -> bool:
        """jitter: il motore e' unica autorita' su Aggr/MinMove (CASO 1/2/3 sospesi)."""
        de = self.cfg.diagnostic_engine
        return self.diagnostic_engine is not None and de.enabled and de.mode == "jitter"

    def _guardian_active(self) -> bool:
        """guardian: la v2.3 pilota; il motore rivede le sue mosse e micro-corregge."""
        de = self.cfg.diagnostic_engine
        return self.diagnostic_engine is not None and de.enabled and de.mode == "guardian"

    # ------------------------------------------------------------------ #
    #  Auto-calibrazione: pixel scale da PHD2 + soglie RMS adattive       #
    # ------------------------------------------------------------------ #

    def _apply_pixel_scale_from_phd2(self, context: str = "init") -> None:
        """Legge la pixel scale di guida da PHD2 e la applica come override runtime.

        Override impostato solo se PHD2 riporta un valore valido (>0); su `null`
        o errore RPC si azzera l'override -> fallback ai valori TOML. La baseline
        RMS viene invalidata SOLO se la scala cambia davvero.
        """
        ac = self.cfg.auto_calibration
        if not ac.enabled or not ac.use_phd2_pixel_scale:
            self.cfg.setup.pixel_scale_override = None
            logger.info(
                "[autocal/%s] auto-scala OFF -> pixel scale TOML = %.3f\"/px",
                context, self.cfg.setup.guide_pixel_scale_arcsec,
            )
            return

        scale = self.client.get_pixel_scale()
        prev = self.cfg.setup.pixel_scale_override
        if scale is not None and scale > 0.0:
            self.cfg.setup.pixel_scale_override = scale
            logger.info(
                "[autocal/%s] pixel scale da PHD2 = %.3f\"/px (fonte: RPC)",
                context, scale,
            )
            if prev is not None and abs(prev - scale) > 1e-3:
                self._invalidate_rms_baseline("cambio pixel scale rilevato")
        else:
            self.cfg.setup.pixel_scale_override = None
            logger.warning(
                "[autocal/%s] PHD2 non conosce la pixel scale (null) -> "
                "fallback TOML = %.3f\"/px",
                context, self.cfg.setup.guide_pixel_scale_arcsec,
            )

    def _invalidate_rms_baseline(self, reason: str) -> None:
        """Azzera la baseline RMS: verra' ricalcolata al prossimo periodo stabile.
        Le soglie attive restano agli ultimi valori validi (o TOML) nel frattempo."""
        self._rms_baseline_samples.clear()
        self._rms_baseline_all_samples.clear()   # §33
        self._rms_rolling.clear()                # §44
        self._baseline_frames_seen = 0           # §33
        self._rms_baseline_value = None
        self._rms_baseline_done = False
        self._rms_baseline_rejected = False
        self._rms_high_cap_active = False
        self._rms_high_cap_value = None
        # §25: azzera anche lo stato del refresh ciclico
        self._baseline_finalize_time = None
        self._baseline_refresh_in_progress = False
        self._last_refresh_action = None
        self._last_refresh_baseline = None
        logger.info(
            "[autocal] baseline RMS invalidata (%s): ricalibrazione al prossimo "
            "periodo stabile", reason,
        )

    def _update_rms_baseline(self, snap: AnalysisSnapshot) -> None:
        """Campiona rms_total dai frame SNR-validi (no implosion). Percorso PRIMARIO:
        i frame NOMINAL formano la baseline come sempre (notti buone invariate). §33 —
        FALLBACK: se i baseline_window_frames campioni NOMINAL non si accumulano entro
        baseline_fallback_frames frame SNR-validi, la baseline si forma comunque dalla
        finestra 'tutti i frame' (stimatore best-fraction). Cosi' la baseline si forma
        SEMPRE, anche nelle notti brutte dove non esistono 60 frame NOMINAL — requisito
        di P1: senza riferimento, satisfaction-gate (§30) e RECOVERY (§32) sono inerti."""
        ac = self.cfg.auto_calibration
        if not ac.enabled:
            return
        # §40 — scartiamo solo i frame davvero inutilizzabili (implosion). La soglia SNR
        # NON deve bloccare TUTTO: prima azzerava sia NOMINAL sia il fallback §33 ->
        # niente baseline sulle notti a SNR basso (es. 71F a SNR 9 con gate=10).
        if snap.implosion_detected:
            return
        snr = snap.snr_avg if snap.snr_avg is not None else 0.0
        # Floor anti-garbage (= reject rilevamento PHD2) usato sia dal FALLBACK §33 sia
        # dalla finestra mobile §44. Con baseline_fallback_ignores_snr_gate (shipped) la
        # baseline si forma anche a SNR basso dai frame meno peggio.
        fb_floor = (ac.baseline_fallback_min_snr
                    if ac.baseline_fallback_ignores_snr_gate
                    else ac.baseline_min_snr)
        # §44 — finestra mobile del tracker continuo/bidirezionale: tutti i frame SNR-validi.
        if ac.baseline_track_bidirectional and snr >= fb_floor:
            self._rms_rolling.append(snap.rms_total)

        if self._rms_baseline_done:
            # §44 — dopo la formazione iniziale, aggiornamento CONTINUO e BIDIREZIONALE su
            # finestra mobile (la baseline segue la scala reale della notte). Il refresh
            # ciclico §25 è disattivato in questa modalità (vedi _maybe_start_refresh).
            if ac.baseline_track_bidirectional:
                self._continuous_track_baseline()
            return

        # ----- FORMAZIONE INIZIALE (§33/§40, invariata) -----
        # Percorso PRIMARIO (notti buone): frame NOMINAL con SNR >= baseline_min_snr.
        if snap.condition == SeeingCondition.NOMINAL and snr >= ac.baseline_min_snr:
            self._rms_baseline_samples.append(snap.rms_total)
        # §33/§40 — finestra rolling per il FALLBACK (tutti i frame sopra fb_floor).
        if ac.baseline_always_form and snr >= fb_floor:
            self._rms_baseline_all_samples.append(snap.rms_total)
            self._baseline_frames_seen += 1
        # Finalize: prima il percorso NOMINAL (notti buone), poi il fallback §33.
        if len(self._rms_baseline_samples) >= ac.baseline_window_frames:
            self._finalize_rms_baseline()
        elif (ac.baseline_always_form
              and self._baseline_frames_seen >= ac.baseline_fallback_frames
              and len(self._rms_baseline_all_samples) >= ac.baseline_window_frames):
            self._finalize_rms_baseline(fallback=True)

    def _finalize_rms_baseline(self, fallback: bool = False) -> None:
        """Deriva rms_high/rms_low dalla baseline e aggiorna la config efficace in
        memoria E l'analyzer (TOML mai riscritto). §23: cap proporzionale + gate
        rifiuto + floor rms_low. §25: tightest-wins durante il refresh ciclico.
        §33 (`fallback=True`): baseline dalla finestra 'tutti i frame' con stimatore
        best-fraction; rifiuto su instabilita'/tetto (NON su valore assoluto basso, una
        notte brutta reale ha baseline alta ma legittima); cap anti-inversione su
        rms_low. Il CAP su rms_high resta invariato in ogni caso."""
        ac = self.cfg.auto_calibration
        scale = self.cfg.setup.guide_pixel_scale_arcsec   # scala efficace (PHD2 o TOML fallback)
        prev_baseline = self._rms_baseline_value   # None al primo finalize, valore corrente in refresh
        in_refresh = self._baseline_refresh_in_progress

        # ----- STIMATORE BASELINE -----
        if fallback:
            # §33 — mediana del MIGLIOR X% (best fraction) della finestra 'tutti i
            # frame': "miglior prestazione raggiungibile nelle condizioni correnti".
            srt = sorted(self._rms_baseline_all_samples)
            k = max(1, int(len(srt) * ac.baseline_best_fraction))
            best = srt[:k]
            new_baseline = statistics.median(best)
            n_used = len(best)
            best_mean = statistics.mean(best)
            best_cov = (statistics.pstdev(best) / best_mean) if best_mean > 1e-9 else 0.0
        else:
            new_baseline = statistics.median(self._rms_baseline_samples)
            n_used = len(self._rms_baseline_samples)

        # ----- GATE DI RIFIUTO BASELINE -----
        if fallback:
            # §33 — rifiuto solo su INSTABILITA' (CoV alto = transitorio/spazzatura) o
            # tetto "guida fondamentalmente rotta"; mai su valore alto-ma-stabile.
            rejected = (best_cov > ac.baseline_fallback_max_cov
                        or new_baseline > ac.baseline_fallback_reject_arcsec)
            reject_desc = (
                f"instabile (CoV={best_cov:.2f} > {ac.baseline_fallback_max_cov})"
                if best_cov > ac.baseline_fallback_max_cov
                else f"oltre tetto guida-rotta ({ac.baseline_fallback_reject_arcsec:.2f}\")"
            )
        else:
            reject_threshold = max(ac.baseline_reject_min_arcsec,
                                   ac.baseline_reject_factor * scale)
            rejected = new_baseline > reject_threshold
            reject_desc = (f"soglia rifiuto = {reject_threshold:.3f}\" = "
                           f"max({ac.baseline_reject_min_arcsec:.2f}\", "
                           f"{ac.baseline_reject_factor:.1f} x {scale:.3f}\"/px)")

        if rejected:
            self._rms_baseline_rejected = True
            self._rms_high_cap_active = False
            self._rms_high_cap_value = None
            self._rms_baseline_done = True
            fb_tag = "fallback, " if fallback else ""
            if in_refresh:
                # Durante refresh: soglie correnti mantenute, baseline corrente preservata,
                # esito del refresh = rifiutato; il timer riparte da ora.
                self._last_refresh_action = "rifiutato"
                self._last_refresh_baseline = new_baseline
                self._baseline_refresh_in_progress = False
                self._baseline_finalize_time = time.monotonic()
                logger.warning(
                    "[autocal] refresh: baseline %.3f\" RIFIUTATA (%s%s); "
                    "soglie correnti mantenute (corrente = %.3f\")",
                    new_baseline, fb_tag, reject_desc,
                    prev_baseline if prev_baseline is not None else 0.0,
                )
            else:
                # Primo finalize rifiutato: aggiorniamo _rms_baseline_value per il display.
                self._rms_baseline_value = new_baseline
                logger.warning(
                    "[autocal] baseline RMS = %.3f\" RIFIUTATA (%s%s): "
                    "mantengo rms_high=%.3f\" rms_low=%.3f\"",
                    new_baseline, fb_tag, reject_desc,
                    self.cfg.thresholds.rms_high, self.cfg.thresholds.rms_low,
                )
            return

        # ----- REGOLA TIGHTEST-WINS (§25, solo durante refresh) -----
        if (in_refresh and ac.refresh_only_if_tighter
                and prev_baseline is not None and new_baseline >= prev_baseline):
            # Nuova baseline non piu' stretta -> rifiuto; soglie e baseline correnti restano.
            self._last_refresh_action = "rifiutato"
            self._last_refresh_baseline = new_baseline
            self._baseline_refresh_in_progress = False
            self._rms_baseline_samples.clear()
            self._rms_baseline_done = True
            self._baseline_finalize_time = time.monotonic()   # timer riparte da ora
            logger.info(
                "[autocal] refresh: nuova baseline %.3f\" >= corrente %.3f\" "
                "(tightest-wins) -> soglie correnti mantenute",
                new_baseline, prev_baseline,
            )
            return

        # ----- APPLICAZIONE (primo finalize OR refresh accettato) -----
        self._rms_baseline_value = new_baseline

        # §24 — derivazione soglie (CAP proporzionale MANTENUTO, floor rms_low,
        # anti-inversione §33) nel punto UNICO _apply_derived_thresholds, condiviso col
        # tracker continuo §44 (così cap/anti-inversione hanno una sola sorgente di verità).
        d = self._apply_derived_thresholds(new_baseline)
        new_high, new_low = d["new_high"], d["new_low"]
        cap_proporzionale, cap_efficace = d["cap_proporzionale"], d["cap_efficace"]
        inversion_capped, derived_low = d["inversion_capped"], d["derived_low"]
        self._rms_baseline_done = True
        self._rms_baseline_rejected = False
        self._baseline_finalize_time = time.monotonic()   # §25: timer del prossimo refresh

        fb_label = (" [FALLBACK best-%d%%]" % round(ac.baseline_best_fraction * 100)) if fallback else ""
        low_tag = (" [ANTI-INV]" if inversion_capped
                   else (" [FLOOR APPLICATO]" if derived_low < ac.rms_low_min_arcsec else ""))
        if in_refresh:
            self._last_refresh_action = "applicato"
            self._last_refresh_baseline = new_baseline
            self._baseline_refresh_in_progress = False
            logger.info(
                "[autocal] refresh: nuova baseline %.3f\"%s < corrente %.3f\" -> APPLICATA. "
                "rms_high=%.3f\"%s rms_low=%.3f\"%s",
                new_baseline, fb_label, prev_baseline if prev_baseline is not None else 0.0,
                new_high, " [CAP]" if self._rms_high_cap_active else "", new_low, low_tag,
            )
        else:
            logger.info(
                "[autocal] baseline RMS = %.3f\"%s su %d frame | "
                "cap = %.1f x %.3f\"/px = %.3f\" (efficace dopo bounds = %.3f\") | "
                "rms_high = %.3f\"%s | rms_low = %.3f\"%s",
                new_baseline, fb_label, n_used,
                ac.rms_high_max_factor, scale, cap_proporzionale, cap_efficace,
                new_high, " [CAP APPLICATO]" if self._rms_high_cap_active else "",
                new_low, low_tag,
            )

    def _apply_derived_thresholds(self, new_baseline: float) -> dict:
        """§24 — deriva rms_high/rms_low da `new_baseline` e li scrive in cfg.thresholds
        + analyzer. Punto UNICO di derivazione soglie, condiviso dal finalize (§33/§25) e
        dal tracker continuo (§44): così il CAP §24, il floor rms_low e l'anti-inversione
        §33 hanno una sola sorgente di verità (nessuna divergenza). NON modifica
        `_rms_baseline_value` né i timer. Ritorna i valori utili al logging."""
        ac = self.cfg.auto_calibration
        scale = self.cfg.setup.guide_pixel_scale_arcsec
        # CAP proporzionale §23/§24 — MANTENUTO: tetto di sicurezza contro soglie troppo larghe.
        cap_proporzionale = ac.rms_high_max_factor * scale
        cap_efficace = max(ac.rms_high_min_arcsec,
                           min(ac.rms_high_max_arcsec, cap_proporzionale))
        derived_high = ac.rms_high_factor * new_baseline
        new_high = min(cap_efficace, derived_high)
        self._rms_high_cap_active = (derived_high > cap_efficace)
        self._rms_high_cap_value = cap_efficace
        # Floor rms_low (§23) + §33 anti-inversione (rms_low sempre sotto rms_high).
        derived_low = ac.rms_low_factor * new_baseline
        new_low = max(ac.rms_low_min_arcsec, derived_low)
        inversion_capped = False
        if ac.baseline_always_form:
            inv_cap = new_high * ac.rms_low_high_ratio_max
            if new_low > inv_cap:
                new_low = inv_cap
                inversion_capped = True
        self.cfg.thresholds.rms_high = new_high
        self.cfg.thresholds.rms_low = new_low
        if self.analyzer is not None:
            self.analyzer.rms_high = new_high
            self.analyzer.rms_low = new_low
        return {
            "new_high": new_high, "new_low": new_low,
            "cap_proporzionale": cap_proporzionale, "cap_efficace": cap_efficace,
            "inversion_capped": inversion_capped, "derived_low": derived_low,
        }

    def _continuous_track_baseline(self) -> None:
        """§44 — tracker CONTINUO e BIDIREZIONALE della baseline su finestra mobile.
        Eseguito a ogni frame dopo la formazione iniziale (solo se
        `baseline_track_bidirectional`). Ricalcola la baseline col best-fraction della
        finestra mobile (aggiornamento liscio: mediana su finestra, non per-frame) e
        ri-deriva le soglie via `_apply_derived_thresholds` (CAP §24 mantenuto,
        anti-inversione §33). BIDIREZIONALE: la baseline può SALIRE col peggiorare del
        seeing o stringersi col migliorare. Backstop: gate di rifiuto §23 (baseline
        assurda da setup rotto -> nessun aggiornamento, soglie correnti mantenute)."""
        ac = self.cfg.auto_calibration
        if len(self._rms_rolling) < ac.baseline_window_frames:
            return   # finestra non ancora piena -> mantieni le soglie correnti
        srt = sorted(self._rms_rolling)
        k = max(1, int(len(srt) * ac.baseline_best_fraction))
        cand = statistics.median(srt[:k])
        # Gate di rifiuto §23 (identico al finalize non-fallback): baseline oltre il
        # tetto "setup rotto" -> non aggiornare (backstop intatto anche in cap-continuo).
        scale = self.cfg.setup.guide_pixel_scale_arcsec
        reject_threshold = max(ac.baseline_reject_min_arcsec, ac.baseline_reject_factor * scale)
        if cand > reject_threshold:
            return
        prev = self._rms_baseline_value
        # Aggiornamento liscio: ignora micro-variazioni (no churn delle soglie / no spam log).
        if prev is not None and abs(cand - prev) < 0.01:
            return
        self._rms_baseline_value = cand
        self._rms_baseline_rejected = False
        self._apply_derived_thresholds(cand)
        arrow = (" ↑" if prev is not None and cand > prev
                 else (" ↓" if prev is not None and cand < prev else ""))
        logger.info(
            "[autocal] baseline continua §44 = %.3f\"%s -> rms_high=%.3f\"%s rms_low=%.3f\"",
            cand, arrow, self.cfg.thresholds.rms_high,
            " [CAP]" if self._rms_high_cap_active else "", self.cfg.thresholds.rms_low,
        )

    def _update_minmove_baseline_filter(self) -> None:
        """§51 — aggiorna l'EMA temporale della baseline §44 (una volta per tick). Costante
        di tempo `filter_tau_minutes`: l'EMA segue lentamente la baseline reale della notte.
        No-op se il cap è disabilitato o la baseline non è pronta/rifiutata (fallback)."""
        mc = self.cfg.minmove_cap
        if not mc.enabled:
            return
        b = (self._rms_baseline_value
             if (self._rms_baseline_value is not None and not self._rms_baseline_rejected)
             else None)
        if b is None:
            return
        now = time.monotonic()
        if self._minmove_baseline_ema is None:
            self._minmove_baseline_ema = b
            self._minmove_baseline_ema_t = now
            return
        dt = now - (self._minmove_baseline_ema_t or now)
        tau = max(1.0, mc.filter_tau_minutes * 60.0)
        alpha = 1.0 - math.exp(-dt / tau) if dt > 0 else 0.0
        self._minmove_baseline_ema += alpha * (b - self._minmove_baseline_ema)
        self._minmove_baseline_ema_t = now

    def _minmove_cap_px(self) -> Optional[float]:
        """§51 — cap MinMove adattivo in PIXEL, o None (fallback = nessun cap) se
        disabilitato o EMA baseline non ancora pronta. Aggiorna anche `_minmove_cap_info`
        (arcsec + px + termine vincente) per /status. Formula:
          cap_arcsec = min(k × baseline_filtrata, imaging_ceiling_arcsec); cap_px = /pixel_scale."""
        mc = self.cfg.minmove_cap
        if not mc.enabled or self._minmove_baseline_ema is None:
            self._minmove_cap_info = None
            return None
        scale = self.cfg.setup.guide_pixel_scale_arcsec
        if scale <= 0:
            self._minmove_cap_info = None
            return None
        cap_guiding = mc.baseline_factor * self._minmove_baseline_ema   # arcsec
        cap_arcsec = min(cap_guiding, mc.imaging_ceiling_arcsec)
        winning = "guiding" if cap_guiding <= mc.imaging_ceiling_arcsec else "imaging"
        cap_px = cap_arcsec / scale
        self._minmove_cap_info = {
            "cap_arcsec": round(cap_arcsec, 3),
            "cap_px": round(cap_px, 3),
            "winning": winning,
            "baseline_filtered_arcsec": round(self._minmove_baseline_ema, 3),
        }
        return cap_px

    def _cap_minmove_up(self, new_mm: float, limits: AxisLimits) -> float:
        """§51 — applica il cap adattivo a un MinMove che sta salendo. Tetto superiore:
        new_mm non supera cap_px; il floor minmove_min resta la barriera inferiore.
        Fallback (cap None): ritorna new_mm invariato (comportamento legacy).
        §0-bis: se il cap TAGLIA la richiesta (cap_px < new_mm) registra clamping_active
        con persistenza anti-flicker (per il badge ACTIVE della dashboard)."""
        cap_px = self._minmove_cap_px()
        if cap_px is None:
            return new_mm
        if cap_px < new_mm:   # il controllore chiedeva più del cap -> il cap ha tagliato
            self._minmove_clamp_active_until = time.monotonic() + _MINMOVE_CLAMP_PERSIST_S
        return max(limits.minmove_min, min(new_mm, cap_px))

    def _maybe_start_refresh(self) -> None:
        """§25: se il refresh ciclico e' abilitato, la baseline e' applicata e il timer
        e' scaduto, riapre la raccolta. Le soglie correnti restano attive durante la
        ri-misura: solo al termine si decide se applicare o rifiutare (tightest-wins)."""
        ac = self.cfg.auto_calibration
        # §44 — in modalità continua/bidirezionale il tracker gestisce gli aggiornamenti
        # a ogni frame: il refresh ciclico §25 (con la sua attesa e il tightest-wins) è
        # disattivato per non interferire.
        if ac.baseline_track_bidirectional:
            return
        if (not ac.enabled or not ac.refresh_enabled
                or self._baseline_refresh_in_progress
                or not self._rms_baseline_done
                or self._baseline_finalize_time is None):
            return
        elapsed = time.monotonic() - self._baseline_finalize_time
        if elapsed < ac.refresh_interval_seconds:
            return
        # Avvia il refresh: NON tocchiamo cfg.thresholds ne' analyzer (restano correnti).
        # Azzeriamo i campioni e _rms_baseline_done per riaprire la raccolta (§22 logic).
        self._rms_baseline_samples.clear()
        self._rms_baseline_all_samples.clear()   # §33: ricomincia anche la finestra fallback
        self._baseline_frames_seen = 0           # §33
        self._rms_baseline_done = False
        self._baseline_refresh_in_progress = True
        logger.info(
            "[autocal] refresh ciclico avviato (intervallo %.0fs scaduto, "
            "soglie correnti restano attive durante la ri-misura)",
            ac.refresh_interval_seconds,
        )

    # ------------------------------------------------------------------ #
    #  Baseline Guardian                                                  #
    # ------------------------------------------------------------------ #

    def save_baseline(self) -> None:
        """Salva i parametri PHD2 originali in baseline.json."""
        if not self._initialized:
            logger.warning("save_baseline() chiamata prima di initialize() - skip")
            return

        baseline = {
            "version": 3,           # v3: aggiunto stato esposizione dinamica
            "saved_at": time.time(),
            "setup_id": self._baseline_setup_id,
            "ra": {
                "aggr_param": self._ra.aggr_param,
                "current_aggr": self._ra.current_aggr,       # scala config (0-100)
                "aggr_native_scale": self._ra.aggr_native_scale,
                "minmove_param": self._ra.minmove_param,
                "current_minmove": self._ra.current_minmove,
            },
            "dec": {
                "aggr_param": self._dec.aggr_param,
                "current_aggr": self._dec.current_aggr,      # scala config (0-100)
                "aggr_native_scale": self._dec.aggr_native_scale,
                "minmove_param": self._dec.minmove_param,
                "current_minmove": self._dec.current_minmove,
            },
            "base_exposure_ms": self.base_exposure_ms,
            "current_exposure_ms": self.current_exposure_ms,
            "exposure_state": self.exposure_state.name,
            "exposure_steps_above_base": self.exposure_steps_above_base,
        }
        try:
            self.baseline_path.write_text(json.dumps(baseline, indent=2))
            logger.info("Baseline salvata in %s (setup=%s)",
                        self.baseline_path, self._baseline_setup_id)
        except Exception as e:
            logger.error("Impossibile salvare baseline: %s", e)

    def restore_baseline(self, source: str = "shutdown") -> bool:
        """Ripristina i parametri PHD2 ai valori della baseline salvata."""
        if not self.baseline_path.exists():
            logger.info("Nessuna baseline da ripristinare")
            return False

        try:
            baseline = json.loads(self.baseline_path.read_text())
        except Exception as e:
            logger.error("Baseline corrotta, skip restore: %s", e)
            return False

        version = baseline.get("version", 1)
        if version < 2:
            logger.warning(
                "Baseline formato v1 (scala aggr non compatibile) - skip restore. "
                "Verra' ricreata alla prossima sessione."
            )
            self.baseline_path.unlink(missing_ok=True)
            return False

        saved_setup = baseline.get("setup_id", "unknown")
        if saved_setup != self._baseline_setup_id:
            logger.warning(
                "Baseline appartiene a setup '%s' ma corrente e' '%s' - skip",
                saved_setup, self._baseline_setup_id,
            )
            return False

        age_hours = (time.time() - baseline.get("saved_at", 0)) / 3600
        if age_hours > 24:
            logger.warning(
                "Baseline vecchia di %.1f ore - skip restore "
                "(riavvio manuale richiesto)",
                age_hours,
            )
            return False

        logger.info(
            "Ripristino baseline (origine=%s, eta=%.1fh, setup=%s)",
            source, age_hours, saved_setup,
        )

        if self.dry_run:
            logger.info("[DRY_RUN] Skipping actual baseline restore")
            return True

        try:
            ra_data = baseline.get("ra", {})
            dec_data = baseline.get("dec", {})

            if ra_data.get("aggr_param"):
                scale = ra_data.get("aggr_native_scale", 1.0)
                val = ra_data["current_aggr"] * scale
                self.client.set_algo_param(
                    "ra", ra_data["aggr_param"],
                    round(val, 4) if scale < 1.0 else int(round(val))
                )
            if ra_data.get("minmove_param"):
                self.client.set_algo_param(
                    "ra", ra_data["minmove_param"], ra_data["current_minmove"]
                )
            if dec_data.get("aggr_param"):
                scale = dec_data.get("aggr_native_scale", 1.0)
                val = dec_data["current_aggr"] * scale
                self.client.set_algo_param(
                    "dec", dec_data["aggr_param"],
                    round(val, 4) if scale < 1.0 else int(round(val))
                )
            if dec_data.get("minmove_param"):
                self.client.set_algo_param(
                    "dec", dec_data["minmove_param"], dec_data["current_minmove"]
                )

            base_exp = baseline.get("base_exposure_ms")
            if base_exp:
                self.client.set_exposure(base_exp)

            if version >= 3:
                saved_current = baseline.get("current_exposure_ms")
                saved_state = baseline.get("exposure_state", "NOMINAL")
                saved_steps = baseline.get("exposure_steps_above_base", 0)
                if saved_steps > 0 or saved_state != "NOMINAL":
                    logger.info(
                        "Baseline v3: esposizione era %s ms (stato %s, %d step) "
                        "— ripristinata a base %s ms",
                        saved_current, saved_state, saved_steps, base_exp,
                    )
                self.exposure_state = ExposureState.NOMINAL
                self.exposure_steps_above_base = 0
                self.current_exposure_ms = base_exp
            else:
                logger.info("Baseline v2 — esposizione dinamica resettata a base")
                self.exposure_state = ExposureState.NOMINAL
                self.exposure_steps_above_base = 0

            logger.info("Baseline ripristinata con successo")
            return True
        except Exception as e:
            logger.error("Errore durante restore baseline: %s", e)
            return False

    def _check_orphan_baseline(self) -> None:
        """Se trova baseline.json al startup, sessione precedente crashata.
        Ripristina PRIMA di operare."""
        if self.baseline_path.exists():
            logger.warning(
                "Trovata baseline.json orfana - sessione precedente "
                "non chiusa correttamente. Tento recovery..."
            )
            self.restore_baseline(source="orphan_recovery")
            # File rimosso solo dopo shutdown pulito; in orphan recovery
            # lo lasciamo perche' verra' sovrascritto da save_baseline.

    def shutdown(self) -> None:
        """Cleanup graceful: ripristina baseline e cancella file."""
        logger.info("Shutdown controller - restore baseline...")
        if self.restore_baseline(source="shutdown"):
            try:
                self.baseline_path.unlink(missing_ok=True)
                logger.info("Baseline file rimosso (shutdown pulito)")
            except Exception as e:
                logger.warning("Impossibile rimuovere baseline file: %s", e)

    # ------------------------------------------------------------------ #
    #  Evaluazione principale                                             #
    # ------------------------------------------------------------------ #

    def ingest_frame(self, snapshot: AnalysisSnapshot) -> None:
        """§34 — hook PER guide-frame (ogni GuideStep), distinto da evaluate() che gira
        sul tick interval_seconds. Quando per_frame_baseline e' attivo:
          1. accumula la baseline sui guide-frame REALI (non sui tick da 10s) → il
             fallback §33 scatta in ~6 min invece di ~30;
          2. popola exposure_ms (valore reale) e diag_state/confidence (ULTIMO esito
             valido) sulle righe fuori-tick, così non escono come placeholder
             (exposure=0 / INSUFFICIENT) che gonfiano le statistiche.
        NON esegue classify ne' muove leve: quello resta in evaluate() (per-tick).
        A kill-switch off e' un no-op completo (baseline torna in evaluate, per-tick)."""
        if not self.cfg.control.per_frame_baseline or not self._initialized:
            return
        # exposure reale su OGNI riga loggata
        snapshot.exposure_ms = int(self.current_exposure_ms or self.base_exposure_ms or 0)
        # accumulo baseline per guide-frame reale (sostituisce quello in evaluate)
        self._maybe_start_refresh()
        self._update_rms_baseline(snapshot)
        # ultimo stato diagnostico valido per le righe fuori-tick (non placeholder).
        # Sui tick, evaluate() sovrascrive subito con la diagnosi fresca.
        if self._current_diag is not None:
            snapshot.diag_state = self._current_diag.state.name
            snapshot.diag_confidence = self._current_diag.confidence

    def evaluate(self, snapshot: AnalysisSnapshot) -> list[ControlAction]:
        """
        Valuta lo snapshot e ritorna la lista delle azioni eseguite (o simulate).
        Da chiamare periodicamente, non per ogni frame.
        """
        if not self._initialized:
            if not self.initialize():
                return []

        actions: list[ControlAction] = []

        # §34 — questo frame e' un tick di valutazione vero (classify + leve), non una
        # semplice riga di log fuori-tick: marcalo per il logging/replay (% INSUFFICIENT
        # reale = solo su evaluated==True).
        snapshot.evaluated = True
        self.eval_count += 1              # §63 — ciclo motore osservabile in dashboard
        self.last_eval_ts = time.time()

        self._update_guiding_state(snapshot)
        self._update_minmove_baseline_filter()   # §51 — EMA baseline per il cap MinMove

        # §31 — Seeing Diagnostic Engine: diagnosi causale a ogni tick (alimenta la
        # dashboard e gli eventuali interventi). A motore spento e' un no-op completo.
        if self.diagnostic_engine is not None:
            snapshot.exposure_ms = int(self.current_exposure_ms or self.base_exposure_ms or 0)
            self._current_diag = self.diagnostic_engine.classify(snapshot)
            snapshot.diag_state = self._current_diag.state.name
            snapshot.diag_confidence = self._current_diag.confidence
            if self._warmup_frames_left > 0:
                self._warmup_frames_left -= 1

        # Tracking condizione NOMINAL per trigger DOWN esposizione seeing
        if snapshot.condition == SeeingCondition.NOMINAL:
            if self._nominal_since is None:
                self._nominal_since = time.monotonic()
        else:
            self._nominal_since = None

        if self.guiding_state == GuidingState.INACTIVE:
            return []

        if snapshot.condition == SeeingCondition.STAR_LOST:
            self.guiding_state = GuidingState.STAR_LOST
            if self.cfg.emergency.auto_recovery:
                actions.extend(self._evaluate_star_lost())
            return actions
        else:
            self.star_lost_since = None

        # Riscritto in forma esplicita (era espressione ternaria ambigua)
        if hasattr(snapshot, "is_ready"):
            if not snapshot.is_ready:
                return []
        elif snapshot.frame_count < 5:
            return []

        # Auto-calibrazione soglie RMS: campiona la baseline PRIMA della logica
        # adattiva (no-op se auto_calibration disabilitata o baseline gia' pronta).
        # §25: prima del campionamento valuta se avviare un refresh ciclico.
        # §34: con per_frame_baseline l'accumulo avviene in ingest_frame (per
        # guide-frame reale → fallback in ~6 min); qui resta solo nel comportamento
        # storico per-tick (kill-switch off).
        if not self.cfg.control.per_frame_baseline:
            self._maybe_start_refresh()
            self._update_rms_baseline(snapshot)

        # §32 — stato del recupero MinMove (contatore consecutivo + reset del run).
        # Globale, una volta per tick, dopo l'aggiornamento baseline (la soglia di
        # recupero e' la mediana corrente).
        self._update_recovery_state(snapshot)

        # §31 — progressione delle finestre outcome aperte e accumulo della media
        # pre-azione. Eseguito PRIMA di qualsiasi azione di questo tick, cosi' una
        # finestra appena aperta inizia ad accumulare il post dal tick successivo.
        if self.diagnostic_engine is not None:
            self._track_outcome(snapshot)

        # Eval emergenza SNR
        if self.cfg.emergency.auto_recovery:
            actions.extend(self._evaluate_exposure(snapshot))
            actions.extend(self._evaluate_pathb_restar(snapshot))   # §35
            actions.extend(self._evaluate_saturation_timer())

        # Valuta RA
        ra_actions = self._evaluate_axis(
            self._ra, self.cfg.ra,
            snapshot.rms_ra, snapshot.consecutive_high, snapshot.consecutive_low,
            snapshot.condition, snapshot,
        )
        actions.extend(ra_actions)

        # Valuta Dec (piu' conservativo di default)
        dec_actions = self._evaluate_axis(
            self._dec, self.cfg.dec,
            snapshot.rms_dec, snapshot.consecutive_high, snapshot.consecutive_low,
            snapshot.condition, snapshot,
        )
        actions.extend(dec_actions)

        # §32 — anti-windup del recupero MinMove: una volta per tick, dopo entrambi
        # gli assi (l'RMS di feedback e' rms_total, non per-asse).
        self._finalize_recovery_windup(snapshot)

        # §31 — azioni del motore. In jitter e' unica autorita' (i CASO 1/2/3 sopra
        # hanno restituito []); in guardian micro-corregge SOLO dove la v2.3 e' ferma
        # in questo tick (asse senza azioni). I review BLOCK/ATTENUATE sono gia' stati
        # gestiti dentro _evaluate_axis via _apply_with_guardian.
        if self._engine_owns_levers():
            actions.extend(self._evaluate_engine_actions(snapshot))
        elif self._guardian_active():
            if not ra_actions:
                actions.extend(self._guardian_micro_correction(self._ra, self.cfg.ra, snapshot))
            if not dec_actions:
                actions.extend(self._guardian_micro_correction(self._dec, self.cfg.dec, snapshot))

        self.action_history.extend(actions)

        if len(self.action_history) > 500:
            self.action_history = self.action_history[-500:]

        return actions

    def _update_guiding_state(self, snapshot: AnalysisSnapshot) -> None:
        rms = snapshot.rms_total
        thresh = self.cfg.thresholds

        if snapshot.condition == SeeingCondition.STAR_LOST:
            self.guiding_state = GuidingState.STAR_LOST
        elif rms > thresh.rms_high * 1.5:
            self.guiding_state = GuidingState.CRITICAL
        elif rms > thresh.rms_high:
            self.guiding_state = GuidingState.DEGRADED
        elif rms < thresh.rms_low and self.guiding_state in (
                GuidingState.DEGRADED, GuidingState.CRITICAL):
            self.guiding_state = GuidingState.RECOVERING
        elif rms < thresh.rms_low:
            self.guiding_state = GuidingState.NORMAL
        # Altrimenti: stato invariato (zona neutra)

    def _evaluate_axis(
        self,
        axis_state: AxisState,
        limits: AxisLimits,
        rms: float,
        consec_high: int,
        consec_low: int,
        condition: SeeingCondition,
        snapshot: AnalysisSnapshot,
    ) -> list[ControlAction]:
        actions: list[ControlAction] = []
        thresh = self.cfg.thresholds
        now = time.monotonic()
        cooldown = self.cfg.control.cooldown_seconds
        minmove_cooldown = cooldown * 1.5  # MinMove piu' conservativo

        # §31 — In modalita' jitter il motore e' unica autorita' sulle leve: i rami
        # CASO 1/2/3 della v2.3 sono SOSPESI (non cancellati: restano attivi a motore
        # spento e in guardian). Le azioni del motore arrivano da _evaluate_engine_actions.
        if self._engine_owns_levers():
            return []

        # ---- CASO 1: Seeing degradato -> abbassa aggressivita' e alza MinMove
        if (rms > thresh.rms_high
                and consec_high >= thresh.consecutive_frames
                and axis_state.aggr_param):

            # Aggressiveness DOWN
            elapsed = now - axis_state.last_action_time
            if elapsed >= cooldown:
                old_v = axis_state.current_aggr
                step = limits.aggr_step_down

                if self.guiding_state == GuidingState.CRITICAL:
                    step = min(step * 2, 15.0)

                new_v = max(limits.aggr_min, old_v - step)
                if new_v != old_v:
                    reason = (
                        f"RMS {axis_state.axis.upper()}={rms:.2f}\" > "
                        f"{thresh.rms_high}\" per {consec_high} frame - "
                        f"abbasso Aggressivita ({condition.name})"
                    )
                    action = self._apply_with_guardian(axis_state, limits,
                                                       axis_state.aggr_param, old_v, new_v,
                                                       reason, caso="CASO1", snapshot=snapshot)
                    actions.append(action)

            # MinMove UP (parallelo all'abbassamento aggressivita')
            mm_elapsed = now - axis_state.last_minmove_action_time
            if (axis_state.minmove_param
                    and mm_elapsed >= minmove_cooldown):
                old_mm = axis_state.current_minmove
                new_mm = min(limits.minmove_max, old_mm + limits.minmove_step)
                new_mm = self._cap_minmove_up(new_mm, limits)   # §51 cap adattivo
                if new_mm != old_mm:
                    reason = (
                        f"Seeing degradato - aumento MinMove "
                        f"per assorbire rumore di seeing/vento"
                    )
                    action = self._apply_with_guardian(axis_state, limits,
                                                       axis_state.minmove_param,
                                                       old_mm, new_mm, reason,
                                                       is_minmove=True, caso="CASO1",
                                                       snapshot=snapshot)
                    actions.append(action)

        # ---- CASO 2: Oscillazione -> abbassa aggressivita' (RA + DEC) ----
        # Modifica vs versione originale: includiamo anche DEC perche' le
        # oscillazioni in DEC con backlash sono altrettanto comuni e gravi.
        # §47 — esperimento outcome-first: gateato da oscillation_branch_enabled
        # (default false -> un trend non riduce piu' l'aggressivita' "perche' oscilla";
        # la condizione cade nel ramo successivo / banda morta). Reversibile.
        elif (self.cfg.diagnostic_engine.oscillation_branch_enabled
              and condition == SeeingCondition.OSCILLATING
              and axis_state.aggr_param):

            elapsed = now - axis_state.last_action_time
            if elapsed >= cooldown:
                old_v = axis_state.current_aggr
                new_v = max(limits.aggr_min, old_v - limits.aggr_step_down)
                if new_v != old_v:
                    trend_val = (snapshot.trend_ra if axis_state.axis == "ra"
                                 else getattr(snapshot, "trend_dec", 0.0))
                    reason = (
                        f"Oscillazione rilevata "
                        f"(trend={trend_val:+.3f} arcsec/frame) "
                        f"- riduco Aggressivita {axis_state.axis.upper()}"
                    )
                    action = self._apply_with_guardian(axis_state, limits,
                                                       axis_state.aggr_param, old_v, new_v,
                                                       reason, caso="CASO2", snapshot=snapshot)
                    actions.append(action)

        # ---- CASO 3: Guida ottima -> aumento graduale aggressivita' + MinMove DOWN
        elif (rms < thresh.rms_low
              and consec_low >= thresh.consecutive_frames
              and axis_state.aggr_param):

            # §30 — Satisfaction gate (stateless): se l'RMS d'asse e' gia' al livello
            # della mediana baseline (o sotto), non spingere le leve verso la
            # reattivita' estrema. Rivalutato a ogni tick: si auto-disattiva se l'RMS
            # risale. Fallback al CASO 3 legacy se disabilitato, baseline non pronta
            # o baseline rifiutata (§23).
            lo_cfg = self.cfg.lever_optimization
            baseline_target_available = (
                lo_cfg.enabled
                and self._rms_baseline_value is not None
                and not self._rms_baseline_rejected
            )
            if baseline_target_available:
                target = self._rms_baseline_value * lo_cfg.target_factor
                if rms <= target:
                    logger.debug(
                        "[opt] %s: gate attivo (RMS %.3f\" <= target %.3f\" = "
                        "mediana × %.2f); leve non vengono spinte",
                        axis_state.axis.upper(), rms, target, lo_cfg.target_factor,
                    )
                    return actions  # nessuna azione di ottimizzazione su questo tick

            # Aggressiveness UP (cooldown raddoppiato, conservativo)
            elapsed = now - axis_state.last_action_time
            if elapsed >= cooldown * 2:
                old_v = axis_state.current_aggr
                new_v = min(limits.aggr_max, old_v + limits.aggr_step_up)
                if new_v != old_v:
                    reason = (
                        f"RMS {axis_state.axis.upper()}={rms:.2f}\" < "
                        f"{thresh.rms_low}\" per {consec_low} frame - "
                        "guida stabile, aumento graduale Aggressivita"
                    )
                    action = self._apply_with_guardian(axis_state, limits,
                                                       axis_state.aggr_param,
                                                       old_v, new_v, reason,
                                                       caso="CASO3", snapshot=snapshot)
                    actions.append(action)

            # MinMove DOWN (cooldown 3x, recupero precisione molto graduale)
            mm_elapsed = now - axis_state.last_minmove_action_time
            if (axis_state.minmove_param
                    and mm_elapsed >= minmove_cooldown * 2):
                old_mm = axis_state.current_minmove
                new_mm = max(limits.minmove_min, old_mm - limits.minmove_step)
                if new_mm != old_mm:
                    reason = (
                        f"Guida stabile - abbasso MinMove "
                        f"per maggior precisione"
                    )
                    action = self._apply_with_guardian(axis_state, limits,
                                                       axis_state.minmove_param,
                                                       old_mm, new_mm, reason,
                                                       is_minmove=True, caso="CASO3",
                                                       snapshot=snapshot)
                    actions.append(action)

        # ---- §32 RECUPERO: banda morta, RMS sopra mediana -> alza MinMove ----------
        # Complemento speculare del satisfaction gate (§30). Qui (ultimo elif) siamo
        # per costruzione nella BANDA MORTA: nessun CASO 1/2/3 e' scattato, cioe' rms
        # non e' > rms_high (CASO 1), non oscilla (CASO 2) e non e' < rms_low (CASO 3).
        # Se pero' l'RMS d'asse resta sopra la mediana baseline (rms > soglia) per
        # consecutive_frames tick, la guida e' peggiorata rispetto alla baseline ma non
        # abbastanza da far scattare CASO 1: alziamo MinMove di un gradino verso la
        # morbidezza, OLTRE il valore iniziale, fino a minmove_max (floor 0.15 intatto).
        # Isteresi anti-pompaggio: su solo se rms > mediana, giu' (CASO 3) solo se
        # rms < rms_low -> tra i due la leva resta ferma. Trigger consecutivo e
        # anti-windup sono gestiti a livello di tick (_update_recovery_state /
        # _finalize_recovery_windup). caso="RECOVERY": in guardian la review() lo
        # CONFERMA (caso ignoto -> CONFIRM), §31 non e' toccato.
        elif (self.cfg.lever_optimization.minmove_recovery_enabled
              and not self._recovery_blocked
              and self._recovery_consec >= thresh.consecutive_frames):
            # §53 — il VERSO è deciso globalmente in _update_recovery_state (esito/stabilità).
            # Un solo verso per asse/tick (anti-flapping). caso="RECOVERY" -> guardian CONFIRM.
            if self._recovery_direction == "stiffen":
                self._recovery_stiffen_axis(axis_state, limits, snapshot,
                                            actions, now, cooldown, minmove_cooldown)
            else:
                self._recovery_soften_axis(axis_state, limits, rms, snapshot,
                                           actions, now, minmove_cooldown)

        return actions

    def _recovery_stiffen_axis(self, axis_state: "AxisState", limits: AxisLimits,
                               snapshot: AnalysisSnapshot, actions: list, now: float,
                               cooldown: float, minmove_cooldown: float) -> None:
        """§53 — irrigidimento verso lo standard §50: aggr SU (solo assi a scala frazionaria,
        mai OLTRE il nominale §50) + MinMove GIÙ (mai SOTTO il nominale §50). Un gradino per
        cooldown; l'esito è valutato in _finalize_recovery_windup (KEEP/STOP)."""
        lo = self.cfg.lever_optimization
        nom_aggr, nom_mm = _STANDARD_INIT[axis_state.axis]
        anchor = (self._recovery_anchor_rms if self._recovery_anchor_rms is not None
                  else snapshot.rms_total)
        # Aggr SU verso il nominale §50 (solo Hysteresis/Resist Switch: scala frazionaria).
        if (lo.recovery_stiffen_aggression and axis_state.aggr_param
                and axis_state.aggr_native_scale == _FRACTIONAL_AGGR_SCALE
                and axis_state.current_aggr < nom_aggr - 1e-6
                and now - axis_state.last_action_time >= cooldown):
            old_v = axis_state.current_aggr
            new_v = min(nom_aggr, old_v + limits.aggr_step_up)   # mai oltre il nominale §50
            if new_v != old_v:
                reason = (f"Recupero simmetrico §53: banda morta stabile - irrigidisco Aggr "
                          f"{axis_state.axis.upper()} {old_v:.0f}→{new_v:.0f} verso lo standard "
                          f"(anchor RMS {anchor:.2f}\")")
                actions.append(self._apply_with_guardian(
                    axis_state, limits, axis_state.aggr_param, old_v, new_v, reason,
                    caso="RECOVERY", snapshot=snapshot))
                self._recovery_applied_this_tick = True
        # MinMove GIÙ verso il nominale §50 (mai sotto il nominale; il cap §51 è tetto in salita).
        if (axis_state.minmove_param and axis_state.current_minmove > nom_mm + 1e-6
                and now - axis_state.last_minmove_action_time >= minmove_cooldown):
            old_mm = axis_state.current_minmove
            new_mm = max(nom_mm, old_mm - limits.minmove_step)   # mai sotto il nominale §50
            if new_mm != old_mm:
                reason = (f"Recupero simmetrico §53: banda morta stabile - abbasso MinMove "
                          f"{axis_state.axis.upper()} {old_mm:.2f}→{new_mm:.2f} verso lo standard "
                          f"(anchor RMS {anchor:.2f}\")")
                actions.append(self._apply_with_guardian(
                    axis_state, limits, axis_state.minmove_param, old_mm, new_mm, reason,
                    is_minmove=True, caso="RECOVERY", snapshot=snapshot))
                self._recovery_applied_this_tick = True

    def _recovery_soften_axis(self, axis_state: "AxisState", limits: AxisLimits, rms: float,
                              snapshot: AnalysisSnapshot, actions: list, now: float,
                              minmove_cooldown: float) -> None:
        """§32 — ammorbidimento (alza MinMove verso la morbidezza) nella banda morta. In §53
        è il FALLBACK: scatta quando il verso del run è 'soften' (leve già allo standard, o
        l'esito ha bloccato l'irrigidimento = seeing vero). Cap §51 tetto in salita, invariato."""
        if not axis_state.minmove_param:
            return
        recovery_threshold = self._recovery_threshold()
        mm_elapsed = now - axis_state.last_minmove_action_time
        if (recovery_threshold is None or rms <= recovery_threshold
                or mm_elapsed < minmove_cooldown):
            return
        old_mm = axis_state.current_minmove
        new_mm = min(limits.minmove_max, old_mm + limits.minmove_step)
        new_mm = self._cap_minmove_up(new_mm, limits)   # §51 cap adattivo
        if new_mm == old_mm:
            return
        lo_factor = self.cfg.lever_optimization.minmove_recovery_factor
        reason = (f"Recupero leve (soften §32): RMS {axis_state.axis.upper()}={rms:.2f}\" sopra "
                  f"mediana×{lo_factor:.2f} nella banda morta - alzo MinMove verso la morbidezza")
        actions.append(self._apply_with_guardian(
            axis_state, limits, axis_state.minmove_param, old_mm, new_mm, reason,
            is_minmove=True, caso="RECOVERY", snapshot=snapshot))
        self._recovery_applied_this_tick = True

    # ------------------------------------------------------------------ #
    #  §32 — Recupero MinMove nella banda morta (asimmetria leve §4)        #
    # ------------------------------------------------------------------ #

    def _recovery_threshold(self) -> Optional[float]:
        """Soglia di recupero = mediana baseline × minmove_recovery_factor.
        None se il recupero non e' disponibile (disabilitato, baseline non pronta o
        rifiutata §23): stessi guard del satisfaction gate §30."""
        lo = self.cfg.lever_optimization
        if (not lo.minmove_recovery_enabled
                or self._rms_baseline_value is None
                or self._rms_baseline_rejected):
            return None
        return self._rms_baseline_value * lo.minmove_recovery_factor

    def _update_recovery_state(self, snapshot: AnalysisSnapshot) -> None:
        """§32/§53 — stato del recupero (una volta per tick, prima degli assi). Aggiorna il
        contatore consecutivo (rms_total > soglia) e la finestra RMS per il trend; §53:
        decide il VERSO del run — 'stiffen' (leve più morbide dello standard §50 + guida
        stabile → irrigidisci verso lo standard) o 'soften' (§32 legacy). Reset del run
        quando l'RMS rientra nel corridoio (<= soglia) o il recupero non è disponibile."""
        self._recovery_applied_this_tick = False
        self._rms_recent.append(snapshot.rms_total)
        threshold = self._recovery_threshold()
        if threshold is None or snapshot.rms_total <= threshold:
            self._recovery_consec = 0
            self._recovery_anchor_rms = None
            self._recovery_actions_since_anchor = 0
            self._recovery_blocked = False
            self._recovery_stiffen_blocked = False
            self._recovery_direction = None
            return
        self._recovery_consec += 1
        # §53 — verso del run: STIFFEN solo se feature on, irrigidimento non già bloccato
        # dall'esito, leve più morbide dello standard §50 e guida stabile; altrimenti SOFTEN.
        lo = self.cfg.lever_optimization
        if (lo.symmetric_recovery_enabled and not self._recovery_stiffen_blocked
                and self._levers_softened() and self._recovery_is_stable(snapshot)):
            self._recovery_direction = "stiffen"
        else:
            self._recovery_direction = "soften"

    def _levers_softened(self) -> bool:
        """§53 — True se almeno un asse è più MORBIDO dello standard §50 (aggr sotto il
        nominale su assi a scala frazionaria, oppure MinMove sopra il nominale)."""
        for axis_state in (self._ra, self._dec):
            nom_aggr, nom_mm = _STANDARD_INIT[axis_state.axis]
            if (axis_state.aggr_native_scale == _FRACTIONAL_AGGR_SCALE
                    and axis_state.aggr_param
                    and axis_state.current_aggr < nom_aggr - 1e-6):
                return True
            if axis_state.minmove_param and axis_state.current_minmove > nom_mm + 1e-6:
                return True
        return False

    def _rms_rising(self) -> bool:
        """§53 — True se l'RMS recente è in salita (ultimo − primo della finestra > eps)."""
        w = list(self._rms_recent)
        if len(w) < 3:
            return False
        return (w[-1] - w[0]) > _RMS_RISING_EPS

    def _recovery_is_stable(self, snapshot: AnalysisSnapshot) -> bool:
        """§53 — guida STABILE = RMS non in salita, non-SEEING, e (advisory) trasparenza
        N1 non-CLOUD. Pre-condizione per tentare l'irrigidimento verso lo standard."""
        if self._rms_rising():
            return False
        if snapshot.condition == SeeingCondition.DEGRADED_SEEING:
            return False
        if self._current_diag is not None and self._current_diag.state.name == "SEEING":
            return False
        ci = self._nina_confidence_input()   # None se non fresco/assente (advisory N1)
        if ci is not None and ci.get("state") == "CLOUD":
            return False
        return True

    def _finalize_recovery_windup(self, snapshot: AnalysisSnapshot) -> None:
        """§32 — anti-windup puro-RMS, una volta per tick dopo entrambi gli assi.
        Se in questo tick e' stato applicato un recupero, verifica che il softening
        stia riducendo l'RMS: ancora il run al primo recupero e, dopo
        recovery_no_progress_k recuperi senza un calo > _RECOVERY_PROGRESS_EPS rispetto
        all'anchor, blocca (RMS atmosferico, non lever-fixable -> niente windup verso
        minmove_max). Se l'RMS cala, ri-ancora e prosegue."""
        if not self._recovery_applied_this_tick:
            return
        rms = snapshot.rms_total
        lo = self.cfg.lever_optimization
        if self._recovery_anchor_rms is None:
            self._recovery_anchor_rms = rms
            self._recovery_actions_since_anchor = 1
            return
        self._recovery_actions_since_anchor += 1

        # §53 — STIFFEN: outcome gate. Dopo la finestra, se l'RMS regge (<= anchor×tol)
        # continua e ri-ancora; se peggiora oltre tolleranza -> STOP (era seeing vero),
        # blocca l'irrigidimento e passa a soften (§32 diventa legittimo).
        if self._recovery_direction == "stiffen":
            win = max(1, lo.recovery_outcome_window_frames)
            if self._recovery_actions_since_anchor >= win:
                tol = self._recovery_anchor_rms * lo.recovery_outcome_tolerance_factor
                if rms <= tol:
                    logger.info("[recovery §53] STIFFEN KEEP: RMS %.3f\" regge vs anchor %.3f\" "
                                "(×%.2f) -> continuo verso lo standard",
                                rms, self._recovery_anchor_rms, lo.recovery_outcome_tolerance_factor)
                    self._recovery_anchor_rms = rms
                    self._recovery_actions_since_anchor = 0
                else:
                    logger.info("[recovery §53] STIFFEN STOP: RMS %.3f\" peggiora oltre anchor "
                                "%.3f\"×%.2f -> era seeing, tengo le leve e passo a soften",
                                rms, self._recovery_anchor_rms, lo.recovery_outcome_tolerance_factor)
                    self._recovery_stiffen_blocked = True
                    self._recovery_anchor_rms = None
                    self._recovery_actions_since_anchor = 0
            return

        # SOFTEN — anti-windup §32 (invariato): dopo K recuperi senza calo RMS, blocca.
        k = max(1, lo.recovery_no_progress_k)
        if self._recovery_actions_since_anchor >= k:
            if rms < self._recovery_anchor_rms - _RECOVERY_PROGRESS_EPS:
                # Il softening sta aiutando: ri-ancora e continua a recuperare.
                self._recovery_anchor_rms = rms
                self._recovery_actions_since_anchor = 0
            else:
                # K recuperi senza calo dell'RMS: e' atmosferico, fermo il softening.
                self._recovery_blocked = True
                logger.info(
                    "[recovery] anti-windup: %d recuperi senza calo RMS "
                    "(%.3f\" vs anchor %.3f\") -> softening sospeso",
                    k, rms, self._recovery_anchor_rms,
                )

    # ------------------------------------------------------------------ #
    #  Seeing Diagnostic Engine (§31) — review, micro, jitter, outcome     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _set_current(axis_state: AxisState, is_minmove: bool, value: float) -> None:
        """Riallinea current_aggr/current_minmove al valore effettivamente applicato."""
        if is_minmove:
            axis_state.current_minmove = value
        else:
            axis_state.current_aggr = value

    def _apply_with_guardian(
        self,
        axis_state: AxisState,
        limits: AxisLimits,
        param_name: str,
        old_value: float,
        new_value: float,
        reason: str,
        is_minmove: bool = False,
        caso: str = "",
        snapshot: Optional[AnalysisSnapshot] = None,
    ) -> ControlAction:
        """Punto unico di applicazione delle mosse leva v2.3 (CASO 1/2/3).

        A motore spento o in jitter (non-guardian) e' un semplice _apply + riallineo
        di current_*. In guardian consulta engine.review(): CONFIRM applica invariato,
        ATTENUATE applica una frazione (guardian_attenuate_factor), BLOCK non applica e
        ritorna un evento axis="guardian". current_* aggiornato solo se applicato."""
        src = _CASO_TO_SOURCE.get(caso, "other")   # §47 attribuzione
        if not self._guardian_active():
            action = self._apply(axis_state, limits, param_name, old_value, new_value,
                                 reason, is_minmove=is_minmove, softening_source=src)
            self._set_current(axis_state, is_minmove, new_value)
            return action

        direction = new_value - old_value
        verdict, factor, vreason = self.diagnostic_engine.review(
            caso, is_minmove, direction,
            context=f"{axis_state.axis}/{param_name}")   # §80

        if verdict == GuardianVerdict.CONFIRM:
            action = self._apply(axis_state, limits, param_name, old_value, new_value,
                                 reason, is_minmove=is_minmove, softening_source=src)
            self._set_current(axis_state, is_minmove, new_value)
            return action

        if verdict == GuardianVerdict.ATTENUATE:
            new2 = old_value + factor * (new_value - old_value)
            if abs(new2 - old_value) < 1e-6:
                # Mossa collassata su old -> equivale a un blocco.
                logger.info("[GUARDIAN] ATTENUATE collassato su old %s/%s — %s",
                            axis_state.axis, param_name, vreason)
                return self._guardian_block_event(axis_state, param_name, old_value,
                                                  new_value, vreason,
                                                  "guardian_attenuate", "attenuate", snapshot)
            full_reason = f"{reason} [GUARDIAN ATTENUATE x{factor:.2f}]"
            action = self._apply(axis_state, limits, param_name, old_value, new2,
                                 full_reason, is_minmove=is_minmove, softening_source=src)
            self._set_current(axis_state, is_minmove, new2)
            logger.info("[GUARDIAN] ATTENUATE %s/%s %.3f->%.3f (v2.3 voleva %.3f) — %s",
                        axis_state.axis, param_name, old_value, new2, new_value, vreason)
            self._open_outcome(
                snapshot, "guardian_attenuate", "attenuate",
                lever_changes=[{"axis": axis_state.axis, "param": param_name,
                                "old": round(old_value, 4), "new": round(new2, 4)}],
                v23_proposed={"axis": axis_state.axis, "param": param_name,
                              "old": round(old_value, 4), "new": round(new_value, 4)},
            )
            return action

        # BLOCK
        logger.info("[GUARDIAN] BLOCK %s/%s (v2.3 voleva %.3f->%.3f) — %s",
                    axis_state.axis, param_name, old_value, new_value, vreason)
        return self._guardian_block_event(axis_state, param_name, old_value, new_value,
                                          vreason, "guardian_block", "block", snapshot)

    def _guardian_block_event(
        self, axis_state: AxisState, param_name: str, old_value: float,
        new_value: float, vreason: str, event: str, action_kind: str,
        snapshot: Optional[AnalysisSnapshot],
    ) -> ControlAction:
        """Costruisce l'evento axis="guardian" per una mossa v2.3 bloccata/azzerata e
        apre la finestra outcome (la v2.5 valutera' se bloccare era giusto)."""
        action = ControlAction(
            timestamp=time.time(), axis="guardian",
            param=f"{action_kind}_{param_name}",
            old_value=old_value, new_value=new_value,
            reason=f"[GUARDIAN {action_kind.upper()}] {vreason}", dry_run=True,
        )
        self._open_outcome(
            snapshot, event, action_kind,
            lever_changes=[],
            v23_proposed={"axis": axis_state.axis, "param": param_name,
                          "old": round(old_value, 4), "new": round(new_value, 4)},
        )
        return action

    def _apply_proposal(
        self, axis_state: AxisState, limits: AxisLimits, proposal, factor: float,
        reason: str, softening_source: str = "guardian_micro",
    ) -> tuple[list[dict], list[ControlAction]]:
        """Traduce una LeverProposal (direzione) in mosse concrete con clamp ai
        [limits], applicate via _apply (×1.0 in jitter, ×guardian_action_factor nelle
        micro). Il cooldown per-asse e' gestito dal chiamante (_diag_last_action).
        Ritorna (lever_changes, actions)."""
        actions: list[ControlAction] = []
        lever_changes: list[dict] = []

        if proposal.aggr != 0 and axis_state.aggr_param:
            base = limits.aggr_step_down if proposal.aggr < 0 else limits.aggr_step_up
            step = base * factor
            if factor < 1.0:
                step = max(1.0, round(step))   # micro: almeno 1 punto di aggr
            old_v = axis_state.current_aggr
            new_v = (max(limits.aggr_min, old_v - step) if proposal.aggr < 0
                     else min(limits.aggr_max, old_v + step))
            if new_v != old_v:
                actions.append(self._apply(axis_state, limits, axis_state.aggr_param,
                                           old_v, new_v, reason,
                                           softening_source=softening_source))
                axis_state.current_aggr = new_v
                lever_changes.append({"axis": axis_state.axis, "param": axis_state.aggr_param,
                                      "old": round(old_v, 4), "new": round(new_v, 4)})

        if proposal.minmove != 0 and axis_state.minmove_param:
            step = limits.minmove_step * factor
            old_mm = axis_state.current_minmove
            new_mm = (min(limits.minmove_max, old_mm + step) if proposal.minmove > 0
                      else max(limits.minmove_min, old_mm - step))
            if proposal.minmove > 0:
                new_mm = self._cap_minmove_up(new_mm, limits)   # §51 cap adattivo (solo in salita)
            if new_mm != old_mm:
                actions.append(self._apply(axis_state, limits, axis_state.minmove_param,
                                           old_mm, new_mm, reason, is_minmove=True,
                                           softening_source=softening_source))
                axis_state.current_minmove = new_mm
                lever_changes.append({"axis": axis_state.axis, "param": axis_state.minmove_param,
                                      "old": round(old_mm, 4), "new": round(new_mm, 4)})

        return lever_changes, actions

    def _engine_action_gate_open(self) -> bool:
        """Cold-start gate condiviso da jitter e micro: refs pronte, fuori warmup,
        nessuna finestra outcome gia' aperta."""
        return (self.diagnostic_engine is not None
                and self.diagnostic_engine.refs_ready
                and self._warmup_frames_left <= 0
                and self._outcome_pending is None)

    def _evaluate_engine_actions(self, snapshot: AnalysisSnapshot) -> list[ControlAction]:
        """jitter: traduce la proposta corrente in mosse a [limits] pieni + cooldown.
        DRIFT/UNCERTAIN/None -> nessuna azione."""
        actions: list[ControlAction] = []
        diag = self._current_diag
        de = self.cfg.diagnostic_engine
        if diag is None or diag.proposal is None or diag.proposal.is_noop():
            return actions
        if not self._engine_action_gate_open():
            return actions
        if diag.confidence < de.act_min_confidence:
            return actions

        now = time.monotonic()
        cooldown = self.cfg.control.cooldown_seconds
        reason = f"[JITTER {diag.state.name}] conf={diag.confidence}"
        all_changes: list[dict] = []
        for axis_state, limits in ((self._ra, self.cfg.ra), (self._dec, self.cfg.dec)):
            if now - self._diag_last_action[axis_state.axis] < cooldown:
                continue
            changes, axis_actions = self._apply_proposal(axis_state, limits,
                                                         diag.proposal, 1.0, reason)
            if axis_actions:
                self._diag_last_action[axis_state.axis] = now
                all_changes.extend(changes)
                actions.extend(axis_actions)
        if all_changes:
            self._open_outcome(snapshot, "action", "engine", lever_changes=all_changes)
        return actions

    def _guardian_micro_correction(self, axis_state: AxisState, limits: AxisLimits,
                                   snapshot: AnalysisSnapshot) -> list[ControlAction]:
        """guardian: micro-correzione propria (ampiezza × guardian_action_factor) SOLO
        dove la v2.3 e' ferma in questo tick e la diagnosi e' confidente SEEING/
        OVERCORRECTION. DRIFT/NOMINAL/UNCERTAIN -> nessuna proposta dal motore."""
        actions: list[ControlAction] = []
        de = self.cfg.diagnostic_engine
        if not self._engine_action_gate_open():
            return actions
        proposal = self.diagnostic_engine.micro_proposal()
        if proposal is None:
            return actions
        now = time.monotonic()
        if now - self._diag_last_action[axis_state.axis] < self.cfg.control.cooldown_seconds:
            return actions
        reason = f"[GUARDIAN micro] {self._current_diag.state.name}"
        changes, axis_actions = self._apply_proposal(axis_state, limits, proposal,
                                                     de.guardian_action_factor, reason)
        if axis_actions:
            self._diag_last_action[axis_state.axis] = now
            self.diagnostic_engine.note_micro_applied()
            self._open_outcome(snapshot, "action", "micro", lever_changes=changes)
            actions.extend(axis_actions)
        return actions

    # ----- Outcome logging azione->esito (pre/post) ----------------------- #

    @staticmethod
    def _outcome_metrics(snap: AnalysisSnapshot) -> dict:
        return {"rms_total": snap.rms_total, "jitter": snap.jitter_rms,
                "spike_score": snap.spike_score}

    @staticmethod
    def _mean_metrics(buf: list[dict]) -> dict:
        keys = ("rms_total", "jitter", "spike_score")
        if not buf:
            return {k: 0.0 for k in keys}
        n = len(buf)
        return {k: sum(d[k] for d in buf) / n for k in keys}

    def _open_outcome(self, snapshot: Optional[AnalysisSnapshot], event: str,
                      action_kind: str, lever_changes: list[dict],
                      v23_proposed: Optional[dict] = None) -> None:
        """Apre una finestra outcome catturando tutto il contesto di decisione
        (schema v2.5-ready). No-op se ne esiste gia' una aperta o manca lo snapshot."""
        if self._outcome_pending is not None or snapshot is None:
            return
        diag = self._current_diag
        de = self.cfg.diagnostic_engine
        ebools = ({"jitter_high": diag.jitter_high, "hfd_high": diag.hfd_high,
                   "oscillation": diag.oscillation, "drift": diag.drift}
                  if diag is not None else
                  {"jitter_high": False, "hfd_high": False,
                   "oscillation": False, "drift": False})
        hfd_ref = diag.metrics.get("hfd_ref", 0.0) if diag is not None else 0.0
        jitter_ref = diag.metrics.get("jitter_ref", 0.0) if diag is not None else 0.0
        self._outcome_pending = {
            "ts_utc": _utc_now_iso(),
            "mode": de.mode,
            "event": event,
            "action_kind": action_kind,
            "diagnosis": {
                "state": diag.state.name if diag is not None else "INSUFFICIENT_DATA",
                "confidence": diag.confidence if diag is not None else 0,
                "evidence_bools": ebools,
            },
            "metrics_at_decision": {
                "rms_total": round(snapshot.rms_total, 4),
                "rms_ra": round(snapshot.rms_ra, 4),
                "rms_dec": round(snapshot.rms_dec, 4),
                "hfd": round(snapshot.hfd_avg, 3),
                "hfd_ref": hfd_ref,
                "jitter": round(snapshot.jitter_rms, 4),
                "jitter_ref": jitter_ref,
                "lag1_ra": round(snapshot.lag1_ra, 3),
                "lag1_dec": round(snapshot.lag1_dec, 3),
                "trend_ra": round(snapshot.trend_ra, 4),
                "trend_dec": round(snapshot.trend_dec, 4),
                "spike_score": round(snapshot.spike_score, 4),
                "snr": round(snapshot.snr_avg, 2),
                "exposure_ms": int(snapshot.exposure_ms),
            },
            "thresholds_active": {
                "rms_high": round(self.cfg.thresholds.rms_high, 4),
                "rms_low": round(self.cfg.thresholds.rms_low, 4),
                "jitter_high_factor": de.jitter_high_factor,
                "hfd_high_factor": de.hfd_high_factor,
                "lag1_oscillation_thresh": de.lag1_oscillation_thresh,
                "trend_drift_min": de.trend_drift_min,
                "guardian_min_confidence": de.guardian_min_confidence,
                "act_min_confidence": de.act_min_confidence,
            },
            "lever_changes": lever_changes,
            "v23_proposed": v23_proposed,
            "pre": self._mean_metrics(self._diag_pre_buffer),
            "post": [],
            "post_max": {"rms_total": 0.0, "jitter": 0.0},
            "opened_monotonic": time.monotonic(),
        }

    def _track_outcome(self, snapshot: AnalysisSnapshot) -> None:
        """Progressione finestra outcome / accumulo media pre. Chiamato a ogni tick
        PRIMA delle azioni: una finestra aperta accumula i frame post; in assenza di
        finestra (e fuori warmup) il frame alimenta il buffer pre."""
        de = self.cfg.diagnostic_engine
        m = self._outcome_metrics(snapshot)
        pending = self._outcome_pending
        if pending is not None:
            pending["post"].append(m)
            pending["post_max"]["rms_total"] = max(pending["post_max"]["rms_total"], m["rms_total"])
            pending["post_max"]["jitter"] = max(pending["post_max"]["jitter"], m["jitter"])
            if len(pending["post"]) >= de.outcome_window_frames:
                self._finalize_outcome(pending)
                self._outcome_pending = None
            return
        if self._warmup_frames_left <= 0:
            self._diag_pre_buffer.append(m)
            if len(self._diag_pre_buffer) > de.outcome_window_frames:
                self._diag_pre_buffer.pop(0)

    def _finalize_outcome(self, pending: dict) -> None:
        """Chiude la finestra: calcola i delta pre->post, scrive il record nel jsonl
        experimental (via session_logger) e salva l'estratto per la dashboard."""
        post_mean = self._mean_metrics(pending["post"])
        pre = pending["pre"]
        keys = ("rms_total", "jitter", "spike_score")
        delta = {k: round(post_mean[k] - pre[k], 4) for k in keys}
        elapsed = time.monotonic() - pending["opened_monotonic"]
        record = {
            "schema_version": 1,
            "ts_utc": pending["ts_utc"],
            "mode": pending["mode"],
            "event": pending["event"],
            "action_kind": pending["action_kind"],
            "diagnosis": pending["diagnosis"],
            "metrics_at_decision": pending["metrics_at_decision"],
            "thresholds_active": pending["thresholds_active"],
            "lever_changes": pending["lever_changes"],
            "v23_proposed": pending["v23_proposed"],
            "outcome": {
                "window_frames": self.cfg.diagnostic_engine.outcome_window_frames,
                "elapsed_s": round(elapsed, 1),
                "pre": {k: round(pre[k], 4) for k in keys},
                "post": {k: round(post_mean[k], 4) for k in keys},
                "post_max": {k: round(v, 4) for k, v in pending["post_max"].items()},
                "delta": delta,
            },
        }
        if self.session_logger is not None:
            try:
                self.session_logger.log_experimental(record)
            except Exception as e:
                logger.warning("Impossibile loggare experimental outcome: %s", e)
        self._last_outcome = {
            "event": pending["event"],
            "action_kind": pending["action_kind"],
            "state": pending["diagnosis"].get("state"),
            "lever_changes": pending["lever_changes"],
            "v23_proposed": pending["v23_proposed"],
            "delta": delta,
            "ts_utc": pending["ts_utc"],
        }

    # ----- Modalita': transizione pulita ---------------------------------- #

    def set_diagnostic_mode(self, target: str) -> dict:
        """Switcher dashboard. "off" = kill switch (sempre permesso) -> v2.3 pura.
        "jitter"/"guardian" = attivazione/cambio, permessi solo se
        allow_dashboard_mode_switch. Ogni cambio passa per la transizione pulita."""
        target = (target or "").strip().lower()
        de = self.cfg.diagnostic_engine

        if target == "off":
            de.enabled = False
            logger.info("[diagnostic_engine] OFF (kill switch) -> v2.3 pura")
            self._apply_mode_transition()
            return {"mode": "off"}

        if target not in ("jitter", "guardian"):
            logger.warning("[diagnostic_engine] target modalita' '%s' ignoto", target)
            return {"mode": de.mode if de.enabled else "off", "error": "unknown_mode"}

        # §54 — guard-rail JITTER (difesa in profondità, oltre alla UI): senza
        # allow_experimental_jitter la richiesta viene coerciata a GUARDIAN con WARNING
        # prominente; si ritorna la modalità EFFETTIVA così la UI riflette la realtà.
        if target == "jitter" and not getattr(de, "allow_experimental_jitter", False):
            logger.warning(
                "[diagnostic_engine] modalità JITTER DEPRECATA e non validata — scavalca "
                "§44/§50/§51/§53; ignorata, uso GUARDIAN. Per esercitarla deliberatamente "
                "impostare [diagnostic_engine] allow_experimental_jitter=true.")
            target = "guardian"

        if not de.allow_dashboard_mode_switch:
            logger.warning(
                "[diagnostic_engine] attivazione '%s' rifiutata: "
                "allow_dashboard_mode_switch=false", target,
            )
            return {"mode": de.mode if de.enabled else "off", "error": "not_allowed"}

        de.enabled = True
        de.mode = target
        if self.diagnostic_engine is None:
            self.diagnostic_engine = self._make_diagnostic_engine()
        logger.info("[diagnostic_engine] modalita' -> %s", target)
        self._apply_mode_transition()
        return {"mode": target}

    def _apply_mode_transition(self) -> None:
        """Transizione pulita tra modalita': leve->baseline, reset analyzer/engine,
        warmup, finestre outcome svuotate."""
        self._restore_levers_to_baseline()
        if self.analyzer is not None:
            self.analyzer.reset()
        if self.diagnostic_engine is not None:
            self.diagnostic_engine.reset("mode_transition")  # §39: non cambia regime -> preserva refs
        self._warmup_frames_left = self.cfg.diagnostic_engine.warmup_frames_after_switch
        self._outcome_pending = None
        self._diag_pre_buffer = []
        self._diag_last_action = {"ra": 0.0, "dec": 0.0}
        logger.info(
            "[diagnostic_engine] transizione pulita: leve->baseline, reset "
            "analyzer/engine, warmup=%d frame", self._warmup_frames_left,
        )

    def _restore_levers_to_baseline(self) -> None:
        """Rilegge aggr/MinMove dalla baseline salvata e li riapplica via _apply,
        riallineando current_*. Se la baseline e' assente/illeggibile: WARNING e prosegue."""
        if not self.baseline_path.exists():
            logger.warning("[diagnostic_engine] baseline assente: skip ripristino leve")
            return
        try:
            baseline = json.loads(self.baseline_path.read_text())
        except Exception as e:
            logger.warning("[diagnostic_engine] baseline illeggibile (%s): skip", e)
            return
        for axis_state, limits, key in ((self._ra, self.cfg.ra, "ra"),
                                        (self._dec, self.cfg.dec, "dec")):
            data = baseline.get(key, {})
            if data.get("aggr_param") and axis_state.aggr_param:
                old, new = axis_state.current_aggr, float(data["current_aggr"])
                if abs(new - old) > 1e-9:
                    self._apply(axis_state, limits, axis_state.aggr_param, old, new,
                                "[mode transition] ripristino Aggressivita baseline")
                axis_state.current_aggr = new
            if data.get("minmove_param") and axis_state.minmove_param:
                old, new = axis_state.current_minmove, float(data["current_minmove"])
                if abs(new - old) > 1e-9:
                    self._apply(axis_state, limits, axis_state.minmove_param, old, new,
                                "[mode transition] ripristino MinMove baseline",
                                is_minmove=True)
                axis_state.current_minmove = new

    # ------------------------------------------------------------------ #
    #  Emergency Routines                                                 #
    # ------------------------------------------------------------------ #

    def _evaluate_exposure(self, snapshot: AnalysisSnapshot) -> list[ControlAction]:
        actions: list[ControlAction] = []
        if self.base_exposure_ms is None or self.base_exposure_ms <= 0:
            return actions

        # Path A: LOW_SNR (priorità più alta)
        actions.extend(self._evaluate_exposure_snr(snapshot))

        # Path B: seeing degradato RMS-based (solo se path A non attivo)
        if self.exposure_state != ExposureState.BOOSTED_FOR_SNR:
            actions.extend(self._evaluate_exposure_seeing(snapshot))

        return actions

    def _evaluate_exposure_snr(self, snapshot: AnalysisSnapshot) -> list[ControlAction]:
        """Path A — gestione LOW_SNR (refattorizzazione logica preesistente)."""
        actions: list[ControlAction] = []

        if (snapshot.condition == SeeingCondition.LOW_SNR
                and self.exposure_state == ExposureState.NOMINAL):
            new_exp = self._snap_exposure(self.base_exposure_ms * 2)
            cur = self.current_exposure_ms or self.base_exposure_ms
            if new_exp > cur:
                reason = (
                    f"SNR basso ({snapshot.snr_avg:.1f} < "
                    f"{self.cfg.thresholds.snr_low}) - aumento esposizione. "
                    f"NOTA: i primi frame post-cambio possono mostrare transitorio "
                    f"nell'algoritmo di guida (stato interno non svuotato senza "
                    f"GuidingPaused/Resumed)."
                )
                action = self._apply_exposure(cur, new_exp, reason,
                                              param="exposure_snr")
                if not action.dry_run:
                    self.exposure_state = ExposureState.BOOSTED_FOR_SNR
                    self.current_exposure_ms = new_exp
                    self.last_exposure_action_time = time.monotonic()
                    if self.analyzer is not None:
                        self.analyzer.reset()
                    if self.diagnostic_engine is not None:
                        self.diagnostic_engine.reset("exposure_change")  # §39: il jitter scala col tempo di posa -> azzera
                actions.append(action)

        elif (snapshot.condition != SeeingCondition.LOW_SNR
              and self.exposure_state == ExposureState.BOOSTED_FOR_SNR):
            cur = self.current_exposure_ms or self.base_exposure_ms
            reason = (
                f"SNR ristabilito ({snapshot.snr_avg:.1f}) - "
                f"ripristino esposizione base. "
                f"NOTA: i primi frame post-cambio possono mostrare transitorio "
                f"nell'algoritmo di guida."
            )
            action = self._apply_exposure(cur, self.base_exposure_ms, reason,
                                          param="exposure_snr")
            if not action.dry_run:
                self.exposure_state = ExposureState.NOMINAL
                self.current_exposure_ms = self.base_exposure_ms
                self.last_exposure_action_time = time.monotonic()
                if self.analyzer is not None:
                    self.analyzer.reset()
                if self.diagnostic_engine is not None:
                    self.diagnostic_engine.reset("exposure_change")  # §39: il jitter scala col tempo di posa -> azzera
            actions.append(action)

        return actions

    def _evaluate_exposure_seeing(self, snapshot: AnalysisSnapshot) -> list[ControlAction]:
        """Path B — esposizione dinamica RMS-based (nuova feature)."""
        actions: list[ControlAction] = []
        ed = self.cfg.exposure_dynamic

        if not ed.enabled:
            return actions

        # Auto Exposure guard: se la base non è nella lista valida, path B disabilitato
        if (self._valid_exposures
                and self.base_exposure_ms not in self._valid_exposures):
            return actions

        now = time.monotonic()
        cur = self.current_exposure_ms or self.base_exposure_ms

        # ---- Trigger UP: NOMINAL → BOOSTED_FOR_SEEING ----
        if self.exposure_state == ExposureState.NOMINAL:
            up_ok = (
                snapshot.condition == SeeingCondition.DEGRADED_SEEING
                and snapshot.condition != SeeingCondition.OSCILLATING   # ridondante, esplicito
                and snapshot.condition != SeeingCondition.LOW_SNR        # delegato path A
                and not snapshot.implosion_suspended
                and snapshot.consecutive_high >= self.cfg.thresholds.consecutive_frames
                and snapshot.spike_score >= ed.spike_min
                and snapshot.hfd_avg * self.cfg.setup.guide_pixel_scale_arcsec >= ed.hfd_min_arcsec
                and (
                    (snapshot.peak_ra / max(snapshot.rms_ra, 0.01)) >= ed.peak_to_rms_ratio_min
                    or (snapshot.peak_dec / max(snapshot.rms_dec, 0.01)) >= ed.peak_to_rms_ratio_min
                )
                and self.exposure_steps_above_base < ed.max_steps_above_base
                and (now - self.last_exposure_action_time) >= ed.cooldown_s
            )

            # Escalation gate: almeno un asse con leve cheap saturate
            if up_ok:
                up_ok = (
                    self._axis_levers_saturated(self._ra, self.cfg.ra)
                    or self._axis_levers_saturated(self._dec, self.cfg.dec)
                )

            if up_ok:
                new_exp = self._snap_exposure(int(cur * ed.step_factor))
                if new_exp > cur:
                    reason = (
                        f"DEGRADED_SEEING: RMS={snapshot.rms_total:.2f}\" "
                        f"spike={snapshot.spike_score:.0%} "
                        f"HFD={snapshot.hfd_avg:.1f}px "
                        f"peak/rms_RA={snapshot.peak_ra / max(snapshot.rms_ra, 0.01):.1f} "
                        f"peak/rms_DEC={snapshot.peak_dec / max(snapshot.rms_dec, 0.01):.1f} "
                        f"— aumento esposizione {cur}→{new_exp}ms "
                        f"(step {self.exposure_steps_above_base + 1}/{ed.max_steps_above_base}). "
                        f"NOTA: i primi frame post-cambio possono mostrare transitorio "
                        f"nell'algoritmo di guida (stato interno non svuotato senza "
                        f"GuidingPaused/Resumed)."
                    )
                    action = self._apply_exposure(cur, new_exp, reason,
                                                  param="exposure_seeing")
                    if not action.dry_run:
                        self.exposure_state = ExposureState.BOOSTED_FOR_SEEING
                        self.exposure_steps_above_base += 1
                        self.current_exposure_ms = new_exp
                        self.last_exposure_action_time = now
                        if self.analyzer is not None:
                            self.analyzer.reset()
                        if self.diagnostic_engine is not None:
                            self.diagnostic_engine.reset("exposure_change")  # §39: il jitter scala col tempo di posa -> azzera
                        # §35 — programma il check saturazione/riselezione dopo un breve
                        # settle (il nuovo tempo deve diventare attivo prima del check).
                        if ed.restar_on_pathb_saturation:
                            self._pathb_restar_pending = True
                            self._pathb_restar_due = now + (
                                ed.pathb_restar_settle_frames * (new_exp / 1000.0))
                    actions.append(action)

        # ---- Trigger DOWN: BOOSTED_FOR_SEEING → riduzione graduale ----
        elif self.exposure_state == ExposureState.BOOSTED_FOR_SEEING:
            down_ok = (
                snapshot.condition == SeeingCondition.NOMINAL
                and snapshot.consecutive_low >= 2 * self.cfg.thresholds.consecutive_frames
                and self._nominal_since is not None
                and (now - self._nominal_since) >= ed.nominal_for_seconds
                and (now - self.last_exposure_action_time) >= ed.cooldown_s * 1.5
            )

            if down_ok:
                new_exp = self._snap_exposure(int(cur / ed.step_factor))
                new_exp = max(new_exp, self.base_exposure_ms)
                if new_exp < cur:
                    reason = (
                        f"Seeing recuperato: condizione NOMINAL da "
                        f"{(now - self._nominal_since):.0f}s, "
                        f"consecutive_low={snapshot.consecutive_low} — "
                        f"riduco esposizione {cur}→{new_exp}ms. "
                        f"NOTA: i primi frame post-cambio possono mostrare transitorio "
                        f"nell'algoritmo di guida."
                    )
                    action = self._apply_exposure(cur, new_exp, reason,
                                                  param="exposure_seeing")
                    if not action.dry_run:
                        self.exposure_steps_above_base -= 1
                        self.current_exposure_ms = new_exp
                        self.last_exposure_action_time = now
                        if self.exposure_steps_above_base <= 0:
                            self.exposure_state = ExposureState.NOMINAL
                            self.exposure_steps_above_base = 0
                        if self.analyzer is not None:
                            self.analyzer.reset()
                        if self.diagnostic_engine is not None:
                            self.diagnostic_engine.reset("exposure_change")  # §39: il jitter scala col tempo di posa -> azzera
                        # §35 — tornando a un'esposizione più bassa la stella non satura
                        # più: annulla l'eventuale check di riselezione in sospeso.
                        self._pathb_restar_pending = False
                    actions.append(action)

        return actions

    def _snap_exposure(self, target_ms: int) -> int:
        """Snap al valore valido più vicino ≤ max_exposure_ms."""
        if not self._valid_exposures:
            return target_ms
        cap = self.cfg.emergency.max_exposure_ms
        valid = [e for e in self._valid_exposures if e <= cap]
        if not valid:
            return target_ms
        return min(valid, key=lambda e: abs(e - target_ms))

    def _axis_levers_saturated(self, axis_state: AxisState,
                               limits: AxisLimits) -> bool:
        """True se le leve cheap (aggressiveness+MinMove) di un asse hanno saturato."""
        aggr_at_min = axis_state.current_aggr <= (limits.aggr_min + 1.0)
        mm_at_max = (axis_state.current_minmove
                     >= (limits.minmove_max - limits.minmove_step))
        elapsed_aggr = time.monotonic() - axis_state.last_action_time
        elapsed_mm = time.monotonic() - axis_state.last_minmove_action_time
        cooldown = self.cfg.control.cooldown_seconds
        return (aggr_at_min and mm_at_max
                and elapsed_aggr >= cooldown
                and elapsed_mm >= cooldown * 1.5)

    def _evaluate_pathb_restar(self, snapshot: AnalysisSnapshot) -> list[ControlAction]:
        """§35 — riselezione stella dopo che Path B ha alzato l'esposizione. Se la
        stella corrente SATURA al nuovo tempo, riseleziona proattivamente la migliore
        stella NON satura (entro pochi secondi, non i 300s del timer reattivo).
        Condizionale: agisce SOLO se la stella satura davvero (mai a ogni cambio
        esposizione). Anti-flapping via cooldown; il timer 300s resta come rete per
        gli altri casi. Riusa find_best_star + la logica is_saturated esistenti."""
        ed = self.cfg.exposure_dynamic
        actions: list[ControlAction] = []
        if not ed.restar_on_pathb_saturation or not self._pathb_restar_pending:
            return actions
        now = time.monotonic()
        if now < self._pathb_restar_due:
            return actions   # settle del nuovo tempo ancora in corso
        self._pathb_restar_pending = False
        # Anti-flapping: non riselezionare troppo spesso (evita oscillazioni su/giù).
        if now - self._pathb_restar_last_time < ed.pathb_restar_cooldown_s:
            return actions
        # PHD2 deve essere in guida valida per riselezionare.
        if self.guiding_state in (GuidingState.STAR_LOST, GuidingState.INACTIVE):
            return actions

        action = ControlAction(
            timestamp=time.time(), axis="camera", param="pathb_restar",
            old_value=1.0, new_value=0.0,
            reason="Path B: verifica saturazione stella al nuovo tempo esposizione",
            dry_run=self.dry_run,
        )
        if self.dry_run:
            logger.info("[TEST] %s", action)
            actions.append(action)
            return actions

        try:
            from phd2_agent.star_finder import find_best_star
            filepath = self.client.save_image()
            if not (filepath and os.path.exists(filepath)):
                return actions
            cx, cy, info = find_best_star(filepath)
            if not info.get("is_saturated"):
                # B.2.2 — la stella NON satura al nuovo tempo: nessuna riselezione.
                return actions
            # Riseleziona la migliore stella NON satura (trade-off saturazione vs SNR).
            ncx, ncy, ninfo = find_best_star(filepath, prefer_unsaturated=True)
            if ncx is not None and ncy is not None:
                self.client.set_lock_position(ncx, ncy)
                self._pathb_restar_last_time = now
                self.saturated_lock_since = None      # nuova stella pulita
                self.last_saturation_info = None
                action.new_value = 1.0
                action.reason = (
                    f"Path B: stella satura al nuovo tempo "
                    f"(peak={info.get('peak_adu', 0)} ADU) -> riselezionata stella non "
                    f"satura a ({ncx:.1f},{ncy:.1f}) peak={ninfo.get('peak_adu', 0)} ADU"
                )
                logger.info("[LIVE] %s", action)
            else:
                # Nessuna alternativa non satura: lascia la rete del timer 300s.
                self.saturated_lock_since = now
                self.last_saturation_info = {**info, "cx": cx, "cy": cy,
                                             "started_at": time.time()}
                action.reason = (
                    f"Path B: stella satura (peak={info.get('peak_adu', 0)} ADU) ma "
                    f"nessuna stella non satura disponibile -> rete timer 300s"
                )
                logger.warning("[LIVE] %s", action)
            actions.append(action)
        except Exception as e:
            logger.error("Errore riselezione stella Path B (§35): %s", e)
        return actions

    def _evaluate_saturation_timer(self) -> list[ControlAction]:
        """
        Se il Path B ha agganciato una stella satura, dopo X secondi
        (configurabile, default 300) tenta un re-scan via find_star() standard
        per vedere se le condizioni sono migliorate (velatura passata).
        """
        actions: list[ControlAction] = []
        if self.saturated_lock_since is None:
            return actions

        now = time.monotonic()
        timeout = getattr(self.cfg.emergency, "saturation_timeout_s", 300)
        elapsed = now - self.saturated_lock_since

        if elapsed < timeout:
            return actions

        peak_adu = (self.last_saturation_info.get("peak_adu", 0)
                    if self.last_saturation_info else 0)
        reason = (
            f"Stella satura tracciata da {elapsed:.0f}s "
            f"(peak={peak_adu} ADU) - forzo re-scan find_star standard"
        )
        action = ControlAction(
            timestamp=time.time(), axis="camera", param="forced_rescan",
            old_value=1.0, new_value=0.0, reason=reason, dry_run=self.dry_run,
        )

        if self.dry_run:
            logger.info("[TEST] %s", action)
        else:
            try:
                self.client.find_star()
                logger.info("[LIVE] %s", action)
                # Logga il periodo satura nel CSV per post-mortem
                self._log_saturation_period_close(now)
                self.saturated_lock_since = None
                self.last_saturation_info = None
            except Exception as e:
                logger.error("Errore forced_rescan find_star: %s", e)
                action.dry_run = True

        actions.append(action)
        return actions

    def _evaluate_star_lost(self) -> list[ControlAction]:
        actions: list[ControlAction] = []
        now = time.monotonic()

        if self.star_lost_since is None:
            self.star_lost_since = now
            return actions

        elapsed = now - self.star_lost_since
        if elapsed < self.cfg.emergency.find_star_delay:
            return actions

        # §75 — percorso UNICO di riselezione: `find_star()` di PHD2, con il
        # backoff a tre livelli del §17 (nato dall'incidente delle 130+ chiamate
        # in 6 minuti su camera crashata via USB). Il vecchio ramo "AI Star
        # Finder" e' stato rimosso: era spento di default, il suo unico valore
        # differenziale (rilevare la saturazione) e' oggi coperto per via NATIVA
        # dal §68 (ErrorCode = STAR_SATURATED, ogni 3 s, senza salvare un FITS)
        # e soprattutto SCAVALCAVA questo backoff — acceso su una camera in
        # crisi avrebbe caricato proprio il bus che stava soffocando.
        # La selezione della stella di guida e' competenza di PHD2: l'Agente
        # misura, interpreta e decide, non duplica algoritmi nativi meglio
        # informati. `star_finder.py` RESTA: lo usa il Path B (riselezione di
        # stelle sature), che e' un sottosistema vivo e diverso da questo.
        failures = self._find_star_failures
        since_last = now - self._find_star_last_attempt

        if failures >= _FIND_STAR_SUSP_THRESHOLD:
            if since_last >= _FIND_STAR_SUSP_INTERVAL:
                logger.warning(
                    "find_star SUSPENDED dopo %d fallimenti consecutivi — "
                    "verificare connessione USB camera.",
                    failures,
                )
                self._find_star_last_attempt = now
            return actions

        if failures >= _FIND_STAR_SLOW_THRESHOLD and since_last < _FIND_STAR_SLOW_INTERVAL:
            return actions

        reason = (
            f"Stella persa consecutivamente per {elapsed:.1f}s - "
            f"Auto-selezione nuova stella"
        )
        action = ControlAction(
            timestamp=time.time(), axis="camera", param="find_star",
            old_value=0.0, new_value=1.0, reason=reason, dry_run=self.dry_run,
        )
        self._find_star_last_attempt = now
        if self.dry_run:
            logger.info("[TEST] %s", action)
        else:
            try:
                self.client.find_star()
                logger.info("[LIVE] %s", action)
                self.star_lost_since = now
                self._find_star_failures = 0
            except Exception as e:
                self._find_star_failures += 1
                logger.error(
                    "Errore find_star (tentativo %d): %s",
                    self._find_star_failures, e,
                )
                action.dry_run = True

        actions.append(action)
        return actions

    # ------------------------------------------------------------------ #
    #  Logging persistente periodi satura (per post-mortem PixInsight)    #
    # ------------------------------------------------------------------ #

    def _log_saturation_period_close(self, end_ts_monotonic: float) -> None:
        """Quando il timer satura si chiude, scrive una riga nel CSV."""
        if self.last_saturation_info is None:
            return
        try:
            self._saturation_csv_dir.mkdir(parents=True, exist_ok=True)
            csv_path = (self._saturation_csv_dir
                        / f"saturated_periods_{date.today():%Y%m%d}.csv")
            is_new = not csv_path.exists()
            duration_s = end_ts_monotonic - (self.saturated_lock_since or end_ts_monotonic)
            with open(csv_path, "a", newline="") as f:
                w = csv.writer(f)
                if is_new:
                    w.writerow([
                        "start_time_unix", "end_time_unix",
                        "star_x", "star_y", "peak_adu", "blob_size_px",
                        "duration_s",
                    ])
                w.writerow([
                    self.last_saturation_info.get("started_at", time.time()),
                    time.time(),
                    self.last_saturation_info.get("cx", 0),
                    self.last_saturation_info.get("cy", 0),
                    self.last_saturation_info.get("peak_adu", 0),
                    self.last_saturation_info.get("blob_size_px", 0),
                    round(duration_s, 1),
                ])
        except Exception as e:
            logger.warning("Impossibile loggare periodo satura: %s", e)

    # ------------------------------------------------------------------ #
    #  Applicazione modifiche                                             #
    # ------------------------------------------------------------------ #

    def _apply(
        self,
        axis_state: AxisState,
        limits: AxisLimits,
        param_name: str,
        old_value: float,
        new_value: float,
        reason: str,
        is_minmove: bool = False,
        softening_source: str = "other",
    ) -> ControlAction:
        """Invia (o simula) la modifica a PHD2."""
        # §47 — MinMove efficace in arcsec (px × pixel-scale viva) per l'attribuzione.
        mm_arcsec = (round(new_value * self.cfg.setup.guide_pixel_scale_arcsec, 3)
                     if is_minmove else None)
        action = ControlAction(
            timestamp=time.time(),
            axis=axis_state.axis,
            param=param_name,
            old_value=old_value,
            new_value=new_value,
            reason=reason,
            dry_run=self.dry_run,
            softening_source=softening_source,
            minmove_arcsec=mm_arcsec,
        )
        # §47 — breakdown sorgenti softening della sessione.
        self._softening_source_counts[softening_source] = (
            self._softening_source_counts.get(softening_source, 0) + 1)

        if self.dry_run:
            logger.info("[TEST] %s", action)
        else:
            try:
                val_to_send = new_value
                if not is_minmove:
                    native_scale = axis_state.aggr_native_scale
                    if native_scale < 1.0:
                        # Hysteresis / ResistSwitch: parametro PHD2 in scala 0-1
                        val_to_send = round(new_value * native_scale, 4)
                    else:
                        # Lowpass2 e altri: parametro PHD2 in scala 0-100, inviare int
                        val_to_send = int(round(new_value))
                else:
                    val_to_send = round(new_value, 3)
                    
                self.client.set_algo_param(axis_state.axis, param_name, val_to_send)
                logger.info("[LIVE] %s", action)
                if is_minmove:
                    axis_state.last_minmove_action_time = time.monotonic()
                else:
                    axis_state.last_action_time = time.monotonic()
                axis_state.last_action_desc = reason
            except PHD2RPCError as e:
                logger.error(
                    "Errore set_algo_param %s/%s: %s",
                    axis_state.axis, param_name, e,
                )
                action.dry_run = True

        return action

    def _apply_exposure(self, old_value: int, new_value: int,
                        reason: str, param: str = "exposure") -> ControlAction:
        action = ControlAction(
            timestamp=time.time(),
            axis="camera",
            param=param,
            old_value=float(old_value),
            new_value=float(new_value),
            reason=reason,
            dry_run=self.dry_run,
        )

        if self.dry_run:
            logger.info("[TEST] %s", action)
        else:
            try:
                self.client.set_exposure(new_value)
                logger.info("[LIVE] %s", action)
            except PHD2RPCError as e:
                logger.error("Errore set_exposure %d: %s", new_value, e)
                action.dry_run = True

        return action

    # ------------------------------------------------------------------ #
    #  Stato pubblico                                                     #
    # ------------------------------------------------------------------ #

    def get_status(self) -> dict:
        """Snapshot dello stato del controller per la dashboard."""
        sat_active = self.saturated_lock_since is not None
        sat_elapsed = 0.0
        if sat_active:
            sat_elapsed = time.monotonic() - self.saturated_lock_since

        last_action = self.action_history[-1] if self.action_history else None
        return {
            "guiding_state": self.guiding_state.name,
            "dry_run": self.dry_run,
            # §63 — ciclo del motore per la dashboard: distingue "in raccolta dati"
            # (eval_count=0), "valuta e non interviene" (eval>0, 0 azioni) e
            # "ultimo intervento" (azioni presenti).
            "engine": {
                "eval_count": self.eval_count,
                "last_eval_ts": self.last_eval_ts,
                "actions_total": len(self.action_history),
                "last_action_ts": last_action.timestamp if last_action else None,
                "last_action": (f"{last_action.axis.upper()} {last_action.param} "
                                f"{last_action.old_value:g}→{last_action.new_value:g}")
                               if last_action else None,
            },
            "ra": {
                "current_aggr": self._ra.current_aggr,
                "current_minmove": self._ra.current_minmove,
                "aggr_param": self._ra.aggr_param,
                "minmove_param": self._ra.minmove_param,
                "available_params": self._ra.param_names,
            },
            "dec": {
                "current_aggr": self._dec.current_aggr,
                "current_minmove": self._dec.current_minmove,
                "aggr_param": self._dec.aggr_param,
                "minmove_param": self._dec.minmove_param,
                "available_params": self._dec.param_names,
            },
            "saturation": {
                "active": sat_active,
                "elapsed_s": round(sat_elapsed, 1),
                "info": self.last_saturation_info or {},
            },
            "exposure": {
                "state": self.exposure_state.name,
                "current_ms": self.current_exposure_ms,
                "base_ms": self.base_exposure_ms,
                "steps_above_base": self.exposure_steps_above_base,
                "cooldown_total_s": self.cfg.exposure_dynamic.cooldown_s,
                "cooldown_residuo_s": round(max(
                    0.0,
                    self.cfg.exposure_dynamic.cooldown_s
                    - (time.monotonic() - self.last_exposure_action_time)
                ), 1),
            },
            "escalation_gate": {
                "enabled": self.cfg.exposure_dynamic.enabled,
                "ra": self._axis_levers_saturated(self._ra, self.cfg.ra),
                "dec": self._axis_levers_saturated(self._dec, self.cfg.dec),
            },
            "auto_calibration": {
                "enabled": self.cfg.auto_calibration.enabled,
                "pixel_scale_arcsec": round(self.cfg.setup.guide_pixel_scale_arcsec, 3),
                "pixel_scale_source": (
                    "phd2" if self.cfg.setup.pixel_scale_override is not None else "toml"
                ),
                "baseline_rms_arcsec": (
                    round(self._rms_baseline_value, 3)
                    if self._rms_baseline_value is not None else None
                ),
                "baseline_done": self._rms_baseline_done,
                "baseline_rejected": self._rms_baseline_rejected,
                "baseline_progress": (
                    f"{len(self._rms_baseline_samples)}/"
                    f"{self.cfg.auto_calibration.baseline_window_frames}"
                ),
                "rms_high_active": round(self.cfg.thresholds.rms_high, 3),
                "rms_low_active": round(self.cfg.thresholds.rms_low, 3),
                "rms_high_cap_arcsec": (
                    round(self._rms_high_cap_value, 3)
                    if self._rms_high_cap_value is not None else None
                ),
                "rms_high_cap_active": self._rms_high_cap_active,
                # §44 — baseline a rinnovo continuo/bidirezionale (vs legacy §25)
                "track_bidirectional": self.cfg.auto_calibration.baseline_track_bidirectional,
                # §25 — refresh ciclico baseline (tightest-wins, modalità legacy)
                "refresh_enabled": self.cfg.auto_calibration.refresh_enabled,
                "refresh_interval_seconds": self.cfg.auto_calibration.refresh_interval_seconds,
                "refresh_in_progress": self._baseline_refresh_in_progress,
                "refresh_progress": (
                    f"{len(self._rms_baseline_samples)}/"
                    f"{self.cfg.auto_calibration.baseline_window_frames}"
                    if self._baseline_refresh_in_progress else None
                ),
                "refresh_seconds_to_next": (
                    round(max(0.0, self.cfg.auto_calibration.refresh_interval_seconds
                              - (time.monotonic() - self._baseline_finalize_time)), 1)
                    if (self._baseline_finalize_time is not None
                        and not self._baseline_refresh_in_progress
                        and self.cfg.auto_calibration.refresh_enabled) else None
                ),
                "last_refresh_action": self._last_refresh_action,
                "last_refresh_baseline_arcsec": (
                    round(self._last_refresh_baseline, 3)
                    if self._last_refresh_baseline is not None else None
                ),
            },
            # §30 — Satisfaction gate (la dashboard confronta a vista RMS vs target)
            "lever_optimization": {
                "enabled": self.cfg.lever_optimization.enabled,
                "target_factor": self.cfg.lever_optimization.target_factor,
                "target_median_arcsec": (
                    round(self._rms_baseline_value * self.cfg.lever_optimization.target_factor, 3)
                    if self._rms_baseline_value is not None and not self._rms_baseline_rejected
                    else None
                ),
            },
            # §31 — Seeing Diagnostic Engine. A motore spento espone solo lo stato
            # minimo {enabled:false,...} (la dashboard mostra lo switcher su OFF).
            "diagnostic_engine": (
                {**self.diagnostic_engine.get_state(),
                 "allow_dashboard_mode_switch": self.cfg.diagnostic_engine.allow_dashboard_mode_switch,
                 "last_outcome": self._last_outcome}
                if self.diagnostic_engine is not None else
                {"enabled": False,
                 "mode": self.cfg.diagnostic_engine.mode,
                 "allow_dashboard_mode_switch": self.cfg.diagnostic_engine.allow_dashboard_mode_switch}
            ),
            # §51 — cap MinMove adattivo: MinMove efficace (arcsec) per asse, cap corrente
            # (arcsec/px) e termine vincente (guiding vs imaging). Aggiorna _minmove_cap_info.
            "minmove_cap": {
                "enabled": self.cfg.minmove_cap.enabled,
                "k": self.cfg.minmove_cap.baseline_factor,
                "imaging_ceiling_arcsec": self.cfg.minmove_cap.imaging_ceiling_arcsec,
                "filter_tau_minutes": self.cfg.minmove_cap.filter_tau_minutes,
                "cap_active": self._minmove_cap_px() is not None,
                # §0-bis — ACTIVE = il cap ha tagliato una richiesta MinMove-up (non "MinMove==cap").
                "clamping_active": time.monotonic() < self._minmove_clamp_active_until,
                "cap_arcsec": (self._minmove_cap_info or {}).get("cap_arcsec"),
                "cap_px": (self._minmove_cap_info or {}).get("cap_px"),
                "winning": (self._minmove_cap_info or {}).get("winning"),
                "baseline_filtered_arcsec": (self._minmove_cap_info or {}).get("baseline_filtered_arcsec"),
                "minmove_ra_arcsec": round(
                    self._ra.current_minmove * self.cfg.setup.guide_pixel_scale_arcsec, 3),
                "minmove_dec_arcsec": round(
                    self._dec.current_minmove * self.cfg.setup.guide_pixel_scale_arcsec, 3),
            },
            # §53 — recupero simmetrico guidato dall'esito (banda morta bidirezionale).
            "recovery": {
                "enabled": self.cfg.lever_optimization.symmetric_recovery_enabled,
                "state": ("IDLE" if self._recovery_consec == 0
                          else ("RECOVERING" if (self._recovery_direction == "stiffen"
                                                 and not self._recovery_stiffen_blocked)
                                else "HOLDING")),
                "direction": self._recovery_direction,
                "anchor_rms": (round(self._recovery_anchor_rms, 3)
                               if self._recovery_anchor_rms is not None else None),
                "consec": self._recovery_consec,
                "blocked": self._recovery_blocked,
                "stiffen_blocked": self._recovery_stiffen_blocked,
            },
            # §47 — esperimento outcome-first: stato ramo oscillazioni + breakdown
            # delle sorgenti di softening della sessione (per dashboard/attribuzione).
            "oscillation_experiment": {
                "branch_enabled": self.cfg.diagnostic_engine.oscillation_branch_enabled,
                "softening_sources": dict(self._softening_source_counts),
                "osc_would_fire": (self.diagnostic_engine.get_state().get("osc_would_fire", 0)
                                   if self.diagnostic_engine is not None else 0),
                "osc_would_fire_degraded": (
                    self.diagnostic_engine.get_state().get("osc_would_fire_degraded", 0)
                    if self.diagnostic_engine is not None else 0),
            },
            "last_actions": [a.to_dict() for a in self.action_history[-10:]],
        }

    def diagnostic_summary_context(self) -> dict:
        """Contesto costante di sessione per il summary.json (§31, formato v2.5-ready).
        Valutato a close() dal SessionLogger: snapshot dei fattori/soglie del motore +
        baseline e contatori, per ricostruire offline le decisioni."""
        from .__about__ import __version__
        de = self.cfg.diagnostic_engine
        eng_state = (self.diagnostic_engine.get_state()
                     if self.diagnostic_engine is not None else None)
        return {
            "schema_version": 3,   # §34: colonna `evaluated`; §36: misura in arcsec (px×scale)
            "agent_version": __version__,
            "setup_profile": self.cfg.setup.profile_name,
            "pixel_scale_arcsec": round(self.cfg.setup.guide_pixel_scale_arcsec, 3),
            "guide_algo_ra": {"aggr": self._ra.aggr_param, "minmove": self._ra.minmove_param},
            "guide_algo_dec": {"aggr": self._dec.aggr_param, "minmove": self._dec.minmove_param},
            "baseline_rms_median": (round(self._rms_baseline_value, 4)
                                    if self._rms_baseline_value is not None else None),
            "diagnostic_engine": {
                "enabled": de.enabled,
                "mode": de.mode,
                "min_frames": de.min_frames,
                "jitter_high_factor": de.jitter_high_factor,
                "hfd_high_factor": de.hfd_high_factor,
                "lag1_oscillation_thresh": de.lag1_oscillation_thresh,
                "trend_drift_min": de.trend_drift_min,
                "ema_alpha": de.ema_alpha,
                "act_min_confidence": de.act_min_confidence,
                "outcome_window_frames": de.outcome_window_frames,
                "warmup_frames_after_switch": de.warmup_frames_after_switch,
                "guardian_min_confidence": de.guardian_min_confidence,
                "guardian_attenuate_factor": de.guardian_attenuate_factor,
                "guardian_action_factor": de.guardian_action_factor,
                "state_counts": (eng_state["counts"] if eng_state else {}),
                "guardian_counts": (eng_state["guardian_counts"] if eng_state else {}),
            },
        }

    def set_dry_run(self, value: bool) -> None:
        self.dry_run = value
        logger.info("DRY_RUN impostato a %s", value)

    def is_initialized(self) -> bool:
        """Public accessor (sostituisce accesso a _initialized da fuori)."""
        return self._initialized

    def mark_uninitialized(self) -> None:
        """Resetta il flag inizializzazione (chiamato su GuidingStopped)."""
        self._initialized = False
