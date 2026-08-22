"""
logger.py — Logging strutturato per sessioni di guida PHD2

Produce due output:
  1. CSV rolling: una riga per evento GuideStep (per analisi offline)
  2. JSON-lines: ogni decisione del controller con motivazione completa
"""
from __future__ import annotations

import csv
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from .analyzer import AnalysisSnapshot
from .controller import ControlAction

logger = logging.getLogger(__name__)

_CSV_FIELDS = [
    "timestamp_iso",
    "ts",
    "rms_ra",
    "rms_dec",
    "rms_total",
    "peak_ra",
    "peak_dec",
    "snr_avg",
    "hfd_avg",
    "spike_score",
    "trend_ra",
    "trend_dec",
    "condition",
    "frame_count",
    "consecutive_high",
    "consecutive_low",
    # §31 — Seeing Diagnostic Engine. jitter_ref/hfd_ref + soglie attive permettono
    # di ricostruire offline jitter_high/hfd_high con QUALSIASI fattore candidato
    # (sweep di soglie senza ri-loggare).
    "exposure_ms",
    "jitter_rms",
    "jitter_n",
    "jitter_ref",
    "hfd_ref",
    "lag1_ra",
    "lag1_dec",
    "rms_high_active",
    "rms_low_active",
    "jitter_anchor",
    "rms_anchor",
    # §101 — la CHIAVE del modello di trasparenza. Senza, le colonne qui
    # sotto misurano qualcosa di cui non si sa a chi appartenga, e il replay
    # per (target, filtro) richiede di riallineare a mano il log di NINA.
    "target",
    "filter",
    "hfr_nina",
    "star_count",
    "airmass",
    # §100 — il fondo cielo misurato e il riferimento del tracker. Erano gia'
    # calcolati a ogni posa e buttati via: senza, un calo di stelle non si puo'
    # attribuire (velatura? Luna? fuoco?) se non per congettura.
    "bkg",
    "base_bkg",
    "base_stars",
    "base_stars_session_best",
    "ref_drift_pct",
    # §102 — stato del FUOCO. Una variazione di posizione NON significa
    # "autofocus": puo" essere l'offset del filtro, la compensazione
    # termica o un intervento manuale. Si registra il fatto, non la causa.
    "focuser_position",
    "focuser_temperature",
    "diag_state",
    "diag_confidence",
    # §45/§46 — Layer-2 NINA: indice di trasparenza + stato + penalità N8 applicata al
    # confidence del SEEING (per replay cap-on/off e validazione live).
    "transparency_index",
    "transparency_state",
    "nina_penalty",
    "evaluated",        # §34: True = frame valutato (tick), False = riga di solo log fuori-tick
    "reset_cause",      # §39: causa del reset del motore in questo frame (vuota se nessun reset)
    "actions_count",
    "actions_summary",
]


