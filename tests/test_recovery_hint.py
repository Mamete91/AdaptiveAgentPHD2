"""
test_recovery_hint.py — §57 S2: RecoveryHintTracker (hint dalla SNR guida).

Paletto 1: autorità safety ZERO (solo osservazione). Paletto 6 + Gate §57-bis:
accumulatore leaky IN SECONDI DI TEMPO REALE (indipendente dal frame-rate di guida).
Clock iniettato: ogni frame simulato avanza di 3 s (frame-rate tipico RC8).
"""
from __future__ import annotations

import unittest

from phd2_agent.config import RecoveryHintConfig
from phd2_agent.recovery_hint import RecoveryHintTracker


def _cfg(**kw) -> RecoveryHintConfig:
    base = dict(enabled=True, snr_recover_frac=0.8, snr_recover_floor=25.0,
                sustained_seconds=15.0, drain_factor=2.0)
    base.update(kw)
    return RecoveryHintConfig(**base)


class _State:
    """Provider mutabile dello stato N1 (state, index)."""
    def __init__(self, state=None, index=None):
        self.state, self.index = state, index
    def __call__(self):
        return (self.state, self.index)


class _Clock:
    """Clock finto: parte da t=1000 e avanza a comando."""
    def __init__(self):
        self.t = 1000.0
    def __call__(self):
        return self.t
    def tick(self, dt=3.0):
        self.t += dt


def _make(state="CLOUD", **cfg_kw):
    st = _State(state)
    clock = _Clock()
    t = RecoveryHintTracker(_cfg(**cfg_kw), state_provider=st, now_fn=clock)
    return t, st, clock


def _frames(t, clock, snr, n, dt=3.0):
    """n frame a SNR data, distanziati dt secondi."""
    for _ in range(n):
        clock.tick(dt)
        t.update(snr)


class TestHintDynamics(unittest.TestCase):
    """1. Niente attivazione su singolo picco; isteresi su/giù (leaky, a tempo)."""

    def test_single_spike_does_not_activate(self):
        t, _, clock = _make()
        _frames(t, clock, 60.0, 1)                       # 1 solo frame buono (3 s)
        self.assertFalse(t.status_block()["active"])
        _frames(t, clock, 5.0, 4)                        # ricade
        self.assertFalse(t.status_block()["active"])
        self.assertEqual(t.status_block()["accumulator_s"], 0.0)

    def test_sustained_activates_and_hysteresis_releases(self):
        t, _, clock = _make()                            # sustained_seconds=15
        _frames(t, clock, 60.0, 6)                       # 15 s buoni accumulati (il 1° frame dt=0)
        self.assertTrue(t.status_block()["active"])
        # Isteresi: un solo frame cattivo NON rilascia (drena 2×3=6 s: 15 -> 9)
        _frames(t, clock, 5.0, 1)
        self.assertTrue(t.status_block()["active"])
        # Rilascio solo ad accumulatore esaurito
        _frames(t, clock, 5.0, 2)
        self.assertFalse(t.status_block()["active"])

    def test_long_gap_does_not_credit_ghost_time(self):
        """Un buco lungo tra frame (stella persa) non accredita tempo buono fantasma."""
        t, _, clock = _make()
        _frames(t, clock, 60.0, 1)                       # primo frame (dt=0)
        _frames(t, clock, 60.0, 1, dt=120.0)             # buco di 2 minuti -> clamp a 5 s
        self.assertLessEqual(t.status_block()["accumulator_s"], 5.0)
        self.assertFalse(t.status_block()["active"])


class TestGating(unittest.TestCase):
    """2. Inerte se l'ultimo stato N1 è CLEAR (o ignoto)."""

    def test_inert_when_clear(self):
        t, _, clock = _make(state="CLEAR")
        _frames(t, clock, 80.0, 20)
        b = t.status_block()
        self.assertFalse(b["active"])
        self.assertEqual(b["accumulator_s"], 0.0)

    def test_inert_when_state_unknown(self):
        t, _, clock = _make(state=None)
        _frames(t, clock, 80.0, 20)
        self.assertFalse(t.status_block()["active"])


