"""
PHD2 Simulator — Emula il server TCP di PHD2 per test senza hardware.

Emette eventi GuideStep sintetici con:
  - Seeing nominale (RMS ~0.3")
  - Spike improvvisi (raffiche di vento)
  - Degradazione graduale del seeing
  - Perdita stella (StarLost)
"""
from __future__ import annotations

import json
import math
import random
import socket
import threading
import time
import logging

logger = logging.getLogger(__name__)


class PHD2SimulatorServer:
    """Piccolo server TCP che emula PHD2 con eventi sintetici."""

    def __init__(self, host: str = "localhost", port: int = 4400):
        self.host = host
        self.port = port
        self._running = False
        self._clients: list[socket.socket] = []
        self._lock = threading.Lock()

        # Stato simulato
        self._algo_params = {
            "ra": {"Aggressiveness": 70.0, "MinMove": 0.15},
            "dec": {"Aggressiveness": 60.0, "MinMove": 0.15},
        }
        self._exposure_ms = 2000
        self._frame_id = 0
        self._app_state = "Guiding"
        self._seeing_phase = "nominal"  # nominal / degraded / spike / recovering

    def start(self) -> None:
        self._running = True
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind((self.host, self.port))
        server_sock.listen(5)
        server_sock.settimeout(1.0)
        logger.info("PHD2 Simulator in ascolto su %s:%d", self.host, self.port)

        # Thread per accettare connessioni
        accept_thread = threading.Thread(target=self._accept_loop, args=(server_sock,), daemon=True)
        accept_thread.start()

        # Thread per generare eventi di guida
        event_thread = threading.Thread(target=self._event_loop, daemon=True)
        event_thread.start()

        # Thread per simulare variazioni di seeing
        seeing_thread = threading.Thread(target=self._seeing_loop, daemon=True)
        seeing_thread.start()

        accept_thread.join()

    def stop(self) -> None:
        self._running = False

    def _accept_loop(self, server_sock: socket.socket) -> None:
        while self._running:
            try:
                conn, addr = server_sock.accept()
                logger.info("Client simulatore connesso da %s", addr)
                with self._lock:
                    self._clients.append(conn)
                threading.Thread(
                    target=self._handle_client, args=(conn,), daemon=True
                ).start()
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    logger.error("Errore accept: %s", e)

    def _handle_client(self, conn: socket.socket) -> None:
        """Gestisce le richieste RPC da un client."""
        # Invia messaggi iniziali
        self._send(conn, {
            "Event": "Version",
            "Timestamp": time.time(),
            "Host": "PHD2-Simulator",
            "Inst": 1,
            "PHDVersion": "2.6.13",
            "PHDSubver": "-sim",
            "MsgVersion": 1,
        })
        self._send(conn, {
            "Event": "AppState",
            "Timestamp": time.time(),
            "Host": "PHD2-Simulator",
            "Inst": 1,
            "State": self._app_state,
        })
        self._send(conn, {
            "Event": "StartGuiding",
            "Timestamp": time.time(),
            "Host": "PHD2-Simulator",
            "Inst": 1,
        })

        buf = b""
        conn.settimeout(1.0)
        while self._running:
            try:
                chunk = conn.recv(1024)
                if not chunk:
                    break
                buf += chunk
            except socket.timeout:
                continue
            except Exception:
                break

            while b"\r\n" in buf:
                line, buf = buf.split(b"\r\n", 1)
                if line.strip():
                    self._handle_rpc(conn, line.decode("utf-8", errors="replace"))

        with self._lock:
            if conn in self._clients:
                self._clients.remove(conn)
        logger.info("Client simulatore disconnesso")

    def _handle_rpc(self, conn: socket.socket, line: str) -> None:
        """Processa un comando JSON-RPC e invia la risposta."""
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            return

        method = req.get("method", "")
        params = req.get("params", [])
        rpc_id = req.get("id", 0)

        result = None
        error = None

        if method == "get_app_state":
            result = self._app_state

        elif method == "get_pixel_scale":
            result = 1.08  # arcsec/px tipico

        elif method == "get_calibrated":
            result = True

        elif method == "get_connected":
            result = True

        elif method == "get_profile":
            result = {"id": 1, "name": "Simulator"}

        elif method == "get_exposure":
            result = self._exposure_ms

        elif method == "get_exposure_durations":
            result = [500, 1000, 1500, 2000, 3000, 4000, 5000]

        elif method == "set_exposure":
            if params:
                self._exposure_ms = int(params[0])
            result = 0

        elif method == "find_star":
            logger.info("🔭 Simulatore: find_star invocato")
            result = 0

        elif method == "get_algo_param_names":
            axis = params[0] if params else "ra"
            result = list(self._algo_params.get(axis, {}).keys())

        elif method == "get_algo_param":
            axis, name = (params[0] if params else "ra"), (params[1] if len(params) > 1 else "")
            val = self._algo_params.get(axis, {}).get(name)
            if val is not None:
                result = val
            else:
                error = {"code": -1, "message": f"Param '{name}' non trovato per asse '{axis}'"}

        elif method == "set_algo_param":
            axis = params[0] if params else "ra"
            name = params[1] if len(params) > 1 else ""
            value = params[2] if len(params) > 2 else 0
            if axis in self._algo_params and name in self._algo_params[axis]:
                self._algo_params[axis][name] = float(value)
                result = 0
                logger.info("⚙️  Simulatore: set %s/%s = %.2f", axis, name, value)
                # Notifica tutti i client
                self._broadcast({
                    "Event": "GuideParamChange",
                    "Timestamp": time.time(),
                    "Host": "PHD2-Simulator",
                    "Inst": 1,
                    "Name": name,
                    "Value": float(value),
                })
            else:
                error = {"code": -1, "message": f"Param '{name}' non supportato per asse '{axis}'"}

        elif method == "get_current_equipment":
            result = {
                "camera": {"name": "Simulator Camera", "connected": True},
                "mount": {"name": "Simulator Mount", "connected": True},
            }

        else:
            error = {"code": -32601, "message": f"Metodo '{method}' non implementato nel simulatore"}

        # Risposta
        response: dict = {"jsonrpc": "2.0", "id": rpc_id}
        if error:
            response["error"] = error
        else:
            response["result"] = result
        self._send(conn, response)

    # ---------------------------------------------------------------- #
    #  Generazione eventi di guida                                      #
    # ---------------------------------------------------------------- #

    def _event_loop(self) -> None:
        """Emette GuideStep sintetici simulando condizioni astronomiche."""
        base_rms = 0.28
        noise_scale = 0.10

        while self._running:
            self._frame_id += 1

            # Determina errore in base alla fase del seeing
            if self._seeing_phase == "nominal":
                ra_err = random.gauss(0, base_rms)
                dec_err = random.gauss(0, base_rms * 0.7)
                snr = random.gauss(45, 5)
                hfd = random.gauss(2.1, 0.3)

            elif self._seeing_phase == "degraded":
                ra_err = random.gauss(0, base_rms * 2.5)
                dec_err = random.gauss(0, base_rms * 1.8)
                snr = random.gauss(30, 8)
                hfd = random.gauss(3.5, 0.5)

            elif self._seeing_phase == "spike":
                ra_err = random.gauss(0, base_rms * 5.0) + random.choice([-1, 1]) * 0.8
                dec_err = random.gauss(0, base_rms * 3.0)
                snr = random.gauss(25, 10)
                hfd = random.gauss(4.5, 1.0)

            elif self._seeing_phase == "recovering":
                ra_err = random.gauss(0, base_rms * 1.5)
                dec_err = random.gauss(0, base_rms * 1.0)
                snr = random.gauss(38, 6)
                hfd = random.gauss(2.8, 0.4)

            else:
                ra_err = random.gauss(0, base_rms)
                dec_err = random.gauss(0, base_rms * 0.7)
                snr = 40.0
                hfd = 2.0

            aggressiveness = self._algo_params["ra"].get("Aggressiveness", 70.0) / 100.0
            ra_dur = abs(ra_err) * aggressiveness * 1000 * random.uniform(0.8, 1.2)
            dec_dur = abs(dec_err) * 0.6 * 1000

            event = {
                "Event": "GuideStep",
                "Timestamp": time.time(),
                "Host": "PHD2-Simulator",
                "Inst": 1,
                "Frame": self._frame_id,
                "Time": self._frame_id * (self._exposure_ms / 1000),
                "StarMass": max(10000, random.gauss(85000, 10000)),
                "SNR": max(5, snr),
                "HFD": max(0.5, hfd),
                "AvgDist": abs(ra_err) * 1.1,
                "RADistanceRaw": ra_err,
                "DECDistanceRaw": dec_err,
                "RADuration": ra_dur,
                "DECDuration": dec_dur,
                "RADirection": "E" if ra_err > 0 else "W",
                "DECDirection": "N" if dec_err > 0 else "S",
                "Correction": "accepted",
            }
            self._broadcast(event)
            time.sleep(self._exposure_ms / 1000)

    def _seeing_loop(self) -> None:
        """Varia il seeing nel tempo per simulare condizioni reali."""
        phases = [
            ("nominal", 60),      # 60s di guida buona
            ("degraded", 45),     # 45s di seeing degradato
            ("spike", 15),        # 15s di raffiche di vento
            ("recovering", 30),   # 30s di recupero
            ("nominal", 90),      # 90s di guida eccellente
        ]
        while self._running:
            for phase, duration in phases:
                if not self._running:
                    break
                self._seeing_phase = phase
                logger.info("🌀 Simulatore: fase seeing = %s (%ds)", phase, duration)
                time.sleep(duration)

    # ---------------------------------------------------------------- #
    #  Utility                                                          #
    # ---------------------------------------------------------------- #

    def _send(self, conn: socket.socket, msg: dict) -> None:
        try:
            data = (json.dumps(msg) + "\r\n").encode("utf-8")
            conn.sendall(data)
        except Exception:
            pass

    def _broadcast(self, msg: dict) -> None:
        with self._lock:
            dead = []
            for conn in self._clients:
                try:
                    data = (json.dumps(msg) + "\r\n").encode("utf-8")
                    conn.sendall(data)
                except Exception:
                    dead.append(conn)
            for c in dead:
                self._clients.remove(c)
