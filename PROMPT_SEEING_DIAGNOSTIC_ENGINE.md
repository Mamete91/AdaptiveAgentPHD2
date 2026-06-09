# PROMPT PER CLAUDE CODE (Antigravity) — Seeing Diagnostic Engine (jitter + lag-1): modalità JITTER e GUARDIAN
# Da copiare e incollare integralmente nella conversazione con Claude Code.
# Lavorare nella cartella: PHD2_Assist_PATCHED/

> **NOTA OPERATIVA PER CLAUDE CODE**: questa è la forma DEFINITIVA della feature v2.4.
> Un **motore diagnostico** aggiunge due metriche dai dati GuideStep già ingeriti — **jitter
> frame-to-frame** e **autocorrelazione a lag-1** — e le combina con RMS, HFD e trend per una
> **diagnosi causale** del regime (SEEING / OVERCORRECTION / DRIFT / NOMINAL). Due modalità:
> - **`jitter`** = controllo causale completo: il motore è **unica autorità** su Aggressività e
>   MinMove (i rami leva CASO 1/2/3 della v2.3 sono sospesi). Per ricerca/validazione sul campo.
> - **`guardian`** = assistito: la **v2.3 resta il pilota**; il motore (a) **rivede** le mosse
>   leva della v2.3 (CONFIRM / ATTENUATE / BLOCK) e (b) può fare **micro-correzioni proprie ad
>   ampiezza ridotta SOLO quando la v2.3 è ferma su quell'asse**. Fail-safe, distribuibile.
>
> **Non esiste più una modalità "shadow".** L'osservazione-senza-azione coincide con il motore
> **spento** (`enabled = false`, default di fabbrica = comportamento identico alla v2.3).
> Il motore non tocca **mai** esposizione (§19), backlash, star-lost/saturazione, e non accede
> a `self.client` (l'invio passa solo per `controller._apply`). Riferimenti: NOTE_CLAUDE.md §18
> (EMA), §19 (esposizione path B), §22-25 (auto-calibrazione/baseline), §30 (satisfaction gate).
> Ultima sezione NOTE = §30 → nuova **§31**, Agente v2.3 → **v2.4**.

---

## 0. PRE-FLIGHT OBBLIGATORIO (leggere PRIMA di scrivere codice)

### File PHD2 sorgente da consultare

1. **`phd2-master/phd2-master/src/event_server.cpp`** — evento `GuideStep`:
   ```
   grep -n "GuideStep" event_server.cpp
   grep -n "RADistanceRaw\|DECDistanceRaw\|\"HFD\"\|StarMass\|\"SNR\"" event_server.cpp
   ```
   **Confermare** che il JSON di `GuideStep` contiene `RADistanceRaw`, `DECDistanceRaw`, `HFD`,
   `SNR`, `StarMass` (nel log testuale: `RARawDistance`/`DECRawDistance` — non confonderli). Sono
   **già** i campi letti da `analyzer.ingest_guide_step()`. Nessuna RPC nuova.

2. **`guide_algorithm_hysteresis.cpp` / `guide_algorithm_resistswitch.cpp`** — confermare (come
   §13) che `aggression` è in scala 0.0–1.0. In live l'invio passa per `_apply`, che gestisce
   già `aggr_native_scale`: **non reimplementare la conversione**.

### File Python da consultare
1. `phd2_agent/analyzer.py` — `FrameData` (`ra_raw`/`dec_raw` arcsec), `AnalysisSnapshot`,
   `_compute()`, pattern EMA RMS implosion (`_rms_reference`), `reset()`.
2. `phd2_agent/controller.py` — `evaluate()`, `_evaluate_axis` (CASO 1/2/3 e i punti `_apply`),
   `_apply`, punti di `analyzer.reset()`, baseline (`current_aggr`/`current_minmove`), `get_status()`.
3. `phd2_agent/config.py` — dataclass + parsing TOML retrocompatibile (es. `LeverOptimizationConfig`).
4. `phd2_agent/logger.py` — `_CSV_FIELDS`, `log_snapshot()`, `close()`.
5. `phd2_agent/diagnostic_engine.py` — **da creare**.
6. `server.py` — `/status`, pattern `POST /config/dry_run`.
7. `dashboard/index.html` + `dashboard/app.js` — pattern card esistenti.
8. `phd2_agent/__about__.py` — versione (bump v2.3 → v2.4).

### Conclusioni del pre-flight (già verificate, da confermare)
A. Jitter e lag-1 dai dati già ingeriti (arcsec); nessun campo nuovo da ingerire, nessuna RPC, nessun FITS.
B. Il jitter è un **residuo di loop chiuso** (ambiguo da solo). **HFD** discrimina seeing (stella
   allargata) da over-correzione (nitida); **lag-1** discrimina l'oscillazione del loop (segno che
   si ribalta) dalla deriva. Si decide SEMPRE sulla diagnosi combinata, **mai sul jitter da solo**.
C. Soglie "alto/basso" **relative a reference EMA** (jitter_ref/hfd_ref), aggiornate solo in
   NOMINAL e azzerate a ogni cambio esposizione (con `analyzer.reset()`). Niente baseline assoluta
   per-esposizione in v2.4.
D. Config UNICO `config.toml` (§22). `build_dist.py` copia `config.toml`, `Avvia.bat`,
   `Sblocca_Firewall_8080.bat`, `dashboard/`. Baseline Guardian resta **v3**. Ultima sezione NOTE = §30 → **§31**. Versione → **v2.4**.
E. `analyzer._classify` (incluso `OSCILLATING`/`trend` = drift direzionale) **NON va modificato**:
   lag-1 è il segnale corretto per l'oscillazione, usato solo dal motore.

### Decisioni di design già prese (NON reinterpretare)
a. **`mode`** ∈ `{"jitter", "guardian"}` (nessun "shadow"). **`enabled` default `false`**: a motore
   spento il comportamento è **identico alla v2.3** (motore non istanziato). Quando `enabled=true`,
   `mode` default `"guardian"`.
b. **`jitter`**: motore unica autorità su Aggr/MinMove → i rami leva CASO 1/2/3 di `_evaluate_axis`
   **sospesi**. Decide *quando*; i limiti di *quanto* restano `[limits]`/cooldown v2.3. Leve: solo
   Aggr+MinMove, **mai esposizione**.
