"""
test_star_lost_recovery.py — §75: il recupero StarLost ha un percorso UNICO.

Il vecchio toggle "AI Finder" apriva un secondo percorso di riselezione che
SCAVALCAVA il backoff a tre livelli del §17 — nato dopo un incidente reale
(130+ chiamate a find_star in 6 minuti su camera crashata via USB). Acceso su
una camera in crisi avrebbe caricato proprio il bus che stava soffocando.

Rimosso il ramo, l'invariante da difendere per sempre è: **ogni tentativo di
riselezione passa dal backoff**. Questi test lo blindano contro reintroduzioni.

Nota di confine: `star_finder.py` NON è oggetto di questi test — resta vivo e
usato dal Path B (riselezione di stelle sature al cambio esposizione), che è un
compito diverso e che PHD2 da solo non copre.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from phd2_agent.controller import (AdaptiveController, GuidingState,
                                   _FIND_STAR_SLOW_THRESHOLD,
                                   _FIND_STAR_SUSP_THRESHOLD)
from tests.test_get_status import _make_controller   # stessa factory degli altri test


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class TestSingleRecoveryPath(unittest.TestCase):

    def _controller(self):
        c = _make_controller()
        c.dry_run = False              # il backoff vive nel percorso LIVE
        client = MagicMock()
        c.client = client
        c.guiding_state = GuidingState.STAR_LOST
        return c, client

    def test_no_ai_finder_switch_remains(self):
        """Il toggle non deve tornare: né come attributo né come endpoint."""
        c, _ = self._controller()
        self.assertFalse(hasattr(c, "ai_find_enabled"),
                         "§75: l'interruttore AI Finder è stato rimosso")
        self.assertNotIn("ai_find_enabled", c.get_status(),
                         "/status non deve più esporre il toggle")

    def test_recovery_uses_phd2_find_star(self):
        """La selezione della stella è competenza di PHD2: si chiama find_star()."""
        c, client = self._controller()
        c.star_lost_since = None
        c._evaluate_star_lost()                      # primo giro: arma il timer
        c.star_lost_since = c.star_lost_since - 999  # oltre find_star_delay
        actions = c._evaluate_star_lost()
        client.find_star.assert_called_once()
        self.assertTrue(actions)
        self.assertEqual(actions[0].param, "find_star")

    def test_failures_are_counted_and_slow_down(self):
        """Il backoff §17 è ora l'unico percorso: i fallimenti rallentano i tentativi."""
        c, client = self._controller()
        client.find_star.side_effect = RuntimeError("USB gone")
        c.star_lost_since = 0.0                       # sempre oltre il delay

        for _ in range(_FIND_STAR_SLOW_THRESHOLD):
            c._find_star_last_attempt = 0.0           # nessun freno temporale
            c._evaluate_star_lost()
        self.assertGreaterEqual(c._find_star_failures, _FIND_STAR_SLOW_THRESHOLD)

        # Raggiunta la soglia SLOW, un tentativo immediato viene SOPPRESSO.
        calls_before = client.find_star.call_count
        c._find_star_last_attempt = c.star_lost_since  # "appena tentato"
        import time as _t
        c._find_star_last_attempt = _t.monotonic()
        c._evaluate_star_lost()
        self.assertEqual(client.find_star.call_count, calls_before,
                         "in backoff SLOW non si deve martellare la camera")

    def test_suspends_after_persistent_failures(self):
        """Camera morta: si sospende invece di floodare (lezione del 26/7)."""
        c, client = self._controller()
        client.find_star.side_effect = RuntimeError("camera dead")
        c.star_lost_since = 0.0
        c._find_star_failures = _FIND_STAR_SUSP_THRESHOLD
        import time as _t
        c._find_star_last_attempt = _t.monotonic()
        calls_before = client.find_star.call_count
        actions = c._evaluate_star_lost()
        self.assertEqual(client.find_star.call_count, calls_before)
        self.assertEqual(actions, [], "in SUSPENDED nessuna azione")

    def test_success_resets_the_backoff(self):
        c, client = self._controller()
        c._find_star_failures = 3
        c.star_lost_since = 0.0
        c._find_star_last_attempt = 0.0
        c._evaluate_star_lost()
        self.assertEqual(c._find_star_failures, 0,
                         "un successo azzera il contatore dei fallimenti")


if __name__ == "__main__":
    unittest.main()
