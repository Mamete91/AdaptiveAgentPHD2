"""
test_guide_health.py — §68: osservabilità del canale di guida.

Il caso di riferimento è il guasto reale del 2026-07-26: la camera di guida entra
in uno stato patologico (sospetta congestione USB), PHD2 manda ancora qualche
GuideStep pessimo e poi TACE. `guiding_state` resta congelato su un valore
operativo e nessuno dei quattro latch di N6 poteva scattare.

Qui si verifica solo la MISURA (l'agente misura, il plugin decide): i due orologi
distinti, il gate delle pause annunciate, la corroborazione e la robustezza.
"""
from __future__ import annotations

import unittest

from phd2_agent.config import GuideHealthConfig
from phd2_agent.guide_health import GuideHealthTracker


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def _tracker(clock: _Clock, **kw) -> GuideHealthTracker:
    return GuideHealthTracker(GuideHealthConfig(**kw), now_fn=clock)


class TestTwoClocks(unittest.TestCase):
    """I due orologi distinti sono il cuore del §68."""

    def test_guide_step_updates_both_clocks(self):
        c = _Clock()
        t = _tracker(c)
        t.set_guiding_expected(True, "test")
        t.on_guide_step({"SNR": 30.0, "StarMass": 12000})
        c.advance(20)
        b = t.status_block()
        self.assertAlmostEqual(b["frame_age_s"], 20.0, delta=0.1)
        self.assertAlmostEqual(b["guide_age_s"], 20.0, delta=0.1)

    def test_looping_keeps_channel_alive_but_not_guiding(self):
        """PHD2 espone e tenta il riaggancio: il CANALE è vivo, la guida no.
        Prima del §68 l'evento era ignorato e il canale sembrava muto."""
        c = _Clock()
        t = _tracker(c)
        t.set_guiding_expected(True, "test")
        t.on_guide_step({"SNR": 30.0})
        c.advance(60)
        t.on_looping_exposure({"SNR": 5.0, "ErrorCode": 2})   # LOWSNR
        b = t.status_block()
        self.assertAlmostEqual(b["frame_age_s"], 0.0, delta=0.1,
                               msg="il canale sta producendo frame")
        self.assertAlmostEqual(b["guide_age_s"], 60.0, delta=0.1,
                               msg="ma non si sta guidando da 60 s")

    def test_silence_ages_both_clocks(self):
        """Il caso 26/7: PHD2 tace del tutto."""
        c = _Clock()
        t = _tracker(c)
        t.set_guiding_expected(True, "test")
        t.on_guide_step({"SNR": 30.0})
        c.advance(400)
        b = t.status_block()
        self.assertAlmostEqual(b["frame_age_s"], 400.0, delta=0.1)
        self.assertTrue(b["guiding_expected"],
                        "nessun annuncio di stop => la guida è ancora ATTESA")


class TestExpectationGate(unittest.TestCase):
    """Le pause legittime sono ANNUNCIATE; i guasti no. È l'asimmetria che rende
    sicuro il gate senza toccare `_lastKnownGuidingActive` del plugin."""

    def test_announced_pause_clears_expectation(self):
        c = _Clock()
        t = _tracker(c)
        t.set_guiding_expected(True, "avvio")
        for reason in ("guida fermata", "pausa"):
            t.set_guiding_expected(False, reason)
            self.assertFalse(t.status_block()["guiding_expected"])
            t.set_guiding_expected(True, "ripresa")
            self.assertTrue(t.status_block()["guiding_expected"])

    def test_resume_resets_clocks(self):
        """Alla ripartenza gli orologi valgono da adesso: la pausa non deve
        presentarsi come un'anomalia appena la guida riprende."""
        c = _Clock()
        t = _tracker(c)
        t.set_guiding_expected(True, "avvio")
        t.on_guide_step({"SNR": 30.0})
        t.set_guiding_expected(False, "flip")
        c.advance(900)                       # 15 minuti di flip
        t.set_guiding_expected(True, "ripresa")
        b = t.status_block()
        self.assertAlmostEqual(b["frame_age_s"], 0.0, delta=0.1)
        self.assertAlmostEqual(b["guide_age_s"], 0.0, delta=0.1)