c. **`guardian`** (la v2.3 pilota):
   - **Review** delle mosse leva v2.3 → CONFIRM / ATTENUATE / BLOCK. **Fail-safe**: in dubbio
     (INSUFFICIENT_DATA/UNCERTAIN, refs non pronte, `confidence < guardian_min_confidence`) → CONFIRM.
   - **Micro-correzioni proprie** ad ampiezza ridotta (`guardian_action_factor`, default 0.4) **SOLO
     quando la v2.3 NON ha agito su quell'asse nel tick** (banda neutra / nessun CASO scattato) e la
     diagnosi è confidente (SEEING/OVERCORRECTION). DRIFT escluso. È il "buco" dove la causa è chiara
     ma l'RMS non ha ancora superato le soglie v2.3. Mai origina mosse mentre la v2.3 agisce.
d. **Interventi review chiave (gli unici BLOCK)**: CASO1 (ammorbidisce) in **DRIFT** → BLOCK;
   CASO3 (aggr↑) in **OVERCORRECTION** → BLOCK; CASO1 in OVERCORRECTION → ATTENUATE del MinMove↑;
   altrimenti CONFIRM.
e. **Cold-start gate**: agire/intervenire/micro-correggere solo con diagnosi valida + refs pronte
   + confidence ≥ soglia.
f. **In jitter**: DRIFT → nessuna azione; NOMINAL → ottimizzazione gentile gated dal satisfaction
   gate (mediana baseline §30).
g. **Logging azione→esito** (pre/post su `outcome_window_frames`) in `experimental_*.jsonl`: per
   le azioni di `jitter` E per le micro-correzioni di `guardian`. I BLOCK/ATTENUATE di review si
   loggano come eventi `axis="guardian"`; il CONFIRM non si logga.
h. **Il modulo motore NON accede a `self.client`**, non chiama mai `set_algo_param`/`set_exposure`.
i. **Dashboard**: switcher **OFF / GUARDIAN / JITTER**. **OFF (→ v2.3 puro) sempre permesso** senza
   conferma (kill switch). Attivare/commutare un motore è permesso solo se
   `allow_dashboard_mode_switch = true` (default `false`) e con **conferma**. Ogni cambio passa per
   `_apply_mode_transition` (transizione pulita: ripristino leve a baseline + `analyzer.reset()` +
   `engine.reset()` + warmup).

### Se qualcosa non torna → STOP
Se i nomi dei campi JSON-RPC, l'ordine di `evaluate()`, i punti di `analyzer.reset()` o la firma di
`_apply` differiscono, **fermati e riportami** prima di procedere.

---

## 1. OBIETTIVO E SCOPO
Superare la diagnosi sul solo RMS con un motore che distingue la *causa* del degrado. **`jitter`**:
il motore guida le leve e si misura azione per azione (ricerca, setup di Alessandro). **`guardian`**:
la v2.3 guida, il motore le evita le mosse sbagliate e riempie i buchi con micro-correzioni gentili
(sicuro, distribuibile). Spento (`enabled=false`) = v2.3 pura.

**Cosa NON fa**: non tocca esposizione (§19)/backlash/star-lost/saturazione/baseline; non decide mai
sul jitter isolato; in guardian non origina mosse mentre la v2.3 agisce; non agisce prima che
diagnosi/reference siano pronte.

---

## REGOLE INDEROGABILI
- **NON toccare** la backlash compensation di PHD2.
- **NON modificare** `analyzer._classify` (incl. `OSCILLATING`/`trend`), l'esposizione §19, lo
  star-lost/saturazione, la baseline §22-25. In `jitter` i rami leva CASO 1/2/3 vanno **sospesi**
  (non cancellati: attivi in guardian).
- **Il motore NON accede a `self.client`**; invio solo via `controller._apply`.
- **In guardian, micro-correzione solo se la v2.3 NON ha agito sull'asse nel tick**; mai mentre la
  v2.3 agisce. Ampiezza ridotta (`guardian_action_factor`). DRIFT escluso.
- **Leve del motore: solo Aggressività e MinMove, entro `[limits]`, cooldown `[control]`. MAI esposizione.**
- **Fail-safe guardian review**: in dubbio CONFIRM.
- **Cold-start gate** rispettato. **`enabled` default `false`** (= v2.3 pura). `mode` default `"guardian"`.
- **Retrocompatibilità TOML**: sezione assente → default. `mode` ignoto → fallback "guardian" con WARNING.
- **`engine.reset()`** ovunque si chiami `analyzer.reset()` e in `_apply_mode_transition`.
- Stile/convenzioni del progetto (type hints, dataclass, logging italiano, Enum `auto()`).

### MODALITÀ OPERATIVA
> A motore spento (`enabled=false`, default) il comportamento è **identico alla v2.3**. Con
> `jitter` o `guardian` il motore **incide sulle leve** sul setup di chi le attiva. NON cambiare
> `dry_run`. Sicurezza: leve entro `[limits]`, niente esposizione/backlash, cold-start gate,
> fail-safe guardian, micro-correzioni guardian solo nei buchi e ad ampiezza ridotta, kill switch
> dashboard → OFF. Default di fabbrica: motore spento.

---

## SPECIFICA FUNZIONALE

### 2A. `analyzer.py` — nuove metriche
`AnalysisSnapshot` (default retrocompatibili):
```python
    jitter_rms: float = 0.0      # sqrt(mean(step_i^2)), step_i = hypot(Δra_raw, Δdec_raw), arcsec
    jitter_n: int = 0
    lag1_ra: float = 0.0         # autocorrelazione lag-1 di ra_raw, [-1,1]; <<0 = oscillazione loop
    lag1_dec: float = 0.0
    exposure_ms: int = 0
    diag_state: str = "INSUFFICIENT_DATA"
    diag_confidence: int = 0
```
In `_compute()`, dopo il trend:
```python
        if n >= 2:
            steps = [math.hypot(ra_vals[i]-ra_vals[i-1], dec_vals[i]-dec_vals[i-1])
                     for i in range(1, n)]
            snap.jitter_n = len(steps)
            snap.jitter_rms = math.sqrt(sum(s*s for s in steps)/len(steps)) if steps else 0.0
        snap.lag1_ra = _lag1_autocorr(ra_vals)
        snap.lag1_dec = _lag1_autocorr(dec_vals)
```
Funzione pura (accanto a `_linear_trend`):
```python
def _lag1_autocorr(vals: list[float]) -> float:
    """Autocorrelazione a lag-1 in [-1,1]. ~ -1: il segno si ribalta ogni frame
    (oscillazione/over-correzione del loop). ~ +1: deriva correlata. ~0: casuale."""
    n = len(vals)
    if n < 3:
        return 0.0
    mean = _mean(vals)
    num = sum((vals[i]-mean)*(vals[i-1]-mean) for i in range(1, n))
    den = sum((v-mean)**2 for v in vals)
    return num/den if den > 1e-12 else 0.0
```

