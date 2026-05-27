"""
analyzer.py — Analisi statistica in tempo reale degli eventi GuideStep

Mantiene una sliding window (deque) degli ultimi N frame e calcola:
  - RMS RA / Dec / totale
  - Peak error RA / Dec
  - SNR medio, HFD medio
  - Spike score (% outlier oltre 2σ)
  - Trend (pendenza regressione lineare)
  - Pattern riconosciuto (NOMINAL / DEGRADED_SEEING / OSCILLATING / LOW_SNR)
"""
from __future__ import annotations

import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

logger = logging.getLogger(__name__)

# Implosion detector: se rms_total supera N× il riferimento EMA i frame sono
# considerati garbage (es. camera USB crashata) e le decisioni vengono sospese.
_RMS_IMPLOSION_FACTOR          = 8.0  # moltiplicatore soglia
_RMS_IMPLOSION_SUSPEND_SECONDS = 60   # secondi di sospensione dopo rilevamento


class SeeingCondition(Enum):
    UNKNOWN = auto()
    NOMINAL = auto()          # Guida stabile, buon seeing
    DEGRADED_SEEING = auto()  # RMS alto con spike → turbolenza atmosferica
    OSCILLATING = auto()      # Trend alternato → over-correzione / periodo meccanico
    LOW_SNR = auto()          # Stella guida debole o nubi parziali
    STAR_LOST = auto()        # Stella persa


@dataclass
class FrameData:
    """Dati di un singolo GuideStep."""
    timestamp: float
    ra_raw: float          # arcsec (raw distance)
    dec_raw: float         # arcsec
    ra_duration: float     # ms correzione inviata a RA
    dec_duration: float    # ms correzione inviata a Dec
    snr: float
    hfd: float
    star_mass: float


@dataclass
class AnalysisSnapshot:
    """Risultato di un'analisi sulla finestra corrente."""
    timestamp: float = 0.0
    frame_count: int = 0

    # RMS (arcsec)
    rms_ra: float = 0.0
    rms_dec: float = 0.0
    rms_total: float = 0.0

    # Peak (arcsec)
    peak_ra: float = 0.0
    peak_dec: float = 0.0

    # SNR e HFD
    snr_avg: float = 0.0
    hfd_avg: float = 0.0

    # Distribuzione
    spike_score: float = 0.0   # 0.0–1.0, % di frame outlier oltre 2σ
    sigma_ra: float = 0.0
    sigma_dec: float = 0.0

    # Trend (pendenza regressione lineare, arcsec/frame)
    trend_ra: float = 0.0
    trend_dec: float = 0.0

    # Pattern riconosciuto
    condition: SeeingCondition = SeeingCondition.UNKNOWN
    condition_description: str = ""

    # Contatori consecutivi (usati dal controller)
    consecutive_high: int = 0
    consecutive_low: int = 0

    # Implosion detector
    implosion_detected: bool = False   # frame garbage (RMS >> reference EMA)
    implosion_suspended: bool = False  # analisi sospesa durante finestra post-implosion