class TestCorroboration(unittest.TestCase):
    """Segnali che possono ACCELERARE il riconoscimento, mai deciderlo da soli."""

    def test_error_codes_are_named_and_windowed(self):
        c = _Clock()
        t = _tracker(c, error_window_s=100.0)
        t.set_guiding_expected(True, "test")
        t.on_guide_step({"ErrorCode": 1})     # SATURATED
        t.on_guide_step({"ErrorCode": 7})     # MASSCHANGE
        b = t.status_block()
        self.assertEqual(b["star_errors_recent"], 2)
        self.assertEqual(b["last_star_error"], "MASSCHANGE")
        self.assertIn("SATURATED", b["star_errors_by_code"])
        c.advance(200)                        # fuori finestra
        self.assertEqual(t.status_block()["star_errors_recent"], 0)

    def test_alert_severity_is_structured_not_text(self):
        c = _Clock()
        t = _tracker(c, alert_window_s=120.0)
        t.on_alert("Lost connection to camera", "error")
        b = t.status_block()
        self.assertEqual(b["alert_type"], "error")
        self.assertTrue(b["alert_severe"])
        t.on_alert("Calibration complete", "info")
        self.assertFalse(t.status_block()["alert_severe"],
                         "un alert informativo NON corrobora")

    def test_severe_alert_expires(self):
        c = _Clock()
        t = _tracker(c, alert_window_s=60.0)
        t.on_alert("boom", "warning")
        self.assertTrue(t.status_block()["alert_severe"])
        c.advance(120)
        self.assertFalse(t.status_block()["alert_severe"])

    def test_star_mass_dispersion_separates_electrical_from_optical(self):
        """Salti erratici (frame corrotti) vs calo stabile (velatura)."""
        c = _Clock()
        t = _tracker(c)
        for m in (10000, 200, 9800, 150, 10200, 300, 9900):   # erratico
            t.on_guide_step({"StarMass": m})
            c.advance(2)
        erratic = t.status_block()["star_mass_dispersion"]

        c2 = _Clock()
        t2 = _tracker(c2)
        for m in (5000, 4950, 5010, 4980, 5020, 4990, 5000):  # stabile (anche se basso)
            t2.on_guide_step({"StarMass": m})
            c2.advance(2)
        stable = t2.status_block()["star_mass_dispersion"]

        self.assertIsNotNone(erratic)
        self.assertIsNotNone(stable)
        self.assertGreater(erratic, stable * 5,
                           "la dispersione deve distinguere i due regimi")