### 2B. `config.py` — `DiagnosticEngineConfig` + parsing
```python
@dataclass
class DiagnosticEngineConfig:
    """Seeing Diagnostic Engine (§31, Agente v2.4)."""
    enabled: bool = False          # DEFAULT spento = comportamento identico v2.3
    mode: str = "guardian"         # "jitter" | "guardian" (usato solo se enabled)
    # --- soglie diagnosi (relative alle reference EMA) ---
    min_frames: int = 30
    jitter_high_factor: float = 1.6
    hfd_high_factor: float = 1.25
    lag1_oscillation_thresh: float = -0.35
    trend_drift_min: float = 0.05
    ema_alpha: float = 0.1
    # --- azione (entrambe le modalità) ---
    act_min_confidence: int = 60
    outcome_window_frames: int = 15
    warmup_frames_after_switch: int = 10
    # --- guardian ---
    guardian_min_confidence: int = 60      # sotto questa confidence il review CONFERMA sempre
    guardian_attenuate_factor: float = 0.5 # ampiezza ridotta quando il review ATTENUA una mossa v2.3
    guardian_action_factor: float = 0.4    # ampiezza delle micro-correzioni proprie di guardian (vs step pieni)
    # --- UI ---
    allow_dashboard_mode_switch: bool = False
```
In `AgentConfig`: `diagnostic_engine: DiagnosticEngineConfig = field(default_factory=DiagnosticEngineConfig)`.

Parsing (validare `mode`, fallback "guardian" con WARNING):
```python
    if "diagnostic_engine" in raw:
        de = raw["diagnostic_engine"]
        mode = str(de.get("mode", "guardian"))
        if mode not in ("jitter", "guardian"):
            logger.warning("[diagnostic_engine] mode '%s' ignoto -> guardian", mode)
            mode = "guardian"
        cfg.diagnostic_engine = DiagnosticEngineConfig(
            enabled=bool(de.get("enabled", False)),
            mode=mode,
            min_frames=int(de.get("min_frames", 30)),
            jitter_high_factor=float(de.get("jitter_high_factor", 1.6)),
            hfd_high_factor=float(de.get("hfd_high_factor", 1.25)),
            lag1_oscillation_thresh=float(de.get("lag1_oscillation_thresh", -0.35)),
            trend_drift_min=float(de.get("trend_drift_min", 0.05)),
            ema_alpha=float(de.get("ema_alpha", 0.1)),
            act_min_confidence=int(de.get("act_min_confidence", 60)),
            outcome_window_frames=int(de.get("outcome_window_frames", 15)),
            warmup_frames_after_switch=int(de.get("warmup_frames_after_switch", 10)),
            guardian_min_confidence=int(de.get("guardian_min_confidence", 60)),
            guardian_attenuate_factor=float(de.get("guardian_attenuate_factor", 0.5)),
            guardian_action_factor=float(de.get("guardian_action_factor", 0.4)),
            allow_dashboard_mode_switch=bool(de.get("allow_dashboard_mode_switch", False)),
        )
```

### 2C. `phd2_agent/diagnostic_engine.py` — nuovo modulo (NO client)
Classi: `DiagnosisState` (INSUFFICIENT_DATA, NOMINAL, SEEING, OVERCORRECTION, DRIFT, UNCERTAIN),
`GuardianVerdict` (CONFIRM, ATTENUATE, BLOCK), `LeverProposal` (direzione -1/0/+1 per aggr e minmove),
`DiagnosisResult`, `SeeingDiagnosticEngine`.

`SeeingDiagnosticEngine`:
- `__init__(cfg, thresholds_provider, baseline_provider)` — reference EMA `_jitter_ref`/`_hfd_ref`,
  `_last`, `_counts`, `_guardian_counts`.
- `reset()` → azzera le reference.
- `refs_ready` → entrambe le reference formate.
- `classify(snap) -> DiagnosisResult`: identica alla logica già concordata —
  INSUFFICIENT_DATA se dati scarsi/implosion/star-lost; in NOMINAL (rms≤rms_low & condition NOMINAL)
  aggiorna le EMA e propone ottimizzazione gentile solo se `rms_total > mediana_baseline`
  (satisfaction gate); altrimenti deriva `jitter_high` (>factor×ref), `hfd_high` (>factor×ref),
  `oscillation` (lag1≤soglia su RA o DEC), `drift` (|trend|≥soglia e non jitter_high) e classifica:
  SEEING (rms>rms_high & jitter_high & hfd_high) → proposal(aggr−, minmove+);
  OVERCORRECTION (oscillation & non hfd_high) → proposal(aggr−);
  DRIFT (drift & non hfd_high) → proposal None;
  altrimenti UNCERTAIN → proposal None. `confidence` euristica provvisoria (40 + 18×segnali, cap 95),
  `confidence_calibrated=False`.
- `review(caso, is_minmove, direction) -> (GuardianVerdict, factor, reason)` (per guardian):
  fail-safe → CONFIRM se diagnosi non confidente (INSUFFICIENT_DATA/UNCERTAIN, refs non pronte,
  confidence<guardian_min_confidence). Poi: CASO1 & DRIFT → BLOCK; CASO1 & OVERCORRECTION & is_minmove
  → ATTENUATE(guardian_attenuate_factor); CASO3 & OVERCORRECTION & aggr & direction>0 → BLOCK; altrimenti
  CONFIRM. Aggiorna `_guardian_counts`.
