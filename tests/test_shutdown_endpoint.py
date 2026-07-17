"""
test_shutdown_endpoint.py — §58: POST /shutdown (spegnimento graceful dal plugin).

Il callback registrato da main.py setta _stop_event: qui si verifica il contratto
HTTP (200 prima dell'innesco, idempotenza, 503 senza callback), non il restore
baseline (coperto dal percorso di shutdown esistente, §Baseline Guardian).
"""
from __future__ import annotations

import time
import unittest

try:
    from fastapi.testclient import TestClient
    import server
    _HTTP_OK = True
except Exception:                                     # pragma: no cover
    _HTTP_OK = False

_NEEDS_HTTP = unittest.skipUnless(_HTTP_OK, "fastapi/httpx non disponibili")


@_NEEDS_HTTP
class TestShutdownEndpoint(unittest.TestCase):

    def setUp(self):
        server._shutdown_requested = False
        server.set_shutdown_callback(None)
        self.calls = []

    def tearDown(self):
        server._shutdown_requested = False
        server.set_shutdown_callback(None)

    def _client(self):
        return TestClient(server.app)

    def test_unsupported_without_callback(self):
        r = self._client().post("/shutdown")
        self.assertEqual(r.status_code, 503)
        self.assertFalse(r.json()["shutting_down"])

    def test_shutdown_invokes_callback_after_response(self):
        server.set_shutdown_callback(lambda: self.calls.append(time.time()))
        r = self._client().post("/shutdown")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["shutting_down"])
        # la risposta arriva PRIMA dell'innesco (Timer ~0.3 s)
        self.assertEqual(self.calls, [])
        time.sleep(0.6)
        self.assertEqual(len(self.calls), 1)

    def test_idempotent_second_call(self):
        server.set_shutdown_callback(lambda: self.calls.append(1))
        c = self._client()
        r1 = c.post("/shutdown")
        r2 = c.post("/shutdown")
        self.assertEqual((r1.status_code, r2.status_code), (200, 200))
        self.assertTrue(r2.json().get("already_requested"))
        time.sleep(0.6)
        self.assertEqual(len(self.calls), 1)          # callback UNA sola volta

    def test_callback_exception_is_swallowed(self):
        def boom():
            self.calls.append(1)
            raise RuntimeError("x")
        server.set_shutdown_callback(boom)
        r = self._client().post("/shutdown")
        self.assertEqual(r.status_code, 200)
        time.sleep(0.6)
        self.assertEqual(len(self.calls), 1)          # nessuna propagazione

    def test_selfkill_watchdog_fires_when_graceful_stalls(self):
        """§59 — il 200 è un CONTRATTO: se il graceful non completa (main loop
        piantato), il watchdog forza l'uscita dopo la grazia."""
        saved_grace = server.SHUTDOWN_SELFKILL_GRACE_S
        saved_force = server._force_exit
        fired = []
        try:
            server.SHUTDOWN_SELFKILL_GRACE_S = 0.2
            server._force_exit = lambda: fired.append(time.time())
            server.set_shutdown_callback(lambda: None)   # graceful che non termina mai
            r = self._client().post("/shutdown")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["selfkill_grace_s"], 0.2)
            self.assertEqual(fired, [])                  # non PRIMA della grazia
            time.sleep(0.5)
            self.assertEqual(len(fired), 1)              # scattato una volta
        finally:
            server.SHUTDOWN_SELFKILL_GRACE_S = saved_grace
            server._force_exit = saved_force


if __name__ == "__main__":
    unittest.main()
