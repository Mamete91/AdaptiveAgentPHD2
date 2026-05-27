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
        session_id = self._session_start.strftime("%Y%m%d_%H%M%S")

        self._csv_path = self.csv_dir / f"session_{session_id}.csv"
        self._jsonl_path = self.csv_dir / f"decisions_{session_id}.jsonl"

        self._csv_file = open(self._csv_path, "w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._csv_file, fieldnames=_CSV_FIELDS)
        self._writer.writeheader()

        self._jsonl_file = open(self._jsonl_path, "a", encoding="utf-8")

        # Statistiche di sessione
        self._total_frames = 0
        self._total_actions = 0
        self._peak_rms_total = 0.0

        logger.info("Logger sessione aperto: %s", self._csv_path)

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
            "session_start": self._session_start.isoformat(),
            "duration_minutes": round(duration_s / 60, 1),
            "total_frames": self._total_frames,
            "total_actions": self._total_actions,
            "peak_rms_total_arcsec": round(self._peak_rms_total, 4),
            "csv_file": str(self._csv_path),
            "jsonl_file": str(self._jsonl_path),
        }

        try:
            self._csv_file.close()
            self._jsonl_file.close()
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