- `micro_proposal() -> Optional[LeverProposal]` (per le micro-correzioni guardian): ritorna una
  proposta SOLO se la diagnosi corrente è confidente (refs pronte, confidence≥guardian_min_confidence)
  e lo stato è SEEING (aggr−, minmove+) o OVERCORRECTION (aggr−). DRIFT/NOMINAL/UNCERTAIN → None.
- `get_state() -> dict`: enabled, mode, refs_ready, state, **label** (etichetta in linguaggio
  astrofotografico, vedi mappa), confidence, confidence_calibrated, suggestion,
  **evidence** (lista fattori umani ✓/◦, vedi sotto),
  **evidence_bools**{jitter_high,hfd_high,oscillation,drift} (i booleani grezzi, per log/replay v2.5),
  metrics{rms,hfd,hfd_ref,jitter,jitter_ref,lag1_ra,lag1_dec,trend_max}, counts, guardian_counts.
  (NB: il blocco numerico grezzo si chiama `metrics`, non più `evidence`. `DiagnosisResult` deve
  memorizzare i quattro booleani `jitter_high/hfd_high/oscillation/drift`, usati sia da
  `_build_evidence` sia dal logging.)

> **Mappa `state` → `label`** (generata nel motore, così dashboard e log restano coerenti):
> `NOMINAL`→"GUIDA STABILE" · `SEEING`→"SEEING DEGRADATO" · `OVERCORRECTION`→"SOVRA-CORREZIONE" ·
> `DRIFT`→"DERIVA SISTEMATICA" · `UNCERTAIN`→"QUADRO INCERTO" · `INSUFFICIENT_DATA`→"DATI INSUFFICIENTI".
> `suggestion` resta la frase esplicativa breve (sottotitolo).

