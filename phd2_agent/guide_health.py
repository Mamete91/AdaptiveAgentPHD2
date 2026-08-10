"""
guide_health.py — §68: OSSERVABILITÀ del canale di guida (non qualità).

Guasto del 26/7 (forense §68): la camera di guida entra in uno stato patologico
(sospetta congestione USB), PHD2 perde la stella, manda ancora qualche GuideStep
pessimo e poi tace. `controller.guiding_state` resta CONGELATO su un valore
operativo e `/status` continua a servirlo come se fosse attuale: N6 legge "sta
guidando male" quando la verità è "non sta guidando affatto". Nessuno dei quattro
latch poteva scattare — il Safety Monitor sarebbe rimasto SAFE tutta la notte.

Principio (§55 esteso all'ultimo canale scoperto): perdere l'osservazione
affidabile è di per sé una condizione di rischio. Questo modulo NON giudica la
QUALITÀ della guida (competenza del motore adattivo, §65): misura solo se il
canale sta ancora producendo informazione attendibile.

Cosa PHD2 espone davvero (verificato sul sorgente `event_server.cpp`):
  • `GuideStep`         → guida attiva; porta StarMass/SNR/HFD e, SOLO in caso di
                          problema, `ErrorCode` (Star::FindResult).
  • `LoopingExposures`  → la camera espone ma NON si sta guidando (tipico dei
                          tentativi di riaggancio): stessi campi + `Status`.
                          Distinguere i due orologi è il cuore del modulo: se
                          cessano ANCHE i looping, la camera è morta davvero.
  • `Alert` + `Type`    → severità strutturata (info|question|warning|error):
                          niente string-matching fragile sui messaggi.
  • `ErrorCode`         → STAR_SATURATED / STAR_MASSCHANGE / STAR_LOWSNR ... la
                          firma del frame corrotto (elettrico) vs velatura (ottica).

L'agente MISURA e basta: nessuna decisione di safety vive qui (la prende il
plugin, §68 latch GUIDE_UNOBSERVABLE). Thread-safety: alimentato dal thread del
loop eventi, letto dal thread uvicorn su /status.
"""
from __future__ import annotations

import logging
import statistics
import threading
import time
from collections import deque
from typing import Any, Callable, Optional

from .config import GuideHealthConfig

logger = logging.getLogger(__name__)

# Star::FindResult di PHD2 (src/star.h) — il valore 0 non viene mai emesso.
STAR_ERROR_NAMES = {
    1: "SATURATED",
    2: "LOWSNR",
    3: "LOWMASS",
    4: "LOWHFD",
    5: "HIHFD",
    6: "TOO_NEAR_EDGE",
    7: "MASSCHANGE",
    8: "ERROR",
}

# Severità Alert che consideriamo corroboranti (le altre sono informative).
_ALERT_SEVERE = ("warning", "error")


