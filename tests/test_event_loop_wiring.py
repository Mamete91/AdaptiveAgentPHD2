"""
test_event_loop_wiring.py — §63: il VERO _event_loop deve girare senza eccezioni.

Lezione della notte 2026-07-19: `recovery_hint_tracker` era referenziato in
_event_loop come variabile locale di main() (NameError al primo frame "ready");
l'eccezione risaliva all'handler esterno il cui `finally` DISCONNETTEVA da PHD2
→ 178 cicli connect/crash in 65 minuti, controller mai valutato, hint mai
alimentato, baseline affamata. I 297 test erano verdi perché NESSUNO eseguiva
il corpo reale del loop: questi test chiudono quel buco per sempre.
"""
from __future__ import annotations

import queue
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from main import _event_loop
from phd2_agent.config import AgentConfig, ControlConfig
from phd2_agent.controller import AdaptiveController, ControlAction


def _snapshot() -> SimpleNamespace:
    """Snapshot minimale con TUTTI i campi che il corpo del loop tocca."""
    return SimpleNamespace(
        rms_ra=0.5, rms_dec=0.4, rms_total=0.64,
        snr_avg=42.0, condition=SimpleNamespace(name="NORMAL"),
        condition_description="ok", evaluated=False,
    )


def _guide_step() -> dict:
    return {"Event": "GuideStep", "Timestamp": time.time()}


class _Stubs:
    """Fabbrica degli stub condivisi dai tre casi."""

    def __init__(self, events: list[dict]):
        self.stop = threading.Event()

        self.client = MagicMock()
        self.client.event_queue = queue.Queue()
        for e in events:
            self.client.event_queue.put(e)
        self.client.connected = True

        self.snapshot = _snapshot()
        self.analyzer = MagicMock()
        self.analyzer.is_ready = True
        self.analyzer.ingest_guide_step.return_value = self.snapshot
        self.analyzer.last_snapshot = self.snapshot

        self.controller = MagicMock()
        self.controller.cfg = SimpleNamespace(
            setup=SimpleNamespace(guide_pixel_scale_arcsec=1.0),
            analyzer=SimpleNamespace(convert_distance_to_arcsec=True),
        )
        self.controller.saturated_lock_since = None
        self.controller.evaluate.return_value = []
        self.controller._current_diag = None

        self.logger = MagicMock()
        # il log del primo snapshot ferma il loop: un giro completo e usciamo
        self.logger.log_snapshot.side_effect = lambda *a, **k: self.stop.set()

        self.tracker = MagicMock()

    def run(self, tracker="default") -> None:
        with patch("server.sync_broadcast", lambda msg: None):
            _event_loop(
                client=self.client,
                analyzer=self.analyzer,
                controller=self.controller,
                session_logger=self.logger,
                stop_event=self.stop,
                eval_interval=0.0,
                monitor_only=False,
                recovery_hint_tracker=self.tracker if tracker == "default" else tracker,
            )


class TestEventLoopWiring(unittest.TestCase):
    def test_full_frame_path_runs_hint_and_evaluate(self):
        """Il caso che avrebbe intercettato il NameError: un GuideStep attraversa
        TUTTO il corpo reale del loop — ingest, hint, evaluate, log — senza eccezioni."""
        s = _Stubs([_guide_step()])
        s.run()   # qualsiasi eccezione non gestita fa fallire il test
        s.controller.ingest_frame.assert_called_once_with(s.snapshot)
        s.tracker.update.assert_called_once_with(42.0)
        s.controller.evaluate.assert_called_once_with(s.snapshot)
        s.logger.log_snapshot.assert_called_once()

    def test_hint_observer_crash_never_kills_the_loop(self):
        """§63 — un osservatore passivo che esplode NON deve abbattere il loop:
        evaluate e logging proseguono, l'errore è loggato una sola volta."""
        s = _Stubs([_guide_step(), _guide_step()])
        calls = []
        # ferma al SECONDO snapshot loggato: proviamo che il loop sopravvive al crash
        s.logger.log_snapshot.side_effect = (
            lambda *a, **k: (calls.append(1), len(calls) >= 2 and s.stop.set()))
        s.tracker.update.side_effect = RuntimeError("observer boom")
        s.run()
        self.assertEqual(s.controller.evaluate.call_count, 2)
        self.assertEqual(len(calls), 2)

    def test_tracker_none_is_supported(self):
        """Robustezza: senza tracker (None) il loop gira identico."""
        s = _Stubs([_guide_step()])
        s.run(tracker=None)
        s.controller.evaluate.assert_called_once()


class TestEngineCycleStatus(unittest.TestCase):
    """§63 — i contatori del ciclo motore esposti in get_status()['engine']."""

    def _controller(self) -> AdaptiveController:
        cfg = AgentConfig()
        cfg.control = ControlConfig(dry_run=True)
        return AdaptiveController(client=MagicMock(), config=cfg)

    def test_engine_block_shape_and_last_action(self):
        ctrl = self._controller()
        eng = ctrl.get_status()["engine"]
        self.assertEqual(eng["eval_count"], 0)
        self.assertIsNone(eng["last_eval_ts"])
        self.assertEqual(eng["actions_total"], 0)
        self.assertIsNone(eng["last_action"])

        ctrl.eval_count = 7
        ctrl.last_eval_ts = 1234.5
        ctrl.action_history.append(ControlAction(
            timestamp=1230.0, axis="ra", param="aggression",
            old_value=70.0, new_value=65.0, reason="test", dry_run=True))
        eng = ctrl.get_status()["engine"]
        self.assertEqual(eng["eval_count"], 7)
        self.assertEqual(eng["actions_total"], 1)
        self.assertEqual(eng["last_action_ts"], 1230.0)
        self.assertIn("RA aggression 70", eng["last_action"])


if __name__ == "__main__":
    unittest.main()