> **`evidence`** = lista di stringhe brevi in linguaggio umano che spiegano QUALI fattori hanno
> portato alla diagnosi. Derivata SOLO dai booleani già calcolati in `classify` (`jitter_high`,
> `hfd_high`, `oscillation`, `drift`) e dallo stato di `trend`/RMS — **zero nuove metriche, zero
> calcolo aggiuntivo**. Ogni voce ha un segno: `✓` = fattore a sostegno della diagnosi, `◦` =
> neutro/secondario. **Il testo riflette lo stato REALE misurato** (es. "HFD nella norma" vs "HFD
> sopra riferimento"), non una stringa fissa per stato. Costruirla con un helper
> `_build_evidence(state, jitter_high, hfd_high, oscillation, drift, snap)`. Esempi:
> - SEEING: `["✓ HFD sopra riferimento", "✓ Jitter sopra riferimento", "✓ Lag-1 non oscillante"]`
> - OVERCORRECTION: `["✓ Lag-1 fortemente negativo", "✓ HFD nella norma", f"{'✓' if jitter_high else '◦'} Jitter " + ("elevato" if jitter_high else "normale")]`
> - DRIFT: `["✓ Trend elevato", "✓ Jitter nella norma", "✓ HFD nella norma"]`
> - NOMINAL: `["✓ RMS sotto soglia bassa", "✓ regime stabile"]`
> - UNCERTAIN: `["◦ Nessun fattore dominante"]` · INSUFFICIENT_DATA: `["◦ Finestra/reference non pronte"]`

> Il motore esprime solo la **direzione** della mossa; l'**ampiezza** la decide il controller con
> `[limits]` (×1.0 in jitter, ×`guardian_action_factor` nelle micro-correzioni guardian) e i clamp.

(Il dettaglio del codice segue lo scheletro già validato nelle iterazioni precedenti; mantenere
firme e nomi indicati qui.)

### 2D. `controller.py` — modalità, sospensione (jitter), guardian review+micro, esecuzione
**Stato in `__init__`**:
```python
self.diagnostic_engine = None
self._diag_last_state = None
self._current_diag = None
self._warmup_frames_left = 0
self._outcome_pending = None
self._last_outcome = None
self._diag_last_action = {"ra": 0.0, "dec": 0.0}   # cooldown per-asse per azioni del motore
```
**In `initialize()`**: istanzia il motore **solo se `cfg.diagnostic_engine.enabled`** (con
`thresholds_provider`/`baseline_provider` come nelle iterazioni precedenti); altrimenti
`self.diagnostic_engine = None` (→ v2.3 pura). Log INFO con `mode`.

**Helper**:
```python
def _engine_owns_levers(self) -> bool:
    de = self.cfg.diagnostic_engine
    return self.diagnostic_engine is not None and de.enabled and de.mode == "jitter"

def _guardian_active(self) -> bool:
    de = self.cfg.diagnostic_engine
    return self.diagnostic_engine is not None and de.enabled and de.mode == "guardian"
```

**In `evaluate()`**:
- `snapshot.exposure_ms = int(self.current_exposure_ms or self.base_exposure_ms or 0)`.
- Se `self.diagnostic_engine is not None`: `self._current_diag = classify(snapshot)`, stampa
  `diag_state`/`diag_confidence` sullo snapshot, decrementa `_warmup_frames_left`.
- Valuta RA e DEC (raccogli per-asse le azioni: `ra_actions`, `dec_actions`). In `jitter` i rami
  leva sono sospesi (vedi sotto); in guardian passano per il review.
- Se `_engine_owns_levers()`: `actions += self._evaluate_engine_actions(snapshot)` (azioni dirette).
- Se `_guardian_active()`: per ogni asse **senza azioni v2.3 nel tick**, prova
  `self._guardian_micro_correction(axis_state, limits, snapshot)`.
- `actions += ...`; `self._track_outcome(snapshot)`.

**Sospensione CASO 1/2/3 (solo jitter)** — in cima a `_evaluate_axis`, dopo `now/cooldown`:
```python
    if self._engine_owns_levers():
        return []
```

**Guardian review** — sostituire le chiamate dirette a `self._apply(...)` nei CASO 1/2/3 con
`self._apply_with_guardian(..., caso="CASO1"|"CASO2"|"CASO3")`, che in non-guardian è `_apply`, e in
guardian consulta `engine.review(...)`: CONFIRM→`_apply`; ATTENUATE→`_apply` con
`new2 = old + factor*(new-old)` (se ≈ old → evento blocco); BLOCK→non applica, ritorna evento
`axis="guardian"` `param=f"{verdict.lower()}_{param}"` `dry_run=True` + log `[GUARDIAN] ...`.
`current_*` aggiornato solo se la mossa è stata effettivamente applicata.

**Guardian micro-correzione** — `_guardian_micro_correction(axis_state, limits, snap)`:
- precondizioni: v2.3 non ha agito sull'asse nel tick (passato dal chiamante), cooldown per-asse
  elapsed (`_diag_last_action`), `engine.micro_proposal()` ritorna una proposta (quindi diagnosi
  confidente SEEING/OVERCORRECTION). Altrimenti return [].
- step ridotti: `aggr_step = max(1, round(limits.aggr_step_down * guardian_action_factor))` per aggr↓,
  `minmove_step_g = limits.minmove_step * guardian_action_factor` per minmove↑; applica via `_apply`
  con reason `"[GUARDIAN micro] <stato>"`; aggiorna `current_*` e `_diag_last_action`; apri finestra outcome.

**`_evaluate_engine_actions(snapshot)` (jitter)**: dalla `proposal` corrente, se `refs_ready`,
`confidence≥act_min_confidence`, `_warmup_frames_left==0`, `_outcome_pending is None`, per ciascun
asse traduce la direzione in mossa con `[limits]` pieni e cooldown (come i CASO v2.3), applica via
`_apply`, aggiorna `current_*`, apre la finestra outcome. DRIFT/UNCERTAIN/None → nessuna azione.

**`_track_outcome(snapshot)`**: buffer per la media `pre` (ultimi `outcome_window_frames`, esclusi i
warmup). All'azione (jitter / micro guardian) o all'intervento guardian BLOCK/ATTENUATE apre
`_outcome_pending` catturando **tutto il contesto di decisione** secondo lo schema di 2F
(`diagnosis`+`evidence_bools`, `metrics_at_decision` con le reference, `thresholds_active`,
`lever_changes`, `v23_proposed` se è un review); accumula `post` per `outcome_window_frames`
(tenendo anche `post_max`); al completamento calcola i `delta`, scrive il record (con
`schema_version`) in `experimental_<session_id>.jsonl`, salva un estratto in `self._last_outcome`
(per la dashboard), azzera.

**`get_status()`** — aggiungere:
```python
"diagnostic_engine": ({**self.diagnostic_engine.get_state(),
                       "allow_dashboard_mode_switch": self.cfg.diagnostic_engine.allow_dashboard_mode_switch,
                       "last_outcome": self._last_outcome}
                      if self.diagnostic_engine is not None else
                      {"enabled": False, "mode": self.cfg.diagnostic_engine.mode,
                       "allow_dashboard_mode_switch": self.cfg.diagnostic_engine.allow_dashboard_mode_switch}),
```

**`set_diagnostic_mode(target)` + `_apply_mode_transition(...)`** — `target` ∈ {"off","jitter","guardian"}:
- `"off"` (kill switch, **sempre permesso**): `enabled=False` (se il motore era istanziato resta in
  memoria ma non agisce; alla prossima `initialize()` non viene istanziato). Poi transizione pulita.
- `"jitter"`/`"guardian"` (attivazione/cambio): permesso solo se `allow_dashboard_mode_switch`; se
  rifiutato → WARNING, nessun cambio. Se accettato: `enabled=True`, `mode=target`; se il motore non
  era istanziato, istanzialo ora; poi transizione pulita.
- `_apply_mode_transition`: `_restore_levers_to_baseline()` → `analyzer.reset()` + `engine.reset()`
  (se presente) → `_warmup_frames_left = warmup_frames_after_switch` → `_outcome_pending=None` →
  log INFO.

**`_restore_levers_to_baseline()`**: rilegge aggr/MinMove dalla baseline (o iniziali) e li riapplica
via `_apply`, riallineando `current_*`. Se assente, WARNING e prosegui.

**`engine.reset()` accanto a `analyzer.reset()`** nei punti di `_evaluate_exposure_*`.

### 2E. `server.py`
```python
class DiagModePayload(BaseModel):
    mode: str   # "off" | "jitter" | "guardian"

@app.post("/config/diagnostic_mode")
async def set_diagnostic_mode(payload: DiagModePayload):
    if _controller:
        _controller.set_diagnostic_mode(payload.mode)
    return JSONResponse({"mode": payload.mode})
```

### 2F. `logger.py` — telemetria estesa + record azione→esito (formato "v2.5-ready")

Tre stream, progettati per essere già il dataset della futura v2.5 (auto-valutazione soglie)
**senza dover cambiare formato**. Ogni record/summary porta **`schema_version`** (intero, parte da
1): la v2.5 potrà estendere il formato restando retrocompatibile coi dati v2.4.

**(1) CSV per-frame** (`session_*.csv`) — serie temporale. `_CSV_FIELDS` (prima di `actions_count`):
`"exposure_ms","jitter_rms","jitter_n","jitter_ref","hfd_ref","lag1_ra","lag1_dec",
"rms_high_active","rms_low_active","diag_state","diag_confidence"`.
(`jitter_ref`/`hfd_ref` + soglie attive permettono di ricostruire offline `jitter_high`/`hfd_high`
con QUALSIASI fattore candidato → sweep di soglie senza ri-loggare.)

**(2) summary.json** — header di sessione (contesto costante). Blocco `context`: `schema_version`,
`agent_version` (da `__about__`), `setup_profile`, `pixel_scale_arcsec`, algoritmi guida RA/DEC,
snapshot di `[diagnostic_engine]` (mode + tutti i fattori/soglie), `baseline_rms_median`. Più
`diagnostic_engine.state_counts` e `guardian_counts`.

**(3) `experimental_<session_id>.jsonl`** — un record per AZIONE (jitter / micro guardian) e per
ogni INTERVENTO guardian BLOCK/ATTENUATE (i CONFIRM non si loggano: bastano i contatori). Schema
auto-descrittivo:
```json
{
  "schema_version": 1,
  "ts_utc": "2026-06-08T22:15:03Z",
  "mode": "guardian",
  "event": "action" | "guardian_block" | "guardian_attenuate",
  "action_kind": "engine" | "micro" | "block" | "attenuate",
  "diagnosis": {"state":"OVERCORRECTION","confidence":84,
                "evidence_bools":{"jitter_high":true,"hfd_high":false,"oscillation":true,"drift":false}},
  "metrics_at_decision": {"rms_total":..,"rms_ra":..,"rms_dec":..,"hfd":..,"hfd_ref":..,
                          "jitter":..,"jitter_ref":..,"lag1_ra":..,"lag1_dec":..,
                          "trend_ra":..,"trend_dec":..,"spike_score":..,"snr":..,"exposure_ms":..},
  "thresholds_active": {"rms_high":..,"rms_low":..,"jitter_high_factor":1.6,"hfd_high_factor":1.25,
                        "lag1_oscillation_thresh":-0.35,"trend_drift_min":0.05,
                        "guardian_min_confidence":60,"act_min_confidence":60},
  "lever_changes": [{"axis":"ra","param":"aggression","old":0.70,"new":0.65}],
  "v23_proposed": {"axis":"ra","param":"aggression","old":0.70,"new":0.75},
  "outcome": {"window_frames":15,"elapsed_s":31.2,
              "pre": {"rms_total":..,"jitter":..,"spike_score":..},
              "post":{"rms_total":..,"jitter":..,"spike_score":..},
              "post_max":{"rms_total":..,"jitter":..},
              "delta":{"rms_total":..,"jitter":..,"spike_score":..}}
}
```
- **NON duplicare** la traiettoria frame-per-frame nel jsonl: è già nel CSV; per ricostruirla basta
  un join su `session_id` + finestra temporale (`ts_utc` … `ts_utc + elapsed_s`).
- Per i record `guardian_block`/`guardian_attenuate`, `v23_proposed` riporta la mossa che la v2.3
  voleva fare e `lever_changes` è `[]` (block) o la mossa ridotta (attenuate); l'`outcome` misura
  comunque la finestra successiva → la v2.5 può valutare se bloccare/attenuare è stata la scelta giusta.
- `session_id`/path forniti dal SessionLogger (es. `experimental_path()`).

> Questo formato basta alla v2.5 per: success-rate per stato (segno/entità di `delta`), **sweep di
> soglie** (rigioca la classificazione su `metrics_at_decision` con fattori diversi), breakdown
> per `setup_profile`, e valutazione degli interventi guardian. Niente cambi di formato previsti:
> se la v2.5 aggiunge campi, lo fa via `schema_version`.

### 2G. `config.toml`
```toml
[diagnostic_engine]
# §31 (Agente v2.4) — Seeing Diagnostic Engine. Diagnosi causale del regime
# (SEEING / OVERCORRECTION / DRIFT / NOMINAL) da jitter + lag-1 + RMS + HFD + trend.
enabled                   = false   # DEFAULT spento = comportamento identico alla v2.3
# "jitter"   = controllo causale completo: il motore è UNICA AUTORITÀ su Aggr/MinMove (CASO 1/2/3 sospesi) — ricerca
# "guardian" = assistito: la v2.3 pilota; il motore conferma/attenua/blocca le mosse v2.3 e fa
#              micro-correzioni proprie ad ampiezza ridotta solo quando la v2.3 è ferma — distribuibile
mode                      = "guardian"
# --- soglie diagnosi (relative alle reference EMA, robuste multi-setup) ---
min_frames                = 30
jitter_high_factor        = 1.6
hfd_high_factor           = 1.25
lag1_oscillation_thresh   = -0.35
trend_drift_min           = 0.05
ema_alpha                 = 0.1
# --- azione ---
act_min_confidence        = 60
outcome_window_frames     = 15
warmup_frames_after_switch = 10
# --- guardian ---
guardian_min_confidence   = 60      # sotto questa confidence il review CONFERMA sempre (fail-safe)
guardian_attenuate_factor = 0.5     # ampiezza ridotta quando il review ATTENUA una mossa v2.3
guardian_action_factor    = 0.4     # ampiezza delle micro-correzioni proprie di guardian (frazione degli step)
# --- UI ---
# false (flotta) = la dashboard può solo spegnere (OFF -> v2.3 puro); true (setup di Alessandro) =
# la dashboard può anche attivare/commutare jitter/guardian (con conferma).
allow_dashboard_mode_switch = false
```

### 2H. Dashboard — card "Seeing Diagnostic Engine"
Legge `controller.diagnostic_engine`. **Gerarchia voluta: prima la diagnosi in linguaggio
astrofotografico, poi l'azione/esito, e SOLO in fondo (dettaglio tecnico) i numeri.** Il tester
deve poter confrontare a colpo d'occhio ciò che vede sul cielo/grafico PHD2 con la diagnosi, senza
leggere lag-1 o jitter.

**1) HERO — Diagnosi corrente (elemento dominante della card)**:
- `label` in **grande**, colorato per stato: GUIDA STABILE (verde) / SEEING DEGRADATO (ambra) /
  SOVRA-CORREZIONE (arancio) / DERIVA SISTEMATICA (viola) / QUADRO INCERTO (grigio) /
  DATI INSUFFICIENTI (grigio chiaro).
