"""
test_transparency_ratchet.py — §66: il riferimento N1 non si auto-erode ("rana bollita").

Osservato sul cielo il 2026-07-20: con un degrado LENTO il riferimento rolling-high
seguiva il cielo anche verso il basso — denominatore e numeratore scendevano insieme,
l'indice restava ~1.00 e il peggioramento non emergeva mai. Il cricchetto adotta subito
i miglioramenti, congela il riferimento mentre lo stato e' gia' degradato e rilascia i
peggioramenti solo lentamente a cielo sereno (cosi' i cali LEGITTIMI — target che scende,
Luna, cambio campo — non creano mai una soglia irraggiungibile).
"""
from __future__ import annotations

import unittest

from phd2_agent.nina_indices import TransparencyTracker


class _Clock:
    """Clock finto in secondi (il rilascio §66 e' misurato in tempo reale)."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance_min(self, minutes: float) -> None:
        self.t += minutes * 60.0


def _tracker(clock: _Clock, **kw) -> TransparencyTracker:
    params = dict(baseline_window_subs=12, base_best_fraction=0.5, now_fn=clock)
    params.update(kw)
    return TransparencyTracker(**params)


def _ingest(tr: TransparencyTracker, stars: float, filt: str = "L", bkg: float | None = None,
            target: str | None = None, airmass: float | None = None) -> None:
    payload = {"image": {"star_count": stars, "filter": filt}}
    if bkg is not None:
        payload["image"]["median_adu"] = bkg
    if airmass is not None:
        payload["image"]["airmass"] = airmass
    if target is not None:
        payload["context"] = {"target": target}
    tr.ingest(payload)


class TestBoilingFrog(unittest.TestCase):
    """Il caso che ha motivato il §66."""

    # Degrado lento REALISTICO: -2% a posa su 36 pose da 5 min = 3 ore, cielo che
    # scende al 48% del suo valore iniziale. Tasso scelto sul banco: e' il regime che
    # il comportamento §45 NON riesce a vedere (vedi controprova sotto).
    _DECLINE_PER_SUB = 0.02
    _DECLINE_SUBS = 36

    def _run_slow_decline(self, tr: TransparencyTracker, clock: _Clock) -> dict:
        for _ in range(12):                      # cielo stabile a 200 stelle
            _ingest(tr, 200)
            clock.advance_min(5)
        stars = 200.0
        for _ in range(self._DECLINE_SUBS):
            stars *= (1 - self._DECLINE_PER_SUB)
            _ingest(tr, stars)
            clock.advance_min(5)
        return tr.status_block()

    def test_slow_decline_is_detected(self):
        clock = _Clock()
        b = self._run_slow_decline(_tracker(clock), clock)
        self.assertLess(b["index"], 0.8,
                        "il degrado lento DEVE emergere: indice sceso sotto CLEAR")
        self.assertIn(b["state"], ("HAZE", "CLOUD"))

    def test_legacy_behaviour_boils_the_frog(self):
        """Controprova: col kill-switch il difetto storico si ripresenta identico."""
        clock = _Clock()
        b = self._run_slow_decline(_tracker(clock, ref_ratchet_enabled=False), clock)
        self.assertGreater(b["index"], 0.8,
                           "comportamento §45: cielo dimezzato, indice ancora CLEAR")
        self.assertEqual(b["state"], "CLEAR")


class TestRatchetRules(unittest.TestCase):

    def test_improvement_is_adopted_immediately(self):
        clock = _Clock()
        tr = _tracker(clock)
        for _ in range(12):
            _ingest(tr, 100)
            clock.advance_min(5)
        base_before = tr.status_block()["base_stars"]
        for _ in range(12):                      # cielo che MIGLIORA
            _ingest(tr, 300)
            clock.advance_min(5)
        b = tr.status_block()
        self.assertGreater(b["base_stars"], base_before)
        self.assertEqual(b["state"], "CLEAR", "un cielo migliore non deve mai dare allarmi")

    def test_reference_frozen_while_degraded(self):
        """Regola 2: durante un evento il metro di paragone non si tocca."""
        clock = _Clock()
        tr = _tracker(clock)
        for _ in range(12):
            _ingest(tr, 200)
            clock.advance_min(5)
        ref_clear = tr.status_block()["base_stars"]

        for _ in range(10):                      # nube: crollo -> stato degradato
            _ingest(tr, 40)
            clock.advance_min(5)
        b = tr.status_block()
        self.assertIn(b["state"], ("HAZE", "CLOUD"))
        self.assertAlmostEqual(b["base_stars"], ref_clear, delta=0.01,
                               msg="riferimento CONGELATO durante l'evento")

    def test_slow_release_when_clear_avoids_unreachable_threshold(self):
        """Regola 3: un calo legittimo e stabile viene assorbito (nessuno stallo)."""
        clock = _Clock()
        tr = _tracker(clock, ref_release_half_life_min=25.0)
        for _ in range(12):
            _ingest(tr, 200)
            clock.advance_min(5)
        # nuovo campo, stabile a 150: all'inizio l'indice cala...
        for _ in range(12):
            _ingest(tr, 150)
            clock.advance_min(5)
        mid = tr.status_block()["index"]
        # ...ma con il tempo il riferimento rilascia e l'indice risale verso 1
        for _ in range(24):
            _ingest(tr, 150)
            clock.advance_min(20)
        end = tr.status_block()
        self.assertGreater(end["index"], mid)
        self.assertGreater(end["index"], 0.9,
                           "un livello basso STABILE deve tornare CLEAR (proprieta' §45)")

    def test_freeze_has_a_cap_no_permanent_stall(self):
        """Il congelamento NON è eterno: un livello basso STABILE oltre il tetto è la
        nuova normalità (cambio campo/Luna) e il riferimento riprende a rilasciare.

        Difetto trovato dal banco PRIMA del rilascio: senza tetto, un cambio di campo
        che porta l'indice in HAZE bloccava il riferimento per SEMPRE (stallo)."""
        clock = _Clock()
        tr = _tracker(clock, ref_freeze_max_min=90.0, ref_release_half_life_min=25.0)
        for _ in range(12):
            _ingest(tr, 200)
            clock.advance_min(5)
        # nuovo campo stabile al 60%: entra in HAZE e il riferimento si congela
        for _ in range(12):
            _ingest(tr, 120)
            clock.advance_min(5)
        self.assertIn(tr.status_block()["state"], ("HAZE", "CLOUD"))
        # ...ma con il passare del tempo deve tornare CLEAR: nessuno stallo permanente
        for _ in range(60):
            _ingest(tr, 120)
            clock.advance_min(5)
        b = tr.status_block()
        self.assertGreaterEqual(b["index"], 0.8,
                                "oltre il tetto di congelamento il riferimento DEVE adattarsi")
        self.assertEqual(b["state"], "CLEAR")

    def test_release_is_time_based_not_sample_based(self):
        """§57-bis: il comportamento non deve dipendere dalla durata dei sub."""
        results = []
        for sub_min in (1.0, 10.0):
            clock = _Clock()
            tr = _tracker(clock, ref_release_half_life_min=25.0)
            for _ in range(12):
                _ingest(tr, 200)
                clock.advance_min(sub_min)
            # stesso TEMPO totale di degrado (100 min), cadenze diverse
            n = int(100 / sub_min)
            for _ in range(n):
                _ingest(tr, 120)
                clock.advance_min(sub_min)
            results.append(tr.status_block()["base_stars"])
        self.assertAlmostEqual(results[0], results[1], delta=results[0] * 0.15,
                               msg="il rilascio dipende dal tempo, non dal numero di pose")


