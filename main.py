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

from phd2_agent.__about__ import banner_lines
from phd2_agent.client import PHD2Client, PHD2ConnectionError
from phd2_agent.analyzer import StatisticsAnalyzer, SeeingCondition
from phd2_agent.controller import AdaptiveController
from phd2_agent.logger import SessionLogger
from phd2_agent.config import load_config
from phd2_agent.nina_telemetry import NinaTelemetryStore
from phd2_agent.nina_indices import TransparencyTracker
from phd2_agent.recovery_hint import RecoveryHintTracker
from phd2_agent.guide_health import GuideHealthTracker
from phd2_agent.reconnect_log import ReconnectLogPolicy
from phd2_agent.safety_state import SafetyStateStore


def setup_logging(level: str = "INFO") -> None:
    fmt = "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
    handlers: list[logging.Handler] = []
    # §58 — build windowed (PyInstaller console=False): sys.stderr e' None/inutilizzabile
    # -> niente StreamHandler (il log vive su file). Da sorgente/console resta anche stdout.
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    # §56 — persistenza del log su file (rotazione): senza, i crash notturni non
    # lasciano traceback. In background (§58) e' il canale di log PRIMARIO
    # (viewer: Mostra_Log.bat). Fallback graceful se logs/ non e' scrivibile.
    try:
        from logging.handlers import RotatingFileHandler
        Path("logs").mkdir(exist_ok=True)
        handlers.append(RotatingFileHandler(
            "logs/agent.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8"))
    except Exception:
        pass
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO),
                        format=fmt, handlers=handlers, force=True)
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
        help="[retrocompat] Forza setup.reducer_active=true. Ininfluente con "
             "auto_calibration attiva: la focale del profilo PHD2 comanda la pixel scale.",
    )
    reducer_group.add_argument(
        "--no-reducer",
        action="store_true",
        help="[retrocompat] Forza setup.reducer_active=false. Ininfluente con "
             "auto_calibration attiva: la focale del profilo PHD2 comanda la pixel scale.",
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

    # Banner branded (§26): prime righe del log, identità single source of truth.
    for _line in banner_lines():
        log.info(_line)
    mode_str = "DRY_RUN" if cfg.control.dry_run else "LIVE CONTROL"
    log.info("Modalita: %s | PHD2 target: %s:%d",
             mode_str, cfg.phd2.host, cfg.phd2.port)

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

    # §31 — wiring Seeing Diagnostic Engine: il controller scrive experimental_*.jsonl
    # tramite il logger (stesso session_id del CSV); il logger legge soglie/reference
    # e contesto summary dal controller. Duck-typed: nessun import circolare.
    controller.session_logger = session_logger
    session_logger.bind_controller(controller)

    # §41 — store telemetria NINA (opzionale/graceful). Creato sempre (inerte
    # finché il plugin non POSTa); registrato sul server solo se la dashboard è
    # attiva. Nessun consumatore lo legge in §41: motore/controller/leve intatti.
    nina_store = NinaTelemetryStore(
        enabled=cfg.nina_telemetry.enabled,
        staleness_seconds=cfg.nina_telemetry.staleness_seconds,
        history_frames=cfg.nina_telemetry.history_frames,
        log_arrivals=cfg.nina_telemetry.log_arrivals,
        staleness_exposure_factor=cfg.nina_telemetry.staleness_exposure_factor,
    )

    # §45 — Transparency Index (Layer-2). Alimentato dai payload NINA (lato server) e
    # letto da /status e dal motore §46 (via il controller). §46 — il controller riceve
    # store+tracker per la fusione confidence (freschezza presa dallo store §43).
    transparency_tracker = TransparencyTracker(
        enabled=cfg.nina_indices.enabled,
        baseline_window_subs=cfg.nina_indices.baseline_window_subs,
        base_best_fraction=cfg.nina_indices.base_best_fraction,
        clear_above=cfg.nina_indices.clear_above,
        cloud_below=cfg.nina_indices.cloud_below,
        hysteresis=cfg.nina_indices.hysteresis,
        deadband_deficit=cfg.nina_indices.deadband_deficit,
        ref_ratchet_enabled=cfg.nina_indices.ref_ratchet_enabled,
        ref_release_half_life_min=cfg.nina_indices.ref_release_half_life_min,
        ref_freeze_max_min=cfg.nina_indices.ref_freeze_max_min,
        ref_session_floor_frac=cfg.nina_indices.ref_session_floor_frac,
    )
    controller.nina_store = nina_store
    controller.transparency_tracker = transparency_tracker

    # §57 S2 — RecoveryHintTracker: fratello di N1 (SOLO osservazione, autorità safety
    # ZERO). Legge lo stato N1 via provider read-only; alimentato per-frame con snr_avg
    # nel loop eventi (la SNR guida fluisce anche mentre NINA è in attesa UNSAFE).
    def _n1_state() -> tuple:
        try:
            b = transparency_tracker.status_block()
            return (b.get("state"), b.get("index"))
        except Exception:
            return (None, None)

    recovery_hint_tracker = RecoveryHintTracker(cfg.recovery_hint, state_provider=_n1_state)

    # §68 — osservabilità del canale di guida: misura soltanto (il latch vive nel
    # plugin). Alimentato dagli eventi PHD2 nel loop, incluso LoopingExposures che
    # fino a ora l'agente ignorava del tutto.
    guide_health = GuideHealthTracker(cfg.guide_health)
    # §73 — riflesso dello stato del Safety Monitor del plugin (solo dashboard).
    safety_state = SafetyStateStore()

    # --- Dashboard ---

    if not args.no_dashboard:
        try:
            from server import (start_server, set_global_state, set_nina_store,
                                 set_transparency_tracker, set_recovery_hint_tracker,
                                 set_guide_health, set_safety_state_store)
            set_global_state(controller, analyzer, session_logger)
            set_nina_store(nina_store)
            set_transparency_tracker(transparency_tracker)
            set_recovery_hint_tracker(recovery_hint_tracker)
            set_guide_health(guide_health)
            set_safety_state_store(safety_state)
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

    # §58 — spegnimento graceful via HTTP (plugin NINA alla chiusura): POST /shutdown
    # percorre la stessa strada dei segnali. Registrato qui (dopo la definizione di
    # _stop_event); no-op se la dashboard non è attiva (endpoint non servito).
    if not args.no_dashboard:
        try:
            from server import set_shutdown_callback
            set_shutdown_callback(lambda: (log.info("Shutdown richiesto via POST /shutdown"),
                                           _stop_event.set()))
        except ImportError:
            pass

    # --- Loop principale ---

    RECONNECT_DELAY = 10
    EVAL_INTERVAL = cfg.control.interval_seconds

    # §69 — deduplica del retry: il log della notte 29/7 era per l'85% questo loop
    # (8314 righe su 9716), e con la rotazione a 5 MB il rumore espelle la storia
    # utile. Politica: primi tentativi per esteso -> soppressione -> battito raro
    # -> sintesi al ritorno. Vedi phd2_agent/reconnect_log.py.
    reconnect_log = ReconnectLogPolicy(
        verbose_attempts=cfg.logging.reconnect_verbose_attempts,
        heartbeat_minutes=cfg.logging.reconnect_heartbeat_minutes)

    while not _stop_event.is_set():
        if not reconnect_log.suppressing:
            log.info("Connessione a PHD2...")
        try:
            client.connect()
        except PHD2ConnectionError as e:
            for act in reconnect_log.failure(str(e)):
                getattr(log, act.level)("%s", act.message)
            if not reconnect_log.suppressing:
                log.info("Riprovo tra %ds... (Ctrl+C per uscire)", RECONNECT_DELAY)
            _stop_event.wait(RECONNECT_DELAY)
            continue

        for act in reconnect_log.success():
            getattr(log, act.level)("%s", act.message)
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
                recovery_hint_tracker=recovery_hint_tracker,
                guide_health=guide_health,
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
    recovery_hint_tracker: "RecoveryHintTracker | None" = None,
    guide_health: "GuideHealthTracker | None" = None,
) -> None:
    """Loop principale che consuma la queue eventi di PHD2.

    §63 — recovery_hint_tracker arriva come PARAMETRO: la notte 2026-07-19 il
    riferimento a una variabile locale di main() (NameError al primo frame utile)
    faceva risalire l'eccezione all'handler esterno il cui finally DISCONNETTEVA
    da PHD2 → 178 cicli connect/crash in 65 minuti, controller mai valutato.
    """
    last_eval = time.monotonic()
    is_settling = False
    hint_error_logged = False   # §63 — primo errore loggato, poi silenzio (mai spam)
    gh_error_logged = [False]   # §68 — idem per l'osservatore del canale di guida

    def _gh(method: str, *args) -> None:
        """§63/§68 — un osservatore PASSIVO non deve mai poter abbattere il loop di
        guida: primo errore loggato, poi silenzio."""
        if guide_health is None:
            return
        try:
            getattr(guide_health, method)(*args)
        except Exception as e:
            if not gh_error_logged[0]:
                gh_error_logged[0] = True
                log.error("guide_health.%s fallito (%s) — osservatore ignorato "
                          "per il resto della sessione", method, e)

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

            # §36 — la misura grezza di PHD2 e' in PIXEL: converti in arcsec all'ingest
            # con la pixel-scale VIVA (override PHD2 -> reduced/native). Kill-switch
            # convert_distance_to_arcsec (shipped ON); a OFF passa 1.0 (px grezzi).
            # §68 — osservabilità del canale: aggiorna ENTRAMBI gli orologi + qualità frame.
            _gh("on_guide_step", event)

            px_scale = (controller.cfg.setup.guide_pixel_scale_arcsec
                        if controller.cfg.analyzer.convert_distance_to_arcsec else 1.0)
            snapshot = analyzer.ingest_guide_step(event, pixel_scale=px_scale)
            actions = []

            now = time.monotonic()
            if not monitor_only and analyzer.is_ready:
                # §34 — accumulo baseline + popolamento logging per OGNI guide-frame
                # (no-op se per_frame_baseline è off). La VALUTAZIONE (classify + leve)
                # resta gated sul tick interval_seconds.
                controller.ingest_frame(snapshot)
                # §57 S2 / §63 — hint di recupero: integra la SNR guida per-frame (no-op
                # se disabilitato o stato N1 non degradato). È un osservatore PASSIVO e
                # non deve MAI poter abbattere il loop di guida: try/except difensivo.
                if recovery_hint_tracker is not None:
                    try:
                        recovery_hint_tracker.update(snapshot.snr_avg)
                    except Exception as e:
                        if not hint_error_logged:
                            hint_error_logged = True
                            log.error("recovery_hint.update fallito (%s) — osservatore "
                                      "ignorato per il resto della sessione", e)
                if now - last_eval >= eval_interval:
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
                # §46 — marcatore grafico: NINA ha modulato la confidence del SEEING.
                # Telemetria read-only verso la dashboard (non tocca la guida).
                _diag = getattr(controller, "_current_diag", None)
                if _diag is not None and _diag.metrics.get("nina_penalty", 0) > 0:
                    msg["nina_mod"] = {
                        "penalty": _diag.metrics.get("nina_penalty", 0),
                        "conf_phd2": _diag.metrics.get("confidence_phd2"),
                        "conf_final": _diag.confidence,
                        "state": _diag.metrics.get("transparency_state"),
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
            # §68 — la stella persa NON cambia l'attesa di guida: PHD2 sta ancora
            # guidando (ci prova). Ma il frame esiste: ne registriamo la qualità.
            _gh("on_star_lost", event)   # §71: frame arrivato, stella NO

            actions = []
            if not monitor_only and controller:
                actions = controller.evaluate(snapshot)
                if actions:
                    for a in actions:
                        log.info("%s", a)

            # §68 (punto 5) — gli StarLost finivano SOLO in agent.log: nella forense
            # del 26/7 è mancata proprio questa riga nel CSV di sessione.
            session_logger.log_snapshot(snapshot, actions)

            try:
                _broadcast({"type": "star_lost", "ts": time.time()})
            except Exception:
                pass

        elif event_name == "LoopingExposures":
            # §68 — la camera espone ma NON si sta guidando (tipico dei tentativi di
            # riaggancio). Prima l'agente ignorava del tutto questo evento: il canale
            # poteva essere VIVO e sembrarci muto. Non tocca analyzer/controller.
            _gh("on_looping_exposure", event)

        elif event_name == "LoopingExposuresStopped":
            _gh("set_guiding_expected", False, "PHD2 ha smesso di esporre (looping stopped)")

        elif event_name == "Paused":
            _gh("set_guiding_expected", False, "guida in pausa (annuncio PHD2)")

        elif event_name == "Resumed":
            _gh("set_guiding_expected", True, "guida ripresa (annuncio PHD2)")

        elif event_name == "StartGuiding":
            log.info("PHD2 ha avviato la guida")
            _gh("set_guiding_expected", True, "guida avviata (annuncio PHD2)")
            analyzer.reset()
            if controller.diagnostic_engine is not None:
                controller.diagnostic_engine.reset("guiding_restart")  # §39: cielo/campo nuovi -> azzera
            if not controller.is_initialized():
                controller.initialize()
            try:
                _broadcast({"type": "start_guiding", "ts": time.time()})
            except Exception:
                pass

        elif event_name == "GuidingStopped":
            log.info("PHD2 ha fermato la guida")
            _gh("set_guiding_expected", False, "guida fermata (annuncio PHD2)")
            controller.mark_uninitialized()
            try:
                _broadcast({"type": "guiding_stopped", "ts": time.time()})
            except Exception:
                pass

        elif event_name == "AppState":
            state = event.get("State", "")
            log.info("PHD2 AppState: %s", state)
            # §68 — stato autorevole di PHD2. "LostLock" = sta guidando ma ha perso la
            # stella: la guida è comunque ATTESA. Gli altri stati (Stopped/Paused/
            # Looping/Selected/Calibrating) sono pause ANNUNCIATE: nessun allarme.
            if state in ("Guiding", "LostLock"):
                _gh("set_guiding_expected", True, f"AppState={state}")
            elif state:
                _gh("set_guiding_expected", False, f"AppState={state}")
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
                    if controller.diagnostic_engine is not None:
                        controller.diagnostic_engine.reset("dither")  # §39: dither non tocca l'atmosfera -> preserva refs
                    try:
                        _broadcast({"type": "settling", "ts": time.time(), "is_settling": False})
                    except Exception:
                        pass
                if not controller.is_initialized():
                    controller.initialize()

        elif event_name == "Version":
            # §56 — header di versione nel log: PHD2 invia questo evento alla connessione.
            # (La versione dell'agente e' gia' nel banner; plugin/NINA non si annunciano
            # all'agente, quindi non sono conoscibili qui.)
            log.info("PHD2 v%s (subver=%s, MsgVersion=%s)",
                     event.get("PHDVersion", "?"), event.get("PHDSubver", ""),
                     event.get("MsgVersion", ""))

        elif event_name == "Alert":
            # §68 — l'Alert porta anche `Type` (info|question|warning|error): usiamo la
            # SEVERITÀ strutturata, non il testo (robusto a traduzioni/riformulazioni).
            # Il 26/7 "Lost connection to camera" arrivò 6 s dopo l'ultimo frame e
            # veniva solo loggato.
            log.warning("PHD2 Alert [%s]: %s",
                        event.get("Type", "info"), event.get("Msg", ""))
            _gh("on_alert", event.get("Msg", ""), event.get("Type", "info"))

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
                if controller.diagnostic_engine is not None:
                    controller.diagnostic_engine.reset("settle")  # §39: settle non tocca l'atmosfera -> preserva refs
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

    return PHD2Client(host="127.0.0.1", port=4400)   # §69


if __name__ == "__main__":
    main()
