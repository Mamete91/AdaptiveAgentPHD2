"""
replay_minmove_recovery.py — Replay offline del recupero MinMove (§32, asimmetria
leve §4). Rigioca un session_*.csv prodotto dall'Agente e conta quante volte MinMove
SAREBBE risalito nella banda morta con il fix attivo, contro le ZERO risalite di oggi
(la catena CASO v2.3 non muove MinMove nella banda morta rms_low<rms<rms_high).

NON tocca il codice di produzione: re-implementa, in modo trasparente, la stessa
macchina a stati di controller.py (`_update_recovery_state`, ramo RECOVERY in
`_evaluate_axis`, `_finalize_recovery_windup`). Serve solo a validare il fix sui log
storici PRIMA del campo, come richiesto dal prompt.

Uso:
    python replay_minmove_recovery.py <session.csv> [--summary <summary.json>]
                                      [--start-minmove 0.15] [--recovery-factor 1.0]
                                      [--no-progress-k 3] [--consecutive-frames 5]
                                      [--cooldown-s 30]

Note di modellazione (esplicitate apposta):
  * La mediana baseline e la pixel scale sono lette dal summary.json affiancato al CSV
    (campo context.baseline_rms_median); se assente, la mediana e' stimata come mediana
    di rms_total sui frame NOMINAL del log (approssimazione, segnalata in output).
  * Ogni riga CSV (un GuideStep) e' trattata come un tick di valutazione. La cadenza
    reale (interval_seconds) puo' essere piu' lenta del logging per-frame: il fattore
    limitante dominante resta comunque il cooldown del MinMove (1.5x cooldown_seconds),
    qui applicato sui timestamp reali (colonna ts).
  * Soglie rms_high/rms_low: lette per-frame dal CSV (rms_high_active/rms_low_active).
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path

_RECOVERY_PROGRESS_EPS = 0.01   # identico a controller._RECOVERY_PROGRESS_EPS
_MINMOVE_MIN = 0.15
_MINMOVE_MAX = 0.85
_MINMOVE_STEP = 0.05


def _load_rows(csv_path: Path) -> list[dict]:
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _baseline_from_summary(summary_path: Path) -> tuple[float | None, float | None]:
    if not summary_path.exists():
        return None, None
    data = json.loads(summary_path.read_text(encoding="utf-8"))
    ctx = data.get("context", {})
    return ctx.get("baseline_rms_median"), ctx.get("pixel_scale_arcsec")


def _estimate_median(rows: list[dict]) -> float:
    nominal = [float(r["rms_total"]) for r in rows if r.get("condition") == "NOMINAL"]
    pool = nominal or [float(r["rms_total"]) for r in rows]
    return statistics.median(pool) if pool else 0.0


def replay(csv_path: Path, summary_path: Path | None, start_minmove: float,
           recovery_factor: float, no_progress_k: int, consecutive_frames: int,
           cooldown_s: float) -> dict:
    rows = _load_rows(csv_path)
    summary_path = summary_path or csv_path.with_suffix(".summary.json")
    median, pixel_scale = _baseline_from_summary(summary_path)
    median_source = "summary.json"
    if median is None:
        median = _estimate_median(rows)
        median_source = "stima da rms_total NOMINAL (summary assente)"

    threshold = median * recovery_factor
    minmove_cooldown = cooldown_s * 1.5

    # Stato della macchina (specchio di controller.py)
    consec = 0
    minmove = start_minmove
    last_action_ts = float("-inf")
    anchor_rms: float | None = None
    actions_since_anchor = 0
    blocked = False

    n_total = len(rows)
    n_deadband = 0          # rms_low < rms < rms_high (definizione del prompt/rationale)
    n_eligible = 0          # banda morta E rms > mediana (recupero potenziale)
    n_recovery = 0          # risalite MinMove effettivamente applicate dal fix
    n_caso1 = 0             # frame rms > rms_high (dove SOLO oggi MinMove puo' risalire)
    n_windup_stops = 0
    minmove_trace_max = start_minmove

    for r in rows:
        rms = float(r["rms_total"])
        rms_high = float(r["rms_high_active"])
        rms_low = float(r["rms_low_active"])
        ts = float(r["ts"])
        condition = r.get("condition", "")

        if rms_low < rms < rms_high:
            n_deadband += 1
        if rms >= rms_high:
            n_caso1 += 1

        # _update_recovery_state (per tick)
        if rms > threshold:
            consec += 1
        else:
            consec = 0
            anchor_rms = None
            actions_since_anchor = 0
            blocked = False

        # ramo RECOVERY: solo nella banda morta (non CASO 1: rms>=rms_high; non CASO 3:
        # rms<=rms_low; non CASO 2: OSCILLATING) e sopra la mediana.
        in_band = (rms < rms_high) and (rms > rms_low) and (condition != "OSCILLATING")
        eligible = in_band and (rms > threshold)
        if eligible:
            n_eligible += 1

        applied = False
        if (not blocked and consec >= consecutive_frames and eligible
                and minmove < _MINMOVE_MAX
                and (ts - last_action_ts) >= minmove_cooldown):
            minmove = round(min(_MINMOVE_MAX, minmove + _MINMOVE_STEP), 4)
            last_action_ts = ts
            applied = True
            n_recovery += 1
            minmove_trace_max = max(minmove_trace_max, minmove)

        # _finalize_recovery_windup (anti-windup, una volta per tick)
        if applied:
            if anchor_rms is None:
                anchor_rms = rms
                actions_since_anchor = 1
            else:
                actions_since_anchor += 1
                if actions_since_anchor >= max(1, no_progress_k):
                    if rms < anchor_rms - _RECOVERY_PROGRESS_EPS:
                        anchor_rms = rms
                        actions_since_anchor = 0
                    else:
                        blocked = True
                        n_windup_stops += 1

    return {
        "csv": csv_path.name,
        "frames": n_total,
        "median": median,
        "median_source": median_source,
        "pixel_scale": pixel_scale,
        "threshold": threshold,
        "deadband_frames": n_deadband,
        "deadband_pct": 100.0 * n_deadband / n_total if n_total else 0.0,
        "eligible_frames": n_eligible,
        "recovery_actions_with_fix": n_recovery,
        "recovery_actions_today": 0,            # nella banda morta oggi: ZERO
        "caso1_frames_rms_above_high": n_caso1,
        "windup_stops": n_windup_stops,
        "final_minmove": minmove,
        "max_minmove_reached": minmove_trace_max,
        "start_minmove": start_minmove,
    }


def _print_report(res: dict) -> None:
    sep = "-" * 66
    print(f"\n{sep}\n REPLAY recupero MinMove - {res['csv']}\n{sep}")
    print(f"  Frame totali              : {res['frames']}")
    ps = res["pixel_scale"]
    print(f"  Pixel scale               : {ps if ps is not None else '?'} \"/px")
    print(f"  Mediana baseline          : {res['median']:.4f}\"  ({res['median_source']})")
    print(f"  Soglia recupero (med x fac): {res['threshold']:.4f}\"")
    print(f"  Banda morta (rms_low<rms<rms_high): {res['deadband_frames']} "
          f"({res['deadband_pct']:.0f}%)")
    print(f"  Frame eleggibili (banda morta & rms>mediana): {res['eligible_frames']}")
    print(sep)
    print(f"  >> Risalite MinMove CON IL FIX  : {res['recovery_actions_with_fix']}")
    print(f"  >> Risalite MinMove OGGI (banda morta): {res['recovery_actions_today']}")
    print(f"     (oggi MinMove risale solo su rms>rms_high: {res['caso1_frames_rms_above_high']} "
          f"frame sopra soglia alta)")
    print(f"  Stop anti-windup           : {res['windup_stops']}")
    print(f"  MinMove {res['start_minmove']:.2f} -> {res['final_minmove']:.2f} "
          f"(max raggiunto {res['max_minmove_reached']:.2f})")
    print(sep + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="Replay offline recupero MinMove (§32)")
    ap.add_argument("csv", type=Path, help="session_*.csv da rigiocare")
    ap.add_argument("--summary", type=Path, default=None, help="summary.json (default: affiancato al CSV)")
    ap.add_argument("--start-minmove", type=float, default=_MINMOVE_MIN)
    ap.add_argument("--recovery-factor", type=float, default=1.0)
    ap.add_argument("--no-progress-k", type=int, default=3)
    ap.add_argument("--consecutive-frames", type=int, default=5)
    ap.add_argument("--cooldown-s", type=float, default=30.0)
    args = ap.parse_args()

    res = replay(args.csv, args.summary, args.start_minmove, args.recovery_factor,
                 args.no_progress_k, args.consecutive_frames, args.cooldown_s)
    _print_report(res)


if __name__ == "__main__":
    main()
