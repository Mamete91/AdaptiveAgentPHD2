"""
test_sky_degradation.py — §76: l'evidenza di DEGRADO dal canale guida.

Origine: notte 2026-08-04. La SNR della stella di guida è crollata da ~70 a ~22
(31% del riferimento) fra le 23:07 e le 23:11; N1 ha riconosciuto le nubi solo
alle 23:14 — perché era fermo all'ultima posa buona — e il monitor è passato
UNSAFE alle 23:16. **Otto minuti** durante i quali NINA ha esposto un light
integralmente sotto le nubi.

Il canale guida vede a 3 s, la camera di ripresa a 300 s: questo osservatore
copre la finestra in cui il sensore veloce sa già e quello lento non ancora.

Asimmetria deliberata rispetto all'hint di recupero (§57): soglia più severa
(50% contro 80%) e sostegno più lungo (90 s contro 60 s). Un falso positivo qui
mette in pausa la sequenza, quindi si chiede più evidenza — e nel verso opposto
(recupero) il giudice resta la posa-sonda, mai questo segnale.
"""
from __future__ import annotations

import unittest

from phd2_agent.config import RecoveryHintConfig
from phd2_agent.recovery_hint import RecoveryHintTracker


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class _State:
    """Provider read-only dello stato N1 (il tracker non importa N1)."""

    def __init__(self, state="CLEAR") -> None:
        self.state = state

    def __call__(self):
        return (self.state, None)


def _tracker(clock, state, **kw):
    return RecoveryHintTracker(RecoveryHintConfig(**kw), state_provider=state, now_fn=clock)


def _feed(t, c, snr, seconds, step=3.0):
    """Alimenta il tracker a cadenza di guida (~3 s) per `seconds`."""
    for _ in range(int(seconds / step)):
        t.update(snr)
        c.advance(step)


class TestNight20260804Replay(unittest.TestCase):
    """Il replay della notte, come regressione permanente."""

    def test_degradation_is_detected_before_n1(self):
        c = _Clock()
        st = _State("CLEAR")
        t = _tracker(c, st, snr_degrade_frac=0.5, degrade_sustained_seconds=90.0)

        # 22:50-23:07 — cielo limpido, SNR ~70: si forma il riferimento.
        _feed(t, c, 70.0, 1200)
        b = t.status_block()
        self.assertAlmostEqual(b["snr_ref"], 70.0, delta=1.0)
        self.assertFalse(b["degrading"], "cielo limpido: nessun degrado")

        # 23:08-23:11 — il crollo reale: 51 -> 37 -> 26 -> 23.
        for snr in (51.0, 37.0, 26.0, 23.0):
            _feed(t, c, snr, 60)
        b = t.status_block()
        self.assertTrue(b["degrading"],
                        f"il canale guida DEVE vederlo: {b['degrade_reason']}")
        self.assertIn("sostenuta", b["degrade_reason"])

    def test_it_fires_within_the_wasted_window(self):
        """Deve scattare entro i ~5 minuti in cui N1 era ancora fermo sul buono."""
        c = _Clock()
        st = _State("CLEAR")
        t = _tracker(c, st, snr_degrade_frac=0.5, degrade_sustained_seconds=90.0)
        _feed(t, c, 70.0, 900)
        t0 = c.t
        fired_at = None
        for _ in range(100):
            t.update(24.0)
            c.advance(3.0)
            if t.status_block()["degrading"]:
                fired_at = c.t - t0
                break
        self.assertIsNotNone(fired_at, "il degrado sostenuto deve scattare")
        self.assertLessEqual(fired_at, 120,
                             "entro 2 minuti: N1 ci mise 6 minuti quella notte")


class TestNoFalsePositives(unittest.TestCase):

    def test_stable_sky_never_degrades(self):
        c = _Clock()
        t = _tracker(c, _State("CLEAR"))
        _feed(t, c, 70.0, 3600)
        self.assertFalse(t.status_block()["degrading"], "un'ora di cielo stabile")

    def test_transient_dip_is_not_enough(self):
        """Un satellite, una folata di seeing: 30 s non bastano (ne servono 90)."""
        c = _Clock()
        t = _tracker(c, _State("CLEAR"))
        _feed(t, c, 70.0, 900)
        _feed(t, c, 20.0, 30)
        self.assertFalse(t.status_block()["degrading"])
        _feed(t, c, 70.0, 120)
        self.assertFalse(t.status_block()["degrading"], "e rientra risalendo")

    def test_no_reference_means_no_evidence(self):
        """Fail-inert: senza riferimento credibile il rapporto non significa nulla.
        Mai 'degrado per assenza di dati'."""
        c = _Clock()
        t = _tracker(c, _State("CLEAR"), degrade_min_ref=15.0)
        _feed(t, c, 5.0, 600)      # cielo pessimo da sempre: ref bassissimo
        b = t.status_block()
        self.assertFalse(b["degrading"])
        self.assertIn("riferimento", b["degrade_reason"])

    def test_kill_switch(self):
        c = _Clock()
        t = _tracker(c, _State("CLEAR"), degrade_enabled=False)
        _feed(t, c, 70.0, 900)
        _feed(t, c, 10.0, 600)
        self.assertFalse(t.status_block()["degrading"])


