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

# §76-bis — emivita del RILASCIO verso il basso del riferimento SNR, in minuti di
# tempo reale. Stessa costante e stesso principio del §66 (regola 3): il metro può
# scendere, ma molto più lentamente di quanto scenda il cielo — altrimenti insegue
# il degrado e lo rende invisibile a se stesso.
_SNR_REF_RELEASE_HALF_LIFE_MIN = 25.0

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

        # §76 — accumulatore della polarità OPPOSTA: evidenza di DEGRADO. Vive
        # nella stessa classe perché condivide il riferimento `snr_ref` — due
        # copie dell'EMA divergerebbero, e il riferimento È il metro di entrambi.
        self._degrade_s: float = 0.0
        self._degrading: bool = False
        self._degrading_since: Optional[float] = None
        self._degrade_reason: str = "in attesa di frame"

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
                self._accumulator_s = 0.0
                self._set_active(False, now, "stato N1 non degradato: hint inerte")
                # §76 — proprio QUI vive la polarità opposta: N1 dice ancora CLEAR
                # perché è fermo all'ultima posa buona, ma il canale guida vede il
                # cielo peggiorare ADESSO. È la finestra in cui il monitor resta
                # SAFE ed espone pose ormai da buttare.
                # L'ORDINE CONTA: prima si giudica il frame contro il riferimento,
                # poi si aggiorna il riferimento — altrimenti il frame corrente
                # eroderebbe il metro con cui sta per essere misurato.
                self._update_degrade(float(snr), dt, now)
                if state == "CLEAR":
                    self._update_snr_ref(float(snr), dt)
                return

            # In stato già degradato l'evidenza di degrado non serve più: N1 ha
            # riconosciuto le nubi e l'accumulatore §55 sta già facendo il suo
            # lavoro. Rientra, così non resta armata durante il recupero.
            self._reset_degrade(now, "N1 ha già riconosciuto il degrado")

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

    def _update_snr_ref(self, snr: float, dt: float) -> None:
        """Riferimento SNR di cielo limpido — EMA con CRICCHETTO (chiamata sotto lock).

        §76-bis — difetto trovato scrivendo il replay della notte 4/8: l'EMA
        simmetrica faceva colare il riferimento INSIEME al cielo. Durante il
        crollo (70 -> 23, con N1 ancora CLEAR perché fermo all'ultima posa buona)
        il riferimento scendeva da 70 a 26 e la soglia relativa da 35 a 13: il
        degrado diventava INVISIBILE al proprio stesso metro. È la "rana bollita"
        del §66, identica, in un altro componente — lì il riferimento era il
        conteggio stelle di N1, qui è la SNR di guida.

        Cura, stessa del §66: il miglioramento si adotta subito ("le nubi non
        creano segnale"), il peggioramento NON erode il riferimento finché c'è
        evidenza di degrado in corso. Il congelamento è auto-limitato: appena
        l'evidenza rientra (cielo risalito, o era un transitorio) l'EMA riprende
        normalmente, e se il degrado è reale N1 lo riconosce e questo ramo non
        viene più eseguito.

        Il difetto colpiva ANCHE l'hint di recupero (§57), nel verso opposto: un
        riferimento eroso rende il recupero troppo facile da dichiarare, quindi
        anticipa sonde su cielo ancora cattivo. Questa correzione risana entrambe
        le polarità.
        """
        if self._snr_ref is None:
            self._snr_ref = snr
            return
        if snr >= self._snr_ref:
            # Regola 1 (§66): il miglioramento si adotta subito — "le nubi non
            # creano segnale", quindi una SNR più alta è sempre informazione vera.
            self._snr_ref = (1 - _SNR_REF_ALPHA) * self._snr_ref + _SNR_REF_ALPHA * snr
            return
        # Regola 3 (§66): verso il basso si scende con emivita LUNGA misurata in
        # tempo reale, non a colpi di frame. Con l'EMA simmetrica il riferimento
        # perdeva il 62% in 4 minuti di crollo (70 -> 26) e la soglia crollava con
        # lui; così ne perde meno del 6% e il degrado resta misurabile. Il cielo
        # che peggiora DAVVERO e stabilmente viene comunque riconosciuto da N1
        # sull'immagine — che è il giudice giusto per un cambio di livello.
        if dt > 0:
            keep = 0.5 ** ((dt / 60.0) / _SNR_REF_RELEASE_HALF_LIFE_MIN)
            self._snr_ref = snr + (self._snr_ref - snr) * keep

    def _update_degrade(self, snr: float, dt: float, now: float) -> None:
        """§76 — accumulatore leaky del DEGRADO (chiamata sotto lock, solo a N1 CLEAR).

        Simmetrico all'hint ma con asimmetrie deliberate:
          • soglia più severa (50% del riferimento contro l'80% del recupero) e
            sostegno più lungo (90 s contro 60 s): un falso positivo qui mette in
            pausa la sequenza, quindi si chiede più evidenza;
          • serve un `snr_ref` credibile: senza riferimento, o con riferimento
            troppo basso, il rapporto non significa nulla → nessuna evidenza
            (fail-inert, mai "degrado per assenza di dati").

        Resta pura MISURA: non dichiara UNSAFE. Il plugin la usa solo per
        ACCUMULARE verso unsafe, mai per drenare verso safe.
        """
        if not self.cfg.degrade_enabled:
            return
        if self._snr_ref is None or self._snr_ref < self.cfg.degrade_min_ref:
            self._reset_degrade(now, "riferimento SNR non ancora affidabile")
            return

        threshold = self.cfg.snr_degrade_frac * self._snr_ref
        target = max(1.0, self.cfg.degrade_sustained_seconds)
        if snr <= threshold:
            self._degrade_s = min(target, self._degrade_s + dt)
        else:
            self._degrade_s = max(0.0, self._degrade_s - dt)

        if self._degrade_s >= target and not self._degrading:
            self._degrading = True
            self._degrading_since = now
            self._degrade_reason = (f"snr {snr:.1f} <= {threshold:.1f} "
                                    f"({self.cfg.snr_degrade_frac:.0%} del riferimento "
                                    f"{self._snr_ref:.1f}) sostenuta per {self._degrade_s:.0f}s")
            logger.info("[recovery_hint] DEGRADO — %s", self._degrade_reason)
        elif self._degrade_s <= 0.0 and self._degrading:
            self._reset_degrade(now, f"snr {snr:.1f} risalita sopra {threshold:.1f}")
        elif not self._degrading:
            self._degrade_reason = (f"snr {snr:.1f} {'≤' if snr <= threshold else '>'} "
                                    f"{threshold:.1f} — {self._degrade_s:.0f}/{target:.0f}s")

    def _reset_degrade(self, now: float, reason: str) -> None:
        """Rientro dell'evidenza di degrado (chiamata sotto lock)."""
        was = self._degrading
        self._degrade_s = 0.0
        self._degrading = False
        self._degrading_since = None
        self._degrade_reason = reason
        if was:
            logger.info("[recovery_hint] degrado rientrato — %s", reason)

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
                # §76 — evidenza di DEGRADO (polarità opposta). SOLO misura: il
                # plugin la usa per accumulare verso unsafe, mai per drenare.
                "degrading": self._degrading,
                "degrade_s": round(self._degrade_s, 1),
                "degrade_target_s": self.cfg.degrade_sustained_seconds,
                "degrade_since": self._degrading_since,
                "degrade_reason": self._degrade_reason,
            }
