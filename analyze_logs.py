"""
analyze_logs.py — CLI per analisi offline dei log nativi di PHD2.

Uso:
    python analyze_logs.py                          # Cerca log in Documenti\PHD2
    python analyze_logs.py --dir "C:\PHD2\Logs"    # Cartella personalizzata
    python analyze_logs.py --file log.txt           # File singolo
    python analyze_logs.py --summary                # Solo statistiche aggregate
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from phd2_log import PHD2LogParser, PHD2LogWatcher


def parse_args():
    p = argparse.ArgumentParser(description="PHD2 Log Analyzer — analisi offline dei guide log")
    p.add_argument("--dir",     default=None, help="Cartella log PHD2 (default: Documenti\\PHD2)")
    p.add_argument("--file",    default=None, help="Singolo file .txt da analizzare")
    p.add_argument("--out",     default="phd2_log", help="Cartella output JSON (default: phd2_log)")
    p.add_argument("--summary", action="store_true", help="Stampa solo le statistiche aggregate")
    p.add_argument("--force",   action="store_true", help="Rielabora anche i file già processati")
    p.add_argument("--watch",   action="store_true", help="Modalità watch: aspetta nuovi file")
    return p.parse_args()


def print_session_stats(stats: dict, idx: int = 0) -> None:
    sep = "─" * 60
    print(f"\n{sep}")
    print(f" Sessione #{idx}  |  {stats.get('source_file', '?')}")
    print(sep)
    print(f"  Durata     : {stats.get('duration_minutes', 0):.1f} min")
    print(f"  Frame      : {stats.get('total_frames', 0)}")
    print(f"  RMS RA     : {stats.get('rms_ra_arcsec', 0):.4f}\"")
    print(f"  RMS Dec    : {stats.get('rms_dec_arcsec', 0):.4f}\"")
    print(f"  RMS totale : {stats.get('rms_total_arcsec', 0):.4f}\"")
    print(f"  Peak RA    : {stats.get('peak_ra_arcsec', 0):.4f}\"")
    print(f"  Peak Dec   : {stats.get('peak_dec_arcsec', 0):.4f}\"")
    if stats.get("snr_avg"):
        print(f"  SNR medio  : {stats['snr_avg']:.1f}")
    if stats.get("hfd_avg"):
        print(f"  HFD medio  : {stats['hfd_avg']:.2f}")
    print(f"  Scala pix  : {stats.get('pixel_scale_arcsec_px', 0):.3f} arcsec/px")
    print(f"  Algo RA    : {stats.get('ra_algo', '?')}")
    print(f"  Algo Dec   : {stats.get('dec_algo', '?')}")
    print(f"  Camera     : {stats.get('camera', '?')}")
    print(f"  Montatura  : {stats.get('mount', '?')}")


def main():
    args = parse_args()

    # Modalità file singolo
    if args.file:
        path = Path(args.file)
        if not path.exists():
            print(f"Errore: file non trovato: {path}", file=sys.stderr)
            sys.exit(1)
        parser = PHD2LogParser()
        sessions = parser.parse_file(path)
        print(f"\nFile: {path.name}")
        print(f"Sessioni trovate: {len(sessions)}")
        for i, s in enumerate(sessions):
            stats = s.compute_stats()
            stats["source_file"] = path.name
            print_session_stats(stats, i)
        return

    # Modalità directory / watch
    watcher = PHD2LogWatcher(
        phd2_log_dir=args.dir,
        output_dir=args.out,
    )

    if args.watch:
        print(f"Watch mode attivo. Ctrl+C per uscire.")
        def on_new(summaries):
            for i, s in enumerate(summaries):
                print_session_stats(s, i)
        watcher.watch(callback=on_new)
        return

    summaries = watcher.process_all(force=args.force)

    if not summaries:
        phd2_dir = watcher.phd2_log_dir
        print(f"\nNessun log PHD2 trovato in: {phd2_dir}")
        print("Suggerimento: specifica la cartella con --dir")
        return

    print(f"\nProcessate {len(summaries)} sessioni di guida.")

    if args.summary:
        # Solo riepilogo aggregato
        total_frames = sum(s.get("total_frames", 0) for s in summaries)
        total_minutes = sum(s.get("duration_minutes", 0) for s in summaries)
        avg_rms = sum(s.get("rms_total_arcsec", 0) for s in summaries) / len(summaries)
        print(f"\n{'─'*40}")
        print(f"  Sessioni totali : {len(summaries)}")
        print(f"  Frame totali    : {total_frames}")
        print(f"  Tempo totale    : {total_minutes:.1f} min")
        print(f"  RMS medio tot.  : {avg_rms:.4f}\"")
        print(f"  Output JSON in  : {watcher.output_dir}/")
    else:
        for i, s in enumerate(summaries):
            print_session_stats(s, i)

    print(f"\nFile JSON salvati in: {Path(args.out).resolve()}/")


if __name__ == "__main__":
    main()
