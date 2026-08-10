"""
test_safety_state.py — §73: riflesso dello stato del Safety Monitor.

La decisione vive nel plugin; qui si conserva solo l'ultimo stato PUBBLICATO,
con la sua freschezza. Invariante da difendere: **l'assenza di notizie non e'
mai "sicuro"** (stessa disciplina §55/§68, applicata alla presentazione).
"""
from __future__ import annotations

import unittest

from phd2_agent.safety_state import (SafetyStateStore, STATE_MERIDIAN, STATE_SAFE,
                                     STATE_UNKNOWN, STATE_UNSAFE)


class _Clock:
    def __init__(self) -> None:
        self.t = 500.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class TestReflection(unittest.TestCase):

    def test_states_round_trip(self):
        c = _Clock()
        s = SafetyStateStore(now_fn=c)
        self.assertTrue(s.update(STATE_SAFE))
        b = s.status_block()
        self.assertEqual(b["state"], STATE_SAFE)
        self.assertIsNone(b["cause"], "SAFE non ha causa")

        self.assertTrue(s.update(STATE_UNSAFE, cause="guide_unobservable"))
        b = s.status_block()
        self.assertEqual(b["state"], STATE_UNSAFE)
        self.assertEqual(b["cause"], "GUIDE_UNOBSERVABLE", "causa normalizzata")

    def test_meridian_window_exposes_the_divergence(self):
        """§72 — dentro la finestra il RIPORTATO diverge dall'INTERNO: e' proprio
        cio' che l'osservatore deve poter vedere."""
        c = _Clock()
        s = SafetyStateStore(now_fn=c)
        s.update(STATE_MERIDIAN, detail="flip autorizzato", internal_safe=False)
        b = s.status_block()
        self.assertEqual(b["state"], STATE_MERIDIAN)
        self.assertFalse(b["internal_safe"], "il cielo e' ancora unsafe: va detto")
        self.assertEqual(b["detail"], "flip autorizzato")


class TestNoNewsIsNotSafe(unittest.TestCase):
    """L'invariante piu' importante del modulo."""

    def test_stale_becomes_unknown_not_safe(self):
        c = _Clock()
        s = SafetyStateStore(staleness_seconds=60.0, now_fn=c)
        s.update(STATE_SAFE)
        self.assertEqual(s.status_block()["state"], STATE_SAFE)
        c.advance(120)
        b = s.status_block()
        self.assertEqual(b["state"], STATE_UNKNOWN,
                         "silenzio del plugin: SCONOSCIUTO, mai un verde residuo")
        self.assertFalse(b["fresh"])
        self.assertGreater(b["age_s"], 60)

    def test_never_published_is_unknown(self):
        s = SafetyStateStore(now_fn=_Clock())
        b = s.status_block()
        self.assertEqual(b["state"], STATE_UNKNOWN)
        self.assertIsNone(b["age_s"])

    def test_monitor_disconnected_is_unknown(self):
        """Monitor scollegato in NINA: fatto NOTO, ma comunque non 'sicuro'."""
        c = _Clock()
        s = SafetyStateStore(now_fn=c)
        s.update(STATE_SAFE, connected=False)
        b = s.status_block()
        self.assertEqual(b["state"], STATE_UNKNOWN)
        self.assertFalse(b["connected"])

    def test_unsafe_never_decays_into_safe(self):
        c = _Clock()
        s = SafetyStateStore(staleness_seconds=30.0, now_fn=c)
        s.update(STATE_UNSAFE, cause="CLOUD")
        c.advance(600)
        self.assertEqual(s.status_block()["state"], STATE_UNKNOWN,
                         "un UNSAFE stantio non diventa MAI SAFE")


class TestHeartbeatWindow(unittest.TestCase):
    """§73-ter — il difetto trovato sul campo il 4/8: il publisher deduplicava
    (POST solo al cambio) mentre lo store ha una freschezza. A stato stabile
    nessuno dei due parlava piu' e la dashboard diceva UNKNOWN con il monitor
    perfettamente vivo. Ora il plugin manda un BATTITO a ogni tick e dichiara la
    propria cadenza; la finestra si DERIVA da quella (principio §43)."""

    def test_stable_state_survives_with_heartbeat(self):
        """Il caso reale: SAFE stabile per mezz'ora deve restare SAFE."""
        c = _Clock()
        s = SafetyStateStore(now_fn=c)
        for _ in range(120):                     # 30 minuti a 15 s
            s.update(STATE_SAFE, poll_interval_s=15)
            c.advance(15)
            self.assertEqual(s.status_block()["state"], STATE_SAFE)

    def test_window_derives_from_declared_cadence(self):
        """Cadenza lenta (120 s, il massimo configurabile): la finestra si allarga,
        altrimenti una soglia fissa a 60 s scadrebbe SEMPRE a monitor vivo."""
        c = _Clock()
        s = SafetyStateStore(now_fn=c)
        s.update(STATE_SAFE, poll_interval_s=120)
        self.assertEqual(s.status_block()["staleness_window_s"], 360.0,
                         "3 battiti persi a 120 s")
        c.advance(200)
        self.assertEqual(s.status_block()["state"], STATE_SAFE,
                         "un solo battito perso non e' ignoranza")

    def test_fast_cadence_keeps_the_floor(self):
        """Cadenza rapida (5 s): non si scende sotto il pavimento, per non
        dichiarare ignoranza al primo singhiozzo di rete."""
        c = _Clock()
        s = SafetyStateStore(now_fn=c)
        s.update(STATE_SAFE, poll_interval_s=5)
        self.assertEqual(s.status_block()["staleness_window_s"],
                         SafetyStateStore.MIN_STALENESS_S)

    def test_silence_beyond_the_window_is_still_unknown(self):
        """L'invariante non si indebolisce: il plugin che TACE resta ignoto."""
        c = _Clock()
        s = SafetyStateStore(now_fn=c)
        s.update(STATE_SAFE, poll_interval_s=15)
        c.advance(3 * 15 + 1)
        self.assertEqual(s.status_block()["state"], STATE_UNKNOWN)


class TestRobustness(unittest.TestCase):

    def test_unknown_state_is_rejected_not_guessed(self):
        """Payload di una versione futura: si rifiuta, non si indovina."""
        c = _Clock()
        s = SafetyStateStore(now_fn=c)
        s.update(STATE_SAFE)
        self.assertFalse(s.update("PARKED_FOR_RAIN"))
        self.assertEqual(s.status_block()["state"], STATE_SAFE,
                         "lo stato precedente resta, non viene corrotto")

    def test_case_and_whitespace_tolerated(self):
        s = SafetyStateStore(now_fn=_Clock())
        self.assertTrue(s.update("  meridian_protection  "))
        self.assertEqual(s.status_block()["state"], STATE_MERIDIAN)

    def test_cause_only_shown_for_unsafe(self):
        c = _Clock()
        s = SafetyStateStore(now_fn=c)
        s.update(STATE_SAFE, cause="CLOUD")   # incoerente: la causa va ignorata
        self.assertIsNone(s.status_block()["cause"])


if __name__ == "__main__":
    unittest.main()