- **Confidence** accanto come badge secondario (con nota "provvisoria — non calibrata").
- `suggestion` come **sottotitolo** in linguaggio naturale (1 riga).
- **EVIDENZE** (`evidence`): subito sotto la diagnosi, la lista di fattori in linguaggio umano con
  ✓/◦ (es. "✓ HFD sopra riferimento · ✓ Jitter sopra riferimento · ✓ Lag-1 non oscillante").
  Spiega il *perché* della diagnosi **senza numeri** — è ciò che il tester confronta col cielo/grafico.

**2) Azione & esito (in evidenza — è ciò che valida il motore)**:
- Cosa sta facendo il motore (azione applicata / "nessuna azione"); in guardian indicare se è una
  micro-correzione o un intervento di review (CONFIRM/ATTENUATE/BLOCK) con il motivo.
- **Esito ultima azione** (`last_outcome`): leve prima→dopo + Δ RMS / Δ jitter / Δ spike (pre→post).

**3) Dettaglio tecnico (in fondo, font piccolo, sezione collassabile "Dettaglio tecnico ▸")** —
non è il focus: il *perché* è già dato a parole dalle EVIDENZE; qui ci sono i numeri esatti dietro
di esse, per chi li vuole. Dal blocco `metrics`:
- RMS, HFD (+hfd_ref), Jitter (+jitter_ref), Lag1 RA/DEC, Trend; contatori guardian
  (`guardian_counts`: CONFIRM / ATTENUATE / BLOCK / micro).

