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
import re
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

    # §57/§126 — RecoveryHintTracker: il sensore del cielo dalla guida (SOLO misura,
    # decide il plugin); alimentato per-frame con snr_avg nel loop eventi (la SNR guida
    # fluisce anche mentre NINA e' in attesa UNSAFE).
    # §73 — riflesso dello stato del Safety Monitor del plugin (dashboard; dal
    # §126-sexies anche la durata del sereno chiesto dopo un cambio in UNSAFE).
    safety_state = SafetyStateStore()

    # §126-bis — il giudizio del cielo sopravvive a un riavvio dell'Agente a notte in
    # corso (file accanto a rig_contribution.json, ignorato da git).
    recovery_hint_tracker = RecoveryHintTracker(cfg.recovery_hint,
                                                stato_file=Path("cielo_guida.json"),
                                                unsafe_provider=safety_state.monitor_in_unsafe)

    # §68 — osservabilità del canale di guida: misura soltanto (il latch vive nel
    # plugin). Alimentato dagli eventi PHD2 nel loop, incluso LoopingExposures che
    # fino a ora l'agente ignorava del tutto.
    guide_health = GuideHealthTracker(cfg.guide_health)

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


def _stato_phd2(controller, nuovo: str, perche: str) -> None:
    """§124 — aggiorna lo stato di PHD2 ricavandolo dagli eventi.

    PHD2 manda l'evento `AppState` UNA VOLTA SOLA, alla connessione del client:
    in `event_server.cpp` e' inviato alla riga 541 (saluto al client appena
    connesso) e dentro `NotifyAppState()`, che non e' chiamata da nessuna parte
    nel sorgente. Dopo la connessione, i cambi di stato PHD2 li annuncia con
    eventi SPECIFICI — StartGuiding, GuidingStopped, Paused, LoopingExposures,
    StartCalibration — non ri-mandando AppState.

    Conseguenza del §110, che ha legato `sospeso` ad `app_state`: avviando
    l'Agente PRIMA della guida (cioe' sempre: NINA lo accende, PHD2 guida dopo)
    lo stato restava "Stopped" per tutta la notte e l'Agente non ingeriva un solo
    fotogramma. Osservato dal vivo il 03/10: PHD2 in "Guiding", Agente sospeso,
    baseline ferma a 0/60.
    """
    if controller is None or not nuovo:
        return
    precedente = controller.app_state
    if precedente == nuovo:
        return
    controller.app_state = nuovo
    log.info("Stato PHD2: %s -> %s (%s)", precedente or "ignoto", nuovo, perche)


_RE_POSA = re.compile(r"^\s*(\d+)\s*ms")


def _leggi_posa(valore) -> "int | str | None":
    """§126-sexies — la posa di guida dal GuideParamChange "Exposure" di PHD2.

    PHD2 manda una stringa (myframe.cpp, ExposureDurationSummary): "2000 ms", con
    ", VarDelay (...)" se attivo, oppure "Auto (min = ..., max = ..., SNR = ...)".
    Ritorna i millisecondi, "auto", o None se il valore non si capisce."""
    if isinstance(valore, bool):
        return None
    if isinstance(valore, (int, float)):
        return int(valore) if valore > 0 else None
    if isinstance(valore, str):
        m = _RE_POSA.match(valore)
        if m:
            return int(m.group(1))
        if valore.strip().lower().startswith("auto"):
            return "auto"
    return None


