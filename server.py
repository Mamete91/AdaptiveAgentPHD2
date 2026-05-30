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
from pydantic import BaseModel

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

# Broadcast buffer per WebSocket
_ws_queue: asyncio.Queue = None
_connected_ws: list[WebSocket] = []


def set_global_state(controller, analyzer, session_logger):
    global _controller, _analyzer, _session_logger
    _controller = controller
    _analyzer = analyzer
    _session_logger = session_logger


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
        
    return JSONResponse({
        "timestamp": time.time(),
        "controller": ctrl_status,
        "analyzer": analyzer_status,
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
