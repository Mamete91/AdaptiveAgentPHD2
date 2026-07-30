"""
reconnect_log.py — §69: deduplica del log di riconnessione a PHD2.

Problema misurato sui log del 29/7: **85% delle righe** (8314 su 9716) erano il
retry di connessione a PHD2 — 3 righe identiche ogni 12 secondi, per ore, quando
PHD2 e' chiuso ma l'Agente resta vivo insieme a NINA. Non e' un guasto, ma con la
rotazione a 5 MB quel rumore ESPELLE dal file la storia utile: in una forense
futura si rischia di non trovare piu' le righe che contano.

Politica (concordata con Alessandro):
  1. i primi tentativi si loggano per esteso (serve vedere l'errore vero);
  2. poi UNA riga di soppressione;
  3. durante la soppressione un BATTITO raro — perche' il silenzio non e' mai una
     prova: senza, un lettore futuro non distingue "agente vivo che ritenta" da
     "agente morto" (e' l'ambiguita' che ci e' costata tempo in §63 e §68);
  4. al ritorno una SINTESI con tentativi e durata — il dato forense che oggi si
     dovrebbe ricostruire contando centinaia di righe a mano;
  5. se cambia il messaggio d'errore (anomalia DIVERSA) si torna verbosi.

Logica PURA e testabile con clock iniettabile (stile RecoveryProbeGate/§57): qui
non si scrive nulla sul logger, si decide soltanto COSA andrebbe scritto.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class LogAction:
    """Una riga che il chiamante deve emettere (livello + messaggio)."""
    level: str      # "info" | "warning" | "error"
    message: str


class ReconnectLogPolicy:
    """Decide quali righe emettere durante i tentativi di riconnessione a PHD2."""

    def __init__(self, verbose_attempts: int = 3,
                 heartbeat_minutes: float = 10.0,
                 now_fn: Callable[[], float] = time.monotonic) -> None:
        self.verbose_attempts = max(1, int(verbose_attempts))
        self.heartbeat_s = max(0.0, float(heartbeat_minutes) * 60.0)
        self._now = now_fn

        self._attempts = 0
        self._first_failure_ts: Optional[float] = None
        self._last_heartbeat_ts: Optional[float] = None
        self._last_error: Optional[str] = None

    # ------------------------------------------------------------------ #

    @property
    def attempts(self) -> int:
        return self._attempts

    @property
    def suppressing(self) -> bool:
        return self._attempts > self.verbose_attempts

    def _elapsed_min(self, now: float) -> float:
        if self._first_failure_ts is None:
            return 0.0
        return (now - self._first_failure_ts) / 60.0

    def failure(self, error: str) -> list[LogAction]:
        """Un tentativo fallito. Ritorna le righe da emettere (anche nessuna)."""
        now = self._now()
        error = str(error)

        # Anomalia DIVERSA => la storia precedente non vale piu': si torna verbosi.
        if self._last_error is not None and error != self._last_error:
            self._attempts = 0
            self._first_failure_ts = None
            self._last_heartbeat_ts = None
        self._last_error = error

        self._attempts += 1
        if self._first_failure_ts is None:
            self._first_failure_ts = now

        if self._attempts <= self.verbose_attempts:
            return [LogAction("error", error)]

        if self._attempts == self.verbose_attempts + 1:
            self._last_heartbeat_ts = now
            every = "" if self.heartbeat_s <= 0 else \
                f" (riepilogo ogni {self.heartbeat_s / 60:.0f} min)"
            return [LogAction("warning",
                              f"PHD2 ancora non raggiungibile dopo {self._attempts} tentativi "
                              f"— ulteriori tentativi soppressi{every}")]

        # Battito: il silenzio non e' una prova, quindi ogni tanto lo si rompe.
        if self.heartbeat_s > 0 and self._last_heartbeat_ts is not None \
                and (now - self._last_heartbeat_ts) >= self.heartbeat_s:
            self._last_heartbeat_ts = now
            return [LogAction("info",
                              f"PHD2 ancora irraggiungibile — {self._attempts} tentativi "
                              f"in {self._elapsed_min(now):.0f} min (log soppresso)")]
        return []

    def success(self) -> list[LogAction]:
        """Connessione riuscita. Ritorna la sintesi SOLO se c'era stata soppressione."""
        now = self._now()
        actions: list[LogAction] = []
        if self.suppressing:
            actions.append(LogAction(
                "info",
                f"PHD2 raggiungibile dopo {self._attempts} tentativi "
                f"in {self._elapsed_min(now):.0f} min"))
        self._attempts = 0
        self._first_failure_ts = None
        self._last_heartbeat_ts = None
        self._last_error = None
        return actions