**4) Controlli (riga in basso)** — **Badge modalità** read-only (OFF / JITTER — controllo causale
completo / GUARDIAN — assistito) e **Switcher OFF / GUARDIAN / JITTER**:
- **OFF** sempre attivo (kill switch, nessuna conferma): `POST /config/diagnostic_mode {mode:"off"}`.
- **GUARDIAN / JITTER** abilitati solo se `allow_dashboard_mode_switch==true`, con **conferma JS**
  (es. `confirm("Attivare JITTER? Il motore diventa unica autorità sulle leve.")`).

La leggibilità della **diagnosi** (punti 1-2) ha priorità visiva sui numeri (punto 3): font più
grande, colore, posizione in alto.

---

## TEST ATTESI

### Sanity simulator
```bash
python main.py --simulator --dry-run
```
Con `[diagnostic_engine] enabled=false` (default): nessun blocco diagnostic_engine attivo, v2.3
invariata. Con `enabled=true` temporaneo: `/status` ritorna il blocco; in guardian nessuna azione
finché refs non pronte.

### Test unitari (`tests/test_diagnostic_engine.py`) — unittest + MagicMock
1. Jitter calcolato da deque noto.
2. lag-1 alternato < -0.8; monotòno > 0.
3. SEEING → state + proposal (aggr↓/minmove↑). 4. OVERCORRECTION → proposal (aggr↓).
5. DRIFT → proposal None. 6. NOMINAL aggiorna ref; rms≤mediana → no proposal; rms>mediana → proposal gentile.
7. INSUFFICIENT_DATA → no azione.
8. **enabled=false** (default): motore non istanziato → nessun blocco diagnostic in get_status (o `{enabled:false}`); `set_algo_param` non chiamato dal motore; v2.3 invariata.
9. **jitter agisce**: mode jitter, SEEING, refs+confidence → `_apply` su RA/DEC; CASO 1/2/3 di `_evaluate_axis` ritornano `[]`.
10. **bounds**: nessuna mossa fuori `aggr_min/max`, `minmove_min/max` (jitter e guardian micro).
11. **cold-start gate**: refs non pronte / confidence<soglia → nessuna azione.
12. **guardian review BLOCK su DRIFT** (CASO1) e **su OVERCORRECTION** (CASO3 aggr↑): mossa v2.3 non applicata, evento `axis="guardian"`.
13. **guardian review ATTENUATE**: CASO1 + OVERCORRECTION su MinMove → `_apply` con valore attenuato.
14. **guardian review fail-safe**: UNCERTAIN o confidence bassa → CONFIRM (v2.3 applicato invariato).
15. **guardian micro SOLO se v2.3 ferma**: con CASO scattato sull'asse → nessuna micro; con asse fermo + OVERCORRECTION confidente → micro applicata con ampiezza ≈ `guardian_action_factor`×step.
16. **guardian DRIFT** → nessuna micro.
17. **set_diagnostic_mode("off")** sempre accettato → enabled=false + transizione pulita; **("jitter")** rifiutato se `allow_dashboard_mode_switch=False`, accettato se True (+ transizione).
18. **last_outcome / engine.reset**: outcome completato → delta pre→post; `engine.reset()` azzera ref.
19. **retrocompat**: TOML senza sezione → default (enabled=false, mode="guardian"); `mode` ignoto → "guardian".

### Test esistenti
`test_get_status.py`: il blocco `diagnostic_engine` è presente anche a motore spento (forma
`{enabled:false,...}`) — aggiornare gli attesi. `python -m pytest tests/ -v` verde.

---

