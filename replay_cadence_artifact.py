"""
replay_cadence_artifact.py — Replay del problema "cadenza loop / baseline lenta /
INSUFFICIENT artefatto" (§34). Rigioca un session_*.csv prodotto dal codice PRE-fix e
mostra che l'~85% INSUFFICIENT e' un ARTEFATTO di logging/cadenza, non vera paralisi:
le righe fuori-tick (evaluate non gira: ~1 frame su 5) escono con placeholder
(exposure_ms=0, diag_state=INSUFFICIENT). Ricalcola la % INSUFFICIENT REALE (solo
frame valutati, proxy = exposure_ms != 0) e stima il tempo-baseline col fix.

Uso: python replay_cadence_artifact.py <session.csv> [--fallback-frames 180]
"""
from __future__ import annotations

import argparse
import csv
import statistics
from pathlib import Path


def replay(csv_path: Path, fallback_frames: int) -> dict:
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    n = len(rows)

    def is_insuff(r):
        return r.get("diag_state", "") == "INSUFFICIENT_DATA"

    def exp(r):
        try:
            return float(r.get("exposure_ms", 0) or 0)
        except ValueError:
            return 0.0

    tick_rows = [r for r in rows if exp(r) != 0.0]          # frame valutati (proxy)
    offtick_rows = [r for r in rows if exp(r) == 0.0]       # righe fuori-tick (placeholder)

    insuff_all = sum(is_insuff(r) for r in rows)
    insuff_tick = sum(is_insuff(r) for r in tick_rows)

    # intervallo frame (mediana dei delta ts) e frame-per-tick
    ts = []
    for r in rows:
        try:
            ts.append(float(r["ts"]))
        except (KeyError, ValueError):
            pass
    deltas = [b - a for a, b in zip(ts, ts[1:]) if 0 < (b - a) < 60]
    frame_dt = statistics.median(deltas) if deltas else 0.0
    frames_per_tick = (n / len(tick_rows)) if tick_rows else 0.0

    # tempo-baseline: fallback §33 conta i guide-frame (col fix) vs i tick (oggi)
    t_new = fallback_frames * frame_dt
    t_old = fallback_frames * frame_dt * frames_per_tick

    return {
        "csv": csv_path.name, "frames": n,
        "tick": len(tick_rows), "offtick": len(offtick_rows),
        "insuff_all_pct": 100.0 * insuff_all / n if n else 0.0,
        "insuff_tick_pct": 100.0 * insuff_tick / len(tick_rows) if tick_rows else 0.0,
        "frame_dt": frame_dt, "frames_per_tick": frames_per_tick,
        "t_old_min": t_old / 60.0, "t_new_min": t_new / 60.0,
        "fallback_frames": fallback_frames,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", type=Path)
    ap.add_argument("--fallback-frames", type=int, default=180)
    a = ap.parse_args()
    r = replay(a.csv, a.fallback_frames)
    sep = "-" * 70
    print(f"\n{sep}\n REPLAY cadenza/artefatto INSUFFICIENT - {r['csv']}\n{sep}")
    print(f"  Frame totali (righe CSV)        : {r['frames']}")
    print(f"  Frame VALUTATI (exposure!=0)    : {r['tick']}")
    print(f"  Righe FUORI-TICK (exposure=0)   : {r['offtick']}  "
          f"({100.0*r['offtick']/r['frames']:.0f}%)")
    print(sep)
    print(f"  INSUFFICIENT su TUTTE le righe  : {r['insuff_all_pct']:.0f}%   <- artefatto")
    print(f"  INSUFFICIENT sui frame VALUTATI : {r['insuff_tick_pct']:.0f}%   <- comportamento REALE")
    print(sep)
    print(f"  Intervallo frame (mediana)      : {r['frame_dt']:.2f}s")
    print(f"  Frame per tick valutazione      : {r['frames_per_tick']:.1f}")
    print(f"  Tempo baseline OGGI (per-tick)  : ~{r['t_old_min']:.1f} min "
          f"({r['fallback_frames']} tick)")
    print(f"  Tempo baseline COL FIX (frame)  : ~{r['t_new_min']:.1f} min "
          f"({r['fallback_frames']} guide-frame)")
    print(sep + "\n")


if __name__ == "__main__":
    main()
