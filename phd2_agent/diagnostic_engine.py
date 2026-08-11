"""
diagnostic_engine.py — Seeing Diagnostic Engine (§31, Agente v2.4)

Motore diagnostico causale del regime di guida. Aggiunge due metriche dai dati
GuideStep gia' ingeriti dall'analyzer — jitter frame-to-frame e autocorrelazione
a lag-1 — e le combina con RMS, HFD e trend per distinguere la CAUSA del degrado:

    SEEING          turbolenza atmosferica (firma dinamica: RMS alto + jitter alto)
    OVERCORRECTION  il loop oscilla (lag-1 fortemente negativo)
    DRIFT           deriva sistematica (trend elevato, jitter nella norma)
    NOMINAL         regime stabile

§37 — l'HFD resta calcolato/loggato (CSV + card dashboard) ma e' DECLASSATO a
informativo: sulla camera di guida e' cieco al seeing (hfd_avg/hfd_ref ~ 1.0 a
ogni cielo), quindi non gatea piu' alcuna diagnosi. SEEING ora si decide sulla
sola firma dinamica jitter+RMS (specifica grazie al `not oscillation`). Il
kill-switch [diagnostic_engine] hfd_gates_seeing=true ripristina il gate §31.

Si decide SEMPRE sulla diagnosi combinata, mai sul jitter isolato (il jitter e' un
residuo di loop chiuso, ambiguo da solo). Le soglie "alto/basso" sono relative a
reference (jitter_ref/hfd_ref) azzerate a ogni cambio esposizione via reset().

§38 — le reference si formano col BEST-FRACTION su una finestra mobile (i frame piu'
calmi), come la baseline RMS §33: cosi' jitter_ref si forma sempre e presto, anche
nelle notti in cui rms quasi mai scende sotto rms_low (col vecchio ramo stretto
NOMINAL+rms<=rms_low la reference restava None nell'~88% dei frame -> motore "armato
e muto"). Post-§37 l'HFD e' informativo: refs_ready dipende SOLO da jitter_ref.
Kill-switch refs_always_form=false ripristina la formazione EMA-in-NOMINAL §31.

Il modulo NON accede a self.client e non invia mai comandi: esprime solo la
DIREZIONE della mossa (LeverProposal). L'ampiezza e l'invio li decide il controller
(via controller._apply, entro [limits] e cooldown). Mai esposizione/backlash.

Due usi (decisi dal controller in base a cfg.mode):
  * jitter   — il motore e' unica autorita' su Aggr/MinMove (CASO 1/2/3 sospesi).
  * guardian — la v2.3 pilota; il motore rivede le sue mosse (review: CONFIRM /
               ATTENUATE / BLOCK) e fa micro-correzioni proprie nei buchi.
"""
from __future__ import annotations

import math
from collections import deque
from datetime import datetime, timezone
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Optional

from .analyzer import AnalysisSnapshot, SeeingCondition


class DiagnosisState(Enum):
    INSUFFICIENT_DATA = auto()
    NOMINAL = auto()
    SEEING = auto()
    OVERCORRECTION = auto()
    DRIFT = auto()
    UNCERTAIN = auto()


class GuardianVerdict(Enum):
    CONFIRM = auto()    # la v2.3 puo' agire invariata
    ATTENUATE = auto()  # la v2.3 agisce ad ampiezza ridotta
    BLOCK = auto()      # la v2.3 non agisce


# Mappa stato -> etichetta in linguaggio astrofotografico. Generata nel motore
# cosi' dashboard e log restano coerenti (single source of truth).
_STATE_LABEL: dict[DiagnosisState, str] = {
    DiagnosisState.NOMINAL: "GUIDA STABILE",
    DiagnosisState.SEEING: "SEEING DEGRADATO",
    DiagnosisState.OVERCORRECTION: "SOVRA-CORREZIONE",
    DiagnosisState.DRIFT: "DERIVA SISTEMATICA",
    DiagnosisState.UNCERTAIN: "QUADRO INCERTO",
    DiagnosisState.INSUFFICIENT_DATA: "DATI INSUFFICIENTI",
}