## VALIDAZIONE SUL CAMPO
- **OFF (default)**: comportamento identico v2.3.
- **jitter** (Alessandro): analisi finestre outcome (pre/post) negli episodi **DRIFT/OVERCORRECTION** (NON l'RMS medio aggregato).
- **guardian** (distribuibile): verificare nei log `axis="guardian"` i BLOCK/ATTENUATE (motivi
  DRIFT/OVERCORRECTION), le micro-correzioni nei buchi, e il fail-safe nei dubbi. Candidata a default flotta in v2.5.
- **Tuning**: SEEING spuri → ↑`jitter_high_factor`/`hfd_high_factor`; OVERCORRECTION non rilevata →
  ↑(meno negativo) `lag1_oscillation_thresh`; DRIFT frequente → ↑`trend_drift_min`; guardian troppo/poco
  attivo → `guardian_min_confidence` / `guardian_action_factor`.

---

## PROCEDURA REBUILD
1. `python build_dist.py` (copia automatica config/Avvia/Sblocca/dashboard).
2. Verificare `[diagnostic_engine]` in `Pacchetto_Distribuzione/config.toml`.
3. Ripristinare `LEGGIMI_PER_AVVIARE.txt` se sovrascritto.
4. Ricreare ZIP:
   ```powershell
   Remove-Item PHD2_Agent_Distribuzione.zip -ErrorAction SilentlyContinue
   [System.IO.Compression.ZipFile]::CreateFromDirectory(
       (Resolve-Path "Pacchetto_Distribuzione").Path,
       (Join-Path (Get-Location) "PHD2_Agent_Distribuzione.zip"))
   ```
5. Bump `phd2_agent/__about__.py`: v2.3 → **v2.4**.

---

## AGGIORNAMENTO DOCUMENTAZIONE

### `CONTESTO_PROGETTO.md`
Aggiornare data e titolo "(§31 — Agente v2.4)". Prima di "Cosa NON è stato ancora fatto":
```markdown
### Seeing Diagnostic Engine (jitter + lag-1) — modalità JITTER e GUARDIAN (§31) — IMPLEMENTATA (2026-06-08) — Agente v2.4
Nuovo modulo `phd2_agent/diagnostic_engine.py`. L'analyzer calcola jitter RMS frame-to-frame e
autocorrelazione lag-1 (RA/DEC). Il motore combina RMS+HFD+jitter+lag1+trend per classificare il
regime (SEEING / OVERCORRECTION / DRIFT / NOMINAL), con soglie relative a reference EMA (azzerate al
cambio esposizione). Due modalità (la vecchia "shadow" è stata eliminata): `jitter` (motore unica
autorità su Aggr/MinMove, CASO 1/2/3 sospesi — ricerca, logging azione→esito pre/post in
`experimental_*.jsonl`) e `guardian` (la v2.3 pilota; il motore conferma/attenua/blocca le sue mosse
e fa micro-correzioni proprie ad ampiezza ridotta — `guardian_action_factor` — solo quando la v2.3 è
ferma sull'asse; fail-safe; distribuibile). `enabled=false` di default = comportamento identico alla
v2.3. DRIFT non genera azioni; NOMINAL ottimizza solo sopra mediana baseline (§30). Il motore non
tocca mai esposizione (§19)/backlash; non accede a `self.client`. Dashboard: switcher OFF/GUARDIAN/
JITTER (OFF sempre, attivazione gated da `allow_dashboard_mode_switch` + conferma). Vedi NOTE_CLAUDE.md §31.
```
In "Cosa NON è stato ancora fatto":
```
- Validazione §31: jitter su RC8+CEM70G/Askar+AM5 (esiti negli episodi DRIFT/OVERCORRECTION);
  guardian su flotta (review sensati, micro-correzioni nei buchi, fail-safe). Tarare le soglie e
  i fattori guardian. Decidere in v2.5 se guardian diventa default flotta (enabled=true).
```

### `NOTE_CLAUDE.md` — nuova sezione **§31**
Struttura: Motivazione (superare il solo-RMS; jitter=velocità, lag-1=struttura, HFD=degrado; due
usi jitter/guardian; shadow e ab_alternate scartate); Architettura (file modificati: analyzer,
diagnostic_engine, controller, config, logger, server, dashboard, __about__); Comportamento
(enabled=false=v2.3; jitter unica autorità con CASO sospesi; guardian review + micro-correzioni nei
buchi, fail-safe; esposizione §19 sempre v2.3); Limiti (jitter residuo loop chiuso; soglie/confidence
provvisorie; dipendenza esposizione mitigata; OSCILLATING/trend non modificato; guardian è assistente
attivo gentile, non solo rete passiva); Validazione (jitter outcome su DRIFT/OVERCORRECTION; guardian
review+micro+fail-safe; v2.5 = eventuale guardian default flotta + baseline jitter per-esposizione +
riconciliazione con OSCILLATING/§30).

---

## CHECKLIST FINALE PRIMA DI COMMIT
- [ ] Pre-flight §0 eseguito (campi GuideStep, `_apply`, punti `analyzer.reset()`)
- [ ] analyzer: jitter/lag-1 + `_lag1_autocorr`; campi snapshot con default
- [ ] diagnostic_engine.py: classify + review + micro_proposal; **nessun `self.client`**; reference EMA + reset
- [ ] `enabled=false` default → motore NON istanziato → v2.3 pura (nessun percorso d'azione)
- [ ] `_engine_owns_levers()` (jitter) → CASO 1/2/3 sospesi; intatti in guardian
- [ ] `_apply_with_guardian` ai punti `_apply` dei CASO 1/2/3; CONFIRM/ATTENUATE/BLOCK; `current_*` solo se applicato
- [ ] review: BLOCK CASO1/DRIFT e CASO3-aggr↑/OVERCORRECTION; ATTENUATE MinMove↑ in OVERCORRECTION; fail-safe CONFIRM
- [ ] guardian micro-correzione SOLO se v2.3 ferma sull'asse; ampiezza ×`guardian_action_factor`; DRIFT escluso; cold-start; outcome-logged
- [ ] jitter: `_apply` + `[limits]` pieni + cooldown; DRIFT no-action; NOMINAL gated §30; clamp rispettati
- [ ] outcome logging pre/post (jitter + micro guardian) in `experimental_*.jsonl`; `last_outcome` in get_status
- [ ] config.py: `DiagnosticEngineConfig` (mode {jitter,guardian}, enabled=false default, fattori guardian) + parsing + validazione mode
- [ ] config.toml: `[diagnostic_engine]` (enabled=false, mode="guardian")
- [ ] logger.py: CSV (incl. `jitter_ref`,`hfd_ref`,`rms_high_active`,`rms_low_active`) + summary `context`+counts + `experimental_*.jsonl` "v2.5-ready" con `schema_version`, `metrics_at_decision`(grezzi+ref), `thresholds_active`, `v23_proposed`, `outcome` pre/post/post_max/delta
- [ ] server.py: `POST /config/diagnostic_mode` ("off"/"jitter"/"guardian"); OFF sempre; attivazione gated + conferma
- [ ] `set_diagnostic_mode`/`_apply_mode_transition`: OFF sempre permesso; attivazione gated; transizione pulita (baseline+reset+warmup)
- [ ] dashboard: **diagnosi (`label`) in primo piano** (grande, colorata) + suggestion sottotitolo; azione/esito in evidenza; metriche (HFD/jitter/lag1/trend) in dettaglio tecnico secondario/collassabile; switcher OFF/GUARDIAN/JITTER
- [ ] `get_state()` espone `label` (mappa state→etichetta IT) coerente con i log
- [ ] `get_state()` espone `evidence` (lista fattori umani ✓/◦ da `_build_evidence`, derivata dai booleani di `classify`, zero nuovo calcolo); blocco numerico rinominato `metrics`; dashboard mostra EVIDENZE sotto la diagnosi
- [ ] __about__.py: v2.3 → v2.4
- [ ] tests/test_diagnostic_engine.py: 19 casi; test_get_status.py aggiornato; `pytest` verde
- [ ] build_dist + ZIP; config.toml in Pacchetto_Distribuzione aggiornato
- [ ] CONTESTO_PROGETTO.md (§31 + "non fatto") e NOTE_CLAUDE.md §31 aggiornati
- [ ] Nessuna modifica a backlash/esposizione §19/star-lost/saturazione/baseline; motore mai su esposizione

---

## DOMANDE DA FARMI PRIMA DI PROCEDERE (se servono)
Se trovi: firma di `_apply` diversa, `session_id` non ovvio da ricavare nel controller, o ambiguità
su come intercettare i punti `_apply` dei CASO 1/2/3 per il review/micro guardian → **fermati e
chiedi**. Procedi step-by-step, mostrami i diff prima di applicarli, poi rebuild e doc. Grazie.
