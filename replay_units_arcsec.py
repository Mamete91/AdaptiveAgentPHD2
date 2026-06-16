"""
replay_units_arcsec.py — Replay del FIX unità px→arcsec (§36). I session_*.csv PRE-fix
hanno rms_total in PIXEL. Questo script applica la conversione (× pixel-scale dal
summary) e mostra l'impatto: l'RMS reale in arcsec e il verdetto del gate di rifiuto
baseline PRIMA (px confrontati con soglia arcsec) vs DOPO (arcsec vs arcsec).

Uso: python replay_units_arcsec.py <session.csv> [--summary <summary.json>]
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path

# coerenti col TOML di progetto (gate rifiuto §23)
_REJECT_FACTOR = 3.0
_REJECT_MIN_ARCSEC = 1.50
# cap rms_high (§23)
_CAP_FACTOR = 2.0
_CAP_MIN = 0.70
_CAP_MAX = 1.00
_RMS_HIGH_FACTOR = 1.3


def _pct(v, q):
    s = sorted(v)
    if not s:
        return 0.0
    i = min(len(s) - 1, int(q * len(s)))
    return s[i]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", type=Path)
    ap.add_argument("--summary", type=Path, default=None)
    a = ap.parse_args()

    summ = a.summary or a.csv.with_suffix(".summary.json")
    scale = 0.508
    if summ.exists():
        scale = json.loads(summ.read_text(encoding="utf-8")).get(
            "context", {}).get("pixel_scale_arcsec", scale)

    with open(a.csv, "r", encoding="utf-8", newline="") as f:
        rms_px = [float(r["rms_total"]) for r in csv.DictReader(f) if r.get("rms_total")]

    med_px = statistics.median(rms_px)
    med_as = med_px * scale
    reject = max(_REJECT_MIN_ARCSEC, _REJECT_FACTOR * scale)
    cap = max(_CAP_MIN, min(_CAP_MAX, _CAP_FACTOR * scale))

    # baseline = mediana (proxy). PRE-fix usa px, POST usa arcsec.
    pre_rejected = med_px > reject
    post_rejected = med_as > reject

    sep = "-" * 68
    print(f"\n{sep}\n REPLAY fix unita px->arcsec - {a.csv.name}\n{sep}")
    print(f"  Pixel scale (summary)        : {scale} \"/px")
    print(f"  Frame                        : {len(rms_px)}")
    print(sep)
    print(f"  RMS mediano LOGGATO (px)     : {med_px:.3f}   <- cio' che l'Agente 'vedeva'")
    print(f"  RMS mediano REALE (arcsec)   : {med_as:.3f}\"  <- = {med_px:.2f} x {scale}")
    print(f"  RMS p90 reale / max reale    : {_pct(rms_px,0.9)*scale:.2f}\" / {max(rms_px)*scale:.2f}\"")
    print(sep)
    print(f"  Gate rifiuto baseline        : max({_REJECT_MIN_ARCSEC}, {_REJECT_FACTOR}x{scale}) = {reject:.3f}\"")
    print(f"  PRIMA (baseline px {med_px:.2f} vs {reject:.2f}\")  -> "
          f"{'RIFIUTATA (spuria)' if pre_rejected else 'accettata'}")
    print(f"  DOPO  (baseline {med_as:.2f}\" vs {reject:.2f}\")  -> "
          f"{'rifiutata' if post_rejected else 'ACCETTATA (corretta)'}")
    print(f"  cap rms_high efficace        : {cap:.2f}\"  (rms_high = min({cap:.2f}, 1.3xbaseline))")
    print(sep + "\n")


if __name__ == "__main__":
    main()
