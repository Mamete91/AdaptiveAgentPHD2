"""
test_reconnect_log.py — §69: deduplica del log di riconnessione a PHD2.

Misura che ha motivato la modifica: nella notte del 2026-07-29 l'85% del log
(8314 righe su 9716) era il retry di connessione. Con la rotazione a 5 MB quel
rumore espelle dal file la storia utile.
"""
from __future__ import annotations

import unittest

from phd2_agent.reconnect_log import ReconnectLogPolicy


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance_min(self, m: float) -> None:
        self.t += m * 60.0


ERR = "Impossibile connettersi a PHD2 su localhost:4400 — [WinError 10061]"


class TestVerboseThenSuppress(unittest.TestCase):

    def test_first_attempts_are_verbose_then_one_suppression_line(self):
        c = _Clock()
        p = ReconnectLogPolicy(verbose_attempts=3, now_fn=c)
        for i in range(3):
            acts = p.failure(ERR)
            self.assertEqual(len(acts), 1)
            self.assertEqual(acts[0].level, "error")
            self.assertFalse(p.suppressing)
        # 4° tentativo: UNA riga di soppressione
        acts = p.failure(ERR)
        self.assertEqual(len(acts), 1)
        self.assertEqual(acts[0].level, "warning")
        self.assertIn("soppress", acts[0].message)
        self.assertTrue(p.suppressing)

    def test_the_real_case_hours_of_silence(self):
        """Il caso reale: PHD2 chiuso, agente vivo con NINA. Prima ~700 righe/ora."""
        c = _Clock()
        p = ReconnectLogPolicy(verbose_attempts=3, heartbeat_minutes=10.0, now_fn=c)
        emitted = 0
        for _ in range(300):              # 300 tentativi * 12 s = 1 ora
            emitted += len(p.failure(ERR))
            c.advance_min(0.2)
        # 3 verbosi + 1 soppressione + ~6 battiti in un'ora
        self.assertLessEqual(emitted, 11,
                             f"un'ora di retry deve costare pochissime righe (emesse {emitted})")
        self.assertGreaterEqual(emitted, 4, "ma non deve sparire del tutto")


class TestHeartbeat(unittest.TestCase):

    def test_heartbeat_breaks_the_silence_periodically(self):
        """Il silenzio non e' mai una prova: senza battito non si distingue
        'agente vivo che ritenta' da 'agente morto' (lezione §63/§68)."""
        c = _Clock()
        p = ReconnectLogPolicy(verbose_attempts=1, heartbeat_minutes=10.0, now_fn=c)
        p.failure(ERR)                    # verboso
        p.failure(ERR)                    # soppressione
        self.assertEqual(p.failure(ERR), [], "subito dopo: silenzio")
        c.advance_min(11)
        acts = p.failure(ERR)
        self.assertEqual(len(acts), 1)
        self.assertIn("tentativi", acts[0].message)
        self.assertEqual(p.failure(ERR), [], "il battito non si ripete subito")

    def test_heartbeat_can_be_disabled(self):
        c = _Clock()
        p = ReconnectLogPolicy(verbose_attempts=1, heartbeat_minutes=0.0, now_fn=c)
        p.failure(ERR)
        p.failure(ERR)
        for _ in range(50):
            c.advance_min(30)
            self.assertEqual(p.failure(ERR), [])


class TestRecoveryAndStateChange(unittest.TestCase):

    def test_recovery_emits_a_forensic_summary(self):
        c = _Clock()
        p = ReconnectLogPolicy(verbose_attempts=3, now_fn=c)
        for _ in range(50):
            p.failure(ERR)
            c.advance_min(0.2)
        acts = p.success()
        self.assertEqual(len(acts), 1)
        self.assertIn("50 tentativi", acts[0].message)
        self.assertIn("min", acts[0].message)
        self.assertEqual(p.attempts, 0, "lo stato si azzera dopo il recupero")

    def test_no_summary_when_there_was_no_suppression(self):
        c = _Clock()
        p = ReconnectLogPolicy(verbose_attempts=3, now_fn=c)
        p.failure(ERR)
        self.assertEqual(p.success(), [], "un singolo fallimento non merita sintesi")

    def test_a_different_error_resumes_verbose_logging(self):
        """Anomalia DIVERSA = fatto nuovo: non va nascosto dalla soppressione."""
        c = _Clock()
        p = ReconnectLogPolicy(verbose_attempts=2, now_fn=c)
        for _ in range(10):
            p.failure(ERR)
        self.assertTrue(p.suppressing)
        acts = p.failure("Connessione rifiutata: porta occupata da altro processo")
        self.assertEqual(len(acts), 1)
        self.assertEqual(acts[0].level, "error")
        self.assertFalse(p.suppressing)


if __name__ == "__main__":
    unittest.main()