class TestChannelReady(unittest.TestCase):
    """§71 — "canale pronto" per la sonda: consenso AND di condizioni sostenute.
    Il riferimento è il profilo REALE della notte 3-4/8 (frazione di frame con
    stella, dai log): 0%% → 41%% (riaggancio-lampo) → 86%% sostenuto."""

    def _feed_minute(self, t, c, tracked, lost, err_code=2):
        """Un minuto di frame a ~3 s: `tracked` GuideStep e `lost` StarLost."""
        total = tracked + lost
        for i in range(total):
            if i < lost:
                t.on_star_lost({"ErrorCode": err_code, "SNR": 1.0})
            else:
                t.on_guide_step({"SNR": 25.0, "StarMass": 9000})
            c.advance(60.0 / max(1, total))

    def test_replay_20260803_progression(self):
        c = _Clock()
        t = _tracker(c, ready_window_s=90.0, ready_min_tracked_fraction=0.7,
                     ready_frame_max_age_s=10.0, ready_max_errors=2,
                     ready_min_samples=10, error_window_s=120.0)
        t.set_guiding_expected(True, "test")

        # 23:37 — buio totale: 21 StarLost, 0 GuideStep
        self._feed_minute(t, c, tracked=0, lost=21)
        b = t.status_block()
        self.assertFalse(b["channel_ready"], "0% tracciata: gate chiuso")

        # 23:40 — riaggancio-lampo: 9 tracciati / 13 persi = 41%
        self._feed_minute(t, c, tracked=9, lost=13)
        b = t.status_block()
        self.assertFalse(b["channel_ready"],
                         "41% NON è stabilità: la sonda reale partì qui per niente")
        self.assertTrue(any("instabile" in r or "errori" in r
                            for r in b["channel_not_ready_reasons"]))

        # 23:47-48 — riaggancio sostenuto: >2 min di guida pulita
        # (drena sia la finestra della frazione sia quella degli errori)
        self._feed_minute(t, c, tracked=21, lost=0)
        self._feed_minute(t, c, tracked=21, lost=0)
        self._feed_minute(t, c, tracked=21, lost=0)
        b = t.status_block()
        self.assertTrue(b["channel_ready"],
                        f"86%+ sostenuto deve aprire: {b['channel_not_ready_reasons']}")
        self.assertGreaterEqual(b["tracked_fraction"], 0.9)

    def test_dead_channel_26_7_stays_closed(self):
        """Canale muto (26/7): nessun frame -> mai pronto. Il tetto S1 dei 15 min
        (lato plugin) resta l'unica via — per diagnosi, non per ripresa."""
        c = _Clock()
        t = _tracker(c)
        t.set_guiding_expected(True, "test")
        t.on_guide_step({"SNR": 30.0})
        c.advance(300)
        b = t.status_block()
        self.assertFalse(b["channel_ready"])
        self.assertTrue(any("frame" in r for r in b["channel_not_ready_reasons"]))

    def test_severe_alert_blocks_readiness(self):
        c = _Clock()
        t = _tracker(c, alert_window_s=180.0)
        t.set_guiding_expected(True, "test")
        for _ in range(30):
            t.on_guide_step({"SNR": 30.0})
            c.advance(3)
        self.assertTrue(t.status_block()["channel_ready"])
        t.on_alert("Lost connection to camera", "error")
        b = t.status_block()
        self.assertFalse(b["channel_ready"])
        self.assertIn("alert PHD2 severo recente", b["channel_not_ready_reasons"])

    def test_insufficient_samples_is_not_ready(self):
        """Poca statistica = NON pronto (mai 'pronto per assenza di prove')."""
        c = _Clock()
        t = _tracker(c, ready_min_samples=10)
        t.set_guiding_expected(True, "test")
        for _ in range(4):
            t.on_guide_step({"SNR": 30.0})
            c.advance(3)
        b = t.status_block()
        self.assertFalse(b["channel_ready"])
        self.assertTrue(any("statistica" in r for r in b["channel_not_ready_reasons"]))

    def test_error_burst_blocks_even_with_good_fraction(self):
        """MASSCHANGE/SATURATED ripetuti (firma USB 26/7): anche a stella
        'tracciata', il canale non è affidabile."""
        c = _Clock()
        t = _tracker(c, ready_max_errors=2, error_window_s=120.0)
        t.set_guiding_expected(True, "test")
        for i in range(30):
            ev = {"SNR": 28.0, "StarMass": 9000}
            if i % 5 == 0:
                ev["ErrorCode"] = 7          # MASSCHANGE, frame comunque "guidato"
            t.on_guide_step(ev)
            c.advance(3)
        b = t.status_block()
        self.assertFalse(b["channel_ready"])
        self.assertTrue(any("errori" in r for r in b["channel_not_ready_reasons"]))


class TestRobustness(unittest.TestCase):

    def test_kill_switch_makes_it_inert(self):
        c = _Clock()
        t = _tracker(c, enabled=False)
        t.set_guiding_expected(True, "test")
        t.on_guide_step({"SNR": 30.0, "ErrorCode": 1})
        t.on_alert("boom", "error")
        b = t.status_block()
        self.assertFalse(b["enabled"])
        self.assertIsNone(b["frame_age_s"])
        self.assertFalse(b["guiding_expected"])

    def test_malformed_events_never_raise(self):
        c = _Clock()
        t = _tracker(c)
        for ev in ({}, {"ErrorCode": None}, {"StarMass": "x"}, {"ErrorCode": 0},
                   {"StarMass": -5}, {"SNR": float("nan")}):
            t.on_guide_step(ev)
            t.on_looping_exposure(ev)
        t.on_alert(None, None)                # type: ignore[arg-type]
        b = t.status_block()
        self.assertEqual(b["star_errors_recent"], 0, "ErrorCode 0/None non è un errore")
        self.assertIsNotNone(b["frame_age_s"])

    def test_status_block_shape_is_stable(self):
        """Contratto con il plugin: le chiavi devono esserci sempre."""
        t = _tracker(_Clock())
        keys = set(t.status_block().keys())
        for k in ("enabled", "frame_age_s", "guide_age_s", "guiding_expected",
                  "star_errors_recent", "last_star_error", "alert_type",
                  "alert_severe", "star_mass_dispersion"):
            self.assertIn(k, keys)


if __name__ == "__main__":
    unittest.main()
