"""
§57 S2 — RecoveryHintTracker: "il cielo sta tornando?" dalla SNR della stella guida.

Contesto (deadlock provato, notte 12/7): durante l'attesa UNSAFE NINA non salva light
→ N1 congelato → N6 non può tornare SAFE. Ma la SNR guida (GuideStep di PHD2) continua
a fluire: è un segnale di cielo indipendente dai light. Questo tracker la integra e
stima un HINT di recupero che può solo ANTICIPARE la posa-sonda S1 (istruzione
RecoveryProbe del plugin). PALETTO 1 — autorità ZERO sulla safety: questo modulo non ha
alcun percorso verso N6/IsSafe; espone solo osservazione su /status.

La SNR guida è un proxy CONTAMINATO (seeing/fuoco/magnitudine della stella guida):
una stella luminosa sopravvive a velature sottili. Per questo l'hint non giudica mai:
la verità resta la camera di imaging (posa-sonda → N1 → drain §55 → N6).

Dinamica (§57-bis, Gate): accumulatore leaky IN SECONDI DI TEMPO REALE — sale di dt sui
frame con SNR "buona" (>= max(floor, frac×snr_ref)), scende di drain_factor×dt sugli
altri; latch active a sustained_seconds, rilascio a 0. Il criterio è così indipendente
dal frame-rate di guida (0.5–4 s per setup) e fisicamente coerente col cielo.
Gating: valutato solo se l'ultimo stato N1 noto è degradato (CLOUD/HAZE); a CLEAR è
inerte e aggiorna snr_ref (EMA della SNR di cielo limpido, il riferimento pre-nube).

Fratello di N1 (non lo importa, non lo modifica): legge lo stato via un provider
read-only iniettato da main.py.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any, Callable, Optional

from .config import RecoveryHintConfig

logger = logging.getLogger(__name__)

# EMA della SNR di riferimento in CLEAR: lenta (il riferimento è "com'era il cielo
# limpido", non l'ultimo frame).
_SNR_REF_ALPHA = 0.05

# dt massimo accreditabile per un singolo frame (s): un buco lungo tra frame (stella
# persa, dithering) non deve accreditare "tempo buono" fantasma al frame successivo.
_MAX_FRAME_DT_S = 5.0

_DEGRADED = ("CLOUD", "HAZE")


class RecoveryHintTracker:
    """Osserva la SNR guida per-frame ed espone l'hint di recupero su /status."""

    def __init__(
        self,
        config: RecoveryHintConfig,
        state_provider: Optional[Callable[[], tuple[Optional[str], Optional[float]]]] = None,
        now_fn: Callable[[], float] = time.time,
    ) -> None:
        self.cfg = config
        # provider read-only dell'ultimo (state, index) di N1; None => gating inerte.
        self._state_provider = state_provider
        self._now = now_fn          # iniettabile nei test (clock finto)
        self._lock = threading.Lock()

        self._snr_ref: Optional[float] = None      # SNR media pre-nube (catturata in CLEAR)
        self._last_snr: Optional[float] = None
        self._last_frame_ts: Optional[float] = None
        self._accumulator_s: float = 0.0            # secondi di segnale buono accumulati (leaky)
        self._active: bool = False
        self._active_since: Optional[float] = None
        self._reason: str = "in attesa di frame"
        self._last_seen_state: Optional[str] = None  # stato N1 all'ultimo frame (pre-sonda)

        # Telemetria sonde (paletto 8): ultimi record, esposti su /status e dashboard.
        self._probes: deque[dict[str, Any]] = deque(maxlen=12)

    # ------------------------------------------------------------------ #
    #  Aggiornamento per-frame (thread del loop principale)               #
    # ------------------------------------------------------------------ #

    def update(self, snr: Optional[float]) -> None:
        """Un guide-frame: integra la SNR nell'accumulatore a tempo (gated da N1)."""
        if not self.cfg.enabled:
            return
        if snr is None or not (snr > 0):
            return   # frame senza SNR utile: non conta né a favore né contro

        state, _index = self._read_state()
        now = self._now()
        with self._lock:
            # dt reale dal frame precedente, clampato (buchi lunghi non accreditano tempo).
            dt = 0.0
            if self._last_frame_ts is not None:
                dt = min(max(now - self._last_frame_ts, 0.0), _MAX_FRAME_DT_S)
            self._last_frame_ts = now
            self._last_snr = float(snr)
            self._last_seen_state = state

            if state not in _DEGRADED:
                # CLEAR (o stato ignoto): hint inerte. In CLEAR aggiorniamo il
                # riferimento pre-nube; l'accumulatore rientra.
                if state == "CLEAR":
                    self._snr_ref = (
                        float(snr) if self._snr_ref is None
                        else (1 - _SNR_REF_ALPHA) * self._snr_ref + _SNR_REF_ALPHA * float(snr)
                    )
                self._accumulator_s = 0.0
                self._set_active(False, now, "stato N1 non degradato: hint inerte")
                return

            # Stato degradato: valuta la SNR contro la soglia relativa (floor assoluto).
            threshold = self.cfg.snr_recover_floor
            if self._snr_ref is not None:
                threshold = max(threshold, self.cfg.snr_recover_frac * self._snr_ref)

            target = max(1.0, self.cfg.sustained_seconds)
            if float(snr) >= threshold:
                self._accumulator_s = min(target, self._accumulator_s + dt)
            else:
                self._accumulator_s = max(0.0, self._accumulator_s - self.cfg.drain_factor * dt)

            if self._accumulator_s >= target:
                self._set_active(True, now,
                                 f"snr {snr:.1f} >= {threshold:.1f} sostenuta per "
                                 f"{self._accumulator_s:.0f}s")
            elif self._accumulator_s <= 0.0 and self._active:
                self._set_active(False, now, f"snr {snr:.1f} < {threshold:.1f} — accumulatore esaurito")
            elif not self._active:
                self._reason = (f"snr {snr:.1f} {'≥' if snr >= threshold else '<'} "
                                f"{threshold:.1f} — {self._accumulator_s:.0f}/"
                                f"{target:.0f}s (non sostenuto)")

    def _set_active(self, value: bool, now: float, reason: str) -> None:
        if value and not self._active:
            self._active_since = now
            logger.info("[recovery_hint] ACTIVE — %s (snr_ref=%s)", reason,
                        f"{self._snr_ref:.1f}" if self._snr_ref is not None else "n/d")
        elif not value and self._active:
            logger.info("[recovery_hint] rientrato — %s", reason)
            self._active_since = None
        self._active = value
        self._reason = reason

    def _read_state(self) -> tuple[Optional[str], Optional[float]]:
        try:
            if self._state_provider is not None:
                return self._state_provider()
        except Exception:
            pass
        return (None, None)

    # ------------------------------------------------------------------ #
    #  Telemetria sonde (paletto 8) — thread FastAPI                      #
    # ------------------------------------------------------------------ #

    def observe_probe(self, transparency_after: Optional[dict]) -> None:
        """Chiamata (da server.py, accanto all'ingest N1) quando arriva un light mentre
        l'ultimo contesto era degradato: è la firma di una posa-sonda (o del primo light
        dopo le nubi). Registra trigger presunto ed esito — i numeri per tarare S2."""
        if not self.cfg.enabled:
            return
        with self._lock:
            if self._last_seen_state not in _DEGRADED:
                return   # light di normale imaging: non è una sonda
            after = transparency_after or {}
            record = {
                "ts": self._now(),
                # attribuzione by-construction: se l'hint era attivo, la sonda è stata
                # (o sarebbe stata) anticipata da S2; altrimenti è la cadenza S1.
                "trigger": "hint_S2" if self._active else "timeout_S1",
                "outcome_index": after.get("index"),
                "outcome_state": after.get("state"),
                "hint_active": self._active,
                "snr": self._last_snr,
                "snr_ref": self._snr_ref,
                "accumulator_s": round(self._accumulator_s, 1),
            }
            self._probes.append(record)
            logger.info(
                "[recovery_probe] sonda osservata: trigger=%s -> index=%s state=%s "
                "(hint_active=%s snr=%s ref=%s acc=%.0fs)",
                record["trigger"], record["outcome_index"], record["outcome_state"],
                self._active,
                f"{self._last_snr:.1f}" if self._last_snr is not None else "n/d",
                f"{self._snr_ref:.1f}" if self._snr_ref is not None else "n/d",
                self._accumulator_s,
            )

    # ------------------------------------------------------------------ #
    #  Lettura per /status e dashboard                                    #
    # ------------------------------------------------------------------ #

    def status_block(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self.cfg.enabled,
                "active": self._active,
                "snr": round(self._last_snr, 1) if self._last_snr is not None else None,
                "snr_ref": round(self._snr_ref, 1) if self._snr_ref is not None else None,
                "accumulator_s": round(self._accumulator_s, 1),
                "sustained_target_s": self.cfg.sustained_seconds,
                "since": self._active_since,
                "reason": self._reason,
                "probes": list(self._probes),
            }