# Sottotitolo esplicativo breve (in linguaggio naturale).
_STATE_SUGGESTION: dict[DiagnosisState, str] = {
    DiagnosisState.NOMINAL: "Regime stabile: nessun intervento necessario.",
    DiagnosisState.SEEING: "Turbolenza atmosferica: ammorbidisco le leve (aggr giu', MinMove su).",
    DiagnosisState.OVERCORRECTION: "Il loop oscilla: riduco l'aggressivita'.",
    DiagnosisState.DRIFT: "Deriva sistematica (meccanica/allineamento): nessuna leva soft, "
                          "valutare intervento manuale.",
    DiagnosisState.UNCERTAIN: "Quadro non univoco: attendo conferme prima di agire.",
    DiagnosisState.INSUFFICIENT_DATA: "Finestra dati o reference non ancora pronte.",
}


@dataclass
class LeverProposal:
    """Direzione (non ampiezza) della mossa proposta per asse.
    -1 = abbassa, 0 = invariato, +1 = alza. L'ampiezza la decide il controller."""
    aggr: int = 0
    minmove: int = 0

    def is_noop(self) -> bool:
        return self.aggr == 0 and self.minmove == 0


@dataclass
class DiagnosisResult:
    """Esito di classify(): stato, confidence, proposta e fattori che l'hanno
    determinata. I quattro booleani grezzi servono sia a _build_evidence sia al
    logging azione->esito (evidence_bools)."""
    state: DiagnosisState
    confidence: int
    confidence_calibrated: bool
    proposal: Optional[LeverProposal]
    label: str
    suggestion: str
    evidence: list[str]
    # Booleani grezzi della diagnosi (per evidence + log/replay v2.5)
    jitter_high: bool
    hfd_high: bool
    oscillation: bool
    drift: bool
    metrics: dict = field(default_factory=dict)


# §39 — cause di reset che NON cambiano il regime del jitter (dither sposta la
# stella, non l'atmosfera; la transizione di modalita' non tocca esposizione/cielo):
# i riferimenti di calma e le finestre §38 vanno PRESERVATI. Tutte le altre cause
# (exposure_change/pixel_scale_change/target_change/guiding_restart/manual) AZZERANO.
_PRESERVE_CAUSES: frozenset[str] = frozenset({"dither", "settle", "mode_transition"})


def _ema(prev: Optional[float], new: float, alpha: float) -> float:
    """Aggiornamento EMA. Al primo campione adotta il valore corrente."""
    if prev is None:
        return new
    return (1.0 - alpha) * prev + alpha * new