class GuideHealthTracker:
    """Osservabilità del canale di guida PHD2. Solo misura, nessuna decisione."""

    def __init__(self, config: GuideHealthConfig,
                 now_fn: Callable[[], float] = time.monotonic) -> None:
        self.cfg = config
        self._now = now_fn                      # iniettabile nei test (clock finto)
        self._lock = threading.Lock()

        # Due orologi DISTINTI (vedi docstring).
        self._last_guide_step: Optional[float] = None   # ultima guida vera
        self._last_frame: Optional[float] = None        # ultimo frame QUALSIASI

        # Attesa di guida: derivata dagli annunci ESPLICITI di PHD2. È il gate che
        # evita i falsi allarmi durante le pause legittime (flip, autofocus, stop
        # volontario): PHD2 le annuncia, mentre sui guasti tace. NB: volutamente
        # indipendente da `_lastKnownGuidingActive` del plugin, che governa altri
        # latch e non va toccato.
        self._guiding_expected: bool = False
        self._expected_since: Optional[float] = None
        self._last_reason: str = "mai guidato in questa sessione"

        # Errori per-frame e severità (corroborazione, mai trigger da soli).
        self._errors: deque[tuple[float, int]] = deque(maxlen=200)
        self._last_error: Optional[tuple[float, int]] = None
        self._last_alert: Optional[tuple[float, str, str]] = None   # (ts, type, msg)

        # StarMass: la DISPERSIONE distingue il guasto elettrico (salti erratici)
        # dalla velatura (calo graduale). Solo telemetria, in questa fase.
        self._masses: deque[tuple[float, float]] = deque(maxlen=120)

        # §71 — cronologia (ts, stella_tracciata) per la FRAZIONE SOSTENUTA: il
        # riaggancio-lampo (3/8 23:40: 41% di frame utili, ripersa subito) non deve
        # aprire il gate della sonda. Cadenza guida ~3 s => 400 campioni ≈ 20 min.
        self._frames: deque[tuple[float, bool]] = deque(maxlen=400)

    # ------------------------------------------------------------------ #
    #  Ingest dagli eventi PHD2 (thread del loop eventi)                  #
    # ------------------------------------------------------------------ #

    def on_guide_step(self, event: dict) -> None:
        """GuideStep: guida attiva. Aggiorna ENTRAMBI gli orologi."""
        if not self.cfg.enabled:
            return
        now = self._now()
        with self._lock:
            self._last_guide_step = now
            self._last_frame = now
            self._frames.append((now, True))
            self._note_frame_quality(event, now)

    def on_star_lost(self, event: dict) -> None:
        """§71 — StarLost: la camera HA consegnato un frame (canale vivo) ma la
        stella non c'è. Aggiorna l'orologio dei frame, NON quello di guida, e
        registra il frame come non-tracciato per la frazione sostenuta. Gli
        StarLost portano ErrorCode/SNR/StarMass del tentativo fallito: la
        qualità va annotata (è la corroborazione del latch §68)."""
        if not self.cfg.enabled:
            return
        now = self._now()
        with self._lock:
            self._last_frame = now
            self._frames.append((now, False))
            self._note_frame_quality(event, now)

    def on_looping_exposure(self, event: dict) -> None:
        """LoopingExposures: la camera espone ma NON guida (riaggancio in corso).
        Aggiorna solo l'orologio dei frame: il canale è vivo, la guida no."""
        if not self.cfg.enabled:
            return
        now = self._now()
        with self._lock:
            self._last_frame = now
            self._frames.append((now, False))
            self._note_frame_quality(event, now)

    def _note_frame_quality(self, event: dict, now: float) -> None:
        """Campi di qualità del frame (chiamata sotto lock)."""
        err = event.get("ErrorCode")
        if isinstance(err, int) and err > 0:
            self._errors.append((now, err))
            self._last_error = (now, err)
        mass = event.get("StarMass")
        if isinstance(mass, (int, float)) and mass > 0:
            self._masses.append((now, float(mass)))

    def on_alert(self, msg: str, alert_type: str) -> None:
        """Alert di PHD2. `Type` è strutturato (info|question|warning|error):
        usiamo la SEVERITÀ, non il testo (robusto a traduzioni e riformulazioni)."""
        if not self.cfg.enabled:
            return
        with self._lock:
            self._last_alert = (self._now(), (alert_type or "info").lower(), msg or "")

    def set_guiding_expected(self, expected: bool, reason: str) -> None:
        """Annuncio esplicito di PHD2 sullo stato della guida. Le pause legittime
        sono ANNUNCIATE; i guasti no: è questa asimmetria a rendere il gate sicuro."""
        if not self.cfg.enabled:
            return
        now = self._now()
        with self._lock:
            if expected and not self._guiding_expected:
                self._expected_since = now
                # Ripartenza: gli orologi valgono da adesso, non dall'era precedente.
                self._last_guide_step = now
                self._last_frame = now
            elif not expected:
                self._expected_since = None
            self._guiding_expected = bool(expected)
            self._last_reason = reason
        logger.info("[guide_health] guida attesa=%s — %s", expected, reason)

    # ------------------------------------------------------------------ #
    #  Lettura per /status (thread uvicorn)                               #
    # ------------------------------------------------------------------ #

    def _age(self, ts: Optional[float], now: float) -> Optional[float]:
        return None if ts is None else round(max(0.0, now - ts), 1)

    def _mass_dispersion(self, now: float) -> Optional[float]:
        """Dispersione relativa robusta di StarMass sulla finestra recente (MAD/mediana).
        Alta = salti erratici (frame corrotti); bassa = livello stabile, anche se basso."""
        window = self.cfg.mass_window_s
        vals = [m for ts, m in self._masses if now - ts <= window]
        if len(vals) < 5:
            return None
        med = statistics.median(vals)
        if med <= 0:
            return None
        mad = statistics.median([abs(v - med) for v in vals])
        return round(mad / med, 3)

    def _channel_ready(self, now: float, errors_recent: int,
                       alert_severe: bool) -> tuple[bool, list[str], Optional[float]]:
        """§71 — "il canale guida merita una sonda da 300 s?" — consenso AND di
        condizioni binarie SOSTENUTE, mai uno score pesato (anti-§68: i pesi non
        si validano sul cielo e un punteggio non spiega COSA manca).

        L'asticella è volutamente SOPRA il criterio di PHD2: PHD2 si dichiara
        "guiding" nell'istante dell'aggancio; qui serve stabilità dimostrata.
        Il 3/8 alle 23:40 (riaggancio al 41%%, ripersa subito) resta respinto;
        alle 23:47 (86%% sostenuto) il gate si apre. Chiamata sotto lock.

        SOLO MISURA: il plugin usa questo per DIFFERIRE la sonda S1 entro un
        tetto rigido (15 min) — mai per decidere il SAFE, mai come veto.
        """
        reasons: list[str] = []

        frame_age = self._age(self._last_frame, now)
        if frame_age is None or frame_age > self.cfg.ready_frame_max_age_s:
            reasons.append("nessun frame recente dal canale")

        window = [tr for ts, tr in self._frames if now - ts <= self.cfg.ready_window_s]
        fraction: Optional[float] = None
        if len(window) < self.cfg.ready_min_samples:
            reasons.append(f"base statistica insufficiente ({len(window)} frame)")
        else:
            fraction = round(sum(window) / len(window), 3)
            if fraction < self.cfg.ready_min_tracked_fraction:
                reasons.append(f"stella instabile ({fraction:.0%} tracciata)")

        if errors_recent > self.cfg.ready_max_errors:
            reasons.append(f"{errors_recent} errori stella recenti")
        if alert_severe:
            reasons.append("alert PHD2 severo recente")

        return (not reasons, reasons, fraction)

    def status_block(self) -> dict[str, Any]:
        with self._lock:
            now = self._now()
            recent = [(ts, e) for ts, e in self._errors
                      if now - ts <= self.cfg.error_window_s]
            counts: dict[str, int] = {}
            for _ts, e in recent:
                counts[STAR_ERROR_NAMES.get(e, str(e))] = \
                    counts.get(STAR_ERROR_NAMES.get(e, str(e)), 0) + 1

            alert_type = alert_age = alert_msg = None
            if self._last_alert is not None:
                a_ts, alert_type, alert_msg = self._last_alert
                alert_age = self._age(a_ts, now)

            alert_severe_now = bool(alert_type in _ALERT_SEVERE
                                    and alert_age is not None
                                    and alert_age <= self.cfg.alert_window_s)
            ready, reasons, tracked_fraction = self._channel_ready(
                now, len(recent), alert_severe_now)

            return {
                "enabled": self.cfg.enabled,
                # I due orologi: `frame_age_s` è l'osservabilità VERA del canale
                # (guida o riaggancio); `guide_age_s` è "da quanto non si guida".
                "frame_age_s": self._age(self._last_frame, now),
                "guide_age_s": self._age(self._last_guide_step, now),
                "guiding_expected": self._guiding_expected,
                "expected_age_s": self._age(self._expected_since, now),
                "reason": self._last_reason,
                # Corroborazione (mai trigger da sola, lato plugin).
                "star_errors_recent": len(recent),
                "star_errors_by_code": counts,
                "last_star_error": (STAR_ERROR_NAMES.get(self._last_error[1],
                                                         str(self._last_error[1]))
                                    if self._last_error else None),
                "last_star_error_age_s": (self._age(self._last_error[0], now)
                                          if self._last_error else None),
                "alert_type": alert_type,
                "alert_age_s": alert_age,
                "alert_msg": alert_msg,
                "alert_severe": bool(alert_type in _ALERT_SEVERE
                                     and alert_age is not None
                                     and alert_age <= self.cfg.alert_window_s),
                "star_mass_dispersion": self._mass_dispersion(now),
                "error_window_s": self.cfg.error_window_s,
                # §71 — "canale pronto" per la sonda: consenso AND, vedi _channel_ready.
                "channel_ready": ready,
                "channel_not_ready_reasons": reasons,
                "tracked_fraction": tracked_fraction,
            }