class TestDiagnosticsAndIsolation(unittest.TestCase):

    def test_session_best_is_exposed_and_never_decreases(self):
        clock = _Clock()
        tr = _tracker(clock)
        for _ in range(12):
            _ingest(tr, 200)
            clock.advance_min(5)
        best = tr.status_block()["base_stars_session_best"]
        for _ in range(12):
            _ingest(tr, 80)
            clock.advance_min(5)
        b = tr.status_block()
        self.assertAlmostEqual(b["base_stars_session_best"], best, delta=0.01,
                               msg="high-water di sessione: non scende mai")
        self.assertIsNotNone(b["ref_drift_pct"])

    def test_reference_is_per_filter(self):
        clock = _Clock()
        tr = _tracker(clock)
        for _ in range(12):
            _ingest(tr, 200, filt="L")
            clock.advance_min(5)
        for _ in range(12):                      # R: meno luce, campo piu' povero
            _ingest(tr, 90, filt="R")
            clock.advance_min(5)
        b = tr.status_block()
        self.assertEqual(b["filter"], "R")
        self.assertGreater(b["index"], 0.9,
                           "il riferimento della R e' suo: nessun falso allarme al cambio filtro")


class TestTargetAwareBaseline(unittest.TestCase):
    """§67 — il cambio campo non si DEDUCE piu' dal conteggio stelle: NINA lo dice."""

    def test_target_change_does_not_raise_a_false_alarm(self):
        """Il caso che il tetto di congelamento §66 doveva tamponare per ~2 ore."""
        clock = _Clock()
        tr = _tracker(clock)
        for _ in range(12):                                   # campo ricco
            _ingest(tr, 200, target="M27")
            clock.advance_min(5)
        self.assertEqual(tr.status_block()["state"], "CLEAR")
        for _ in range(6):                                    # nuovo target, campo POVERO
            _ingest(tr, 60, target="NGC 7009")
            clock.advance_min(5)
        b = tr.status_block()
        self.assertEqual(b["target"], "NGC 7009")
        self.assertGreater(b["index"], 0.9,
                           "campo nuovo = baseline nuova: nessun falso allarme, subito")
        self.assertEqual(b["state"], "CLEAR")

    def test_returning_to_a_previous_target_restores_its_baseline(self):
        clock = _Clock()
        tr = _tracker(clock)
        for _ in range(12):
            _ingest(tr, 200, target="M27")
            clock.advance_min(5)
        base_m27 = tr.status_block()["base_stars"]
        for _ in range(12):
            _ingest(tr, 60, target="NGC 7009")
            clock.advance_min(5)
        _ingest(tr, 200, target="M27")                        # si torna su M27
        b = tr.status_block()
        self.assertAlmostEqual(b["base_stars"], base_m27, delta=base_m27 * 0.05,
                               msg="la storia di M27 non si perde cambiando target")
        self.assertGreater(b["index"], 0.9)

    def test_cloud_on_same_target_still_detected(self):
        """La chiave per target NON deve indebolire il rilevamento nubi."""
        clock = _Clock()
        tr = _tracker(clock)
        for _ in range(12):
            _ingest(tr, 200, target="M27")
            clock.advance_min(5)
        for _ in range(6):                                    # nube sullo STESSO target
            _ingest(tr, 40, target="M27")
            clock.advance_min(5)
        self.assertIn(tr.status_block()["state"], ("HAZE", "CLOUD"))

    def test_backward_compatible_without_target(self):
        """Plugin vecchio / riprese manuali: nessun target -> comportamento §66 identico."""
        clock = _Clock()
        tr = _tracker(clock)
        for _ in range(12):
            _ingest(tr, 200)
            clock.advance_min(5)
        b = tr.status_block()
        self.assertIsNone(b["target"])
        self.assertEqual(b["state"], "CLEAR")
        for _ in range(6):
            _ingest(tr, 40)
            clock.advance_min(5)
        self.assertIn(tr.status_block()["state"], ("HAZE", "CLOUD"))

    def test_airmass_is_telemetry_only(self):
        """§67: l'airmass viaggia ed e' esposta, ma NON tocca nessuna decisione."""
        clock = _Clock()
        results = []
        for am in (1.0, 2.5):
            tr = _tracker(_Clock())
            for _ in range(12):
                _ingest(tr, 200, target="M27", airmass=am)
            results.append(tr.status_block())
        self.assertAlmostEqual(results[0]["index"], results[1]["index"], delta=1e-9,
                               msg="l'airmass non deve influenzare l'indice in questa fase")
        self.assertAlmostEqual(results[1]["airmass"], 2.5, delta=1e-6)


