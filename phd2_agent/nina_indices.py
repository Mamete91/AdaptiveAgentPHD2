"""
nina_indices.py — Layer-2: indici derivati dalla telemetria NINA (§45, N1).

Transparency Index: un segnale di trasparenza del cielo ORTOGONALE a PHD2, ricavato
dal conteggio stelle e dal fondo cielo della camera di RIPRESA (centinaia di stelle),
che PHD2 — vedendo solo la stella di guida — non può dare.

Principio (anti soglie assolute): il riferimento è SEMPRE RELATIVO al campo+filtro
corrente — "cielo più limpido recente per QUESTO filtro" (rolling-high best-fraction
su finestra mobile). Conseguenze volute:
  • campo POVERO ma stabile (poche stelle, livello costante) -> TI ~ 1 -> CLEAR
    (NON deve scattare: nessun numero assoluto entra in alcuna decisione);
  • calo % RAPIDO del conteggio stelle (velature/nubi) -> TI scende -> HAZE/CLOUD
    (il riferimento rolling-high "ricorda" il cielo limpido recente e lagga il crollo).
NIENTE HFR qui (domini separati: HFR = fuoco/seeing, non trasparenza — vedi N3/N4).

Layer-2 PURO: NON modifica lo store Layer-1 (§41/§42). Thread-safe (ingest dal thread
uvicorn sul POST; letture da /status e dal motore sul thread di guida).
"""
from __future__ import annotations

import statistics
import threading
import time
from collections import deque
from typing import Any, Callable, Optional

_DEGRADED = ("HAZE", "CLOUD")
_MAX_RELEASE_DT_MIN = 240.0   # assenza lunga di un filtro: rilascio praticamente completo


