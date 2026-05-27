"""
client.py — Connessione TCP a PHD2 (JSON-RPC 2.0, porta 4400)

PHD2 usa lo stesso socket per due tipi di messaggi:
  1. Event push (server → client): {"Event": "GuideStep", ...}
  2. RPC responses (correlate per id): {"jsonrpc": "2.0", "result": ..., "id": N}

Questo client usa:
  - Un thread listener dedicato che legge continuamente dal socket
  - Una queue per gli eventi push (consumata dall'Analyzer)
  - Un dizionario di Future per le risposte RPC (correlate per id)
"""
from __future__ import annotations

import json
import logging
import queue
import socket
import threading
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)


class PHD2ConnectionError(Exception):
    pass


class PHD2RPCError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(f"RPC Error {code}: {message}")
        self.code = code


class PHD2Client:
    """Client async-safe per il server JSON-RPC di PHD2."""

    DEFAULT_TIMEOUT = 10.0  # secondi per le chiamate RPC

    def __init__(self, host: str = "localhost", port: int = 4400):
        self.host = host
        self.port = port

        self._sock: socket.socket | None = None
        self._reader_thread: threading.Thread | None = None
        self._running = False

        # Contatore ID per le richieste RPC
        self._rpc_id = 0
        self._rpc_lock = threading.Lock()

        # Pending RPC calls: id → threading.Event + risultato
        self._pending: dict[int, dict] = {}
        self._pending_lock = threading.Lock()

        # Coda eventi push da PHD2 (GuideStep, StarLost, ecc.)
        self.event_queue: queue.Queue[dict] = queue.Queue(maxsize=500)

        # Callback opzionale chiamato su ogni evento push
        self.on_event: Callable[[dict], None] | None = None

        # Stato connessione
        self.connected = False

    # ------------------------------------------------------------------ #
    #  Connessione                                                         #
    # ------------------------------------------------------------------ #

    def connect(self, timeout: float = 10.0) -> None:
        """Apre la connessione TCP e avvia il thread listener."""
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(timeout)
            self._sock.connect((self.host, self.port))
            self._sock.settimeout(None)  # reader usa blocking read
        except OSError as e:
            self._sock = None
            raise PHD2ConnectionError(f"Impossibile connettersi a PHD2 su {self.host}:{self.port} — {e}") from e

        self._running = True
        self.connected = True
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True, name="phd2-reader")
        self._reader_thread.start()
        logger.info("Connesso a PHD2 su %s:%d", self.host, self.port)

    def disconnect(self) -> None:
        """Chiude la connessione e ferma il thread listener."""
        self._running = False
        self.connected = False
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        if self._reader_thread:
            self._reader_thread.join(timeout=3.0)
        logger.info("Disconnesso da PHD2")

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.disconnect()

    # ------------------------------------------------------------------ #
    #  Thread listener                                                     #
    # ------------------------------------------------------------------ #

    def _reader_loop(self) -> None:
        """Legge righe JSON dal socket e le smista."""
        buf = b""
        while self._running and self._sock:
            try:
                chunk = self._sock.recv(4096)
                if not chunk:
                    logger.warning("PHD2 ha chiuso la connessione")
                    self.connected = False
                    break
                buf += chunk
            except OSError:
                if self._running:
                    logger.error("Errore lettura socket PHD2")
                break

            # Ogni messaggio termina con CR LF
            while b"\r\n" in buf:
                line, buf = buf.split(b"\r\n", 1)
                if line.strip():
                    self._dispatch(line.decode("utf-8", errors="replace"))

    def _dispatch(self, line: str) -> None:
        """Smista un messaggio JSON verso evento o RPC response."""
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            logger.debug("Riga non-JSON ricevuta: %s", line[:120])
            return

        # RPC response: ha il campo "id" e NON ha "Event"
        if "id" in msg and "Event" not in msg:
            self._handle_rpc_response(msg)
        # Event push: ha il campo "Event"
        elif "Event" in msg:
            self._handle_event(msg)
        else:
            logger.debug("Messaggio non classificato: %s", str(msg)[:120])

    def _handle_rpc_response(self, msg: dict) -> None:
        rpc_id = msg.get("id")
        with self._pending_lock:
            entry = self._pending.get(rpc_id)
        if entry is None:
            logger.debug("Risposta RPC senza pending id=%s", rpc_id)
            return
        entry["response"] = msg
        entry["event"].set()

    def _handle_event(self, msg: dict) -> None:
        event_name = msg.get("Event", "Unknown")
        logger.debug("Evento PHD2: %s", event_name)
        try:
            self.event_queue.put_nowait(msg)
        except queue.Full:
            # Scarta il messaggio più vecchio e inserisci il nuovo
            try:
                self.event_queue.get_nowait()
            except queue.Empty:
                pass
            self.event_queue.put_nowait(msg)

        if self.on_event:
            try:
                self.on_event(msg)
            except Exception:
                logger.exception("Errore nel callback on_event")

    # ------------------------------------------------------------------ #
    #  RPC call                                                            #
    # ------------------------------------------------------------------ #

    def call(self, method: str, params: list | dict | None = None, timeout: float | None = None) -> Any:
        """Invia una chiamata JSON-RPC e attende la risposta."""
        if not self._sock or not self._running:
            raise PHD2ConnectionError("Non connesso a PHD2")

        with self._rpc_lock:
            self._rpc_id += 1
            rpc_id = self._rpc_id

        request: dict[str, Any] = {"method": method, "id": rpc_id}
        if params is not None:
            request["params"] = params

        entry = {"event": threading.Event(), "response": None}
        with self._pending_lock:
            self._pending[rpc_id] = entry

        payload = json.dumps(request) + "\r\n"
        try:
            self._sock.sendall(payload.encode("utf-8"))
        except OSError as e:
            with self._pending_lock:
                self._pending.pop(rpc_id, None)
            raise PHD2ConnectionError(f"Errore invio comando: {e}") from e

        timeout = timeout or self.DEFAULT_TIMEOUT
        signaled = entry["event"].wait(timeout=timeout)
        with self._pending_lock:
            self._pending.pop(rpc_id, None)

        if not signaled:
            raise TimeoutError(f"PHD2 non ha risposto al comando '{method}' entro {timeout}s")

        response = entry["response"]
        if "error" in response:
            err = response["error"]
            raise PHD2RPCError(err.get("code", -1), err.get("message", "Errore sconosciuto"))

        return response.get("result")

    # ------------------------------------------------------------------ #
    #  Metodi di alto livello                                              #
    # ------------------------------------------------------------------ #

    def get_app_state(self) -> str:
        """Ritorna lo stato corrente di PHD2 (es. 'Guiding', 'Stopped')."""
        return self.call("get_app_state")

    def get_pixel_scale(self) -> float | None:
        """Pixel scale di guida (arcsec/px) dal profilo PHD2 attivo.

        Ritorna None se PHD2 risponde `null` (camera non connessa, focale non
        impostata nel profilo, driver senza pixel size, o scala reale == 1.00"/px,
        indistinguibile lato RPC) oppure se la chiamata RPC fallisce.
        """
        try:
            result = self.call("get_pixel_scale")
        except Exception as e:
            logger.warning("get_pixel_scale: chiamata RPC fallita (%s)", e)
            return None
        if result is None:
            return None
        try:
            return float(result)
        except (TypeError, ValueError):
            return None

    def get_calibrated(self) -> bool:
        return bool(self.call("get_calibrated"))

    def get_algo_param_names(self, axis: str) -> list[str]:
        """Ritorna i nomi dei parametri dell'algoritmo per l'asse dato ('ra' o 'dec')."""
        result = self.call("get_algo_param_names", [axis])
        return result if isinstance(result, list) else []

    def get_algo_param(self, axis: str, name: str) -> float:
        """Legge il valore corrente di un parametro algoritmo."""
        result = self.call("get_algo_param", [axis, name])
        return float(result)

    def set_algo_param(self, axis: str, name: str, value: float) -> None:
        """Imposta un parametro algoritmo. Lancia eccezione se PHD2 rifiuta."""
        self.call("set_algo_param", [axis, name, value])
        logger.info("✅ set_algo_param axis=%s name=%s value=%.2f", axis, name, value)

    def get_connected(self) -> bool:
        return bool(self.call("get_connected"))

    def get_exposure(self) -> int:
        """Ritorna il tempo di esposizione corrente in ms."""
        return int(self.call("get_exposure"))

    def get_exposure_durations(self) -> list[int]:
        """Lista dei tempi di esposizione disponibili in ms."""
        result = self.call("get_exposure_durations")
        return result if isinstance(result, list) else []

    def set_exposure(self, duration_ms: int) -> None:
        """Imposta il tempo di esposizione (deve essere un valore valido da get_exposure_durations)."""
        self.call("set_exposure", [duration_ms])
        logger.info("✅ set_exposure %d ms", duration_ms)

    def get_star_image(self) -> dict:
        """Richiede l'immagine corrente della stella guida."""
        return self.call("get_star_image")

    def set_paused(self, paused: bool, full: bool = False) -> None:
        params: list[Any] = [paused]
        if paused and full:
            params.append("full")
        self.call("set_paused", params)

    def get_profile(self) -> dict:
        return self.call("get_profile")

    def get_current_equipment(self) -> dict:
        return self.call("get_current_equipment")

    # ------------------------------------------------------------------ #
    #  Utility                                                             #
    # ------------------------------------------------------------------ #

    def wait_for_state(self, target_state: str, timeout: float = 60.0) -> bool:
        """Blocca fino a quando PHD2 raggiunge lo stato desiderato."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                state = self.get_app_state()
                if state == target_state:
                    return True
            except Exception:
                pass
            time.sleep(1.0)
        return False

    def probe_algo_params(self) -> dict[str, dict[str, float]]:
        """
        Legge i nomi e i valori dei parametri guida per entrambi gli assi.
        Ritorna dict: {'ra': {'Hysteresis': 10.0, ...}, 'dec': {...}}
        """
        res = {"ra": {}, "dec": {}}
        for axis in ["ra", "dec"]:
            names = self.call("get_algo_param_names", [axis])
            if isinstance(names, list):
                for name in names:
                    if name == "algorithmName":
                        continue
                    try:
                        val = self.call("get_algo_param", [axis, name])
                        res[axis][name] = float(val)
                    except PHD2RPCError:
                        pass
        return res

    # ------------------------------------------------------------------ #
    #  Emergency Recovery Actions                                        #
    # ------------------------------------------------------------------ #

    def get_exposure(self) -> int:
        """
        Restituisce il tempo di esposizione corrente (in millisecondi).
        """
        val = self.call("get_exposure", [])
        return int(val) if val is not None else 0

    def set_exposure(self, duration_ms: int) -> None:
        """
        Imposta il tempo di esposizione. E.g. 2000 per 2 secondi.
        """
        self.call("set_exposure", [duration_ms])

    def find_star(self) -> None:
        """
        Forza la sgancio e l'auto-selezione di una nuova stella guida.
        """
        self.call("find_star", [])

    def save_image(self) -> str | None:
        """Salva l'immagine corrente dalla telecamera di PHD2 e ritorna il path su disco."""
        resp = self.call("save_image")
        if isinstance(resp, dict) and "filename" in resp:
            return resp["filename"]
        return None

    def set_lock_position(self, x: float, y: float, exact: bool = True) -> bool:
        """Forza PHD2 a impostare il centroide (o la box di ricerca) a coordinate esatte x, y."""
        try:
            resp = self.call("set_lock_position", [x, y, exact])
            if isinstance(resp, dict) and "error" in resp:
                return False
            return resp == 0
        except Exception as e:
            logger.error("Errore set_lock_position: %s", e)
            return False