class TestSessionFloor(unittest.TestCase):
    """§67 — il best di sessione promosso da diagnostico a PAVIMENTO del rilascio."""

    def test_reference_never_falls_below_session_floor(self):
        clock = _Clock()
        tr = _tracker(clock, ref_session_floor_frac=0.70, ref_freeze_max_min=0.0)
        for _ in range(12):
            _ingest(tr, 200, target="M27")
            clock.advance_min(5)
        best = tr.status_block()["base_stars_session_best"]
        # degrado profondo e prolungatissimo: senza pavimento il riferimento seguirebbe
        for _ in range(80):
            _ingest(tr, 50, target="M27")
            clock.advance_min(30)
        b = tr.status_block()
        self.assertGreaterEqual(b["base_stars"], best * 0.70 - 0.01,
                                "il riferimento non scende sotto il pavimento di sessione")
        self.assertIn(b["state"], ("HAZE", "CLOUD"),
                      "col pavimento il degrado profondo resta VISIBILE per sempre")

    def test_floor_is_per_target_so_a_new_field_is_free(self):
        """Il pavimento e' sicuro proprio perche' e' per (target, filtro)."""
        clock = _Clock()
        tr = _tracker(clock, ref_session_floor_frac=0.70)
        for _ in range(12):
            _ingest(tr, 200, target="M27")
            clock.advance_min(5)
        for _ in range(12):                        # campo nuovo al 25% del precedente
            _ingest(tr, 50, target="NGC 7009")
            clock.advance_min(5)
        self.assertGreater(tr.status_block()["index"], 0.9,
                           "il pavimento di M27 non vincola NGC 7009")

    def test_floor_can_be_disabled(self):
        clock = _Clock()
        tr = _tracker(clock, ref_session_floor_frac=0.0, ref_freeze_max_min=0.0)
        for _ in range(12):
            _ingest(tr, 200, target="M27")
            clock.advance_min(5)
        for _ in range(80):
            _ingest(tr, 50, target="M27")
            clock.advance_min(30)
        self.assertGreater(tr.status_block()["index"], 0.9,
                           "senza pavimento il riferimento converge al livello basso")


if __name__ == "__main__":
    unittest.main()