def _testo_posa(posa) -> str:
    if posa is None:
        return "?"
    if posa == "auto":
        return "Auto"
    return f"{posa} ms"


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

    rh_error_logged = [False]
    # §126-bis — alla connessione PHD2 rimanda lo stato corrente, compreso uno
    # StarSelected (event_server.cpp, saluto al client, chiuso da AppState): NON e'
    # una stella nuova e non deve buttare il riferimento del giudice del cielo.
    in_catchup = True
    # §126-bis — ultima posizione nota della stella (StarSelected/LockPositionSet):
    # serve a capire se PHD2 ha scelto la STESSA stella o un'altra.
    ultima_stella: list = [None]
    # §126-quater — calibrazione in corso: il lock rimesso alla fine (o dopo un
    # fallimento) non e' una selezione. Armato a StartCalibration, disarmato a
    # StartGuiding / GuidingStopped / CalibrationFailed.
    calib_in_corso = [False]
    _px = getattr(getattr(guide_health, "cfg", None), "stessa_stella_px", None)
    soglia_stessa_stella = float(_px) if isinstance(_px, (int, float)) else 15.0
    # §126-sexies — ultima posa di guida annunciata da PHD2 (GuideParamChange).
    ultima_posa: list = [None]

    def _cambio_stella(x, y, motivo: str, se_ignota: bool) -> None:
        """Nuova posizione di aggancio: se lontana dalla precedente e' un'altra
        stella e il giudice del cielo lo deve sapere (reset_stella decide se
        reimparare il riferimento o tenerlo). Senza una posizione precedente si
        avvisa solo se `se_ignota` (una selezione esplicita); il lock rimesso a
        inizio guida dopo una calibrazione e' la stessa stella."""
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            return
        prima = ultima_stella[0]
        ultima_stella[0] = (float(x), float(y))
        _rh("posizione_stella", float(x), float(y))
        if prima is None and not se_ignota:
            return
        if prima is not None:
            d = ((float(x) - prima[0]) ** 2 + (float(y) - prima[1]) ** 2) ** 0.5
            if d <= soglia_stessa_stella:
                log.info("Stella di guida: la stessa di prima (%.1f px) — riferimento "
                         "conservato (%s)", d, motivo)
                return
            motivo = f"{motivo}, {d:.0f} px dalla precedente"
        _gh("reset_stella", motivo)
        _rh("reset_stella", motivo)

    def _rh(method: str, *args) -> None:
        """§126 — stesso paletto per il sensore del cielo: sospensione e cambio
        stella non devono mai poter abbattere il loop di guida."""
        if recovery_hint_tracker is None:
            return
        try:
            getattr(recovery_hint_tracker, method)(*args)
        except Exception as e:
            if not rh_error_logged[0]:
                rh_error_logged[0] = True
                log.error("recovery_hint.%s fallito (%s) — ignorato per il resto "
                          "della sessione", method, e)

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
            # §108 — anche questo percorso porta a `evaluate`, che puo' cambiare
            # l'esposizione o riselezionare la stella: ad anello aperto falserebbe
            # la misura in corso. Era l'unica chiamata a evaluate fuori dai rami
            # GuideStep/StarLost, e quindi l'unica scoperta.
            if (not monitor_only
                    and not controller.sospeso
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
            # §124 — il GuideStep arriva SOLO mentre PHD2 guida: e' la conferma
            # piu' frequente che abbiamo, e rimette in riga lo stato se un
            # evento di transizione si fosse perso.
            _stato_phd2(controller, "Guiding", "arrivato un GuideStep")
            # §126 — l'orologio del canale si aggiorna PRIMA di ogni filtro. Prima
            # stava dopo `if sospeso: continue`: durante il Guiding Assistant PHD2
            # manda un GuideStep a ogni frame, l'Agente li scartava senza segnarli
            # e il plugin vedeva un canale muto (UNSAFE "guida non osservabile"
            # dopo ~2 minuti, il 2/10 alle 23:13:42). Il frame e' arrivato: che sia
            # utile alla guida o al motore lo decidono i filtri qui sotto.
            _gh("on_guide_step", event)
            if is_settling:
                # Ignoriamo i GuideStep durante il dithering (falsi errori)
                continue

            # §108 — ad ANELLO APERTO (Guiding Assistant, Polar Drift, o spunta
            # "Enable guide output" tolta a mano) PHD2 non corregge la stella:
            # l'errore che arriva e' il moto NON corretto, quindi l'RMS schizza a
            # diversi arcosecondi. Ingerirlo avvelenerebbe la baseline della
            # sessione (60 frame, e una misura GA ne dura 120-150), il cap MinMove
            # §51 che ne discende, e la diagnosi. Peggio: il controller lo
            # leggerebbe come degrado e ammorbidirebbe le leve o alzerebbe la posa
            # NEL MEZZO della misura, falsando la caratterizzazione che stiamo
            # aspettando (il GA costruisce i suoi filtri sulla posa d'avvio).
            if controller is not None and controller.sospeso:
                continue

            # §36 — la misura grezza di PHD2 e' in PIXEL: converti in arcsec all'ingest
            # con la pixel-scale VIVA (override PHD2 -> reduced/native). Kill-switch
            # convert_distance_to_arcsec (shipped ON); a OFF passa 1.0 (px grezzi).
            # §68 — osservabilità del canale: aggiornata in testa al ramo (§126).

            px_scale = (controller.cfg.setup.guide_pixel_scale_arcsec
                        if controller.cfg.analyzer.convert_distance_to_arcsec else 1.0)
            snapshot = analyzer.ingest_guide_step(event, pixel_scale=px_scale)
            actions = []

            now = time.monotonic()
            # §126-bis — il sensore del cielo e' un OSSERVATORE: lavora anche con
            # --monitor-only, che toglie il controllo, non la sicurezza. Prima il
            # giudice del cielo restava senza SNR in quella modalita'.
            if monitor_only and analyzer.is_ready and recovery_hint_tracker is not None:
                try:
                    recovery_hint_tracker.update(snapshot.snr_avg)
                except Exception as e:
                    if not hint_error_logged:
                        hint_error_logged = True
                        log.error("recovery_hint.update fallito (%s) — osservatore "
                                  "ignorato per il resto della sessione", e)
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
            # §126-bis — un frame senza stella non e' evidenza di sereno.
            if controller is None or not controller.sospeso:
                _rh("on_star_lost")

            actions = []
            # §108 — ad anello aperto non si valuta: `evaluate` puo' chiamare
            # find_star, che riselezionerebbe la stella nel mezzo della misura.
            if not monitor_only and controller and not controller.sospeso:
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
            _stato_phd2(controller, "Looping", "PHD2 espone senza guidare")
            # §68 — la camera espone ma NON si sta guidando (tipico dei tentativi di
            # riaggancio). Prima l'agente ignorava del tutto questo evento: il canale
            # poteva essere VIVO e sembrarci muto. Non tocca analyzer/controller.
            _gh("on_looping_exposure", event)

        elif event_name == "LoopingExposuresStopped":
            _stato_phd2(controller, "Stopped", "PHD2 ha smesso di esporre")
            _gh("set_guiding_expected", False, "PHD2 ha smesso di esporre (looping stopped)")

        elif event_name == "Paused":
            _stato_phd2(controller, "Paused", "guida in pausa")
            _gh("set_guiding_expected", False, "guida in pausa (annuncio PHD2)")

        elif event_name == "Resumed":
            _stato_phd2(controller, "Guiding", "guida ripresa")
            _gh("set_guiding_expected", True, "guida ripresa (annuncio PHD2)")

        elif event_name == "StartGuiding":
            log.info("PHD2 ha avviato la guida")
            calib_in_corso[0] = False
            _stato_phd2(controller, "Guiding", "annuncio StartGuiding")
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

        elif event_name == "StartCalibration":
            _stato_phd2(controller, "Calibrating", "calibrazione avviata")
            # §126 — in calibrazione PHD2 non manda frame di guida con SNR: la guida
            # NON e' attesa e gli stati di prima non devono restare accesi. Il 24/8
            # uno stato di stella persa rimasto congelato e' stato contato dal
            # plugin durante la calibrazione fino a UNSAFE (00:11:06).
            _gh("set_guiding_expected", False, "calibrazione in corso (annuncio PHD2)")
            _rh("sospendi", "calibrazione")
            # §126-bis/quater — la calibrazione sposta la stella di proposito e il
            # lock viene rimesso a inizio guida: non e' un cambio di stella. La
            # posizione di prima resta (se la calibrazione fallisce e PHD2 sceglie
            # un'altra stella, il confronto la riconosce).
            calib_in_corso[0] = True
            # §109 — durante la calibrazione PHD2 comanda spostamenti grandi e
            # misura di quanto la stella si muove rispetto al punto di partenza.
            # Non arrivano GuideStep, ma arrivano gli StarLost — e da li' l'Agente
            # chiamerebbe find_star, che lato PHD2 non ha alcuna guardia di stato
            # e sposterebbe la lock position nel mezzo della misura.
            if controller is not None and not controller.in_calibrazione:
                controller.in_calibrazione = True
                log.warning("PHD2 sta CALIBRANDO. L'Agente si ferma: niente azioni, "
                            "niente ingest — la calibrazione misura lo spostamento "
                            "dal punto di partenza e non va disturbata.")
                try:
                    _broadcast({"type": "calibrazione", "ts": time.time(),
                                "in_corso": True})
                except Exception:
                    pass

        elif event_name == "Calibrating":
            # §126 — un passo di calibrazione riuscito e' prova che la stella c'e'.
            # La stella persa NON si congela a guida ferma (il 24/8 l'allarme nato
            # prima della calibrazione era con ogni probabilita' giusto: nubi): si
            # spegne quando la stella si rivede, qui o al primo GuideStep.
            _gh("on_calibration_step", event)

        elif event_name in ("CalibrationComplete", "CalibrationFailed"):
            if event_name == "CalibrationFailed":
                calib_in_corso[0] = False
            if controller is not None and controller.in_calibrazione:
                controller.in_calibrazione = False
                esito = ("completata" if event_name == "CalibrationComplete"
                         else "FALLITA")
                log.info("Calibrazione %s. Reset statistiche.", esito)
                analyzer.reset()
                if controller.diagnostic_engine is not None:
                    # La calibrazione ha spostato la stella di parecchio, ma non ha
                    # toccato l'atmosfera: i riferimenti di calma restano validi.
                    controller.diagnostic_engine.reset("calibrazione")
                try:
                    _broadcast({"type": "calibrazione", "ts": time.time(),
                                "in_corso": False})
                except Exception:
                    pass

        elif event_name == "GuidingStopped":
            _stato_phd2(controller, "Stopped", "guida fermata")
            log.info("PHD2 ha fermato la guida")
            calib_in_corso[0] = False
            _gh("set_guiding_expected", False, "guida fermata (annuncio PHD2)")
            _rh("sospendi", "guida fermata")
            controller.mark_uninitialized()
            try:
                _broadcast({"type": "guiding_stopped", "ts": time.time()})
            except Exception:
                pass

        elif event_name == "AppState":
            state = event.get("State", "")
            log.info("PHD2 AppState: %s", state)
            # §126-bis — AppState chiude il saluto di PHD2 al client (event_server.cpp):
            # da qui gli StarSelected sono selezioni vere.
            if in_catchup:
                # §126-quater — la memoria su disco vale solo per la stella che PHD2
                # sta guidando adesso (presa dal saluto); senza stella si scarta.
                _rh("conferma_memoria", ultima_stella[0], soglia_stessa_stella)
            in_catchup = False
            # §110 — l'Agente agisce solo quando PHD2 sta davvero guidando. E' una
            # condizione POSITIVA: copre anche gli stati non enumerati (Manual
            # Guide, Star Cross, strumenti futuri) senza doverli rincorrere.
            if controller is not None and state:
                controller.app_state = state
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

        elif event_name == "StarSelected":
            # §126 — PHD2 ha selezionato una stella (anche in automatico a ogni
            # ripartenza della guida: dopo l'autofocus e' un'altra stella in 15
            # casi su 22). Il riferimento SNR della precedente non vale piu'.
            # NON LockPositionSet: quello scatta a ogni dither.
            log.info("PHD2 ha selezionato una stella (%s, %s)",
                     event.get("X", "?"), event.get("Y", "?"))
            if in_catchup:
                # Saluto alla connessione: e' la stella gia' in uso. Se ne prende
                # solo la posizione, per riconoscerla alla prossima selezione.
                if isinstance(event.get("X"), (int, float)) and isinstance(event.get("Y"), (int, float)):
                    ultima_stella[0] = (float(event["X"]), float(event["Y"]))
                    _rh("posizione_stella", float(event["X"]), float(event["Y"]))
            else:
                _cambio_stella(event.get("X"), event.get("Y"), "StarSelected", True)

        elif event_name == "LockPositionSet":
            # §126-bis — PHD2 cambia stella anche SENZA StarSelected: a fine Guiding
            # Assistant con multistar riseleziona partendo da SELECTED
            # (guider_multistar.cpp, AutoSelect; visto il 2/10 alle 23:19:25). Il
            # dither sposta il lock di pochi pixel: sotto la soglia non e' un cambio.
            # §126-quater — PHD2 manda SEMPRE LockPositionSet prima di StarSelected
            # (guider.cpp: SetLockPosition poi NotifyStarSelected): con la posizione
            # precedente ignota il lock E' gia' la selezione. Nel saluto e durante la
            # calibrazione invece si prende solo la posizione.
            if in_catchup or calib_in_corso[0]:
                if isinstance(event.get("X"), (int, float)) and isinstance(event.get("Y"), (int, float)):
                    ultima_stella[0] = (float(event["X"]), float(event["Y"]))
                    _rh("posizione_stella", float(event["X"]), float(event["Y"]))
            else:
                _cambio_stella(event.get("X"), event.get("Y"), "LockPositionSet", True)

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
            _nome = str(event.get("Name", ""))
            if _nome == "MountGuidingEnabled" and controller is not None:
                _attiva = bool(event.get("Value"))
                if not _attiva and not controller.anello_aperto:
                    controller.anello_aperto = True
                    # §126 — dall'inizio del Guiding Assistant alla fine del test del
                    # backlash l'uscita di guida resta disattivata
                    # (guiding_assistant.cpp: SetGuidingEnabled(false) all'avvio,
                    # ripristino in DoStop, dopo EndBacklashTest). Nel test del
                    # backlash PHD2 non manda frame per ~2 minuti: con la guida
                    # "attesa" il plugin dichiarava UNSAFE. E' uno strumento di
                    # misura con l'operatore presente, non una sessione da sorvegliare.
                    _gh("set_guiding_expected", False,
                        "uscita di guida sospesa (Guiding Assistant o misura)")
                    _rh("sospendi", "anello aperto")
                    log.warning(
                        "PHD2 ha SOSPESO l'uscita di guida (Guiding Assistant o "
                        "altro strumento di misura). L'Agente si ferma: niente "
                        "azioni, niente ingest — l'anello e' aperto e l'RMS non "
                        "descrive piu' la qualita' della guida.")
                    try:
                        _broadcast({"type": "anello_aperto", "ts": time.time(),
                                    "aperto": True})
                    except Exception:
                        pass
                elif _attiva and controller.anello_aperto:
                    controller.anello_aperto = False
                    log.info("PHD2 ha RIPRESO l'uscita di guida. Reset statistiche.")
                    if controller.app_state in ("Guiding", "LostLock"):
                        _gh("set_guiding_expected", True, "uscita di guida ripristinata")
                    analyzer.reset()
                    if controller.diagnostic_engine is not None:
                        # L'anello aperto non tocca l'atmosfera: i riferimenti di
                        # calma restano validi, come per il dithering (§39).
                        controller.diagnostic_engine.reset("anello_aperto")
                    # §108 — e' il momento in cui una caratterizzazione appena
                    # conclusa e' gia' nel profilo ma non ancora vista da nessuno.
                    try:
                        controller.ricontrolla_baseline_ga()
                    except Exception as exc:      # noqa: BLE001
                        log.warning("Rilettura baseline GA fallita: %s", exc)
                    try:
                        _broadcast({"type": "anello_aperto", "ts": time.time(),
                                    "aperto": False})
                    except Exception:
                        pass
            elif _nome == "Exposure":
                # §126-sexies — PHD2 annuncia la posa SOLO quando cambia davvero
                # (myframe_events.cpp: OnExposureDurationSelected -> NotifyExposureChanged)
                # e mai nel saluto alla connessione (event_server.cpp,
                # send_catchup_events). La SNR cambia con la posa, il riferimento del
                # cielo no: decisione dell'operatore, si tratta come un cambio di stella.
                _posa = _leggi_posa(event.get("Value"))
                if _posa is None:
                    log.debug("GuideParamChange Exposure non interpretabile: %r",
                              event.get("Value"))
                elif _posa != ultima_posa[0]:
                    _prima = ultima_posa[0]
                    ultima_posa[0] = _posa
                    log.info("PHD2: posa di guida %s -> %s. Reset statistiche.",
                             _testo_posa(_prima), _testo_posa(_posa))
                    # Come per i cambi di posa dell'Agente (§95, _consolida) e a ogni
                    # ripartenza della guida: le statistiche della posa vecchia non
                    # descrivono la nuova (§39: il jitter scala con la posa). Senza, il
                    # sensore del cielo deciderebbe su una media ancora quasi tutta
                    # della posa vecchia.
                    analyzer.reset()
                    if controller is not None and controller.diagnostic_engine is not None:
                        controller.diagnostic_engine.reset("exposure_change")
                    _rh("cambio_posa", f"posa di guida {_testo_posa(_prima)} -> "
                                       f"{_testo_posa(_posa)}")
                    if _posa == "auto":
                        log.warning(
                            "PHD2 usa la posa di guida AUTOMATICA: la regola per tenere la "
                            "SNR al bersaglio (myframe.cpp, AdjustAutoExposure), quindi la "
                            "SNR non misura piu' le nubi finche' la posa non arriva al "
                            "massimo. Con la guida giudice del cielo serve una posa fissa.")
            elif controller is not None and (
                    "minmove" in _nome.lower() or "aggress" in _nome.lower()):
                # Qualcuno ha toccato una leva fuori dall'Agente (tipicamente
                # Applica nella finestra del Guiding Assistant, che arriva DOPO la
                # riapertura dell'anello). Senza questo, lo stato interno resta
                # indietro e il delta della modifica successiva sarebbe falso.
                try:
                    controller.risincronizza_leve()
                except Exception as exc:      # noqa: BLE001
                    log.debug("Risincronizzazione leve fallita: %s", exc)

        elif event_name == "SettleBegin":
            if not is_settling:
                log.info("PHD2 SettleBegin: Dithering in corso. Pausa valutazioni.")
                is_settling = True
                try:
                    _broadcast({"type": "settling", "ts": time.time(), "is_settling": True})
                except Exception:
                    pass

        elif event_name == "SettleDone":
            # §126 — l'esito dell'assestamento si registra sempre: Status != 0
            # significa che la guida non e' ripartita come richiesto.
            _esito = event.get("Status", 0)
            _gh("on_settle_done", _esito if isinstance(_esito, int) else 1,
                str(event.get("Error", "") or ""))
            if isinstance(_esito, int) and _esito != 0:
                log.info("PHD2 SettleDone con esito %s: %s", _esito, event.get("Error", ""))
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
