"""
server.py — Mini server FastAPI con WebSocket per la dashboard real-time

Espone:
  GET  /status          → stato attuale del controller in JSON
  GET  /history         → ultime N azioni del controller
  POST /config/dry_run  → attiva/disattiva modalità DRY_RUN
  WS   /ws              → stream eventi (GuideStep processati + azioni)
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from pydantic import BaseModel, Field

from phd2_agent.__about__ import about_payload

logger = logging.getLogger(__name__)

app = FastAPI(title="PHD2 Adaptive Agent Dashboard", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Stato globale condiviso (impostato da main.py)
_controller = None
_analyzer = None
_session_logger = None
# §41 — store telemetria NINA (opzionale). Registrato via set_nina_store() per
# NON toccare la firma di set_global_state (retrocompat totale). None => nessun
# canale NINA: /status riporta nina disabilitato/assente (graceful).
_nina_store = None
# §45 — tracker Layer-2 (Transparency Index). None => blocco transparency assente.
_transparency_tracker = None
# §57 S2 — hint di recupero dalla SNR guida. None => blocco recovery_hint assente.
_recovery_hint_tracker = None

# Broadcast buffer per WebSocket
_ws_queue: asyncio.Queue = None
_connected_ws: list[WebSocket] = []


def set_global_state(controller, analyzer, session_logger):
    global _controller, _analyzer, _session_logger
    _controller = controller
    _analyzer = analyzer
    _session_logger = session_logger


def set_nina_store(store) -> None:
    """§41 — registra lo store telemetria NINA (duck-typed: NinaTelemetryStore).
    Setter dedicato per non modificare la firma di set_global_state."""
    global _nina_store
    _nina_store = store


def set_transparency_tracker(tracker) -> None:
    """§45 — registra il TransparencyTracker (Layer-2). Alimentato sul POST telemetria
    ed esposto in /status.nina.transparency."""
    global _transparency_tracker
    _transparency_tracker = tracker


def set_recovery_hint_tracker(tracker) -> None:
    """§57 S2 — registra il RecoveryHintTracker (fratello di N1, SOLO osservazione:
    nessuna autorità safety). Esposto in /status.recovery_hint; osserva le sonde
    (paletto 8) accanto all'ingest N1."""
    global _recovery_hint_tracker
    _recovery_hint_tracker = tracker


# Forma di default del blocco `nina` in /status quando lo store non è registrato
# (es. --no-dashboard non lo registra, o nessuno l'ha mai impostato). Graceful.
_NINA_ABSENT_BLOCK = {
    "enabled": False,
    "connected": False,
    "schema_version": None,
    "last_age_s": None,
    "metrics": {},
}


async def get_ws_queue() -> asyncio.Queue:
    global _ws_queue
    if _ws_queue is None:
        _ws_queue = asyncio.Queue(maxsize=1000)
    return _ws_queue


async def broadcast(message: dict) -> None:
    """Invia un messaggio a tutti i client WebSocket connessi."""
    q = await get_ws_queue()
    try:
        q.put_nowait(message)
    except asyncio.QueueFull:
        pass
    disconnected = []
    for ws in list(_connected_ws):
        try:
            await ws.send_json(message)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        _connected_ws.remove(ws)


_uvicorn_loop = None

@app.on_event("startup")
async def startup_event():
    global _uvicorn_loop
    _uvicorn_loop = asyncio.get_running_loop()

def sync_broadcast(message: dict) -> None:
    """Versione thread-safe di broadcast (chiamabile da thread non-async)."""
    try:
        if _uvicorn_loop and _uvicorn_loop.is_running():
            asyncio.run_coroutine_threadsafe(broadcast(message), _uvicorn_loop)
    except Exception:
        pass


# ------------------------------------------------------------------ #
#  Mount static files                                                 #
# ------------------------------------------------------------------ #

import sys

def get_base_path() -> Path:
    """Returns the correct base path whether running via Python or PyInstaller exe."""
    if getattr(sys, 'frozen', False):
        # We are running as a PyInstaller executable
        return Path(sys.executable).parent
    # We are running from normal Python
    return Path(__file__).parent

_dashboard_path = get_base_path() / "dashboard"

if _dashboard_path.exists():
    app.mount("/static", StaticFiles(directory=str(_dashboard_path)), name="static")


@app.get("/", include_in_schema=False)
async def root():
    index = _dashboard_path / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return JSONResponse({
        "message": "Dashboard UI non trovata",
        "error": f"Cartella attesa in: {_dashboard_path}"
    })


# ------------------------------------------------------------------ #
#  REST API                                                           #
# ------------------------------------------------------------------ #

@app.get("/about")
async def about() -> dict:
    """Identità del progetto: nome, autore, versione, copyright, contatto Telegram.
    Chiamato una volta sola al caricamento della dashboard (NON a ogni tick)."""
    return about_payload()


