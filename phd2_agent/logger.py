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
    "diag_state",
    "diag_confidence",
    "evaluated",        # §34: True = frame valutato (tick), False = riga di solo log fuori-tick
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
            "diag_state": getattr(snapshot, "diag_state", "INSUFFICIENT_DATA"),
            "diag_confidence": int(getattr(snapshot, "diag_confidence", 0)),
            "evaluated": bool(getattr(snapshot, "evaluated", False)),   # §34
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
            "schema_version": 3,   # §34: colonna `evaluated`; §36: misura RMS/jitter in ARCSEC (px×scale)
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