class TransparencyTracker:
    """Calcola e mantiene il Transparency Index (N1) per-filtro, su finestra mobile."""

    def __init__(
        self,
        enabled: bool = True,
        baseline_window_subs: int = 12,
        base_best_fraction: float = 0.5,
        clear_above: float = 0.8,
        cloud_below: float = 0.5,
        hysteresis: float = 0.05,
        deadband_deficit: float = 0.10,
        ref_ratchet_enabled: bool = True,
        ref_release_half_life_min: float = 25.0,
        ref_freeze_max_min: float = 90.0,
        ref_session_floor_frac: float = 0.70,
        now_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self.enabled = bool(enabled)
        self.window = max(1, int(baseline_window_subs))
        self.base_best_fraction = float(base_best_fraction)
        self.clear_above = float(clear_above)
        self.cloud_below = float(cloud_below)
        self.hysteresis = float(hysteresis)
        self.deadband_deficit = float(deadband_deficit)
        # §66 — cricchetto anti "rana bollita" (vedi _ratchet).
        self.ref_ratchet_enabled = bool(ref_ratchet_enabled)
        self.ref_release_half_life_min = float(ref_release_half_life_min)
        self.ref_freeze_max_min = float(ref_freeze_max_min)
        self.ref_session_floor_frac = float(ref_session_floor_frac)
        self._now = now_fn                              # iniettabile nei test (clock finto)
        self._degraded_since: Optional[float] = None    # inizio dell'evento degradato corrente
        self._target: Optional[str] = None              # §67 — target corrente (da NINA)
        self._last_airmass: Optional[float] = None      # §67 — solo telemetria

        self._lock = threading.Lock()
        self._stars_by_filter: dict[str, deque] = {}   # filtro -> finestra mobile star_count
        self._bkg_by_filter: dict[str, deque] = {}      # filtro -> finestra mobile median_adu
        # §66 — riferimenti PERSISTENTI per filtro (il cricchetto vive qui, non nella
        # finestra) + high-water di sessione, puramente DIAGNOSTICO.
        self._ref_stars_by_filter: dict[str, float] = {}
        self._ref_bkg_by_filter: dict[str, float] = {}
        self._best_stars_by_filter: dict[str, float] = {}
        self._last_ts_by_filter: dict[str, float] = {}
        # Ultimo esito calcolato (per /status e per il motore N8).
        self._filter: Optional[str] = None
        self._index: Optional[float] = None
        self._state: Optional[str] = None       # "CLEAR" | "HAZE" | "CLOUD"
        self._deficit: float = 0.0
        self._confirmed_subs: int = 0
        self._base_stars: Optional[float] = None
        self._last_star: Optional[float] = None
        self._last_bkg: Optional[float] = None

    # ------------------------------------------------------------------ #
    #  Ingest (per-posa)                                                  #
    # ------------------------------------------------------------------ #

    def ingest(self, payload: dict) -> None:
        """Aggiorna gli indici da un payload §41 (model_dump). No-op se disabilitato o
        se il frame non ha una star detection usabile (niente indice spazzatura)."""
        if not self.enabled:
            return
        img = (payload or {}).get("image") or {}
        sc = img.get("star_count")
        if not isinstance(sc, (int, float)) or sc < 0:
            return   # frame senza star detection -> non sporchiamo l'indice
        sc = float(sc)
        filt = img.get("filter") or ""
        bkg = img.get("median_adu")
        bkg = float(bkg) if isinstance(bkg, (int, float)) and bkg > 0 else None
        am = img.get("airmass")
        am = float(am) if isinstance(am, (int, float)) and am > 0 else None

        # §67 — il TARGET arriva da NINA (`context.target`): il cambio campo diventa un
        # fatto NOTO invece che un'inferenza sul conteggio stelle. La baseline è quindi
        # indicizzata per (target, filtro): un target nuovo parte con la SUA storia (e
        # tornando su un target già visto se ne ritrova la baseline, gratis).
        # Retrocompat: plugin vecchio / riprese manuali -> target assente -> chiave ("",
        # filtro) = identica al comportamento §45/§66.
        target = ((payload or {}).get("context") or {}).get("target") or ""
        target = target.strip() if isinstance(target, str) else ""
        key = (target, filt)

        with self._lock:
            stars = self._stars_by_filter.setdefault(key, deque(maxlen=self.window))
            bkgs = self._bkg_by_filter.setdefault(key, deque(maxlen=self.window))
            stars.append(sc)
            if bkg is not None:
                bkgs.append(bkg)

            # CANDIDATO = rolling-high (mediana del best-fraction più ALTO della finestra)
            # = "cielo più limpido recente per questo filtro". Include il campione corrente
            # ma il best-fraction-high ignora un singolo crollo -> un calo rapido resta
            # confrontato col limpido recente (CLOUD), un livello basso STABILE no.
            srt = sorted(stars, reverse=True)
            k = max(1, int(len(srt) * self.base_best_fraction))
            cand_stars = statistics.median(srt[:k])
            # Fondo candidato = cielo più scuro recente (min robusto = best-fraction basso).
            cand_bkg = None
            if bkgs:
                srt_b = sorted(bkgs)
                kb = max(1, int(len(srt_b) * self.base_best_fraction))
                cand_bkg = statistics.median(srt_b[:kb])

            # §66 — il RIFERIMENTO non è il candidato: ci passa attraverso il cricchetto,
            # che impedisce l'auto-erosione lenta ("rana bollita", osservata sul cielo
            # 2026-07-20). prev_state è lo stato PRIMA di questa posa: se il cielo è già
            # riconosciuto degradato il riferimento non scende di un ADU.
            prev_state = self._state
            now = self._now()
            last_ts = self._last_ts_by_filter.get(key)
            dt_min = None if last_ts is None else max(0.0, (now - last_ts) / 60.0)
            self._last_ts_by_filter[key] = now

            # High-water di SESSIONE per (target, filtro) — aggiornato PRIMA del cricchetto
            # perché ne è il pavimento. §67: con la chiave per target il massimo di sessione
            # non è più pericoloso (un campo nuovo ha una chiave nuova, quindi un high-water
            # nuovo) e può quindi PROMUOVERSI da diagnostico a vincolo operativo.
            hw = self._best_stars_by_filter.get(key)
            self._best_stars_by_filter[key] = cand_stars if hw is None else max(hw, cand_stars)

            base_stars = self._ratchet(self._ref_stars_by_filter, key, cand_stars,
                                       prev_state, dt_min, higher_is_better=True,
                                       session_best=self._best_stars_by_filter[key])
            base_bkg = (self._ratchet(self._ref_bkg_by_filter, key, cand_bkg,
                                      prev_state, dt_min, higher_is_better=False)
                        if cand_bkg is not None else None)

            star_ratio = (sc / base_stars) if base_stars and base_stars > 0 else 1.0
            bkg_factor = 1.0
            if base_bkg is not None and bkg is not None and bkg > 0:
                bkg_factor = base_bkg / bkg   # fondo che SALE (più chiaro) -> < 1 (secondario)
            index = max(0.0, min(1.0, star_ratio * bkg_factor))
            deficit = max(0.0, 1.0 - star_ratio)   # calo % vs riferimento del campo

            # confirmed_subs: pose CONSECUTIVE con calo oltre la dead-band (anti singolo
            # frame anomalo: satellite/raffica/bordo nube transitorio). È il TREND, non il frame.
            if deficit > self.deadband_deficit:
                self._confirmed_subs += 1
            else:
                self._confirmed_subs = 0

            self._target = target or None
            self._last_airmass = am
            self._state = self._next_state(index, self._state)
            # §66 — durata dell'evento degradato corrente (governa il tetto al congelamento).
            if self._state in _DEGRADED:
                if self._degraded_since is None:
                    self._degraded_since = now
            else:
                self._degraded_since = None
            self._filter = filt
            self._index = index
            self._deficit = deficit
            self._base_stars = base_stars
            self._last_star = sc
            self._last_bkg = bkg

    def _ref_drift_pct(self) -> Optional[float]:
        """§66 — quanto il riferimento operativo è sotto il meglio della serata (stesso
        filtro), in %. 0 = siamo al meglio della notte; valori alti = il metro si è
        spostato (o le condizioni sono calate stabilmente). Solo osservazione."""
        key = (self._target or "", self._filter or "")
        best = self._best_stars_by_filter.get(key)
        ref = self._ref_stars_by_filter.get(key)
        if not best or best <= 0 or ref is None:
            return None
        return round(max(0.0, (1.0 - ref / best)) * 100.0, 1)

    def _ratchet(self, refs: dict, key: tuple, candidate: float,
                 prev_state: Optional[str], dt_min: Optional[float],
                 higher_is_better: bool, session_best: Optional[float] = None) -> float:
        """§66 — riferimento a CRICCHETTO (anti "rana bollita").

        Il riferimento rolling-high puro seguiva il cielo ANCHE verso il basso: in un
        degrado lento il denominatore scendeva insieme al numeratore, l'indice restava
        ~1.00 e il cielo peggiorava senza che nulla lo dicesse (osservato in diretta il
        2026-07-20). Le tre regole, in ordine di precedenza:

          1. MIGLIORAMENTO -> adottato SUBITO. Le nubi non creano stelle: un candidato
             migliore è sempre evidenza legittima, non serve prudenza.
          2. Stato già DEGRADATO (HAZE/CLOUD) -> riferimento CONGELATO. Durante un evento
             il metro di paragone non si tocca: è la regola che impedisce al cielo di
             "riscrivere la propria normalità" mentre sta peggiorando (stessa disciplina
             di snr_ref in §57, congelato fuori da CLEAR). Il congelamento ha però un
             TETTO (`ref_freeze_max_min`): un degrado che dura più a lungo di qualunque
             passaggio nuvoloso plausibile non è un evento ma la nuova normalità (cambio
             di campo, Luna alta), e senza il tetto il riferimento resterebbe bloccato
             PER SEMPRE — stallo trovato dal banco di prova prima del rilascio.
          3. PEGGIORAMENTO a cielo sereno -> RILASCIO LENTO verso il candidato, con
             emivita configurabile e misurata in TEMPO REALE (§57-bis: mai in campioni —
             il comportamento non deve dipendere dalla durata dei sub). Serve ad adattarsi
             ai cali LEGITTIMI e irreversibili (target che scende, sorgere della Luna,
             cambio di campo) senza mai creare una soglia irraggiungibile.

        `higher_is_better`: True per il conteggio stelle, False per il fondo cielo (più
        scuro = meglio), così il cricchetto vale in entrambi i domini.
        """
        ref = refs.get(key)
        if ref is None or not self.ref_ratchet_enabled:
            refs[key] = candidate           # primo campione, o kill-switch: comportamento §45
            return candidate

        improved = candidate >= ref if higher_is_better else candidate <= ref
        if improved:
            refs[key] = candidate           # regola 1
            return candidate
        if prev_state in _DEGRADED and self._degraded_since is not None:
            frozen_min = (self._now() - self._degraded_since) / 60.0
            if frozen_min < self.ref_freeze_max_min:
                return ref                  # regola 2 — congelato durante l'evento
        if dt_min is not None and self.ref_release_half_life_min > 0:
            decay = 0.5 ** (min(dt_min, _MAX_RELEASE_DT_MIN) / self.ref_release_half_life_min)
            ref = candidate + (ref - candidate) * decay     # regola 3

        # Regola 4 (§67) — PAVIMENTO di sessione: il riferimento non scende sotto una
        # frazione del meglio della notte PER QUESTO (target, filtro). È il rilascio
        # temporale a essere illimitato nel tempo: senza pavimento, un degrado
        # sufficientemente lento erode il riferimento all'infinito. Con la chiave per
        # target il vincolo è sicuro (un campo nuovo ha un high-water nuovo) e i cali
        # LEGITTIMI restano dentro il margine: l'estinzione per airmass a queste altezze
        # vale pochi punti percentuali, molto meno del pavimento.
        if (session_best is not None and higher_is_better
                and 0.0 < self.ref_session_floor_frac <= 1.0):
            ref = max(ref, session_best * self.ref_session_floor_frac)

        refs[key] = ref
        return ref

    def _next_state(self, index: float, prev: Optional[str]) -> str:
        """Stato con isteresi: per LASCIARE uno stato migliore serve superare la soglia
        di un margine (anti-flicker sui bordi)."""
        h = self.hysteresis
        if prev == "CLEAR":
            if index < self.cloud_below - h:
                return "CLOUD"
            if index < self.clear_above - h:
                return "HAZE"
            return "CLEAR"
        if prev == "CLOUD":
            if index >= self.clear_above + h:
                return "CLEAR"
            if index >= self.cloud_below + h:
                return "HAZE"
            return "CLOUD"
        # da HAZE o stato iniziale: soglie nominali
        if index >= self.clear_above:
            return "CLEAR"
        if index < self.cloud_below:
            return "CLOUD"
        return "HAZE"

    # ------------------------------------------------------------------ #
    #  Letture                                                            #
    # ------------------------------------------------------------------ #

    def status_block(self) -> dict[str, Any]:
        """Blocco `nina.transparency` per /status. Numeri relativi + ultimo grezzo."""
        with self._lock:
            return {
                "enabled": self.enabled,
                "available": self._index is not None,
                "index": round(self._index, 3) if self._index is not None else None,
                "state": self._state,
                "deficit_pct": round(self._deficit * 100.0, 1) if self._index is not None else None,
                "confirmed_subs": self._confirmed_subs,
                "base_stars": round(self._base_stars, 1) if self._base_stars is not None else None,
                # §66 — osservabilità della deriva: il meglio della serata per QUESTO filtro
                # e di quanto il riferimento operativo se ne è allontanato. Diagnostico puro.
                "base_stars_session_best": (
                    round(self._best_stars_by_filter[(self._target or "", self._filter or "")], 1)
                    if (self._target or "", self._filter or "") in self._best_stars_by_filter
                    else None),
                "ref_drift_pct": self._ref_drift_pct(),
                # §67 — contesto noto a NINA (target) e geometria (airmass, SOLO telemetria).
                "target": self._target,
                "airmass": round(self._last_airmass, 3) if self._last_airmass is not None else None,
                "star_count": self._last_star,
                "bkg": self._last_bkg,
                "background": self._last_bkg,   # §48 — alias del contratto consumatori (N6)
                "filter": self._filter,
            }

    def confidence_input(self) -> Optional[dict]:
        """Input per la fusione N8 (§46). None se nessun dato. La FRESCHEZZA è decisa a
        monte (dal controller via lo store §43): qui solo i valori derivati."""
        with self._lock:
            if self._index is None:
                return None
            return {
                "index": self._index,
                "state": self._state,
                "deficit": self._deficit,
                "confirmed_subs": self._confirmed_subs,
            }