class StatisticsAnalyzer:
    """
    Mantiene una sliding window degli ultimi window_size frame e
    produce un AnalysisSnapshot aggiornato a ogni nuovo frame.
    """

    def __init__(self, window_size: int = 30, rms_high: float = 0.80, rms_low: float = 0.35,
                 snr_low: float = 10.0, spike_ratio_high: float = 0.30):
        self.window_size = window_size
        self.rms_high = rms_high
        self.rms_low = rms_low
        self.snr_low = snr_low
        self.spike_ratio_high = spike_ratio_high

        self._window: deque[FrameData] = deque(maxlen=window_size)
        self._consecutive_high = 0
        self._consecutive_low = 0
        self._last_snapshot: Optional[AnalysisSnapshot] = None
        self._star_lost = False
        self._rms_reference: Optional[float] = None
        self._implosion_suspended_until: float = 0.0

    # ------------------------------------------------------------------ #
    #  Ingestione dati                                                     #
    # ------------------------------------------------------------------ #

    def ingest_guide_step(self, event: dict) -> AnalysisSnapshot:
        """Processa un evento GuideStep e ritorna il nuovo snapshot."""
        self._star_lost = False

        frame = FrameData(
            timestamp=event.get("Timestamp", time.time()),
            ra_raw=float(event.get("RADistanceRaw", 0.0)),
            dec_raw=float(event.get("DECDistanceRaw", 0.0)),
            ra_duration=float(event.get("RADuration", 0.0)),
            dec_duration=float(event.get("DECDuration", 0.0)),
            snr=float(event.get("SNR", 0.0)),
            hfd=float(event.get("HFD", 0.0)),
            star_mass=float(event.get("StarMass", 0.0)),
        )
        self._window.append(frame)
        snapshot = self._compute()
        self._last_snapshot = snapshot
        return snapshot

    def ingest_star_lost(self, _event: dict) -> AnalysisSnapshot:
        """Segna la stella come persa."""
        self._star_lost = True
        snap = AnalysisSnapshot(
            timestamp=time.time(),
            frame_count=len(self._window),
            condition=SeeingCondition.STAR_LOST,
            condition_description="Stella guida persa",
        )
        self._last_snapshot = snap
        return snap

    @property
    def last_snapshot(self) -> Optional[AnalysisSnapshot]:
        return self._last_snapshot

    @property
    def is_ready(self) -> bool:
        """True se abbiamo abbastanza frame per un'analisi significativa."""
        return len(self._window) >= max(5, self.window_size // 3)

    # ------------------------------------------------------------------ #
    #  Calcolo statistiche                                                 #
    # ------------------------------------------------------------------ #

    def _compute(self) -> AnalysisSnapshot:
        frames = list(self._window)
        n = len(frames)
        snap = AnalysisSnapshot(timestamp=time.time(), frame_count=n)

        if n == 0:
            return snap

        ra_vals = [f.ra_raw for f in frames]
        dec_vals = [f.dec_raw for f in frames]
        snr_vals = [f.snr for f in frames]
        hfd_vals = [f.hfd for f in frames if f.hfd > 0]

        # RMS
        snap.rms_ra = _rms(ra_vals)
        snap.rms_dec = _rms(dec_vals)
        snap.rms_total = math.hypot(snap.rms_ra, snap.rms_dec)

        # Peak
        snap.peak_ra = max(abs(v) for v in ra_vals)
        snap.peak_dec = max(abs(v) for v in dec_vals)

        # SNR / HFD
        snap.snr_avg = _mean(snr_vals)
        snap.hfd_avg = _mean(hfd_vals) if hfd_vals else 0.0

        # Deviazione standard e spike score
        mean_ra = _mean(ra_vals)
        mean_dec = _mean(dec_vals)
        snap.sigma_ra = _std(ra_vals, mean_ra)
        snap.sigma_dec = _std(dec_vals, mean_dec)

        threshold_ra = 2.0 * snap.sigma_ra if snap.sigma_ra > 0 else float("inf")
        threshold_dec = 2.0 * snap.sigma_dec if snap.sigma_dec > 0 else float("inf")
        outliers = sum(
            1 for ra, dec in zip(ra_vals, dec_vals)
            if abs(ra - mean_ra) > threshold_ra or abs(dec - mean_dec) > threshold_dec
        )
        snap.spike_score = outliers / n if n > 0 else 0.0

        # Trend (regressione lineare su RA e Dec)
        snap.trend_ra = _linear_trend(ra_vals)
        snap.trend_dec = _linear_trend(dec_vals)

        # RMS implosion detection
        # EMA aggiornata solo su frame validi (no garbage, SNR sufficiente) per
        # evitare che frame patologici sub-soglia spostino il riferimento verso l'alto.
        _ref = self._rms_reference
        if _ref is None:
            if n >= self.window_size and snap.snr_avg >= self.snr_low:
                self._rms_reference = snap.rms_total
        else:
            if snap.rms_total >= _RMS_IMPLOSION_FACTOR * _ref:
                snap.implosion_detected = True
                if time.monotonic() > self._implosion_suspended_until:
                    logger.critical(
                        "RMS IMPLOSION: %.2f\" >> %.1f× ref %.2f\" — "
                        "decisioni sospese per %ds",
                        snap.rms_total, _RMS_IMPLOSION_FACTOR, _ref,
                        _RMS_IMPLOSION_SUSPEND_SECONDS,
                    )
                self._implosion_suspended_until = (
                    time.monotonic() + _RMS_IMPLOSION_SUSPEND_SECONDS
                )
            elif snap.snr_avg >= self.snr_low:
                self._rms_reference = 0.9 * _ref + 0.1 * snap.rms_total

        if time.monotonic() < self._implosion_suspended_until:
            snap.implosion_suspended = True

        # Contatori consecutivi (non aggiornati durante implosion per evitare
        # CRITICAL spurio al ritorno alla normalità)
        if not snap.implosion_suspended:
            rms_now = snap.rms_total
            if rms_now > self.rms_high:
                self._consecutive_high += 1
                self._consecutive_low = 0
            elif rms_now < self.rms_low:
                self._consecutive_low += 1
                self._consecutive_high = 0
            else:
                # Zona neutra: reset graduale
                self._consecutive_high = max(0, self._consecutive_high - 1)
                self._consecutive_low = max(0, self._consecutive_low - 1)

        snap.consecutive_high = self._consecutive_high
        snap.consecutive_low = self._consecutive_low

        # Pattern recognition
        snap.condition, snap.condition_description = self._classify(snap)

        if snap.implosion_suspended:
            snap.condition = SeeingCondition.NOMINAL
            snap.condition_description = (
                f"RMS implosion detector — analisi sospesa "
                f"(RMS={snap.rms_total:.2f}\", ref={self._rms_reference:.2f}\")"
            )

        return snap

    def _classify(self, snap: AnalysisSnapshot) -> tuple[SeeingCondition, str]:
        """Classifica le condizioni di seeing dal snapshot."""

        if self._star_lost:
            return SeeingCondition.STAR_LOST, "Stella guida persa"

        if snap.snr_avg < self.snr_low and snap.snr_avg > 0:
            return SeeingCondition.LOW_SNR, f"SNR basso ({snap.snr_avg:.1f} < {self.snr_low})"

        # Oscillazione: trend RA alternato (pendenza elevata ma RMS medio)
        if (abs(snap.trend_ra) > 0.05 and snap.rms_ra > self.rms_low
                and snap.spike_score < 0.25):
            return SeeingCondition.OSCILLATING, (
                f"Trend RA oscillante ({snap.trend_ra:+.3f} arcsec/frame) "
                "→ possibile over-correzione"
            )

        if snap.spike_score > self.spike_ratio_high and snap.rms_total > self.rms_high:
            return SeeingCondition.DEGRADED_SEEING, (
                f"Seeing degradato: RMS={snap.rms_total:.2f}\" "
                f"spike={snap.spike_score:.0%}"
            )

        if snap.rms_total > self.rms_high:
            return SeeingCondition.DEGRADED_SEEING, (
                f"RMS elevato ({snap.rms_total:.2f}\") oltre soglia {self.rms_high}\""
            )

        return SeeingCondition.NOMINAL, f"Guida nominale (RMS={snap.rms_total:.2f}\")"

    def reset(self) -> None:
        """Azzera la finestra (es. dopo un cambio di parametri importante)."""
        self._window.clear()
        self._consecutive_high = 0
        self._consecutive_low = 0
        self._star_lost = False
        self._rms_reference = None
        self._implosion_suspended_until = 0.0


# ------------------------------------------------------------------ #
#  Funzioni statistiche pure                                          #
# ------------------------------------------------------------------ #

def _mean(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def _rms(vals: list[float]) -> float:
    if not vals:
        return 0.0
    return math.sqrt(sum(v * v for v in vals) / len(vals))


def _std(vals: list[float], mean: float) -> float:
    if len(vals) < 2:
        return 0.0
    return math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals))


def _linear_trend(vals: list[float]) -> float:
    """
    Stima la pendenza (slope) della retta di regressione sui valori.
    Ritorna arcsec/frame (positivo = errore crescente).
    """
    n = len(vals)
    if n < 3:
        return 0.0
    xs = list(range(n))
    mean_x = (n - 1) / 2.0
    mean_y = _mean(vals)
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, vals))
    den = sum((x - mean_x) ** 2 for x in xs)
    return num / den if den != 0 else 0.0