@app.get("/status")
async def get_status():
    """Stato completo del controller e ultima analisi."""
    ctrl_status = _controller.get_status() if _controller else {}
    snap = _analyzer.last_snapshot if _analyzer else None

    analyzer_status = {}
    if snap:
        analyzer_status = {
            "rms_ra": round(snap.rms_ra, 4),
            "rms_dec": round(snap.rms_dec, 4),
            "rms_total": round(snap.rms_total, 4),
            "peak_ra": round(snap.peak_ra, 4),
            "peak_dec": round(snap.peak_dec, 4),
            "snr_avg": round(snap.snr_avg, 2),
            "hfd_avg": round(snap.hfd_avg, 2),
            "spike_score": round(snap.spike_score, 4),
            "trend_ra": round(snap.trend_ra, 6),
            "trend_dec": round(snap.trend_dec, 6),
            "condition": snap.condition.name,
            "condition_description": snap.condition_description,
            "frame_count": snap.frame_count,
            "consecutive_high": snap.consecutive_high,
            "consecutive_low": snap.consecutive_low,
        }

    if _controller is not None:
        ctrl_status["ai_find_enabled"] = _controller.ai_find_enabled

    # §41 — blocco top-level `nina` (telemetria esterna, NON stato del controller).
    # Difensivo: qualunque errore dello store degrada a "assente", non rompe /status.
    try:
        nina_status = (_nina_store.status_block()
                       if _nina_store is not None else dict(_NINA_ABSENT_BLOCK))
    except Exception:
        logger.exception("Errore leggendo NinaTelemetryStore in /status")
        nina_status = dict(_NINA_ABSENT_BLOCK)

    # §45/§48 — sotto-blocco transparency (Layer-2, unico riconoscitore N1). Graceful:
    # assente -> available:false. `fresh` (§48) è la freschezza single-source dello store
    # §43. §55 (fix N6): accanto a `fresh` esponiamo anche `age_s` (età telemetria) e
    # `window_s` (finestra adattiva §43) — il plugin li logga a ogni tick, così "stantio"
    # diventa PROVATO nei log, non dedotto (lezione della notte 2026-07-10).
    try:
        transp = (_transparency_tracker.status_block() if _transparency_tracker is not None
                  else {"enabled": False, "available": False, "index": None, "state": None})
        try:
            transp["fresh"] = bool(_nina_store.is_fresh) if _nina_store is not None else False
        except Exception:
            transp["fresh"] = False
        transp["age_s"] = nina_status.get("last_age_s")
        transp["window_s"] = nina_status.get("effective_staleness_s")
        nina_status["transparency"] = transp
    except Exception:
        logger.exception("Errore leggendo TransparencyTracker in /status")
        nina_status["transparency"] = {"enabled": False, "available": False,
                                       "index": None, "state": None, "fresh": False,
                                       "age_s": None, "window_s": None}

    # §57 S2 — blocco recovery_hint (solo osservazione; graceful se assente/spento).
    try:
        recovery_hint = (_recovery_hint_tracker.status_block()
                         if _recovery_hint_tracker is not None
                         else {"enabled": False, "active": False})
    except Exception:
        logger.exception("Errore leggendo RecoveryHintTracker in /status")
        recovery_hint = {"enabled": False, "active": False}

    return JSONResponse({
        "timestamp": time.time(),
        "controller": ctrl_status,
        "analyzer": analyzer_status,
        "nina": nina_status,
        "recovery_hint": recovery_hint,
    })


@app.get("/history")
async def get_history(limit: int = 100):
    """Ultime N azioni del controller."""
    if _controller is None:
        return JSONResponse({"actions": []})
    history = [a.to_dict() for a in _controller.action_history[-limit:]]
    return JSONResponse({"actions": history})


class DryRunPayload(BaseModel):
    enabled: bool

class AIFindPayload(BaseModel):
    enabled: bool

class DiagModePayload(BaseModel):
    mode: str   # "off" | "jitter" | "guardian"

@app.post("/config/dry_run")
async def set_dry_run(payload: DryRunPayload):
    """Cambia modalità DRY_RUN a runtime."""
    if _controller:
        _controller.set_dry_run(payload.enabled)
    return JSONResponse({"dry_run": payload.enabled})

@app.post("/config/ai_find")
async def set_ai_find(payload: AIFindPayload):
    """Attiva/Disattiva AI Star Finder."""
    if _controller:
        _controller.ai_find_enabled = payload.enabled
    return JSONResponse({"ai_find": payload.enabled})

@app.post("/config/diagnostic_mode")
async def set_diagnostic_mode(payload: DiagModePayload):
    """§31 — Switcher Seeing Diagnostic Engine: "off" (kill switch, sempre permesso),
    "jitter"/"guardian" (gated da allow_dashboard_mode_switch + conferma lato UI)."""
    if _controller:
        return JSONResponse(_controller.set_diagnostic_mode(payload.mode))
    return JSONResponse({"mode": payload.mode})


# ------------------------------------------------------------------ #
#  §41 — Ingresso telemetria NINA (POST /nina/telemetry)             #
# ------------------------------------------------------------------ #
#
# Contratto JSON versionato (schema_version=1), inoltrato dal plugin a ogni
# sotto-posa salvata (IImageSaveMediator.ImageSaved — lato plugin RIMANDATO al
# ripristino del PC, vedi NOTE §41). Difensivo: tutti i campi opzionali tranne
# schema_version; validazione di range (>=0) -> 422 senza toccare lo store;
# nessuna eccezione raggiunge mai il loop di guida (endpoint isolato sul thread
# uvicorn, non chiama controller/motore/leve). Step 0: nessun consumatore agisce.