class TestSnrReference(unittest.TestCase):
    """3. snr_ref catturata in CLEAR e usata come soglia relativa; floor rispettato."""

    def test_relative_threshold_from_clear_reference(self):
        t, st, clock = _make(state="CLEAR")
        _frames(t, clock, 58.0, 50)                      # cielo limpido: ref -> ~58
        self.assertAlmostEqual(t.status_block()["snr_ref"], 58.0, delta=1.0)

        st.state = "CLOUD"                               # arrivano le nubi
        _frames(t, clock, 40.0, 10)                      # 40 < 0.8*58=46.4 -> NON buono
        self.assertFalse(t.status_block()["active"])
        _frames(t, clock, 50.0, 6)                       # 50 >= 46.4 -> buono, 15 s
        self.assertTrue(t.status_block()["active"])

    def test_absolute_floor_without_reference(self):
        t, _, clock = _make()                            # mai CLEAR: nessuna ref
        _frames(t, clock, 20.0, 10)                      # sotto il floor 25 -> non buono
        self.assertFalse(t.status_block()["active"])
        _frames(t, clock, 30.0, 6)                       # sopra il floor -> buono
        self.assertTrue(t.status_block()["active"])


class TestStructuralNoSafetyPath(unittest.TestCase):
    """4. Paletto 1 strutturale: nessun percorso verso N6/safety."""

    def test_module_has_no_safety_imports_or_api(self):
        import phd2_agent.recovery_hint as mod
        src_names = dir(mod)
        self.assertNotIn("SafetyDecisionEngine", src_names)
        self.assertNotIn("controller", src_names)        # non importa il controller
        self.assertNotIn("diagnostic_engine", src_names)
        t, _, _ = _make()
        public = [n for n in dir(t) if not n.startswith("_")]
        self.assertEqual(sorted(public),
                         ["cfg", "observe_probe", "status_block", "update"])

    def test_active_hint_never_touches_transparency(self):
        """L'hint attivo non altera lo stato N1 letto dal provider (read-only)."""
        t, st, clock = _make()
        st.index = 0.1
        _frames(t, clock, 80.0, 10)
        self.assertTrue(t.status_block()["active"])
        self.assertEqual((st.state, st.index), ("CLOUD", 0.1))   # intatto


class TestKillSwitch(unittest.TestCase):
    """5. enabled=false -> nessun effetto."""

    def test_disabled_is_noop(self):
        t, _, clock = _make(enabled=False)
        _frames(t, clock, 80.0, 20)
        b = t.status_block()
        self.assertFalse(b["enabled"])
        self.assertFalse(b["active"])
        self.assertEqual(b["accumulator_s"], 0.0)
        t.observe_probe({"index": 0.9, "state": "CLEAR"})
        self.assertEqual(b["probes"], [])


class TestProbeTelemetry(unittest.TestCase):
    """Paletto 8: record sonda con attribuzione trigger + esito, gated sul contesto."""

    def test_probe_recorded_with_s1_attribution(self):
        t, _, clock = _make()
        _frames(t, clock, 10.0, 1)                       # contesto degradato, hint spento
        t.observe_probe({"index": 0.12, "state": "CLOUD"})
        probes = t.status_block()["probes"]
        self.assertEqual(len(probes), 1)
        self.assertEqual(probes[0]["trigger"], "timeout_S1")
        self.assertEqual(probes[0]["outcome_state"], "CLOUD")

    def test_probe_recorded_with_s2_attribution_when_hint_active(self):
        t, _, clock = _make()
        _frames(t, clock, 60.0, 6)                       # hint attivo (15 s buoni)
        t.observe_probe({"index": 0.85, "state": "CLEAR"})
        probes = t.status_block()["probes"]
        self.assertEqual(probes[0]["trigger"], "hint_S2")
        self.assertEqual(probes[0]["outcome_state"], "CLEAR")

    def test_normal_imaging_light_not_recorded(self):
        t, _, clock = _make(state="CLEAR")
        _frames(t, clock, 60.0, 1)                       # contesto CLEAR
        t.observe_probe({"index": 0.95, "state": "CLEAR"})
        self.assertEqual(t.status_block()["probes"], [])


if __name__ == "__main__":
    unittest.main()
