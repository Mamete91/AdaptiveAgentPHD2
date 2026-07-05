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
from collections import deque
from typing import Any, Optional


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
    ) -> None:
        self.enabled = bool(enabled)
        self.window = max(1, int(baseline_window_subs))
        self.base_best_fraction = float(base_best_fraction)
        self.clear_above = float(clear_above)
        self.cloud_below = float(cloud_below)
        self.hysteresis = float(hysteresis)
        self.deadband_deficit = float(deadband_deficit)

        self._lock = threading.Lock()
        self._stars_by_filter: dict[str, deque] = {}   # filtro -> finestra mobile star_count
        self._bkg_by_filter: dict[str, deque] = {}      # filtro -> finestra mobile median_adu
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

        with self._lock:
            stars = self._stars_by_filter.setdefault(filt, deque(maxlen=self.window))
            bkgs = self._bkg_by_filter.setdefault(filt, deque(maxlen=self.window))
            stars.append(sc)
            if bkg is not None:
                bkgs.append(bkg)

            # Riferimento RELATIVO = rolling-high (mediana del best-fraction più ALTO della
            # finestra) = "cielo più limpido recente per questo filtro". Include il campione
            # corrente ma il best-fraction-high ignora un singolo crollo -> un calo rapido
            # resta confrontato col limpido recente (CLOUD), un livello basso STABILE no.
            srt = sorted(stars, reverse=True)
            k = max(1, int(len(srt) * self.base_best_fraction))
            base_stars = statistics.median(srt[:k])
            # Fondo di riferimento = cielo più scuro recente (min robusto = best-fraction basso).
            base_bkg = None
            if bkgs:
                srt_b = sorted(bkgs)
                kb = max(1, int(len(srt_b) * self.base_best_fraction))
                base_bkg = statistics.median(srt_b[:kb])

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

            self._state = self._next_state(index, self._state)
            self._filter = filt
            self._index = index
            self._deficit = deficit
            self._base_stars = base_stars
            self._last_star = sc
            self._last_bkg = bkg

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
