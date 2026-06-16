"""
replay_baseline_formation.py — Replay offline del fix "la baseline deve formarsi
SEMPRE" (§33, prerequisito di P1). Rigioca un session_*.csv e confronta:

  OGGI   : baseline solo da frame condition==NOMINAL -> se non se ne accumulano
           baseline_window_frames (60), baseline = None (controllore senza ancora).
  COL FIX: percorso NOMINAL invariato + FALLBACK (best-fraction della finestra
           'tutti i frame' SNR-validi) -> baseline formata anche nelle notti brutte;
           rms_high resta CAPPATO (1.00"), rms_low cappato sotto rms_high (anti-inv).

Re-implementa in modo trasparente la logica di controller._update_rms_baseline /
_finalize_rms_baseline. NON tocca il codice di produzione.

Uso:
    python replay_baseline_formation.py <session.csv> [--summary <summary.json>]
        [--window 60] [--fallback-frames 180] [--best-fraction 0.33]
        [--min-snr 10] [--ratio-max 0.85] [--fallback-max-cov 0.50]
        [--fallback-reject 4.0]
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import deque
from pathlib import Path

# Default coerenti con AutoCalibrationConfig / Thresholds di progetto.
_RMS_HIGH_FACTOR = 1.3
_RMS_LOW_FACTOR = 0.75
_RMS_HIGH_MAX_FACTOR = 2.0
_RMS_HIGH_MIN_ARCSEC = 0.70
_RMS_HIGH_MAX_ARCSEC = 1.00     # il CAP che NON si tocca
_RMS_LOW_MIN_ARCSEC = 0.25


def _load(csv_path: Path) -> list[dict]:
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _scale_from_summary(summary_path: Path) -> float | None:
    if not summary_path.exists():
        return None
    return json.loads(summary_path.read_text(encoding="utf-8")).get("context", {}).get("pixel_scale_arcsec")


def _derive_thresholds(baseline: float, scale: float, ratio_max: float) -> tuple[float, float, bool, bool]:
    cap = max(_RMS_HIGH_MIN_ARCSEC, min(_RMS_HIGH_MAX_ARCSEC, _RMS_HIGH_MAX_FACTOR * scale))
    derived_high = _RMS_HIGH_FACTOR * baseline
    rms_high = min(cap, derived_high)
    capped = derived_high > cap
    rms_low = max(_RMS_LOW_MIN_ARCSEC, _RMS_LOW_FACTOR * baseline)
    inv = False
    inv_cap = rms_high * ratio_max
    if rms_low > inv_cap:
        rms_low = inv_cap
        inv = True
    return rms_high, rms_low, capped, inv


def replay(csv_path: Path, summary_path: Path | None, window: int, fallback_frames: int,
           best_fraction: float, min_snr: float, ratio_max: float,
           fallback_max_cov: float, fallback_reject: float) -> dict:
    rows = _load(csv_path)
    summary_path = summary_path or csv_path.with_suffix(".summary.json")
    scale = _scale_from_summary(summary_path) or 0.508

    nominal_samples: list[float] = []
    all_samples: deque[float] = deque(maxlen=max(1, fallback_frames))
    frames_seen = 0
    result_path = None       # "NOMINAL" | "FALLBACK" | None
    baseline = None
    rms_high = rms_low = None
    capped = inv = False

    n_nominal_total = 0      # quanti frame NOMINAL SNR-validi in tutta la sessione (diagnosi OGGI)

    for r in rows:
        rms = float(r["rms_total"])
        snr = float(r.get("snr_avg", 0.0) or 0.0)
        cond = r.get("condition", "")
        snr_ok = snr >= min_snr
        if not snr_ok:
            continue
        if cond == "NOMINAL":
            n_nominal_total += 1

        if result_path is not None:
            continue   # baseline gia' formata: smetti (come done=True)

        if cond == "NOMINAL":
            nominal_samples.append(rms)
        all_samples.append(rms)
        frames_seen += 1

        if len(nominal_samples) >= window:
            baseline = statistics.median(nominal_samples)
            result_path = "NOMINAL"
        elif frames_seen >= fallback_frames and len(all_samples) >= window:
            srt = sorted(all_samples)
            k = max(1, int(len(srt) * best_fraction))
            best = srt[:k]
            cand = statistics.median(best)
            best_mean = statistics.mean(best)
            cov = (statistics.pstdev(best) / best_mean) if best_mean > 1e-9 else 0.0
            if cov > fallback_max_cov or cand > fallback_reject:
                # rifiutata: continua a cercare (in realta' done=True nel codice, ma per il
                # replay segnaliamo il rifiuto e ci fermiamo come fa il controller)
                result_path = "FALLBACK_REJECTED"
                baseline = cand
                break
            baseline = cand
            result_path = "FALLBACK"

    if result_path in ("NOMINAL", "FALLBACK"):
        rms_high, rms_low, capped, inv = _derive_thresholds(baseline, scale, ratio_max)

    # Comportamento OGGI: forma solo se n_nominal_total >= window
    today_baseline = "FORMATA" if n_nominal_total >= window else "None"

    return {
        "csv": csv_path.name, "scale": scale, "frames": len(rows),
        "nominal_total": n_nominal_total, "window": window,
        "today": today_baseline,
        "fix_path": result_path, "baseline": baseline,
        "rms_high": rms_high, "rms_low": rms_low, "capped": capped, "inv": inv,
    }


def _report(res: dict) -> None:
    sep = "-" * 68
    print(f"\n{sep}\n REPLAY baseline-sempre-formata - {res['csv']}\n{sep}")
    print(f"  Frame totali              : {res['frames']}")
    print(f"  Pixel scale               : {res['scale']} \"/px")
    print(f"  Frame NOMINAL (SNR-validi): {res['nominal_total']}  (servono {res['window']})")
    print(sep)
    print(f"  OGGI  -> baseline         : {res['today']}"
          + ("  (mai abbastanza frame NOMINAL)" if res["today"] == "None" else ""))
    if res["fix_path"] in ("NOMINAL", "FALLBACK"):
        print(f"  FIX   -> baseline         : {res['baseline']:.3f}\"  (via {res['fix_path']})")
        print(f"           rms_high         : {res['rms_high']:.3f}\""
              + ("  [CAP 1.00 invariato]" if res["capped"] else ""))
        print(f"           rms_low          : {res['rms_low']:.3f}\""
              + ("  [ANTI-INVERSIONE]" if res["inv"] else "")
              + f"   (rms_low < rms_high: {res['rms_low'] < res['rms_high']})")
    elif res["fix_path"] == "FALLBACK_REJECTED":
        print(f"  FIX   -> baseline         : RIFIUTATA (instabile/oltre tetto), "
              f"candidata {res['baseline']:.3f}\"")
    else:
        print("  FIX   -> baseline         : non formata (frame insufficienti)")
    print(sep + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="Replay offline baseline-sempre-formata (§33)")
    ap.add_argument("csv", type=Path)
    ap.add_argument("--summary", type=Path, default=None)
    ap.add_argument("--window", type=int, default=60)
    ap.add_argument("--fallback-frames", type=int, default=180)
    ap.add_argument("--best-fraction", type=float, default=0.33)
    ap.add_argument("--min-snr", type=float, default=10.0)
    ap.add_argument("--ratio-max", type=float, default=0.85)
    ap.add_argument("--fallback-max-cov", type=float, default=0.50)
    ap.add_argument("--fallback-reject", type=float, default=4.0)
    a = ap.parse_args()
    res = replay(a.csv, a.summary, a.window, a.fallback_frames, a.best_fraction,
                 a.min_snr, a.ratio_max, a.fallback_max_cov, a.fallback_reject)
    _report(res)


if __name__ == "__main__":
    main()
