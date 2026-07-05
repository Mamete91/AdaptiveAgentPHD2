"""
nina_telemetry.py — Store in memoria della telemetria per-posa di NINA (§41, Step 0).

Layer-1 puro (telemetria GREZZA): conserva l'ultimo payload ricevuto dal plugin
NINA via `POST /nina/telemetry` (HFR, conteggio stelle, SNR/fondo, eccentricità),
il suo timestamp di arrivo e un breve storico per future baseline per-campo.

NESSUNA logica derivata qui: niente TransparencyIndex, niente indici Layer-2,
niente confidence. Sono prompt successivi (N1→N8). Questo modulo è solo il "tubo".

OPZIONALE e GRACEFUL: senza POST il resto dell'Agente è bit-identico a oggi. Lo
store NON è letto da motore/controller/leve in §41 — solo `/status` lo espone.

Thread-safe: l'Agente ha il loop eventi PHD2 + il thread uvicorn (endpoint POST e
lettura `/status`). Un `threading.Lock` protegge l'accesso allo stato condiviso.
Il modulo non dipende da FastAPI/pydantic né da altri moduli del progetto.
"""
from __future__ import annotations

import copy
import logging
import math
import threading
import time
from collections import deque
from typing import Any, Optional

logger = logging.getLogger(__name__)


class NinaTelemetryStore:
    """Store opzionale e thread-safe dell'ultima telemetria NINA + breve storico.

    Parametri (dalla sezione `[nina_telemetry]` del config):
      enabled            kill-switch. A False lo store non memorizza nulla e
                         `status_block()` riporta `enabled=False`.
      staleness_seconds  oltre questo intervallo senza nuovi POST l'ultima
                         telemetria è "stantia" (`is_fresh=False`, `connected=False`).
      history_frames     ampiezza del deque di storico (per future baseline/trend).
      log_arrivals       se True, logga ogni arrivo (debug); default False.
    """

    def __init__(
        self,
        enabled: bool = True,
        staleness_seconds: float = 180.0,
        history_frames: int = 60,
        log_arrivals: bool = False,
        staleness_exposure_factor: float = 1.5,
    ) -> None:
        self.enabled = bool(enabled)
        self.staleness_seconds = float(staleness_seconds)
        self.log_arrivals = bool(log_arrivals)
        # §43 — la freschezza è adattiva alla posa: la telemetria arriva una volta per
        # sotto-posa (anche 300s), quindi una finestra fissa la marcherebbe "stantia"
        # per metà ciclo pur essendo tutto ok. effective_window =
        # max(staleness_seconds, staleness_exposure_factor × exposure_s ultima posa).
        self.staleness_exposure_factor = float(staleness_exposure_factor)

        self._lock = threading.Lock()
        self._last: Optional[dict] = None          # ultimo payload grezzo (model_dump)
        self._last_monotonic: float = 0.0          # time.monotonic() all'arrivo
        self._schema_version: Optional[int] = None
        self._count: int = 0                        # arrivi totali accettati
        # maxlen>=1 anche se history_frames fosse <=0 (deque(maxlen=0) scarterebbe tutto)
        self._history: deque = deque(maxlen=max(1, int(history_frames)))

    # ------------------------------------------------------------------ #
    #  Scrittura                                                          #
    # ------------------------------------------------------------------ #

    def update(self, payload: dict, schema_version: int) -> None:
        """Registra un payload valido (già validato a monte). Thread-safe.

        `payload` è il dump grezzo del contratto JSON (image/context/...);
        `schema_version` è esposto a parte in `/status` per comodità.
        """
        now = time.monotonic()
        # Copia difensiva: lo store possiede il proprio dato, indipendente dal chiamante.
        snap = copy.deepcopy(payload)
        with self._lock:
            self._last = snap
            self._last_monotonic = now
            self._schema_version = int(schema_version)
            self._count += 1
            self._history.append(
                {"recv_monotonic": now, "schema_version": int(schema_version), "payload": snap}
            )
        # Logging fuori dal lock (niente I/O sotto lock).
        if self.log_arrivals:
            logger.info("NINA telemetry ricevuta (schema_version=%s): %s",
                        schema_version, payload)

    # ------------------------------------------------------------------ #
    #  Lettura                                                            #
    # ------------------------------------------------------------------ #

    def _effective_window(self, last: Optional[dict]) -> float:
        """§43 — finestra di freschezza adattiva: max(staleness_seconds,
        staleness_exposure_factor × exposure_s dell'ultimo payload). Graceful: se
        `exposure_s` è assente/non valido, ricade su `staleness_seconds` (pavimento)."""
        window = self.staleness_seconds
        if last is not None and self.staleness_exposure_factor > 0:
            img = last.get("image") or {}
            exp = img.get("exposure_s")
            if isinstance(exp, (int, float)) and math.isfinite(exp) and exp > 0:
                window = max(window, self.staleness_exposure_factor * float(exp))
        return window

    @property
    def is_fresh(self) -> bool:
        """True se è arrivata telemetria entro la finestra di freschezza adattiva
        (§43). False se mai ricevuta, stantia o store disabilitato."""
        with self._lock:
            last = self._last
            ts = self._last_monotonic
        if last is None:
            return False
        return (time.monotonic() - ts) < self._effective_window(last)

    @property
    def last_age_s(self) -> Optional[float]:
        """Secondi dall'ultimo POST accettato; None se mai ricevuto."""
        with self._lock:
            if self._last is None:
                return None
            ts = self._last_monotonic
        return round(time.monotonic() - ts, 1)

    @property
    def count(self) -> int:
        """Numero totale di payload accettati dall'avvio."""
        with self._lock:
            return self._count

    def status_block(self) -> dict[str, Any]:
        """Blocco `nina` per `/status`. Graceful: store assente/disabilitato o
        nessun POST -> connected=False, metrics={}, last_age_s=None."""
        with self._lock:
            last = self._last
            schema = self._schema_version
            ts = self._last_monotonic
            enabled = self.enabled
        if last is None:
            return {
                "enabled": bool(enabled),
                "connected": False,
                "schema_version": None,
                "last_age_s": None,
                "effective_staleness_s": None,
                "metrics": {},
            }
        age = time.monotonic() - ts
        window = self._effective_window(last)   # §43: adattiva alla posa
        # deepcopy fuori dal lock: `last` non viene mai mutato dopo lo store (update
        # sostituisce sempre il riferimento), quindi è sicuro copiarlo qui.
        return {
            "enabled": True,
            "connected": age < window,
            "schema_version": schema,
            "last_age_s": round(age, 1),
            "effective_staleness_s": round(window, 1),
            "metrics": copy.deepcopy(last),
        }

    def history_snapshot(self) -> list[dict]:
        """Copia dello storico recente (per future baseline per-campo/trend §N1)."""
        with self._lock:
            items = list(self._history)
        return copy.deepcopy(items)