class SeeingDiagnosticEngine:
    """Motore diagnostico stateless rispetto alle leve: mantiene solo le reference
    EMA e l'ultimo esito. Nessun accesso al client PHD2."""

    def __init__(
        self,
        cfg,
        thresholds_provider: Callable[[], tuple[float, float]],
        baseline_provider: Callable[[], Optional[float]],
        transparency_provider: Optional[Callable[[], Optional[dict]]] = None,
    ):
        self.cfg = cfg
        # thresholds_provider() -> (rms_high, rms_low) efficaci (post auto-cal §22-25)
        self._thresholds_provider = thresholds_provider
        # baseline_provider() -> mediana baseline (None se non pronta/rifiutata, §30)
        self._baseline_provider = baseline_provider
        # §46 — transparency_provider() -> dict {index,state,deficit,confirmed_subs} o None
        # (telemetria NINA assente/stantia/feature off). Solo informativo per il SEEING.
        self._transparency_provider = transparency_provider

        self._jitter_ref: Optional[float] = None
        self._hfd_ref: Optional[float] = None
        self._last: Optional[DiagnosisResult] = None

        # §38: finestra mobile dei campioni recenti (jitter/HFD) da cui derivare le
        # reference col best-fraction (i frame piu' calmi), come la baseline §33. Si
        # forma sempre, non solo nel raro ramo rms<=rms_low. maxlen = finestra config.
        win = max(1, int(getattr(self.cfg, "refs_window_frames", 120)))
        self._jitter_window: deque[float] = deque(maxlen=win)
        self._hfd_window: deque[float] = deque(maxlen=win)

        # §39 — causa dell'ultimo reset, in attesa di essere loggata sul prossimo
        # frame (read-and-clear dal logger via consume_reset_cause()).
        self._pending_reset_cause: str = ""

        self._counts: dict[str, int] = {s.name: 0 for s in DiagnosisState}
        self._guardian_counts: dict[str, int] = {
            "CONFIRM": 0, "ATTENUATE": 0, "BLOCK": 0, "micro": 0,
        }
        # §80 — ULTIMO verdetto emesso, con istante e leva. NON e' "lo stato del
        # Guardian": il Guardian non ha uno stato, ha una serie di giudizi su
        # singole azioni. Rileggendo una notte, "la leva non si e' mossa" e "la
        # leva si e' mossa a meta'" sono due storie diverse, e finora erano
        # distinguibili solo aprendo i log. Sopravvive al reset come i conteggi.
        self._last_verdict: Optional[dict] = None
        self._verdict_context: Optional[str] = None
        # §47 — shadow: quante volte il ramo oscillazioni AVREBBE agito da disattivo
        # (e in quante di quelle l'RMS stava davvero peggiorando, rms>rms_high).
        self._osc_would_fire: int = 0
        self._osc_would_fire_degraded: int = 0

    # ------------------------------------------------------------------ #
    #  Stato reference                                                     #
    # ------------------------------------------------------------------ #

    def reset(self, cause: str = "manual") -> None:
        """Reset del motore, con la CAUSA (§39). L'ultimo esito si azzera sempre
        (dopo un transiente la diagnosi precedente e' stale). I RIFERIMENTI di calma
        (_jitter_ref/_hfd_ref + finestre §38) si azzerano solo se la causa cambia il
        REGIME del jitter: dither/settle/mode_transition lo PRESERVANO (un dither non
        tocca l'atmosfera), cambio esposizione/pixel-scale/target/restart lo AZZERANO.
        La causa viene comunque registrata per il logging (consume_reset_cause()).
        Kill-switch preserve_refs_on_dither=false => azzera sempre (comportamento §31)."""
        self._last = None
        self._pending_reset_cause = cause
        preserve = (getattr(self.cfg, "preserve_refs_on_dither", True)
                    and cause in _PRESERVE_CAUSES)
        if not preserve:
            self._jitter_ref = None
            self._hfd_ref = None
            self._jitter_window.clear()
            self._hfd_window.clear()

    def consume_reset_cause(self) -> str:
        """§39 — ritorna la causa dell'ultimo reset e la azzera (read-and-clear).
        Chiamata dal logger una volta per frame: la causa compare sul primo frame
        loggato dopo il reset, vuota altrove."""
        c = self._pending_reset_cause
        self._pending_reset_cause = ""
        return c

    @property
    def refs_ready(self) -> bool:
        """True quando la reference del jitter e' formata. §38: post-§37 l'HFD e'
        informativo, quindi la PRONTEZZA del motore non dipende piu' da hfd_ref
        (gating su un segnale non informativo era un residuo). Legacy
        (refs_always_form=false): richiede entrambe le reference EMA (comportamento §31)."""
        if getattr(self.cfg, "refs_always_form", True):
            return self._jitter_ref is not None
        return self._jitter_ref is not None and self._hfd_ref is not None

    @property
    def jitter_ref(self) -> float:
        """Reference EMA del jitter (0.0 se non ancora formata). Per CSV/telemetria."""
        return self._jitter_ref if self._jitter_ref is not None else 0.0

    @property
    def hfd_ref(self) -> float:
        """Reference EMA dell'HFD (0.0 se non ancora formata). Per CSV/telemetria."""
        return self._hfd_ref if self._hfd_ref is not None else 0.0

    @staticmethod
    def _best_fraction_stat(window: deque[float], fraction: float) -> Optional[float]:
        """Statistica robusta del best-fraction: mediana dei valori piu' BASSI
        (= guida piu' calma) nella finestra. Specchio del §33 sulla baseline RMS.
        Ritorna None se la finestra e' vuota."""
        vals = sorted(v for v in window if v > 0.0)
        if not vals:
            return None
        k = max(1, int(len(vals) * fraction))
        best = vals[:k]
        n = len(best)
        mid = n // 2
        return best[mid] if n % 2 else 0.5 * (best[mid - 1] + best[mid])

    def _update_refs_window(self, snap: AnalysisSnapshot) -> None:
        """§38: alimenta le finestre mobili a OGNI frame valido e ricalcola le
        reference dal best-fraction una volta superato il warmup. Cosi' jitter_ref
        (e hfd_ref, informativo) si formano sempre e presto, anche quando rms quasi
        mai scende sotto rms_low (notti turbolente). Adattamento continuo."""
        if snap.jitter_rms > 0.0:
            self._jitter_window.append(snap.jitter_rms)
        if snap.hfd_avg > 0.0:
            self._hfd_window.append(snap.hfd_avg)
        if len(self._jitter_window) < self.cfg.refs_warmup_frames:
            return
        frac = self.cfg.refs_best_fraction
        jref = self._best_fraction_stat(self._jitter_window, frac)
        if jref is not None:
            self._jitter_ref = jref
        href = self._best_fraction_stat(self._hfd_window, frac)
        if href is not None:
            self._hfd_ref = href

    def _is_confident(self) -> bool:
        """Diagnosi confidente = refs pronte, stato non incerto, confidence sopra
        la soglia guardian. Usato dal fail-safe del review e dalle micro-correzioni."""
        r = self._last
        if r is None or not self.refs_ready:
            return False
        if r.state in (DiagnosisState.INSUFFICIENT_DATA, DiagnosisState.UNCERTAIN):
            return False
        return r.confidence >= self.cfg.guardian_min_confidence

    # ------------------------------------------------------------------ #
    #  Classificazione                                                     #
    # ------------------------------------------------------------------ #

    def classify(self, snap: AnalysisSnapshot) -> DiagnosisResult:
        """Classifica il regime corrente dallo snapshot. Aggiorna le reference EMA
        solo in NOMINAL. Memorizza e ritorna l'esito."""
        rms_high, rms_low = self._thresholds_provider()

        # ---- INSUFFICIENT_DATA: dati scarsi, garbage o stella persa ----
        insufficient = (
            snap.frame_count < self.cfg.min_frames
            or snap.jitter_n < 2
            or snap.implosion_detected
            or snap.implosion_suspended
            or snap.condition == SeeingCondition.STAR_LOST
        )
        if insufficient:
            return self._finalize(DiagnosisState.INSUFFICIENT_DATA, 0,
                                  None, snap, False, False, False, False)

        # §38: formazione robusta delle reference (best-fraction su finestra mobile),
        # SCOLLEGATA dal ramo stretto rms<=rms_low: si forma sempre, dai frame piu'
        # calmi disponibili. Aggiornata a ogni frame valido, prima di derivare i
        # segnali (jitter_high) e prima del ramo NOMINAL. Con refs_always_form=false
        # resta la formazione stretta §31 (EMA solo in NOMINAL, sotto).
        if self.cfg.refs_always_form:
            self._update_refs_window(snap)

        # ---- NOMINAL: regime stabile -> aggiorna reference + satisfaction gate ----
        if snap.rms_total <= rms_low and snap.condition == SeeingCondition.NOMINAL:
            if not self.cfg.refs_always_form:
                # Formazione §31 (legacy): EMA solo nel ramo NOMINAL stretto.
                self._jitter_ref = _ema(self._jitter_ref, snap.jitter_rms, self.cfg.ema_alpha)
                self._hfd_ref = _ema(self._hfd_ref, snap.hfd_avg, self.cfg.ema_alpha)

            # §30 satisfaction gate: si e' "soddisfatti" solo con baseline pronta e
            # RMS gia' <= mediana -> nessuna spinta. Altrimenti (baseline non pronta,
            # come nel fallback legacy §30, oppure RMS sopra mediana) ottimizzazione
            # gentile verso piu' reattivita'.
            median = self._baseline_provider()
            satisfied = (median is not None and snap.rms_total <= median)
            proposal = None if satisfied else LeverProposal(aggr=+1, minmove=-1)
            return self._finalize(DiagnosisState.NOMINAL, 75,
                                  proposal, snap, False, False, False, False)

        # ---- Derivazione segnali (relativi alle reference EMA) ----
        jitter_high = (self.refs_ready
                       and snap.jitter_rms > self.cfg.jitter_high_factor * self._jitter_ref)
        # §37: hfd_high resta CALCOLATO (per CSV/dashboard/evidence) ma di default NON
        # gatea piu' alcuna diagnosi. Sulla camera di guida l'HFD e' cieco al seeing
        # (hfd_avg/hfd_ref ~ 1.0 a ogni cielo/SNR) -> faceva da gate AND che azzerava
        # SEEING. Con [diagnostic_engine] hfd_gates_seeing=true torna a gateare (legacy).
        # §38: hfd_ref puo' essere None anche con refs_ready vero (HFD non disponibile):
        # guardia esplicita prima di dereferenziarlo. hfd_high resta solo informativo (§37).
        hfd_high = (self.refs_ready and self._hfd_ref is not None
                    and snap.hfd_avg > self.cfg.hfd_high_factor * self._hfd_ref)
        oscillation = (snap.lag1_ra <= self.cfg.lag1_oscillation_thresh
                       or snap.lag1_dec <= self.cfg.lag1_oscillation_thresh)
        trend_max = max(abs(snap.trend_ra), abs(snap.trend_dec))
        drift = (trend_max >= self.cfg.trend_drift_min) and not jitter_high

        hfd_gates = self.cfg.hfd_gates_seeing

        # ---- Classificazione causale combinata ----
        # SEEING: firma DINAMICA (RMS alto + jitter alto), distinta da OVERCORRECTION
        # (oscillazione del loop: lag-1 << 0) e da DRIFT (trend; gia' mutuamente
        # esclusivo col jitter via la sua definizione). §37: niente vincolo HFD; il
        # `not oscillation` mantiene SEEING specifico (non confuso con la sovra-corr.).
        # Legacy (hfd_gates): SEEING richiede anche hfd_high (comportamento §31).
        if hfd_gates:
            seeing = snap.rms_total > rms_high and jitter_high and hfd_high
        else:
            seeing = snap.rms_total > rms_high and jitter_high and not oscillation

        if seeing:
            signals = 3 if hfd_gates else 2
            conf = min(95, 40 + 18 * signals)
            # §46 N8 — modulazione SOLO sul SEEING: la trasparenza in calo abbassa la
            # confidence (penalità proporzionale, dead-band + persistenza). NINA non tocca
            # mai le altre diagnosi né aumenta la confidence/aggressività.
            nina_pen, nina_mod = self._nina_modulation(conf)
            conf_final = max(0, conf - nina_pen)
            proposal = LeverProposal(aggr=-1, minmove=+1)
            return self._finalize(DiagnosisState.SEEING, conf_final, proposal, snap,
                                  jitter_high, hfd_high, oscillation, drift,
                                  confidence_calibrated=(nina_mod is not None),
                                  nina_mod=nina_mod)

        # OVERCORRECTION: il loop si ribalta (lag-1 << 0). Legacy: solo con HFD nella norma.
        if oscillation and (not hfd_high or not hfd_gates):
            signals = 2 + (1 if jitter_high else 0)
            conf = min(95, 40 + 18 * signals)
            # §47 — esperimento outcome-first: con oscillation_branch_enabled=false lo stato
            # OVERCORRECTION resta INFORMATIVO ma NON emette alcuna azione (proposal=None).
            # Shadow: contiamo quante volte AVREBBE agito (e se l'RMS stava peggiorando).
            osc_on = getattr(self.cfg, "oscillation_branch_enabled", False)
            if osc_on:
                proposal = LeverProposal(aggr=-1, minmove=0)
            else:
                proposal = None
                self._osc_would_fire += 1
                if snap.rms_total > rms_high:
                    self._osc_would_fire_degraded += 1
            return self._finalize(DiagnosisState.OVERCORRECTION, conf, proposal, snap,
                                  jitter_high, hfd_high, oscillation, drift)

        # DRIFT: deriva direzionale (trend) senza jitter. Legacy: solo con HFD nella norma.
        if drift and (not hfd_high or not hfd_gates):
            signals = 3
            conf = min(95, 40 + 18 * signals)
            return self._finalize(DiagnosisState.DRIFT, conf, None, snap,
                                  jitter_high, hfd_high, oscillation, drift)

        # ---- UNCERTAIN: nessun fattore dominante ----
        return self._finalize(DiagnosisState.UNCERTAIN, 40, None, snap,
                              jitter_high, hfd_high, oscillation, drift)

    def _nina_modulation(self, base_conf: int) -> tuple[int, Optional[dict]]:
        """§46 N8 — penalità di confidence PROPORZIONALE al calo % di trasparenza (N1),
        applicata SOLO al SEEING dal chiamante. Curva: dead-band sul rumore -> ramp lineare
        fino a `nina_max_penalty` a `nina_full_deficit`; scatta solo se il calo è confermato
        su >= `nina_persist_subs` pose (anti singolo frame anomalo). Ritorna (penalità, info);
        info=None se NINA non disponibile (graceful: nessuna modulazione, confidence PHD2-only)."""
        if not getattr(self.cfg, "confidence_use_nina", False):
            return 0, None
        prov = self._transparency_provider
        if prov is None:
            return 0, None
        data = prov()
        if not data:
            return 0, None
        deficit = float(data.get("deficit", 0.0))
        confirmed = int(data.get("confirmed_subs", 0))
        deadband = getattr(self.cfg, "nina_deadband", 0.10)
        full = getattr(self.cfg, "nina_full_deficit", 0.45)
        max_pen = int(getattr(self.cfg, "nina_max_penalty", 40))
        persist = int(getattr(self.cfg, "nina_persist_subs", 2))
        penalty = 0
        if confirmed >= persist and deficit > deadband and full > deadband:
            frac = min(1.0, (deficit - deadband) / (full - deadband))
            penalty = int(round(frac * max_pen))
        info = {
            "calibrated": True,                       # NINA fresca -> confidence calibrata
            "confidence_phd2": int(base_conf),
            "penalty": penalty,
            "deficit": round(deficit, 3),
            "confirmed_subs": confirmed,
            "index": round(float(data.get("index", 0.0)), 3),
            "state": data.get("state"),
        }
        return penalty, info

    def _finalize(
        self,
        state: DiagnosisState,
        confidence: int,
        proposal: Optional[LeverProposal],
        snap: AnalysisSnapshot,
        jitter_high: bool,
        hfd_high: bool,
        oscillation: bool,
        drift: bool,
        confidence_calibrated: bool = False,
        nina_mod: Optional[dict] = None,
    ) -> DiagnosisResult:
        """Costruisce il DiagnosisResult, aggiorna i contatori e lo memorizza.
        §46: se `nina_mod` è presente (SEEING con NINA fresca) la evidence riporta la
        modulazione esplicita e le metriche portano la decomposizione del confidence."""
        evidence = self._build_evidence(state, jitter_high, hfd_high,
                                        oscillation, drift, snap)
        metrics = {
            "rms": round(snap.rms_total, 4),
            "hfd": round(snap.hfd_avg, 3),
            "hfd_ref": round(self._hfd_ref, 3) if self._hfd_ref is not None else 0.0,
            "jitter": round(snap.jitter_rms, 4),
            "jitter_ref": round(self._jitter_ref, 4) if self._jitter_ref is not None else 0.0,
            "lag1_ra": round(snap.lag1_ra, 3),
            "lag1_dec": round(snap.lag1_dec, 3),
            "trend_max": round(max(abs(snap.trend_ra), abs(snap.trend_dec)), 4),
        }
        if nina_mod is not None:
            # Decomposizione confidence per dashboard/log/replay (numeri RELATIVI).
            metrics["confidence_phd2"] = nina_mod["confidence_phd2"]
            metrics["nina_penalty"] = nina_mod["penalty"]
            metrics["transparency_index"] = nina_mod["index"]
            metrics["transparency_deficit"] = nina_mod["deficit"]
            metrics["transparency_state"] = nina_mod["state"]
            d_pct = round(nina_mod["deficit"] * 100)
            if nina_mod["penalty"] > 0:
                evidence.append(
                    f"◦ trasparenza in calo (−{d_pct}% vs riferimento campo) → "
                    f"confidence {nina_mod['confidence_phd2']}→{confidence}")
            else:
                evidence.append(
                    f"◦ trasparenza stabile (−{d_pct}% vs riferimento campo) → "
                    f"nessuna modulazione")
        result = DiagnosisResult(
            state=state,
            confidence=confidence,
            confidence_calibrated=confidence_calibrated,
            proposal=proposal,
            label=_STATE_LABEL[state],
            suggestion=_STATE_SUGGESTION[state],
            evidence=evidence,
            jitter_high=jitter_high,
            hfd_high=hfd_high,
            oscillation=oscillation,
            drift=drift,
            metrics=metrics,
        )
        self._counts[state.name] += 1
        self._last = result
        return result

    def _build_evidence(
        self,
        state: DiagnosisState,
        jitter_high: bool,
        hfd_high: bool,
        oscillation: bool,
        drift: bool,
        snap: AnalysisSnapshot,
    ) -> list[str]:
        """Lista di fattori in linguaggio umano (✓ a sostegno, ◦ neutro/secondario)
        derivata SOLO dai booleani gia' calcolati: zero metriche nuove. Il testo
        riflette lo stato REALE misurato (es. HFD nella norma vs sopra riferimento)."""
        hfd_gates = self.cfg.hfd_gates_seeing
        # §37: quando l'HFD non gatea piu', le sue righe diventano "informativo
        # (non-gating)"; il segnale a sostegno della diagnosi e' la firma dinamica.
        hfd_norm_line = "✓ HFD nella norma" if hfd_gates else "◦ HFD informativo (non-gating)"
        if state == DiagnosisState.SEEING:
            if hfd_gates:
                return [
                    "✓ HFD sopra riferimento",
                    "✓ Jitter sopra riferimento",
                    "✓ Lag-1 non oscillante",
                ]
            return [
                "✓ RMS sopra soglia",
                "✓ Jitter sopra riferimento",
                "✓ Lag-1 non oscillante",
                "◦ HFD informativo (non-gating)",
            ]
        if state == DiagnosisState.OVERCORRECTION:
            return [
                "✓ Lag-1 fortemente negativo",
                hfd_norm_line,
                f"{'✓' if jitter_high else '◦'} Jitter " + ("elevato" if jitter_high else "normale"),
            ]
        if state == DiagnosisState.DRIFT:
            return [
                "✓ Trend elevato",
                "✓ Jitter nella norma",
                hfd_norm_line,
            ]
        if state == DiagnosisState.NOMINAL:
            return ["✓ RMS sotto soglia bassa", "✓ regime stabile"]
        if state == DiagnosisState.UNCERTAIN:
            return ["◦ Nessun fattore dominante"]
        return ["◦ Finestra/reference non pronte"]

    # ------------------------------------------------------------------ #
    #  Guardian: review delle mosse v2.3                                   #
    # ------------------------------------------------------------------ #

    def review(self, caso: str, is_minmove: bool, direction: float,
               context: Optional[str] = None
               ) -> tuple[GuardianVerdict, float, str]:
        """Rivede una mossa leva proposta dalla v2.3 (modalita' guardian).

        Fail-safe: in dubbio (diagnosi non confidente) -> CONFIRM. I soli BLOCK:
        CASO1 (ammorbidisce) in DRIFT, e CASO3 (aggr su) in OVERCORRECTION. In
        OVERCORRECTION un CASO1 sul MinMove su viene ATTENUATO. Altrimenti CONFIRM.

        Ritorna (verdict, factor, reason). `factor` e' usato solo per ATTENUATE.
        """
        # §80 — la leva in esame, per l'ultimo verdetto. Depositata qui e letta
        # da _verdict(): cosi' ogni ramo la eredita senza doverla inoltrare.
        self._verdict_context = context

        # Fail-safe: senza diagnosi confidente la v2.3 passa invariata.
        if not self._is_confident():
            return self._verdict(GuardianVerdict.CONFIRM, 1.0,
                                 "diagnosi non confidente -> CONFIRM (fail-safe)")

        state = self._last.state

        if caso == "CASO1" and state == DiagnosisState.DRIFT:
            return self._verdict(GuardianVerdict.BLOCK, 0.0,
                                 "CASO1 ammorbidisce in DRIFT -> BLOCK "
                                 "(la deriva non si cura con leve soft)")

        if caso == "CASO1" and state == DiagnosisState.OVERCORRECTION and is_minmove:
            return self._verdict(GuardianVerdict.ATTENUATE,
                                 self.cfg.guardian_attenuate_factor,
                                 "CASO1 MinMove su in OVERCORRECTION -> ATTENUATE")

        if (caso == "CASO3" and state == DiagnosisState.OVERCORRECTION
                and not is_minmove and direction > 0):
            return self._verdict(GuardianVerdict.BLOCK, 0.0,
                                 "CASO3 aggr su in OVERCORRECTION -> BLOCK "
                                 "(alzare aggr peggiora l'oscillazione)")

        return self._verdict(GuardianVerdict.CONFIRM, 1.0, "nessun conflitto -> CONFIRM")

    def _verdict(self, verdict: GuardianVerdict, factor: float,
                 reason: str) -> tuple[GuardianVerdict, float, str]:
        self._guardian_counts[verdict.name] += 1
        self._last_verdict = {
            "verdict": verdict.name,          # CONFIRM | ATTENUATE | BLOCK
            # Ampiezza superstite: 1.0 confermata, 0.0 bloccata, in mezzo attenuata.
            "factor": round(float(factor), 3),
            "reason": reason,
            "context": self._verdict_context,   # "RA/Aggressiveness", se noto
            "ts_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self._verdict_context = None
        return verdict, factor, reason

    # ------------------------------------------------------------------ #
    #  Micro-correzioni proprie di guardian / azioni jitter               #
    # ------------------------------------------------------------------ #

    def micro_proposal(self) -> Optional[LeverProposal]:
        """Proposta per le micro-correzioni guardian: ritorna una mossa SOLO se la
        diagnosi corrente e' confidente (refs pronte, confidence >= soglia) e lo
        stato e' SEEING (aggr giu', MinMove su) o OVERCORRECTION (aggr giu').
        DRIFT/NOMINAL/UNCERTAIN -> None."""
        if not self._is_confident():
            return None
        state = self._last.state
        if state == DiagnosisState.SEEING:
            return LeverProposal(aggr=-1, minmove=+1)
        if state == DiagnosisState.OVERCORRECTION:
            # §47 — ramo oscillazioni disattivo: nessuna micro su OVERCORRECTION.
            if not getattr(self.cfg, "oscillation_branch_enabled", False):
                return None
            return LeverProposal(aggr=-1, minmove=0)
        return None

    def note_micro_applied(self) -> None:
        """Il controller segnala una micro-correzione effettivamente applicata."""
        self._guardian_counts["micro"] += 1

    # ------------------------------------------------------------------ #
    #  Stato pubblico per dashboard / logging                              #
    # ------------------------------------------------------------------ #

    def get_state(self) -> dict:
        """Snapshot dello stato del motore per dashboard e summary di sessione."""
        r = self._last
        if r is None:
            return {
                "enabled": self.cfg.enabled,
                "mode": self.cfg.mode,
                "refs_ready": self.refs_ready,
                "state": DiagnosisState.INSUFFICIENT_DATA.name,
                "label": _STATE_LABEL[DiagnosisState.INSUFFICIENT_DATA],
                "confidence": 0,
                "confidence_calibrated": False,
                "suggestion": _STATE_SUGGESTION[DiagnosisState.INSUFFICIENT_DATA],
                "evidence": ["◦ Finestra/reference non pronte"],
                "evidence_bools": {"jitter_high": False, "hfd_high": False,
                                   "oscillation": False, "drift": False},
                "metrics": {"rms": 0.0, "hfd": 0.0, "hfd_ref": 0.0, "jitter": 0.0,
                            "jitter_ref": 0.0, "lag1_ra": 0.0, "lag1_dec": 0.0,
                            "trend_max": 0.0},
                "counts": dict(self._counts),
                "guardian_counts": dict(self._guardian_counts),
                "last_verdict": dict(self._last_verdict) if self._last_verdict else None,
                "oscillation_branch_enabled": getattr(self.cfg, "oscillation_branch_enabled", False),
                "osc_would_fire": self._osc_would_fire,
                "osc_would_fire_degraded": self._osc_would_fire_degraded,
            }
        return {
            "enabled": self.cfg.enabled,
            "mode": self.cfg.mode,
            "refs_ready": self.refs_ready,
            "state": r.state.name,
            "label": r.label,
            "confidence": r.confidence,
            "confidence_calibrated": r.confidence_calibrated,
            "suggestion": r.suggestion,
            "evidence": r.evidence,
            "evidence_bools": {
                "jitter_high": r.jitter_high, "hfd_high": r.hfd_high,
                "oscillation": r.oscillation, "drift": r.drift,
            },
            "metrics": r.metrics,
            "counts": dict(self._counts),
            "guardian_counts": dict(self._guardian_counts),
            "last_verdict": dict(self._last_verdict) if self._last_verdict else None,
            "oscillation_branch_enabled": getattr(self.cfg, "oscillation_branch_enabled", False),
            "osc_would_fire": self._osc_would_fire,
            "osc_would_fire_degraded": self._osc_would_fire_degraded,
        }