class SessionLogger:
    """
    Logger per una singola sessione di guida.
    Crea file CSV + JSONL nella directory configurata.
    """

    def __init__(self, csv_dir: str = "logs"):
        self.csv_dir = Path(csv_dir)
        self.csv_dir.mkdir(parents=True, exist_ok=True)

        self._session_start = datetime.now()
        self.session_id = self._session_start.strftime("%Y%m%d_%H%M%S")

        self._csv_path = self.csv_dir / f"session_{self.session_id}.csv"
        self._jsonl_path = self.csv_dir / f"decisions_{self.session_id}.jsonl"
        # §31 — un record per AZIONE/INTERVENTO del motore (stesso session_id del CSV:
        # join offline su ts_utc + finestra). File aperto pigro al primo record.
        self._experimental_path = self.csv_dir / f"experimental_{self.session_id}.jsonl"
        self._experimental_file = None

        self._csv_file = open(self._csv_path, "w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._csv_file, fieldnames=_CSV_FIELDS)
        self._writer.writeheader()

        self._jsonl_file = open(self._jsonl_path, "a", encoding="utf-8")

        # Riferimento duck-typed al controller per soglie attive, reference EMA del
        # motore e contesto del summary. Collegato da main.py (no import circolare).
        self.controller = None

        # Statistiche di sessione
        self._total_frames = 0
        self._total_actions = 0
        self._peak_rms_total = 0.0

        logger.info("Logger sessione aperto: %s", self._csv_path)

    def bind_controller(self, controller) -> None:
        """Collega il controller (per soglie attive, reference EMA, summary context)."""
        self.controller = controller

    def experimental_path(self) -> Path:
        """Percorso del file experimental_<session_id>.jsonl (§31)."""
        return self._experimental_path

    def log_experimental(self, record: dict) -> None:
        """Scrive un record azione->esito (§31) nel jsonl experimental. File aperto
        pigro: niente file vuoto se il motore non agisce mai."""
        try:
            if self._experimental_file is None:
                self._experimental_file = open(self._experimental_path, "a", encoding="utf-8")
            self._experimental_file.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._experimental_file.flush()
        except Exception as e:
            logger.error("Errore scrittura experimental jsonl: %s", e)

    def log_snapshot(
        self,
        snapshot: AnalysisSnapshot,
        actions: Optional[list[ControlAction]] = None,
    ) -> None:
        """Logga un AnalysisSnapshot sul CSV."""
        if actions is None:
            actions = []

        self._total_frames += 1
        self._peak_rms_total = max(self._peak_rms_total, snapshot.rms_total)

        actions_summary = " | ".join(
            f"{a.axis.upper()} {a.param} {a.old_value:.1f}→{a.new_value:.1f}"
            for a in actions
        ) if actions else ""

        # §31 — soglie attive (post auto-cal) e reference EMA del motore dal controller
        # collegato. Sempre presenti nel CSV (0.0 a motore spento) per lo sweep offline.
        ctrl = self.controller
        eng = getattr(ctrl, "diagnostic_engine", None) if ctrl is not None else None
        rms_high_active = round(ctrl.cfg.thresholds.rms_high, 4) if ctrl is not None else 0.0
        rms_low_active = round(ctrl.cfg.thresholds.rms_low, 4) if ctrl is not None else 0.0
        jitter_ref = round(eng.jitter_ref, 4) if eng is not None else 0.0
        hfd_ref = round(eng.hfd_ref, 3) if eng is not None else 0.0
        # §39 — causa del reset del motore (read-and-clear): compare sul primo frame
        # loggato dopo un reset, vuota altrove. Rende i replay futuri fedeli.
        reset_cause = eng.consume_reset_cause() if eng is not None else ""

        # §45/§46 — trasparenza NINA (Layer-2) + penalità N8. Vuoti se non disponibili.
        transparency_index = ""
        transparency_state = ""
        nina_penalty = 0
        # §100 — strumentazione: nessuna di queste colonne e' letta da una decisione.
        bkg = base_bkg = base_stars = base_stars_best = ref_drift_pct = None
        nina_target = nina_filter = ""      # §101 — contesto della riga
        focuser_position = focuser_temperature = None      # §102
        tracker = getattr(ctrl, "transparency_tracker", None) if ctrl is not None else None
        if tracker is not None:
            try:
                tb = tracker.status_block()
                if tb.get("index") is not None:
                    transparency_index = round(tb["index"], 3)
                transparency_state = tb.get("state") or ""
                bkg = tb.get("bkg")
                base_bkg = tb.get("base_bkg")
                base_stars = tb.get("base_stars")
                base_stars_best = tb.get("base_stars_session_best")
                ref_drift_pct = tb.get("ref_drift_pct")
                nina_target = tb.get("target") or ""       # §101
                nina_filter = tb.get("filter") or ""       # §101
                focuser_position = tb.get("focuser_position")        # §102
                focuser_temperature = tb.get("focuser_temperature")  # §102
            except Exception:
                pass
        if eng is not None and getattr(eng, "_last", None) is not None:
            nina_penalty = eng._last.metrics.get("nina_penalty", 0)

        row = {
            "timestamp_iso": datetime.fromtimestamp(snapshot.timestamp).isoformat(timespec="seconds"),
            "ts": round(snapshot.timestamp, 2),
            "rms_ra": round(snapshot.rms_ra, 4),
            "rms_dec": round(snapshot.rms_dec, 4),
            "rms_total": round(snapshot.rms_total, 4),
            "peak_ra": round(snapshot.peak_ra, 4),
            "peak_dec": round(snapshot.peak_dec, 4),
            "snr_avg": round(snapshot.snr_avg, 2),
            "hfd_avg": round(snapshot.hfd_avg, 2),
            "spike_score": round(snapshot.spike_score, 4),
            "trend_ra": round(snapshot.trend_ra, 6),
            "trend_dec": round(snapshot.trend_dec, 6),
            "condition": snapshot.condition.name,
            "frame_count": snapshot.frame_count,
            "consecutive_high": snapshot.consecutive_high,
            "consecutive_low": snapshot.consecutive_low,
            # §31 — Seeing Diagnostic Engine
            "exposure_ms": int(getattr(snapshot, "exposure_ms", 0)),
            "jitter_rms": round(snapshot.jitter_rms, 4),
            "jitter_n": snapshot.jitter_n,
            "jitter_ref": jitter_ref,
            "hfd_ref": hfd_ref,
            "lag1_ra": round(snapshot.lag1_ra, 3),
            "lag1_dec": round(snapshot.lag1_dec, 3),
            "rms_high_active": rms_high_active,
            "rms_low_active": rms_low_active,
            # §94 — misura in ombra: nessuna decisione legge queste colonne.
            "jitter_anchor": getattr(snapshot, "jitter_anchor", None),
            "rms_anchor": getattr(snapshot, "rms_anchor", None),
            "target": nina_target,                          # §101
            "filter": nina_filter,                          # §101
            "hfr_nina": getattr(snapshot, "hfr_nina", None),
            "star_count": getattr(snapshot, "star_count", None),
            "airmass": getattr(snapshot, "airmass", None),
            "bkg": bkg,                                     # §100
            "base_bkg": base_bkg,                           # §100
            "base_stars": base_stars,                       # §100
            "base_stars_session_best": base_stars_best,     # §100
            "ref_drift_pct": ref_drift_pct,                 # §100
            "focuser_position": focuser_position,           # §102
            "focuser_temperature": focuser_temperature,     # §102
            "diag_state": getattr(snapshot, "diag_state", "INSUFFICIENT_DATA"),
            "diag_confidence": int(getattr(snapshot, "diag_confidence", 0)),
            "transparency_index": transparency_index,   # §45
            "transparency_state": transparency_state,   # §45
            "nina_penalty": nina_penalty,               # §46
            "evaluated": bool(getattr(snapshot, "evaluated", False)),   # §34
            "reset_cause": reset_cause,   # §39
            "actions_count": len(actions),
            "actions_summary": actions_summary,
        }
        try:
            self._writer.writerow(row)
            self._csv_file.flush()
        except Exception as e:
            logger.error("Errore scrittura CSV: %s", e)

        # Log decisioni come JSONL
        for action in actions:
            self._log_decision(action)
            self._total_actions += 1

    def _log_decision(self, action: ControlAction) -> None:
        try:
            line = json.dumps(action.to_dict(), ensure_ascii=False)
            self._jsonl_file.write(line + "\n")
            self._jsonl_file.flush()
        except Exception as e:
            logger.error("Errore scrittura JSONL: %s", e)

    def close(self) -> dict:
        """Chiude i file e ritorna un dizionario con le statistiche di sessione."""
        duration_s = time.time() - self._session_start.timestamp()

        summary = {
            "schema_version": 9,   # §34 `evaluated`; §36 arcsec; §39 `reset_cause`; §45/§46 colonne trasparenza NINA + nina_penalty; §94 ancore in ombra + telemetria per-posa; §100 fondo cielo + riferimento del tracker; §101 target e filtro (chiave del modello); §102 stato del fuoco
            "session_start": self._session_start.isoformat(),
            "session_id": self.session_id,
            "duration_minutes": round(duration_s / 60, 1),
            "total_frames": self._total_frames,
            "total_actions": self._total_actions,
            "peak_rms_total_arcsec": round(self._peak_rms_total, 4),
            "csv_file": str(self._csv_path),
            "jsonl_file": str(self._jsonl_path),
            "experimental_file": str(self._experimental_path),
        }

        # §31 — header di sessione (contesto costante: versione, setup, fattori/soglie
        # del motore, baseline, contatori). Valutato qui dal controller collegato.
        if self.controller is not None:
            try:
                summary["context"] = self.controller.diagnostic_summary_context()
            except Exception as e:
                logger.warning("Impossibile costruire summary context: %s", e)

        try:
            self._csv_file.close()
            self._jsonl_file.close()
            if self._experimental_file is not None:
                self._experimental_file.close()
        except Exception:
            pass

        # Scrivi il summary come file JSON separato
        summary_path = self._csv_path.with_suffix(".summary.json")
        try:
            with open(summary_path, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

        logger.info(
            "Sessione chiusa: %d frame, %d azioni, peak RMS=%.3f\"  → %s",
            self._total_frames, self._total_actions,
            self._peak_rms_total, self._csv_path,
        )
        return summary
