"""
test_target_inheritance.py — §70: ereditarietà del contesto per immagini senza target.

Regressione trovata sul campo la notte del 2026-08-03/04 (prima uscita reale del
recupero post-§67): le immagini della Recovery Probe nascono dentro Trigger On
Unsafe, FUORI dal contenitore target di NINA, quindi arrivano SEMPRE senza
`context.target`. Con la chiave §67 (target, filtro) aprivano una chiave vergine
la cui baseline si auto-inizializzava dal campione stesso:

    sonda #1: 7 stelle  / rif 7  = 1.00  -> falso CLEAR -> falso SAFE (23:48)
    sonda #2: 32 stelle / rif 32 = 1.00  (cricchetto regola 1 sulla chiave orfana)

mentre la baseline vera — ("Abell 61","H"), rif 263-264 — era intatta (la prima
light vera, 130 stelle, ha infatti dato 0.49 VELATURE).

Regola §70: un'immagine che non dichiara un target appartiene al contesto di
sessione corrente (ultimo target dichiarato da una light). Il replay della notte
è il test di regressione permanente.
"""
from __future__ import annotations

import unittest

from phd2_agent.nina_indices import TransparencyTracker


class _Clock:
    def __init__(self) -> None:
        self.t = 10_000.0

    def __call__(self) -> float:
        return self.t

    def advance_min(self, m: float) -> None:
        self.t += m * 60.0


def _light(stars: float, filt: str = "H", target: str = "Abell 61") -> dict:
    return {"image": {"star_count": stars, "filter": filt},
            "context": {"target": target}}


def _probe(stars: float, filt: str = "H") -> dict:
    # Immagine di sonda REALE: il blocco context è del tutto ASSENTE
    # (AgentTelemetryForwarder lo omette quando MetaData.Target è null).
    return {"image": {"star_count": stars, "filter": filt}}


def _tracker(clock: _Clock) -> TransparencyTracker:
    return TransparencyTracker(enabled=True, baseline_window_subs=12,
                               base_best_fraction=0.5, clear_above=0.8,
                               cloud_below=0.5, hysteresis=0.05, now_fn=clock)


class TestNight20260803Replay(unittest.TestCase):
    """Il replay fedele della notte: adesso la sonda DEVE dire CLOUD."""

    def _build_abell61_baseline(self, t: TransparencyTracker, c: _Clock) -> None:
        for stars in (258, 262, 264, 261, 263):
            t.ingest(_light(stars))
            c.advance_min(5)
        self.assertEqual(t.status_block()["state"], "CLEAR")

    def test_probe_without_target_inherits_the_real_baseline(self):
        c = _Clock()
        t = _tracker(c)
        self._build_abell61_baseline(t, c)

        # 23:43 — sonda #1: 7 stelle, NESSUN context. Prima del §70: 7/7 = 1.00 CLEAR.
        t.ingest(_probe(7))
        b = t.status_block()
        self.assertLess(b["index"], 0.10,
                        f"7 stelle su rif ~263 deve dare ~0.03, non {b['index']}")
        self.assertEqual(b["state"], "CLOUD",
                         "la sonda sotto nubi fitte DEVE dire CLOUD (il 3/8 disse CLEAR)")
        self.assertEqual(b["target"], "Abell 61",
                         "la sonda eredita il contesto di sessione")

        # 23:50 — sonda #2: 32 stelle. Prima del §70: 32/32 = 1.00.
        c.advance_min(7)
        t.ingest(_probe(32))
        b = t.status_block()
        self.assertLess(b["index"], 0.20)
        self.assertEqual(b["state"], "CLOUD")

    def test_first_real_light_still_evaluates_like_the_field_did(self):
        """Il comportamento che il 3/8 era GIUSTO deve restare identico: la light
        con target da 130 stelle valeva 0.49 (VELATURE)."""
        c = _Clock()
        t = _tracker(c)
        self._build_abell61_baseline(t, c)
        t.ingest(_probe(7))
        c.advance_min(7)
        t.ingest(_probe(32))
        c.advance_min(18)                       # flip + prima posa
        t.ingest(_light(130))
        b = t.status_block()
        self.assertAlmostEqual(b["index"], 0.49, delta=0.06)
        self.assertIn(b["state"], ("HAZE", "CLOUD"))

    def test_recovery_probes_track_the_real_recovery(self):
        """Col fix, le sonde vedono il recupero REALE (284 su rif ~263 = sopra 1),
        non un 1.00 di bootstrap."""
        c = _Clock()
        t = _tracker(c)
        self._build_abell61_baseline(t, c)
        t.ingest(_probe(7))
        c.advance_min(10)
        t.ingest(_probe(284))                   # cielo davvero tornato
        b = t.status_block()
        self.assertGreaterEqual(b["index"], 0.95)
        self.assertEqual(b["state"], "CLEAR")


class TestContextRules(unittest.TestCase):

    def test_no_target_ever_behaves_like_pre_67(self):
        """Chi non usa contenitori target resta sulla chiave ("", filtro):
        comportamento §45/§66, validato sul campo per mesi."""
        c = _Clock()
        t = _tracker(c)
        for stars in (100, 102, 98, 101):
            t.ingest(_probe(stars))             # nessun target, mai
            c.advance_min(5)
        b = t.status_block()
        self.assertEqual(b["state"], "CLEAR")
        self.assertIsNone(b["target"])

    def test_target_change_updates_the_session_context(self):
        """Al cambio target reale le nuove light DICHIARANO: il contesto segue."""
        c = _Clock()
        t = _tracker(c)
        for _ in range(4):
            t.ingest(_light(260, target="Abell 61"))
            c.advance_min(5)
        for _ in range(3):
            t.ingest(_light(90, target="M27"))  # campo più povero: baseline SUA
            c.advance_min(5)
        self.assertEqual(t.status_block()["state"], "CLEAR",
                         "campo povero ma stabile = CLEAR (principio §45)")
        # sonda senza target dopo il cambio: eredita M27, non Abell 61
        t.ingest(_probe(88))
        b = t.status_block()
        self.assertEqual(b["target"], "M27")
        self.assertEqual(b["state"], "CLEAR")
        self.assertGreaterEqual(b["index"], 0.9,
                                "88 su rif ~90 è cielo pulito; su rif 260 sarebbe 0.34")

    def test_filters_stay_separate_within_the_inherited_target(self):
        """L'ereditarietà riguarda il TARGET; il filtro resta quello del payload
        (la sonda espone col vetro montato in quel momento — il 3/8 era O)."""
        c = _Clock()
        t = _tracker(c)
        for _ in range(3):
            t.ingest(_light(260, filt="H"))
            c.advance_min(5)
        for _ in range(3):
            t.ingest(_light(350, filt="O"))
            c.advance_min(5)
        t.ingest(_probe(20, filt="O"))          # sonda su O, eredita Abell 61
        b = t.status_block()
        self.assertEqual(b["filter"], "O")
        self.assertEqual(b["target"], "Abell 61")
        self.assertLess(b["index"], 0.10, "20 su rif ~350 (O), non bootstrap 1.00")


if __name__ == "__main__":
    unittest.main()
