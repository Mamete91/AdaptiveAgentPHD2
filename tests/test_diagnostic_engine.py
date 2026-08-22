"""
test_diagnostic_engine.py — Seeing Diagnostic Engine (§31, Agente v2.4).

Milestone 1 (questo file, parte 1): metriche analyzer (jitter + lag-1) e logica
pura del motore (classify / review / micro_proposal). I test di integrazione col
controller (sospensione CASO in jitter, micro guardian solo a v2.3 ferma,
set_diagnostic_mode, last_outcome) sono aggiunti in una sezione successiva.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from phd2_agent.analyzer import (
    AnalysisSnapshot, SeeingCondition, StatisticsAnalyzer, _lag1_autocorr,
)
from phd2_agent.config import (
    AgentConfig, AxisLimits, ControlConfig, DiagnosticEngineConfig,
    SetupConfig, Thresholds,
)
from phd2_agent.controller import AdaptiveController, GuidingState
from phd2_agent.diagnostic_engine import (
    DiagnosisState, GuardianVerdict, LeverProposal, SeeingDiagnosticEngine,
)


# --------------------------------------------------------------------------- #
#  Helper                                                                       #
# --------------------------------------------------------------------------- #

def _snap(rms_total=0.2, hfd_avg=2.0, jitter_rms=0.1, jitter_n=29,
          lag1_ra=0.0, lag1_dec=0.0, trend_ra=0.0, trend_dec=0.0,
          frame_count=30, condition=SeeingCondition.UNKNOWN,
          implosion_detected=False, implosion_suspended=False) -> AnalysisSnapshot:
    s = AnalysisSnapshot()
    s.frame_count = frame_count
    s.rms_total = rms_total
    s.hfd_avg = hfd_avg
    s.jitter_rms = jitter_rms
    s.jitter_n = jitter_n
    s.lag1_ra = lag1_ra
    s.lag1_dec = lag1_dec
    s.trend_ra = trend_ra
    s.trend_dec = trend_dec
    s.condition = condition
    s.implosion_detected = implosion_detected
    s.implosion_suspended = implosion_suspended
    return s


def _engine(median=None, rms_high=0.8, rms_low=0.35, **cfg_over) -> SeeingDiagnosticEngine:
    cfg = DiagnosticEngineConfig(enabled=True, mode="guardian", **cfg_over)
    return SeeingDiagnosticEngine(
        cfg,
        thresholds_provider=lambda: (rms_high, rms_low),
        baseline_provider=lambda: median,
    )


def _build_refs(eng, jitter=0.1, hfd=2.0, rms=0.2) -> None:
    """Forma le reference del motore con frame calmi. §38: la formazione best-fraction
    richiede >= refs_warmup_frames campioni; in legacy (refs_always_form=false) basta
    il primo frame NOMINAL (EMA). Alimentiamo abbastanza frame per coprire entrambi."""
    n = max(2, getattr(eng.cfg, "refs_warmup_frames", 1))
    for _ in range(n):
        eng.classify(_snap(rms_total=rms, hfd_avg=hfd, jitter_rms=jitter,
                           condition=SeeingCondition.NOMINAL))


# --------------------------------------------------------------------------- #
#  1. Analyzer: jitter da sequenza nota                                         #
# --------------------------------------------------------------------------- #

class TestJitterMetric(unittest.TestCase):

    def test_jitter_from_known_sequence(self):
        an = StatisticsAnalyzer(window_size=30)
        # ra alterna 0,1,0,1,0 -> ogni step = 1.0 -> jitter_rms = 1.0
        snap = None
        for v in (0.0, 1.0, 0.0, 1.0, 0.0):
            snap = an.ingest_guide_step({"RADistanceRaw": v, "DECDistanceRaw": 0.0,
                                         "SNR": 30.0, "HFD": 2.0})
        self.assertEqual(snap.jitter_n, 4)
        self.assertAlmostEqual(snap.jitter_rms, 1.0, places=6)


# --------------------------------------------------------------------------- #
#  2. Analyzer: lag-1 alternato << 0, monotono > 0                              #
# --------------------------------------------------------------------------- #

class TestLag1Autocorr(unittest.TestCase):

    def test_alternating_strongly_negative(self):
        vals = [0.0, 1.0] * 8
        self.assertLess(_lag1_autocorr(vals), -0.8)

    def test_monotonic_positive(self):
        vals = [float(i) for i in range(12)]
        self.assertGreater(_lag1_autocorr(vals), 0.0)

    def test_too_short_returns_zero(self):
        self.assertEqual(_lag1_autocorr([1.0, 2.0]), 0.0)


# --------------------------------------------------------------------------- #
#  3. SEEING -> state + proposal (aggr giu' / minmove su)                        #
# --------------------------------------------------------------------------- #

class TestClassifySeeing(unittest.TestCase):

    def test_seeing(self):
        eng = _engine()
        _build_refs(eng, jitter=0.1, hfd=2.0)
        r = eng.classify(_snap(rms_total=1.0, jitter_rms=0.3, hfd_avg=3.0,
                               lag1_ra=0.0, lag1_dec=0.0))
        self.assertEqual(r.state, DiagnosisState.SEEING)
        self.assertEqual(r.proposal, LeverProposal(aggr=-1, minmove=+1))
        self.assertTrue(r.jitter_high and r.hfd_high)
        self.assertGreaterEqual(r.confidence, 60)


# --------------------------------------------------------------------------- #
#  4. OVERCORRECTION -> proposal (aggr giu')                                     #
# --------------------------------------------------------------------------- #

class TestClassifyOvercorrection(unittest.TestCase):

    def test_overcorrection(self):
        # §47: la proposta OVERCORRECTION è il ramo oscillazioni (ora opt-in) -> True.
        eng = _engine(oscillation_branch_enabled=True)
        _build_refs(eng, jitter=0.1, hfd=2.0)
        r = eng.classify(_snap(rms_total=0.6, jitter_rms=0.1, hfd_avg=2.0,
                               lag1_ra=-0.9, lag1_dec=-0.9))
        self.assertEqual(r.state, DiagnosisState.OVERCORRECTION)
        self.assertEqual(r.proposal, LeverProposal(aggr=-1, minmove=0))
        self.assertTrue(r.oscillation and not r.hfd_high)


# --------------------------------------------------------------------------- #
#  5. DRIFT -> proposal None                                                    #
# --------------------------------------------------------------------------- #

class TestClassifyDrift(unittest.TestCase):

    def test_drift(self):
        eng = _engine()
        _build_refs(eng, jitter=0.1, hfd=2.0)
        r = eng.classify(_snap(rms_total=0.6, jitter_rms=0.1, hfd_avg=2.0,
                               lag1_ra=0.5, lag1_dec=0.5, trend_ra=0.1))
        self.assertEqual(r.state, DiagnosisState.DRIFT)
        self.assertIsNone(r.proposal)
        self.assertTrue(r.drift and not r.hfd_high)


# --------------------------------------------------------------------------- #
#  6. NOMINAL aggiorna ref; gate mediana baseline                               #
# --------------------------------------------------------------------------- #

class TestClassifyNominalGate(unittest.TestCase):

    def test_refs_form_after_warmup(self):
        # §38: la reference si forma dopo il warmup (best-fraction), non al 1° frame.
        eng = _engine(median=0.25)
        self.assertFalse(eng.refs_ready)
        eng.classify(_snap(rms_total=0.2, jitter_rms=0.1,
                           condition=SeeingCondition.NOMINAL))
        self.assertFalse(eng.refs_ready)   # 1 campione < refs_warmup_frames
        _build_refs(eng)                    # alimenta il warmup
        self.assertTrue(eng.refs_ready)

    def test_rms_below_median_no_proposal(self):
        eng = _engine(median=0.25)
        r = eng.classify(_snap(rms_total=0.2, condition=SeeingCondition.NOMINAL))
        self.assertEqual(r.state, DiagnosisState.NOMINAL)
        self.assertIsNone(r.proposal)

    def test_rms_above_median_gentle_proposal(self):
        eng = _engine(median=0.25)
        # 0.30 e' sopra mediana 0.25 ma ancora <= rms_low 0.35 (resta in NOMINAL)
        r = eng.classify(_snap(rms_total=0.30, condition=SeeingCondition.NOMINAL))
        self.assertEqual(r.state, DiagnosisState.NOMINAL)
        self.assertIsNotNone(r.proposal)


# --------------------------------------------------------------------------- #
#  7. INSUFFICIENT_DATA -> no azione                                            #
# --------------------------------------------------------------------------- #

class TestInsufficientData(unittest.TestCase):

    def test_few_frames(self):
        eng = _engine()
        r = eng.classify(_snap(frame_count=5))
        self.assertEqual(r.state, DiagnosisState.INSUFFICIENT_DATA)
        self.assertIsNone(r.proposal)
        self.assertEqual(r.confidence, 0)

    def test_implosion(self):
        eng = _engine()
        r = eng.classify(_snap(implosion_detected=True))
        self.assertEqual(r.state, DiagnosisState.INSUFFICIENT_DATA)


# --------------------------------------------------------------------------- #
#  10. Cold-start gate: refs non pronte -> nessuna azione (anche se classifica)  #
# --------------------------------------------------------------------------- #

class TestColdStartGate(unittest.TestCase):

    def test_no_refs_blocks_action(self):
        eng = _engine()   # nessun NOMINAL -> refs non pronte
        eng.classify(_snap(rms_total=0.6, lag1_ra=-0.9, hfd_avg=2.0))
        self.assertFalse(eng.refs_ready)
        # micro e review si comportano da fail-safe
        self.assertIsNone(eng.micro_proposal())
        verdict, _, _ = eng.review("CASO3", is_minmove=False, direction=+1.0)
        self.assertEqual(verdict, GuardianVerdict.CONFIRM)


# --------------------------------------------------------------------------- #
#  11-12. Guardian review: BLOCK su DRIFT (CASO1) e OVERCORRECTION (CASO3 aggr su)#
# --------------------------------------------------------------------------- #

class TestGuardianReviewBlock(unittest.TestCase):

    def test_block_caso1_drift(self):
        eng = _engine()
        _build_refs(eng)
        eng.classify(_snap(rms_total=0.6, lag1_ra=0.5, lag1_dec=0.5, trend_ra=0.1))
        self.assertEqual(eng._last.state, DiagnosisState.DRIFT)
        verdict, _, _ = eng.review("CASO1", is_minmove=False, direction=-1.0)
        self.assertEqual(verdict, GuardianVerdict.BLOCK)

    def test_block_caso3_aggr_up_overcorrection(self):
        eng = _engine()
        _build_refs(eng)
        eng.classify(_snap(rms_total=0.6, lag1_ra=-0.9, lag1_dec=-0.9))
        self.assertEqual(eng._last.state, DiagnosisState.OVERCORRECTION)
        verdict, _, _ = eng.review("CASO3", is_minmove=False, direction=+1.0)
        self.assertEqual(verdict, GuardianVerdict.BLOCK)


# --------------------------------------------------------------------------- #
#  13. Guardian review: ATTENUATE (CASO1 MinMove su in OVERCORRECTION)           #
# --------------------------------------------------------------------------- #

class TestGuardianReviewAttenuate(unittest.TestCase):

    def test_attenuate_minmove(self):
        eng = _engine(guardian_attenuate_factor=0.5)
        _build_refs(eng)
        eng.classify(_snap(rms_total=0.6, lag1_ra=-0.9, lag1_dec=-0.9))
        verdict, factor, _ = eng.review("CASO1", is_minmove=True, direction=+1.0)
        self.assertEqual(verdict, GuardianVerdict.ATTENUATE)
        self.assertAlmostEqual(factor, 0.5)


# --------------------------------------------------------------------------- #
#  §80. Ultimo verdetto Guardian: un EVENTO, non uno stato                       #
# --------------------------------------------------------------------------- #

class TestLastVerdict(unittest.TestCase):
    """Il Guardian non ha uno stato: ha una serie di giudizi su singole azioni.
    Il campo si chiama last_verdict e porta istante e leva proprio per non poter
    essere letto come "condizione corrente" — il vincolo posto in revisione."""

    def test_absent_until_something_is_judged(self):
        """Mai un verdetto per difetto: se nessuna azione e' stata rivista, e' None."""
        eng = _engine()
        self.assertIsNone(eng.get_state()["last_verdict"],
                          "senza azioni riviste non esiste alcun verdetto")

    def test_records_verdict_lever_and_instant(self):
        eng = _engine()
        _build_refs(eng)
        eng.classify(_snap(rms_total=0.6, lag1_ra=0.5, lag1_dec=0.5, trend_ra=0.1))
        eng.review("CASO1", is_minmove=False, direction=-1.0,
                   context="RA/Aggressiveness")
        lv = eng.get_state()["last_verdict"]
        self.assertEqual(lv["verdict"], "BLOCK")
        self.assertEqual(lv["context"], "RA/Aggressiveness",
                         "la leva in esame va detta: senza, il verdetto non e' rileggibile")
        self.assertEqual(lv["factor"], 0.0, "bloccato = ampiezza superstite nulla")
        self.assertTrue(lv["ts_utc"], "un evento senza istante non e' un evento")
        self.assertIn("DRIFT", lv["reason"])

    def test_attenuate_keeps_the_surviving_amplitude(self):
        """La distinzione che motiva tutto il §80: 'non si e' mossa' contro
        'si e' mossa a meta''."""
        eng = _engine(guardian_attenuate_factor=0.45)
        _build_refs(eng)
        eng.classify(_snap(rms_total=0.6, lag1_ra=-0.9, lag1_dec=-0.9))
        eng.review("CASO1", is_minmove=True, direction=+1.0, context="DEC/MinMove")
        lv = eng.get_state()["last_verdict"]
        self.assertEqual(lv["verdict"], "ATTENUATE")
        self.assertAlmostEqual(lv["factor"], 0.45)

    def test_every_branch_carries_the_lever(self):
        """Il contesto e' depositato da review(), non inoltrato ramo per ramo:
        nessun percorso puo' dimenticarlo. Qui il ramo fail-safe, il piu' lontano
        dal punto di deposito."""
        eng = _engine()                      # refs non pronte -> fail-safe CONFIRM
        eng.review("CASO3", is_minmove=False, direction=+1.0, context="RA/MinMove")
        lv = eng.get_state()["last_verdict"]
        self.assertEqual(lv["verdict"], "CONFIRM")
        self.assertEqual(lv["context"], "RA/MinMove")

    def test_context_does_not_leak_to_the_next_verdict(self):
        """Consumato dopo l'uso: un verdetto senza contesto non deve ereditare
        quello del precedente (sarebbe un'attribuzione falsa)."""
        eng = _engine()
        eng.review("CASO3", is_minmove=False, direction=+1.0, context="RA/Aggressiveness")
        eng.review("CASO3", is_minmove=False, direction=+1.0)
        self.assertIsNone(eng.get_state()["last_verdict"]["context"])

    def test_survives_reset_like_the_counters(self):
        """E' una traccia storica: un dither non cancella cio' che e' accaduto."""
        eng = _engine()
        eng.review("CASO3", is_minmove=False, direction=+1.0, context="RA/Aggressiveness")
        eng.reset("dither")
        self.assertIsNotNone(eng.get_state()["last_verdict"],
                             "il reset azzera la diagnosi, non la cronaca")


# --------------------------------------------------------------------------- #
#  14. Guardian review fail-safe: confidence bassa / UNCERTAIN -> CONFIRM         #
# --------------------------------------------------------------------------- #

class TestGuardianReviewFailSafe(unittest.TestCase):

    def test_uncertain_confirms(self):
        eng = _engine()
        _build_refs(eng)
        # nessun fattore dominante -> UNCERTAIN (confidence 40 < 60)
        eng.classify(_snap(rms_total=0.6, lag1_ra=0.0, lag1_dec=0.0,
                           hfd_avg=2.0, jitter_rms=0.1))
        self.assertEqual(eng._last.state, DiagnosisState.UNCERTAIN)
        verdict, _, _ = eng.review("CASO1", is_minmove=False, direction=-1.0)
        self.assertEqual(verdict, GuardianVerdict.CONFIRM)


# --------------------------------------------------------------------------- #
#  micro_proposal: SEEING/OVERCORRECTION confidenti -> proposta; DRIFT -> None    #
# --------------------------------------------------------------------------- #

class TestMicroProposal(unittest.TestCase):

    def test_seeing_micro(self):
        eng = _engine()
        _build_refs(eng)
        eng.classify(_snap(rms_total=1.0, jitter_rms=0.3, hfd_avg=3.0))
        self.assertEqual(eng.micro_proposal(), LeverProposal(aggr=-1, minmove=+1))

    def test_overcorrection_micro(self):
        eng = _engine(oscillation_branch_enabled=True)   # §47: ramo oscillazioni opt-in
        _build_refs(eng)
        eng.classify(_snap(rms_total=0.6, lag1_ra=-0.9, lag1_dec=-0.9))
        self.assertEqual(eng.micro_proposal(), LeverProposal(aggr=-1, minmove=0))

    def test_drift_no_micro(self):
        eng = _engine()
        _build_refs(eng)
        eng.classify(_snap(rms_total=0.6, lag1_ra=0.5, lag1_dec=0.5, trend_ra=0.1))
        self.assertIsNone(eng.micro_proposal())


# --------------------------------------------------------------------------- #
#  reset() azzera le reference EMA                                              #
# --------------------------------------------------------------------------- #

class TestReset(unittest.TestCase):

    def test_reset_clears_refs(self):
        eng = _engine()
        _build_refs(eng)
        self.assertTrue(eng.refs_ready)
        eng.reset()
        self.assertFalse(eng.refs_ready)
        self.assertIsNone(eng._last)


# =========================================================================== #
#  INTEGRAZIONE COL CONTROLLER (§31)                                           #
# =========================================================================== #

def _make_controller(mode="guardian", allow=True, enabled=True, **de_over) -> AdaptiveController:
    """Controller pronto all'azione (initialized, leve a meta' corsa, cooldown=0)
    con motore §31 nella modalita' richiesta. cooldown_seconds=0 -> le azioni non
    sono frenate dal cooldown nei test."""
    cfg = AgentConfig()
    cfg.control = ControlConfig(dry_run=True, cooldown_seconds=0.0)
    cfg.thresholds = Thresholds(rms_high=0.80, rms_low=0.35, consecutive_frames=5)
    cfg.ra = AxisLimits(aggr_min=35, aggr_max=90, aggr_step_down=5, aggr_step_up=2,
                        minmove_min=0.15, minmove_max=0.85, minmove_step=0.05)
    cfg.dec = AxisLimits(aggr_min=35, aggr_max=90, aggr_step_down=5, aggr_step_up=2,
                         minmove_min=0.15, minmove_max=0.85, minmove_step=0.05)
    cfg.setup = SetupConfig(profile_name="test", guide_pixel_scale_arcsec_native=0.5)
    cfg.diagnostic_engine = DiagnosticEngineConfig(
        enabled=enabled, mode=mode, allow_dashboard_mode_switch=allow,
        min_frames=10, warmup_frames_after_switch=0, **de_over)
    ctrl = AdaptiveController(client=MagicMock(), config=cfg)
    ctrl._initialized = True
    ctrl.guiding_state = GuidingState.NORMAL
    if enabled:
        ctrl.diagnostic_engine = ctrl._make_diagnostic_engine()
    for ax in (ctrl._ra, ctrl._dec):
        ax.aggr_param = "Aggressiveness"
        ax.minmove_param = "MinMove"
        ax.current_aggr = 70.0
        ax.current_minmove = 0.40
        ax.last_action_time = 0.0
        ax.last_minmove_action_time = 0.0
    return ctrl


def _warm_refs(ctrl, n=2, jitter=0.1, hfd=2.0) -> None:
    """Forma le reference EMA del motore via classify diretto (senza far agire il
    controller), cosi' le leve restano a 70/0.40 prima del test vero e proprio."""
    n = max(n, getattr(ctrl.diagnostic_engine.cfg, "refs_warmup_frames", 1))
    for _ in range(n):
        ctrl.diagnostic_engine.classify(
            _snap(rms_total=0.2, jitter_rms=jitter, hfd_avg=hfd,
                  condition=SeeingCondition.NOMINAL))


def _csnap(rms, *, jit=0.1, hfd=2.0, lag=0.0, trend=0.0,
           cond=SeeingCondition.UNKNOWN, consec_high=0, consec_low=0) -> AnalysisSnapshot:
    """Snapshot per il controller. NB: i CASO 1/2/3 della v2.3 si valutano per-asse
    su rms_ra/rms_dec, quindi li allineo a `rms` (il valore nominale del test) cosi'
    le soglie rms_high/rms_low scattano come atteso. Il motore legge rms_total."""
    s = _snap(rms_total=rms, jitter_rms=jit, hfd_avg=hfd, lag1_ra=lag, lag1_dec=lag,
              trend_ra=trend, condition=cond)
    s.rms_ra = rms
    s.rms_dec = rms
    s.consecutive_high = consec_high
    s.consecutive_low = consec_low
    return s


# 8. enabled=false (default) -> motore non istanziato, v2.3 invariata
class TestEngineOffPassthrough(unittest.TestCase):

    def test_engine_not_instantiated(self):
        ctrl = _make_controller(enabled=False, allow=False)
        self.assertIsNone(ctrl.diagnostic_engine)
        block = ctrl.get_status()["diagnostic_engine"]
        self.assertEqual(block, {"enabled": False, "mode": "guardian",
                                 "allow_dashboard_mode_switch": False})

    def test_v23_caso1_still_acts(self):
        ctrl = _make_controller(enabled=False, allow=False)
        snap = _csnap(1.0, cond=SeeingCondition.DEGRADED_SEEING, consec_high=6)
        ctrl.evaluate(snap)
        # CASO1 v2.3 ha abbassato l'aggressivita' (passthrough identico)
        self.assertEqual(ctrl._ra.current_aggr, 65.0)


# 9. jitter agisce su SEEING + CASO 1/2/3 sospesi
class TestJitterActsAndSuspends(unittest.TestCase):

    def test_seeing_action_both_axes(self):
        ctrl = _make_controller(mode="jitter")
        _warm_refs(ctrl)
        ctrl.evaluate(_csnap(1.0, jit=0.3, hfd=3.0))
        self.assertEqual(ctrl._current_diag.state, DiagnosisState.SEEING)
        # aggr giu' / minmove su su entrambi gli assi
        self.assertEqual(ctrl._ra.current_aggr, 65.0)
        self.assertEqual(ctrl._dec.current_aggr, 65.0)
        self.assertAlmostEqual(ctrl._ra.current_minmove, 0.45, places=4)

    def test_caso_suspended_in_jitter(self):
        ctrl = _make_controller(mode="jitter")
        out = ctrl._evaluate_axis(ctrl._ra, ctrl.cfg.ra, 1.0, 6, 0,
                                  SeeingCondition.DEGRADED_SEEING, _csnap(1.0, consec_high=6))
        self.assertEqual(out, [])


# 11. bounds: nessuna mossa fuori dai [limits] (jitter)
class TestBounds(unittest.TestCase):

    def test_clamped_to_limits(self):
        ctrl = _make_controller(mode="jitter")
        _warm_refs(ctrl)
        ctrl._ra.current_aggr = 36.0     # vicino a aggr_min 35
        ctrl._ra.current_minmove = 0.83  # vicino a minmove_max 0.85
        ctrl.evaluate(_csnap(1.0, jit=0.3, hfd=3.0))   # SEEING: aggr giu', minmove su
        self.assertGreaterEqual(ctrl._ra.current_aggr, 35.0)
        self.assertLessEqual(ctrl._ra.current_minmove, 0.85)


# 12. cold-start gate: refs non pronte -> nessuna azione
class TestColdStartController(unittest.TestCase):

    def test_no_action_without_refs(self):
        ctrl = _make_controller(mode="jitter")   # nessun warm_refs
        ctrl.evaluate(_csnap(1.0, jit=0.3, hfd=3.0))
        self.assertFalse(ctrl.diagnostic_engine.refs_ready)
        self.assertEqual(ctrl._ra.current_aggr, 70.0)


# 13/15. guardian review BLOCK (CASO1/DRIFT e CASO3 aggr su/OVERCORRECTION)
class TestGuardianReviewBlockController(unittest.TestCase):

    def test_block_caso1_in_drift(self):
        ctrl = _make_controller(mode="guardian")
        _warm_refs(ctrl)
        snap = _csnap(1.0, jit=0.1, hfd=2.0, lag=0.0, trend=0.1,
                      cond=SeeingCondition.DEGRADED_SEEING, consec_high=6)
        acts = ctrl.evaluate(snap)
        self.assertEqual(ctrl._current_diag.state, DiagnosisState.DRIFT)
        self.assertEqual(ctrl._ra.current_aggr, 70.0)          # NON abbassata
        self.assertTrue(any(a.axis == "guardian" and "block" in a.param for a in acts))

    def test_block_caso3_aggr_up_in_overcorrection(self):
        ctrl = _make_controller(mode="guardian")
        _warm_refs(ctrl)
        snap = _csnap(0.2, jit=0.1, hfd=2.0, lag=-0.9,
                      cond=SeeingCondition.UNKNOWN, consec_low=6)
        acts = ctrl.evaluate(snap)
        self.assertEqual(ctrl._current_diag.state, DiagnosisState.OVERCORRECTION)
        self.assertEqual(ctrl._ra.current_aggr, 70.0)          # aggr su BLOCCATO
        self.assertTrue(any(a.axis == "guardian" and "block" in a.param for a in acts))


# 16. guardian review ATTENUATE (CASO1 MinMove su in OVERCORRECTION)
class TestGuardianReviewAttenuateController(unittest.TestCase):

    def test_attenuate_minmove(self):
        ctrl = _make_controller(mode="guardian", guardian_attenuate_factor=0.5)
        _warm_refs(ctrl)
        snap = _csnap(1.0, jit=0.1, hfd=2.0, lag=-0.9,
                      cond=SeeingCondition.DEGRADED_SEEING, consec_high=6)
        ctrl.evaluate(snap)
        self.assertEqual(ctrl._current_diag.state, DiagnosisState.OVERCORRECTION)
        # MinMove su attenuato: 0.40 + 0.5*(0.45-0.40) = 0.425
        self.assertAlmostEqual(ctrl._ra.current_minmove, 0.425, places=4)
        # aggr giu' CONFERMATO (la regola ATTENUATE riguarda solo il MinMove su)
        self.assertEqual(ctrl._ra.current_aggr, 65.0)


# 17. guardian fail-safe: UNCERTAIN -> CONFIRM (v2.3 applicato invariato)
class TestGuardianFailSafeController(unittest.TestCase):

    def test_uncertain_confirms_v23(self):
        ctrl = _make_controller(mode="guardian")
        _warm_refs(ctrl)
        snap = _csnap(1.0, jit=0.1, hfd=2.0, lag=0.0, trend=0.0,
                      cond=SeeingCondition.DEGRADED_SEEING, consec_high=6)
        ctrl.evaluate(snap)
        self.assertEqual(ctrl._current_diag.state, DiagnosisState.UNCERTAIN)
        self.assertEqual(ctrl._ra.current_aggr, 65.0)          # CASO1 confermato


# 18. guardian micro SOLO se la v2.3 e' ferma sull'asse
class TestGuardianMicroController(unittest.TestCase):

    def test_micro_when_v23_idle(self):
        # §47: micro su OVERCORRECTION = ramo oscillazioni (ora opt-in) -> True.
        ctrl = _make_controller(mode="guardian", guardian_action_factor=0.4,
                                oscillation_branch_enabled=True)
        _warm_refs(ctrl)
        # rms neutro -> nessun CASO scatta -> v2.3 ferma; OVERCORRECTION confidente
        ctrl.evaluate(_csnap(0.6, jit=0.1, hfd=2.0, lag=-0.9))
        self.assertEqual(ctrl._current_diag.state, DiagnosisState.OVERCORRECTION)
        # micro su RA (primo asse): aggr 70 -> 68 (0.4 * step_down 5 = 2)
        self.assertEqual(ctrl._ra.current_aggr, 68.0)
        # DEC: finestra outcome gia' aperta da RA -> nessuna seconda micro nel tick
        self.assertEqual(ctrl._dec.current_aggr, 70.0)
        self.assertEqual(ctrl.diagnostic_engine._guardian_counts["micro"], 1)

    def test_no_micro_when_v23_acts(self):
        ctrl = _make_controller(mode="guardian")
        _warm_refs(ctrl)
        # OVERCORRECTION ma rms<low -> CASO3 scatta (v2.3 agisce) -> niente micro
        ctrl.evaluate(_csnap(0.2, jit=0.1, hfd=2.0, lag=-0.9, consec_low=6))
        self.assertEqual(ctrl._current_diag.state, DiagnosisState.OVERCORRECTION)
        self.assertEqual(ctrl.diagnostic_engine._guardian_counts["micro"], 0)


# 19. guardian DRIFT -> nessuna micro
class TestGuardianDriftNoMicro(unittest.TestCase):

    def test_drift_no_micro(self):
        ctrl = _make_controller(mode="guardian")
        _warm_refs(ctrl)
        ctrl.evaluate(_csnap(0.6, jit=0.1, hfd=2.0, lag=0.0, trend=0.1))
        self.assertEqual(ctrl._current_diag.state, DiagnosisState.DRIFT)
        self.assertEqual(ctrl.diagnostic_engine._guardian_counts["micro"], 0)
        self.assertEqual(ctrl._ra.current_aggr, 70.0)          # nessuna mossa


# set_diagnostic_mode: OFF sempre permesso; attivazione gated
class TestSetDiagnosticMode(unittest.TestCase):

    def test_off_always_accepted(self):
        ctrl = _make_controller(mode="guardian", allow=False)
        self.assertEqual(ctrl.set_diagnostic_mode("off")["mode"], "off")
        self.assertFalse(ctrl.cfg.diagnostic_engine.enabled)

    def test_activation_gated(self):
        ctrl = _make_controller(mode="guardian", allow=False)
        # §54: jitter è gated anche da allow_experimental_jitter; qui lo sblocchiamo per
        # esercitare il gate allow_dashboard_mode_switch usando jitter come modalità di prova.
        ctrl.cfg.diagnostic_engine.allow_experimental_jitter = True
        ctrl.set_diagnostic_mode("off")
        # rifiutata con allow=false
        self.assertEqual(ctrl.set_diagnostic_mode("jitter").get("error"), "not_allowed")
        self.assertFalse(ctrl.cfg.diagnostic_engine.enabled)
        # accettata con allow=true
        ctrl.cfg.diagnostic_engine.allow_dashboard_mode_switch = True
        self.assertEqual(ctrl.set_diagnostic_mode("jitter")["mode"], "jitter")
        self.assertTrue(ctrl.cfg.diagnostic_engine.enabled)
        self.assertEqual(ctrl.cfg.diagnostic_engine.mode, "jitter")


# last_outcome (pre->post) + engine.reset
class TestOutcomeAndReset(unittest.TestCase):

    def test_outcome_completes_and_reset(self):
        ctrl = _make_controller(mode="jitter", outcome_window_frames=2)
        _warm_refs(ctrl)
        ctrl.evaluate(_csnap(1.0, jit=0.3, hfd=3.0))   # SEEING -> azione + finestra
        ctrl.evaluate(_csnap(0.5))                      # post 1
        ctrl.evaluate(_csnap(0.5))                      # post 2 -> finalize
        self.assertIsNotNone(ctrl._last_outcome)
        self.assertIn("delta", ctrl._last_outcome)
        ctrl.diagnostic_engine.reset()
        self.assertFalse(ctrl.diagnostic_engine.refs_ready)


# =========================================================================== #
#  §37 — HFD declassato a informativo: fuori dal gate SEEING                    #
# =========================================================================== #

class TestHfdDeclassedSeeing(unittest.TestCase):
    """SEEING ora si decide sulla firma dinamica (jitter+RMS) senza vincolo HFD."""

    def test_seeing_fires_with_flat_hfd_default(self):
        # Caso campo: jitter alto + RMS alto, HFD PIATTO (= reference, non alto).
        # Col gate §31 sarebbe UNCERTAIN; con §37 (default) -> SEEING.
        eng = _engine()  # hfd_gates_seeing default False
        _build_refs(eng, jitter=0.1, hfd=2.0)
        r = eng.classify(_snap(rms_total=1.0, jitter_rms=0.3, hfd_avg=2.0,
                               lag1_ra=0.0, lag1_dec=0.0))
        self.assertEqual(r.state, DiagnosisState.SEEING)
        self.assertFalse(r.hfd_high)          # HFD non alto: prima bloccava SEEING
        self.assertTrue(r.jitter_high)
        self.assertEqual(r.proposal, LeverProposal(aggr=-1, minmove=+1))
        self.assertGreaterEqual(r.confidence, 60)

    def test_hfd_still_logged_when_informational(self):
        # hfd_avg/hfd_ref restano nelle metriche (informativi, per CSV + dashboard).
        eng = _engine()
        _build_refs(eng, jitter=0.1, hfd=2.0)
        r = eng.classify(_snap(rms_total=1.0, jitter_rms=0.3, hfd_avg=2.0))
        self.assertIn("hfd", r.metrics)
        self.assertIn("hfd_ref", r.metrics)
        self.assertGreater(r.metrics["hfd_ref"], 0.0)

    def test_seeing_specific_needs_rms_high(self):
        # Jitter alto da solo (RMS sotto rms_high) NON e' SEEING.
        eng = _engine()
        _build_refs(eng, jitter=0.1, hfd=2.0)
        r = eng.classify(_snap(rms_total=0.5, jitter_rms=0.3, hfd_avg=2.0,
                               lag1_ra=0.0, lag1_dec=0.0))
        self.assertNotEqual(r.state, DiagnosisState.SEEING)

    def test_oscillation_is_overcorrection_not_seeing(self):
        # RMS alto + jitter alto MA oscillazione -> OVERCORRECTION (SEEING resta specifico).
        eng = _engine()
        _build_refs(eng, jitter=0.1, hfd=2.0)
        r = eng.classify(_snap(rms_total=1.0, jitter_rms=0.3, hfd_avg=2.0,
                               lag1_ra=-0.9, lag1_dec=-0.9))
        self.assertEqual(r.state, DiagnosisState.OVERCORRECTION)

    def test_legacy_gate_blocks_seeing_with_flat_hfd(self):
        # Regressione: con hfd_gates_seeing=true il gate §31 torna a bloccare SEEING
        # quando l'HFD e' piatto (comportamento identico al pre-fix).
        eng = _engine(hfd_gates_seeing=True)
        _build_refs(eng, jitter=0.1, hfd=2.0)
        r = eng.classify(_snap(rms_total=1.0, jitter_rms=0.3, hfd_avg=2.0,
                               lag1_ra=0.0, lag1_dec=0.0))
        self.assertNotEqual(r.state, DiagnosisState.SEEING)

    def test_legacy_gate_seeing_with_high_hfd(self):
        # Regressione: con gate legacy + HFD alto -> SEEING (come §31).
        eng = _engine(hfd_gates_seeing=True)
        _build_refs(eng, jitter=0.1, hfd=2.0)
        r = eng.classify(_snap(rms_total=1.0, jitter_rms=0.3, hfd_avg=3.0,
                               lag1_ra=0.0, lag1_dec=0.0))
        self.assertEqual(r.state, DiagnosisState.SEEING)


class TestGuardianSeeingReviewOnly(unittest.TestCase):
    """In guardian il nuovo SEEING non deve pilotare: resta review (+ micro solo a
    v2.3 ferma). Nessuna azione spuria in piu' rispetto al baseline."""

    def test_new_seeing_guardian_no_extra_micro_when_v23_acts(self):
        ctrl = _make_controller(mode="guardian")
        _warm_refs(ctrl, jitter=0.1, hfd=2.0)
        # nuovo SEEING (HFD piatto) con v2.3 CASO1 attivo (consec_high)
        snap = _csnap(1.0, jit=0.3, hfd=2.0, lag=0.0,
                      cond=SeeingCondition.DEGRADED_SEEING, consec_high=6)
        ctrl.evaluate(snap)
        self.assertEqual(ctrl._current_diag.state, DiagnosisState.SEEING)
        self.assertFalse(ctrl._current_diag.hfd_high)
        # v2.3 (CASO1) ha agito: aggr 70 -> 65; review CONFIRM, nessuna micro extra.
        self.assertEqual(ctrl._ra.current_aggr, 65.0)
        self.assertEqual(ctrl.diagnostic_engine._guardian_counts["micro"], 0)


# =========================================================================== #
#  §38 — jitter_ref/hfd_ref si formano SEMPRE (best-fraction su finestra mobile) #
# =========================================================================== #

class TestRefsAlwaysForm(unittest.TestCase):

    def test_legacy_ref_stays_none_on_turbulent_stretch(self):
        # Riproduzione scoperta: con la formazione §31 (EMA solo in NOMINAL+rms<=low),
        # uno stretch turbolento (rms mai sotto rms_low) lascia jitter_ref None.
        eng = _engine(refs_always_form=False)
        for _ in range(120):
            eng.classify(_snap(rms_total=1.0, jitter_rms=0.9, hfd_avg=2.0,
                               lag1_ra=0.0, condition=SeeingCondition.DEGRADED_SEEING))
        self.assertIsNone(eng._jitter_ref)
        self.assertFalse(eng.refs_ready)

    def test_new_ref_forms_on_turbulent_stretch(self):
        # §38: stesso stretch turbolento -> la reference si forma comunque (best-fraction).
        eng = _engine()  # refs_always_form default True
        for _ in range(40):
            eng.classify(_snap(rms_total=1.0, jitter_rms=0.9, hfd_avg=2.0,
                               lag1_ra=0.0, condition=SeeingCondition.DEGRADED_SEEING))
        self.assertIsNotNone(eng._jitter_ref)
        self.assertTrue(eng.refs_ready)

    def test_refs_ready_within_warmup(self):
        # refs_ready diventa vero esattamente al raggiungimento del warmup, non a meta'
        # sessione.
        eng = _engine(refs_warmup_frames=10)
        for _ in range(9):
            eng.classify(_snap(rms_total=1.0, jitter_rms=0.9,
                               condition=SeeingCondition.DEGRADED_SEEING))
            self.assertFalse(eng.refs_ready)
        eng.classify(_snap(rms_total=1.0, jitter_rms=0.9,
                           condition=SeeingCondition.DEGRADED_SEEING))
        self.assertTrue(eng.refs_ready)

    def test_refs_ready_independent_of_hfd(self):
        # §38 + §37: con HFD assente (hfd_ref resta None) ma jitter_ref formata,
        # refs_ready e' comunque vero (la prontezza non dipende piu' da hfd_ref).
        eng = _engine(refs_warmup_frames=5)
        for _ in range(5):
            eng.classify(_snap(rms_total=1.0, jitter_rms=0.9, hfd_avg=0.0,
                               condition=SeeingCondition.DEGRADED_SEEING))
        self.assertIsNotNone(eng._jitter_ref)
        self.assertIsNone(eng._hfd_ref)
        self.assertTrue(eng.refs_ready)

    def test_payoff_seeing_now_fires(self):
        # Payoff §37+§38: reference formata su guida mossa -> un frame turbolento
        # (rms alto + jitter alto, non oscillante) ora diagnostica SEEING.
        eng = _engine()
        for _ in range(30):
            eng.classify(_snap(rms_total=0.6, jitter_rms=0.5, hfd_avg=2.0,
                               lag1_ra=0.0, condition=SeeingCondition.DEGRADED_SEEING))
        self.assertTrue(eng.refs_ready)
        r = eng.classify(_snap(rms_total=1.0, jitter_rms=1.2, hfd_avg=2.0,
                               lag1_ra=0.0, lag1_dec=0.0))
        self.assertEqual(r.state, DiagnosisState.SEEING)
        self.assertFalse(r.hfd_high)   # HFD piatto: irrilevante per la diagnosi

    def test_legacy_mode_forms_ref_on_first_nominal(self):
        # Isolamento/regressione: refs_always_form=false -> comportamento §31
        # (1 frame NOMINAL+rms<=low forma le reference via EMA; refs_ready su entrambe).
        eng = _engine(refs_always_form=False)
        eng.classify(_snap(rms_total=0.2, jitter_rms=0.1, hfd_avg=2.0,
                           condition=SeeingCondition.NOMINAL))
        self.assertIsNotNone(eng._jitter_ref)
        self.assertIsNotNone(eng._hfd_ref)
        self.assertTrue(eng.refs_ready)

    def test_nominal_semantics_unchanged_in_new_mode(self):
        # §38 non tocca NOMINAL/satisfaction-gate: con baseline e rms<=mediana ->
        # nessuna proposta (soddisfatti); sopra mediana -> proposta gentile.
        eng = _engine(median=0.25)
        r_sat = eng.classify(_snap(rms_total=0.20, condition=SeeingCondition.NOMINAL))
        self.assertEqual(r_sat.state, DiagnosisState.NOMINAL)
        self.assertIsNone(r_sat.proposal)
        r_push = eng.classify(_snap(rms_total=0.30, condition=SeeingCondition.NOMINAL))
        self.assertEqual(r_push.state, DiagnosisState.NOMINAL)
        self.assertIsNotNone(r_push.proposal)


# =========================================================================== #
#  §39 — i riferimenti di calma SOPRAVVIVONO al dither + logging reset_cause     #
# =========================================================================== #

class TestResetDiscipline(unittest.TestCase):

    def _ready_engine(self, **over):
        eng = _engine(refs_warmup_frames=5, **over)
        for _ in range(5):
            eng.classify(_snap(rms_total=1.0, jitter_rms=0.9,
                               condition=SeeingCondition.DEGRADED_SEEING))
        self.assertTrue(eng.refs_ready)
        return eng

    def test_reset_preserves_on_dither_settle_mode(self):
        for cause in ("dither", "settle", "mode_transition"):
            eng = self._ready_engine()
            jref = eng._jitter_ref
            eng.reset(cause)
            self.assertTrue(eng.refs_ready, f"{cause} deve PRESERVARE")
            self.assertEqual(eng._jitter_ref, jref)
            self.assertGreater(len(eng._jitter_window), 0)

    def test_reset_wipes_on_regime_change(self):
        for cause in ("exposure_change", "pixel_scale_change", "target_change",
                      "guiding_restart", "manual"):
            eng = self._ready_engine()
            eng.reset(cause)
            self.assertFalse(eng.refs_ready, f"{cause} deve AZZERARE")
            self.assertIsNone(eng._jitter_ref)
            self.assertEqual(len(eng._jitter_window), 0)

    def test_refs_survive_repeated_dither(self):
        eng = self._ready_engine()
        jref = eng._jitter_ref
        for _ in range(5):
            eng.reset("dither")
            self.assertTrue(eng.refs_ready)   # niente piu' churn
        self.assertEqual(eng._jitter_ref, jref)

    def test_legacy_mode_wipes_on_dither(self):
        # Regressione: preserve_refs_on_dither=false -> dither azzera (comportamento §31).
        eng = self._ready_engine(preserve_refs_on_dither=False)
        eng.reset("dither")
        self.assertFalse(eng.refs_ready)
        self.assertIsNone(eng._jitter_ref)

    def test_no_poisoning_after_dither(self):
        # Il transiente post-dither (jitter anomalo) NON degrada jitter_ref: il
        # best-fraction resta ancorato ai frame calmi gia' in finestra.
        eng = _engine(refs_warmup_frames=10)
        for _ in range(30):
            eng.classify(_snap(rms_total=0.6, jitter_rms=0.5,
                               condition=SeeingCondition.DEGRADED_SEEING))
        jref_before = eng._jitter_ref
        eng.reset("dither")   # preserva refs + finestra
        for _ in range(3):
            eng.classify(_snap(rms_total=1.5, jitter_rms=3.0,
                               condition=SeeingCondition.DEGRADED_SEEING))
        self.assertLessEqual(eng._jitter_ref, jref_before * 1.2)

    def test_consume_reset_cause_read_and_clear(self):
        eng = _engine()
        self.assertEqual(eng.consume_reset_cause(), "")   # nessun reset
        eng.reset("dither")
        self.assertEqual(eng.consume_reset_cause(), "dither")
        self.assertEqual(eng.consume_reset_cause(), "")   # gia' consumata

    def test_reset_cause_logged_in_csv(self):
        # Integrazione col logger: la colonna reset_cause compare sul primo frame
        # dopo il reset e schema_version e' 4.
        import tempfile
        import csv as _csv
        from types import SimpleNamespace
        from phd2_agent.logger import SessionLogger, _CSV_FIELDS
        self.assertIn("reset_cause", _CSV_FIELDS)
        eng = _engine(refs_warmup_frames=2)
        for _ in range(2):
            eng.classify(_snap(rms_total=0.6, jitter_rms=0.5,
                               condition=SeeingCondition.DEGRADED_SEEING))
        eng.reset("dither")
        with tempfile.TemporaryDirectory() as d:
            lg = SessionLogger(csv_dir=d)
            lg.bind_controller(SimpleNamespace(
                diagnostic_engine=eng,
                cfg=SimpleNamespace(thresholds=SimpleNamespace(rms_high=0.8, rms_low=0.35))))
            snap = _snap(rms_total=0.6, jitter_rms=0.5)
            lg.log_snapshot(snap, [])   # primo frame post-reset
            lg.log_snapshot(snap, [])   # secondo frame
            summary = lg.close()
            self.assertEqual(summary["schema_version"], 9)   # §102: stato del fuoco
            rows = list(_csv.DictReader(open(lg._csv_path, encoding="utf-8")))
        self.assertEqual(rows[0]["reset_cause"], "dither")
        self.assertEqual(rows[1]["reset_cause"], "")


if __name__ == "__main__":
    unittest.main()