class NinaImageMetrics(BaseModel):
    """Metriche per-posa dalla star detection NINA (camera di ripresa).
    Tutte opzionali; i campi mancanti restano None (tolleranza di contratto)."""
    hfr: Optional[float] = Field(default=None, ge=0)            # HFR medio (px)
    fwhm: Optional[float] = Field(default=None, ge=0)           # FWHM medio (arcsec) — cross-setup comparabile
    hfr_std: Optional[float] = Field(default=None, ge=0)
    star_count: Optional[int] = Field(default=None, ge=0)       # stelle rilevate
    eccentricity: Optional[float] = Field(default=None, ge=0)   # medio (se disponibile)
    mean_adu: Optional[float] = Field(default=None, ge=0)       # proxy SNR/fondo
    median_adu: Optional[float] = Field(default=None, ge=0)
    stdev_adu: Optional[float] = Field(default=None, ge=0)
    exposure_s: Optional[float] = Field(default=None, ge=0)
    filter: Optional[str] = None


class NinaContext(BaseModel):
    """Contesto operativo per il futuro N2 context-gating (può mancare in §41)."""
    activity: Optional[str] = None   # EXPOSING | AUTOFOCUS | MERIDIAN_FLIP | ...
    target: Optional[str] = None


class NinaTelemetryPayload(BaseModel):
    """Payload del contratto NINA→Agente. `schema_version` obbligatorio; il resto
    opzionale e tollerante (campi mancanti ignorati, mai un 500)."""
    schema_version: int = Field(ge=1)
    source: Optional[str] = None
    ts_unix: Optional[float] = Field(default=None, ge=0)
    image: Optional[NinaImageMetrics] = None
    context: Optional[NinaContext] = None


@app.post("/nina/telemetry")
async def ingest_nina_telemetry(payload: NinaTelemetryPayload):
    """Riceve le metriche per-posa di NINA e le conserva nello store opzionale.

    - store assente o disabilitato -> 200 {"accepted": false, "reason": ...},
      nessuna memorizzazione (kill-switch [nina_telemetry] enabled=false).
    - payload valido -> 200 {"accepted": true, "schema_version": N}, store aggiornato.
    - payload malformato/fuori-range -> 422 gestito da FastAPI prima di qui (lo
      store NON viene toccato). L'endpoint non chiama mai controller/motore/leve.
    """
    store = _nina_store
    if store is None or not getattr(store, "enabled", False):
        return JSONResponse({"accepted": False, "reason": "disabled"})
    try:
        dumped = payload.model_dump()
        store.update(dumped, payload.schema_version)
        # §45 — alimenta il tracker Layer-2 (derivato da Layer-1, non sporca lo store).
        if _transparency_tracker is not None:
            _transparency_tracker.ingest(dumped)
            # §57 — telemetria sonde (paletto 8): un light arrivato a contesto degradato
            # è la firma di una posa-sonda; registra trigger presunto + esito post-ingest.
            # SOLO osservazione (N1 già aggiornato sopra; N6 non c'entra).
            if _recovery_hint_tracker is not None:
                try:
                    _recovery_hint_tracker.observe_probe(_transparency_tracker.status_block())
                except Exception:
                    logger.exception("Errore in RecoveryHintTracker.observe_probe (ignorato)")
    except Exception:
        # Difesa in profondità: un bug nello store non deve mai propagarsi.
        logger.exception("Errore aggiornando NinaTelemetryStore (telemetria scartata)")
        return JSONResponse({"accepted": False, "reason": "store_error"})
    return JSONResponse({"accepted": True, "schema_version": payload.schema_version})


# ------------------------------------------------------------------ #
#  WebSocket                                                          #
# ------------------------------------------------------------------ #

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    _connected_ws.append(websocket)
    logger.info("Client WebSocket connesso (%d totali)", len(_connected_ws))
    try:
        # Invia stato iniziale
        if _controller:
            await websocket.send_json({"type": "status", **await get_status_dict()})
        # Mantieni la connessione
        while True:
            await asyncio.sleep(0.5)
            # Ping per rilevare disconnessioni
            try:
                await websocket.send_json({"type": "ping", "ts": time.time()})
            except Exception:
                break
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in _connected_ws:
            _connected_ws.remove(websocket)
        logger.info("Client WebSocket disconnesso (%d rimasti)", len(_connected_ws))


async def get_status_dict() -> dict:
    resp = await get_status()
    return json.loads(resp.body)


# ------------------------------------------------------------------ #
#  Avvio                                                              #
# ------------------------------------------------------------------ #

def start_server(host: str = "0.0.0.0", port: int = 8080):
    """Avvia il server uvicorn (bloccante — eseguire in un thread separato)."""
    uvicorn.run(app, host=host, port=port, log_level="warning")