class TestReferenceRatchet(unittest.TestCase):
    """§76-bis — la "rana bollita" trovata scrivendo il replay: con l'EMA
    simmetrica il riferimento colava GIÙ insieme al cielo (70 -> 26 in 4 minuti)
    e la soglia con lui, rendendo il degrado invisibile al proprio stesso metro.
    Stesso difetto del §66, altro componente. Colpiva anche l'hint di recupero
    (§57) nel verso opposto: riferimento eroso = recupero troppo facile."""

    def test_reference_does_not_follow_the_sky_down(self):
        c = _Clock()
        t = _tracker(c, _State("CLEAR"))
        _feed(t, c, 70.0, 1200)
        ref_before = t.status_block()["snr_ref"]
        _feed(t, c, 23.0, 240)                     # 4 minuti di crollo
        ref_after = t.status_block()["snr_ref"]
        self.assertGreater(ref_after, 0.9 * ref_before,
                           f"il metro deve reggere: {ref_before} -> {ref_after} "
                           "(con l'EMA simmetrica scendeva a ~26)")

    def test_improvement_is_adopted(self):
        """Verso l'alto nessun freno: una SNR migliore è informazione vera."""
        c = _Clock()
        t = _tracker(c, _State("CLEAR"))
        _feed(t, c, 40.0, 600)
        before = t.status_block()["snr_ref"]
        _feed(t, c, 90.0, 600)
        self.assertGreater(t.status_block()["snr_ref"], before + 10)

    def test_recovery_hint_threshold_is_no_longer_eroded(self):
        """La conseguenza sull'hint §57: dopo un crollo, la soglia di recupero
        deve restare quella del cielo BUONO, non quella del cielo sotto le nubi."""
        c = _Clock()
        st = _State("CLEAR")
        t = _tracker(c, st, snr_recover_frac=0.8)
        _feed(t, c, 70.0, 1200)
        _feed(t, c, 20.0, 300)                     # crollo prolungato
        st.state = "CLOUD"
        _feed(t, c, 40.0, 120)                     # recupero PARZIALE (40 su ~66)
        b = t.status_block()
        self.assertFalse(b["active"],
                         "40 non è l'80% di ~66: il recupero parziale NON deve "
                         f"attivare l'hint ({b['reason']})")


class TestBoundaries(unittest.TestCase):
    """I confini con gli altri sottosistemi: il §76 non deve invadere."""

    def test_inert_once_n1_has_noticed(self):
        """A N1 già degradato l'accumulatore §55 sta già lavorando: qui si rientra,
        così l'evidenza non resta armata durante il recupero."""
        c = _Clock()
        st = _State("CLEAR")
        t = _tracker(c, st)
        _feed(t, c, 70.0, 900)
        _feed(t, c, 20.0, 200)
        self.assertTrue(t.status_block()["degrading"])

        st.state = "CLOUD"                 # N1 ha visto le nubi
        t.update(20.0)
        b = t.status_block()
        self.assertFalse(b["degrading"], "il testimone passa all'accumulatore §55")

    def test_recovery_hint_still_works_unchanged(self):
        """Il §76 non deve toccare la polarità di recupero (§57)."""
        c = _Clock()
        st = _State("CLEAR")
        t = _tracker(c, st, sustained_seconds=60.0)
        _feed(t, c, 70.0, 900)             # riferimento
        st.state = "CLOUD"                 # nube: il hint si attiva sul recupero
        _feed(t, c, 65.0, 90)
        b = t.status_block()
        self.assertTrue(b["active"], f"hint di recupero invariato: {b['reason']}")
        self.assertFalse(b["degrading"], "le due polarità non si sovrappongono")


if __name__ == "__main__":
    unittest.main()
