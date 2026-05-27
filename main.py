"""
main.py - Entry point del PHD2 Adaptive Guiding Agent.

Architettura thread:
  Thread-1 (main):   loop evento PHD2 -> Analyzer -> Controller
  Thread-2 (server): FastAPI uvicorn (dashboard + API)
  Thread-3 (reader): interno a PHD2Client, legge socket

Uso:
  python main.py [--config config.toml] [--dry-run] [--monitor-only] [--no-dashboard]

PATCH APPLICATE rispetto alla versione originale:
  - Chiamata a controller.shutdown() prima del client.disconnect() finale
    (necessaria per il Baseline Guardian)
  - Sostituito accesso privato _initialized con is_initialized()
  - Logica di shutdown ridondante anche su perdita connessione PHD2
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
import time
from pathlib import Path

from phd2_agent.client import PHD2Client, PHD2ConnectionError
from phd2_agent.analyzer import StatisticsAnalyzer, SeeingCondition
from phd2_agent.controller import AdaptiveController
from phd2_agent.logger import SessionLogger
from phd2_agent.config import load_config


def setup_logging(level: str = "INFO") -> None:
    fmt = "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO),
                        format=fmt)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


log = logging.getLogger("phd2_agent.main")


def parse_args():
    p = argparse.ArgumentParser(description="PHD2 Adaptive Guiding Agent")
    p.add_argument("--config", default="config.toml", help="Percorso config.toml")
    p.add_argument("--dry-run", action="store_true",
                   help="Forza modalita DRY_RUN (solo log)")
    p.add_argument("--monitor-only", action="store_true",
                   help="Solo monitoraggio, nessun controller")
    p.add_argument("--no-dashboard", action="store_true",
                   help="Disabilita la web dashboard")
    p.add_argument("--simulator", action="store_true",
                   help="Usa il simulatore invece di PHD2 reale")
    reducer_group = p.add_mutually_exclusive_group()
    reducer_group.add_argument(
        "--with-reducer",
        action="store_true",
        help="Attiva il riduttore di focale (sovrascrive setup.reducer_active=true)",
    )
    reducer_group.add_argument(
        "--no-reducer",
        action="store_true",
        help="Disattiva il riduttore di focale (sovrascrive setup.reducer_active=false)",
    )
    return p.parse_args()


def main():
    args = parse_args()
    cfg = load_config(args.config)
    setup_logging(cfg.logging.log_level)

    if args.dry_run:
        cfg.control.dry_run = True
    if args.monitor_only:
        cfg.control.dry_run = True
    if args.with_reducer:
        cfg.setup.reducer_active = True
        log.info("CLI override: --with-reducer → reducer_active=True")
    elif args.no_reducer:
        cfg.setup.reducer_active = False
        log.info("CLI override: --no-reducer → reducer_active=False")

    mode_str = "DRY_RUN" if cfg.control.dry_run else "LIVE CONTROL"
    log.info("=" * 60)
    log.info("PHD2 Adaptive Guiding Agent v1.1.0 (patched)")
    log.info("   Modalita: %s", mode_str)
    log.info("   PHD2 target: %s:%d", cfg.phd2.host, cfg.phd2.port)
    log.info("=" * 60)

    # --- Inizializzazione componenti ---

    analyzer = StatisticsAnalyzer(
        window_size=cfg.control.window_frames,
        rms_high=cfg.thresholds.rms_high,
        rms_low=cfg.thresholds.rms_low,
        snr_low=cfg.thresholds.snr_low,
        spike_ratio_high=cfg.thresholds.spike_ratio_high,
    )

    if args.simulator:
        client = _make_simulator_client()
    else:
        client = PHD2Client(host=cfg.phd2.host, port=cfg.phd2.port)

    controller = AdaptiveController(client=client, config=cfg, analyzer=analyzer)
    session_logger = SessionLogger(csv_dir=cfg.logging.csv_dir)

    # --- Dashboard ---

    if not args.no_dashboard:
        try:
            from server import start_server, set_global_state
            set_global_state(controller, analyzer, session_logger)
            dash_thread = threading.Thread(
                target=start_server,
                kwargs={"host": cfg.dashboard.host, "port": cfg.dashboard.port},
                daemon=True,
                name="dashboard",
            )
            dash_thread.start()
            log.info("Dashboard: http://localhost:%d", cfg.dashboard.port)
        except ImportError as e:
            log.warning("Dashboard non disponibile: %s", e)

    # --- Gestione segnali di uscita ---

    _stop_event = threading.Event()

    def _shutdown(signum, frame):
        log.info("Shutdown richiesto (segnale %d)...", signum)
        _stop_event.set()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # --- Loop principale ---

    RECONNECT_DELAY = 10
    EVAL_INTERVAL = cfg.control.interval_seconds

    while not _stop_event.is_set():
        log.info("Connessione a PHD2...")
        try:
            client.connect()
        except PHD2ConnectionError as e:
            log.error("%s", e)
            log.info("Riprovo tra %ds... (Ctrl+C per uscire)", RECONNECT_DELAY)
            _stop_event.wait(RECONNECT_DELAY)
            continue

        log.info("Connesso. In attesa che PHD2 avvii la guida...")

        try:
            state = client.get_app_state()
            log.info("Stato PHD2 corrente: %s", state)

            if state == "Guiding":
                controller.initialize()
        except Exception as e:
            log.warning("get_app_state fallito: %s", e)

        try:
            _event_loop(
                client=client,
                analyzer=analyzer,
                controller=controller,
                session_logger=session_logger,
                stop_event=_stop_event,
                eval_interval=EVAL_INTERVAL,
                monitor_only=args.monitor_only,
            )
        except PHD2ConnectionError as e:
            log.error("Connessione PHD2 persa: %s", e)
        except Exception as e:
            log.exception("Errore inatteso nel loop eventi: %s", e)
        finally:
            client.disconnect()

        # Se shutdown richiesto, esci subito senza retry
        if _stop_event.is_set():
            break

        log.info("Riconnessione tra %ds...", RECONNECT_DELAY)
        _stop_event.wait(RECONNECT_DELAY)

    # --- Shutdown graceful ---

    # IMPORTANTE: il controller.shutdown() ripristina i parametri PHD2
    # alla baseline. Se non viene chiamato, PHD2 resta con i valori
    # modificati dall'agente (es. aggressivita' al minimo per emergenza),
    # e la sessione successiva parte da uno stato "sporco".
    try:
        # Prova a riconnettere se la connessione si era persa, per poter
        # inviare i comandi di restore. Tentativo soft, non bloccante.
        if not client.connected:
            try:
                log.info("Riconnessione per restore baseline...")
                client.connect()
            except PHD2ConnectionError:
                log.warning(
                    "Impossibile riconnettere a PHD2 per restore baseline. "
                    "Il file baseline.json viene mantenuto: il prossimo "
                    "avvio dell'agente tentera' orphan recovery."
                )
        if client.connected:
            controller.shutdown()
            client.disconnect()
    except Exception as e:
        log.error("Errore durante shutdown del controller: %s", e)

    summary = session_logger.close()
    log.info("Sessione terminata.")
    log.info("   Frame totali: %d", summary.get("total_frames", 0))
    log.info("   Azioni eseguite: %d", summary.get("total_actions", 0))
    log.info("   Peak RMS: %.3f\"", summary.get("peak_rms_total_arcsec", 0))
    log.info("   Log CSV: %s", summary.get("csv_file", "-"))


def _event_loop(
    client: PHD2Client,
    analyzer: StatisticsAnalyzer,
    controller: AdaptiveController,
    session_logger: SessionLogger,
    stop_event: threading.Event,
    eval_interval: float,
    monitor_only: bool,
) -> None:
    """Loop principale che consuma la queue eventi di PHD2."""
    last_eval = time.monotonic()
    is_settling = False

    import queue as q_module
    from server import sync_broadcast as _broadcast

    while not stop_event.is_set() and client.connected:
        try:
            event = client.event_queue.get(timeout=1.0)
        except q_module.Empty:
            # Anche senza eventi, se c'e' un timer attivo (es. saturation
            # timer) chiamiamo evaluate periodicamente per non lasciarlo
            # in attesa indefinita di un GuideStep.
            now = time.monotonic()
            if (not monitor_only
                    and now - last_eval >= eval_interval
                    and controller.saturated_lock_since is not None):
                # Crea snapshot vuoto per girare il timer
                # (nota: passiamo l'ultimo snapshot dell'analyzer)
                last_snap = analyzer.last_snapshot if hasattr(analyzer, 'last_snapshot') else None
                if last_snap is not None:
                    actions = controller.evaluate(last_snap)
                    last_eval = now
                    if actions:
                        for a in actions:
                            log.info("%s", a)
            continue

        event_name = event.get("Event", "")

        if event_name == "GuideStep":
            if is_settling:
                # Ignoriamo i GuideStep durante il dithering (falsi errori)
                continue

            snapshot = analyzer.ingest_guide_step(event)
            actions = []

            now = time.monotonic()
            if (not monitor_only
                    and now - last_eval >= eval_interval
                    and analyzer.is_ready):
                actions = controller.evaluate(snapshot)
                last_eval = now

            session_logger.log_snapshot(snapshot, actions)

            try:
                msg = {
                    "type": "guide_step",
                    "ts": event.get("Timestamp", time.time()),
                    "rms_ra": round(snapshot.rms_ra, 4),
                    "rms_dec": round(snapshot.rms_dec, 4),
                    "rms_total": round(snapshot.rms_total, 4),
                    "snr": round(snapshot.snr_avg, 2),
                    "condition": snapshot.condition.name,
                    "condition_desc": snapshot.condition_description,
                    "actions": [a.to_dict() for a in actions],
                    "saturation_active": controller.saturated_lock_since is not None,
                }
                _broadcast(msg)
            except Exception:
                pass

            if actions:
                for a in actions:
                    log.info("%s", a)

        elif event_name == "StarLost":
            snapshot = analyzer.ingest_star_lost(event)
            log.warning("StarLost - %s", event.get("Status", ""))

            actions = []
            if not monitor_only and controller:
                actions = controller.evaluate(snapshot)
                if actions:
                    for a in actions:
                        log.info("%s", a)

            try:
                _broadcast({"type": "star_lost", "ts": time.time()})
            except Exception:
                pass

        elif event_name == "StartGuiding":
            log.info("PHD2 ha avviato la guida")
            analyzer.reset()
            if not controller.is_initialized():
                controller.initialize()
            try:
                _broadcast({"type": "start_guiding", "ts": time.time()})
            except Exception:
                pass

        elif event_name == "GuidingStopped":
            log.info("PHD2 ha fermato la guida")
            controller.mark_uninitialized()
            try:
                _broadcast({"type": "guiding_stopped", "ts": time.time()})
            except Exception:
                pass

        elif event_name == "AppState":
            state = event.get("State", "")
            log.info("PHD2 AppState: %s", state)
            if state == "Settling":
                if not is_settling:
                    log.info("PHD2 AppState Settling: Pausa per Dither/Settling.")
                    is_settling = True
                    try:
                        _broadcast({"type": "settling", "ts": time.time(), "is_settling": True})
                    except Exception:
                        pass
            elif state == "Guiding":
                if is_settling:
                    log.info("PHD2 AppState Guiding: Fine Dither. Reset statistiche.")
                    is_settling = False
                    analyzer.reset()
                    try:
                        _broadcast({"type": "settling", "ts": time.time(), "is_settling": False})
                    except Exception:
                        pass
                if not controller.is_initialized():
                    controller.initialize()

        elif event_name == "Alert":
            log.warning("PHD2 Alert: %s", event.get("Msg", ""))

        elif event_name == "GuideParamChange":
            log.debug("PHD2 GuideParamChange: %s", event)

        elif event_name == "SettleBegin":
            if not is_settling:
                log.info("PHD2 SettleBegin: Dithering in corso. Pausa valutazioni.")
                is_settling = True
                try:
                    _broadcast({"type": "settling", "ts": time.time(), "is_settling": True})
                except Exception:
                    pass

        elif event_name == "SettleDone":
            if is_settling:
                log.info("PHD2 SettleDone: Dithering completato. Reset statistiche.")
                is_settling = False
                analyzer.reset()
                try:
                    _broadcast({"type": "settling", "ts": time.time(), "is_settling": False})
                except Exception:
                    pass


def _make_simulator_client():
    """Ritorna un client PHD2 che si connette al simulatore locale."""
    from simulator.phd2_simulator import PHD2SimulatorServer

    sim = PHD2SimulatorServer(port=4400)
    t = threading.Thread(target=sim.start, daemon=True, name="phd2-simulator")
    t.start()
    time.sleep(0.5)

    return PHD2Client(host="localhost", port=4400)


if __name__ == "__main__":
    main()
