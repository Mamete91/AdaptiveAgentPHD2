"""
safety_state.py — §73: lo stato del Safety Monitor, riflesso nella dashboard.

PERCHE' ESISTE QUESTO MODULO. La decisione di sicurezza vive nel PLUGIN (C#):
i quattro latch, la causa, la finestra §72 sono suoi. L'agente misura e serve la
dashboard, ma non sa NULLA di tutto questo. Per mostrare lo stato del monitor
serviva quindi un flusso plugin -> agente: il plugin lo PUBBLICA a ogni tick
(POST /nina/safety), qui viene conservato e riesposto su /status.

Confine invariato: questo store e' un RIFLESSO, non una fonte. Nessuna decisione
di sicurezza nasce o cambia qui; l'agente non consuma questi dati per il motore.
Se il canale si interrompe (NINA chiusa, plugin scollegato) lo stato diventa
STANTIO e la dashboard lo dichiara sconosciuto — mai "verde per assenza di
notizie": e' la lezione §55/§68 applicata anche alla sola presentazione.

Thread-safety: scritto dal thread uvicorn (POST), letto dallo stesso su /status.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Optional

# Stati RIPORTATI dal monitor. Deliberatamente pochi e tutti VERI: ognuno esiste
# davvero nel SafetyDecisionEngine (o e' la finestra §72). Nessuno stato inventato.
STATE_SAFE = "SAFE"
STATE_UNSAFE = "UNSAFE"
STATE_MERIDIAN = "MERIDIAN_PROTECTION"
STATE_UNKNOWN = "UNKNOWN"          # nessuna notizia fresca dal plugin

# Cause di UNSAFE (SafetyCause del plugin). La causa E' l'azione operativa
# distinta: "vai a controllare la camera" vs "aspetta che passi la nuvola".
CAUSE_STAR_LOST = "STAR_LOST"
CAUSE_CLOUD = "CLOUD"
CAUSE_STALE = "STALE_TELEMETRY"
CAUSE_AGENT_LOST = "AGENT_LOST"
CAUSE_GUIDE_UNOBSERVABLE = "GUIDE_UNOBSERVABLE"

_VALID_STATES = {STATE_SAFE, STATE_UNSAFE, STATE_MERIDIAN}


class SafetyStateStore:
    """Ultimo stato pubblicato dal Safety Monitor del plugin, con freschezza."""

    #: Pavimento della finestra di freschezza: sotto questo valore non si scende
    #: mai, per non dichiarare ignoranza al primo singhiozzo di rete.
    MIN_STALENESS_S = 45.0
    #: Tick persi tollerati prima di dichiarare UNKNOWN.
    MISSED_TICKS = 3

    def __init__(self, staleness_seconds: Optional[float] = None,
                 now_fn: Callable[[], float] = time.monotonic) -> None:
        # §73-ter — la finestra si DERIVA dalla cadenza che il plugin dichiara nel
        # payload (`poll_interval_s`), non si indovina: l'intervallo di polling e'
        # configurabile da 5 a 120 s e una soglia fissa sarebbe sbagliata per meta'
        # dei valori possibili (a 120 s una finestra di 60 s scadrebbe SEMPRE, a
        # monitor perfettamente vivo). Stesso principio del §43, dove la finestra
        # di freschezza della telemetria si deriva dalla durata della posa.
        # Un valore esplicito qui lo FISSA (usato dai test).
        self._staleness_override = (float(staleness_seconds)
                                    if staleness_seconds is not None else None)
        self._poll_interval: Optional[float] = None
        self._now = now_fn
        self._lock = threading.Lock()

        self._ts: Optional[float] = None
        self._state: Optional[str] = None
        self._cause: Optional[str] = None
        self._detail: Optional[str] = None
        self._connected: bool = False
        self._internal_safe: Optional[bool] = None

    @property
    def staleness_seconds(self) -> float:
        """Finestra di freschezza corrente: MISSED_TICKS battiti persi, mai sotto
        MIN_STALENESS_S. Prima del primo POST vale il pavimento."""
        if self._staleness_override is not None:
            return self._staleness_override
        if self._poll_interval is None:
            return self.MIN_STALENESS_S
        return max(self.MIN_STALENESS_S, self.MISSED_TICKS * self._poll_interval)

    def update(self, state: str, cause: Optional[str] = None,
               detail: Optional[str] = None, connected: bool = True,
               internal_safe: Optional[bool] = None,
               poll_interval_s: Optional[float] = None) -> bool:
        """Registra una pubblicazione del plugin. Ritorna False se lo stato non e'
        riconosciuto (payload di una versione futura: si ignora, non si indovina)."""
        state = (state or "").strip().upper()
        if state not in _VALID_STATES:
            return False
        with self._lock:
            if poll_interval_s is not None and poll_interval_s > 0:
                self._poll_interval = float(poll_interval_s)
            self._ts = self._now()
            self._state = state
            self._cause = (cause or "").strip().upper() or None
            self._detail = (detail or "").strip() or None
            self._connected = bool(connected)
            self._internal_safe = internal_safe
        return True

    def status_block(self) -> dict[str, Any]:
        with self._lock:
            age = None if self._ts is None else round(self._now() - self._ts, 1)
            fresh = age is not None and age <= self.staleness_seconds

            # Monitor disconnesso in NINA: e' un fatto NOTO (il plugin lo dice),
            # diverso dal silenzio. La dashboard li distingue.
            if not fresh:
                state = STATE_UNKNOWN
            elif not self._connected:
                state = STATE_UNKNOWN
            else:
                state = self._state or STATE_UNKNOWN

            return {
                "state": state,
                "cause": self._cause if state == STATE_UNSAFE else None,
                "detail": self._detail if fresh else None,
                "connected": self._connected and fresh,
                # §72 — dentro la finestra il RIPORTATO diverge dall'INTERNO:
                # la dashboard puo' dire "flip autorizzato, cielo ancora unsafe".
                "internal_safe": self._internal_safe if fresh else None,
                "age_s": age,
                "fresh": fresh,
                # Osservabilita' della finestra stessa: se un giorno la dashboard
                # dicesse UNKNOWN a torto, questi due numeri lo spiegano subito.
                "staleness_window_s": round(self.staleness_seconds, 1),
                "poll_interval_s": self._poll_interval,
            }
