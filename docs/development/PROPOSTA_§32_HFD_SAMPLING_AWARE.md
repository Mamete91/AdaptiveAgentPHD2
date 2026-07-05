# PROPOSTA §32 — Seeing Diagnostic Engine *sampling-aware*

**Stato:** progettazione architetturale. **NESSUNA modifica al codice, nessuna compilazione, nessun commit.** Solo documento di proposta.
**Base:** §31 (Seeing Diagnostic Engine, Agente v2.4) — `AdaptiveAgentPHD2\` (copia canonica).
**Input di contesto:** `DESIGN_RATIONALE_HFD_SAMPLING_AWARE.md` (modello fisico + mappa codice + opzioni).
**Compito di questo documento:** verificare il design rationale sul codice reale, **contestarlo dove serve**, e consolidare una proposta con file/funzioni/righe già individuati e piano di test pronto. Calibrazione numerica: fase successiva, sui log.
**Numerazione:** l'ultima sezione di `NOTE_CLAUDE.md` è la **§31** (verificato: `## 31. Seeing Diagnostic Engine …`, L1732). Quando implementata, questa feature sarà la **§32**. Il paragrafo NOTE_CLAUDE/CONTESTO **non** va scritto ora.

---

## 0. Verdetto in tre righe

1. Il nucleo del design rationale **regge**: a campionamento grosso `hfd_high` rende il SEEING **strutturalmente irraggiungibile** (verificato, AND a 3 su L222), e il confine Guardian/Jitter è davvero **stato-only** (verificato).
2. Ma due affermazioni del rationale **non reggono al codice** e vanno corrette: (a) il disaccoppiamento di `refs_ready` **non è necessario** (le reference si formano in modo atomico); (b) §32 **non mitiga** la fragilità del reset EMA (sono ortogonali). Inoltre l'Opzione A senza un guard `not oscillation` introduce una **regressione di falso-SEEING** reale.
3. Raccomandazione: **Opzione A** (interruttore di regime) con guard `not oscillation`, **`w` da solo prior di pixel scale** in Fase 1 (niente CoV ancora), `refs_ready` **lasciato invariato**, telemetria additiva con `schema_version` 1→2. Tutto confinato in `diagnostic_engine.py` + una riga in `controller.py` + chiavi config + colonne CSV.

---

# PARTE A — REVISIONE CRITICA (risposte al §6 del prompt, *prima* della proposta)

## A.1 — Il ragionamento è corretto? (verifica sul sorgente)

### A.1.1 `hfd_high` è condizione OBBLIGATORIA (AND) per il SEEING? → SÌ (confermato)

`diagnostic_engine.py` L222:

```python
if snap.rms_total > rms_high and jitter_high and hfd_high:
    # SEEING
```

`hfd_high` è in **AND**. Ed `hfd_high` (L214-215) è:

```python
hfd_high = (self.refs_ready
            and snap.hfd_avg > self.cfg.hfd_high_factor * self._hfd_ref)   # factor = 1.25
```

A campionamento grosso il guadagno di trasferimento `g(s)→0` (Parte B.1): l'escursione di seeing non gonfia `hfd_avg` oltre `1.25 × hfd_ref`. Quindi `hfd_high` non scatta quasi mai → **SEEING strutturalmente irraggiungibile**. **Confermato.**

### A.1.2 `review()` e `micro_proposal()` dipendono SOLO da stato/confidence, mai dall'HFD? → SÌ (con una precisazione)

- `review()` (L329-362): usa `self._is_confident()` e `self._last.state`. Nessun accesso a `hfd_high`/`hfd_avg`.
- `micro_proposal()` (L373-385): usa `self._is_confident()` e `self._last.state`. Idem.
- `_is_confident()` (L165-173): usa `self.refs_ready`, `r.state`, `r.confidence`, `self.cfg.guardian_min_confidence`.

**Confermato** che il *segnale* HFD (`hfd_high`/`hfd_avg`) non entra mai in `review`/`micro_proposal`. **Precisazione importante:** `_is_confident()` chiama `refs_ready`, che **oggi** richiede `_hfd_ref is not None` (L153). Quindi esiste una dipendenza *transitiva* da **l'esistenza** di `_hfd_ref` (non dal suo valore). Conseguenza progettuale (vedi A.1.3 e B.6): **se NON tocco `refs_ready`, Guardian/Jitter restano byte-identici al §31.** È un argomento a favore del *non* disaccoppiare.

### A.1.3 Il disaccoppiamento di `refs_ready` è *davvero necessario*? → **NO — SMENTITO**

Il design rationale (§2.3) afferma: *"Se demoto l'HFD ma lascio `refs_ready` accoppiato, la demozione è inefficace (la mancanza di `hfd_ref` blocca comunque tutto)."* **Sul codice reale questo non accade.** Le uniche scritture di `_jitter_ref`/`_hfd_ref` sono:

1. `reset()` (L146-148): entrambe → `None`.
2. ramo NOMINAL (L198-199): entrambe aggiornate **nella stessa iterazione** via `_ema`, e `_ema(None, x, α)` adotta `x` al primo campione (L108-110).

Quindi `_jitter_ref` e `_hfd_ref` sono **sempre nello stesso stato** (entrambe `None` o entrambe formate): diventano non-`None` **sullo stesso frame NOMINAL**. Lo scenario "manca `hfd_ref` ma c'è `jitter_ref`" **non esiste**. Perciò:

- `refs_ready` accoppiato **non** blocca `jitter_high` indipendentemente dall'HFD: quando `jitter_ref` è pronta, `hfd_ref` lo è già.
- Il disaccoppiamento, come motivato, **è un no-op comportamentale**.

C'è anche un'**incoerenza interna** nel rationale: dice (i) *"l'EMA di `hfd_ref` continua comunque ad aggiornarsi"* e (ii) *"`refs_ready` deve richiedere `hfd_ref` solo quando w≥w_min, altrimenti la mancanza blocca tutto"*. Ma se (i) è vero, `hfd_ref` non manca mai → (ii) è vacuo.

**Cosa rende effettiva la demozione** (questa è la parte che conta): **togliere `hfd_high` dall'AND del SEEING (L222) e togliere i guard `not hfd_high` da OVERCORRECTION/DRIFT (L230/L238).** Questi tre cambi bastano: `jitter_high` è già calcolabile appena le reference sono pronte. Il disaccoppiamento di `refs_ready` **non** è tra i cambi necessari.

> **Raccomandazione A.1.3:** in Fase 1 **non** disaccoppiare `refs_ready`. Riduce il footprint, elimina il rischio di ripercussioni su `_is_confident()`/Guardian, e mantiene il confine "Guardian eredita senza modifiche" byte-identico. Rivalutare in Fase 2 **solo se** `w_measured` rendesse condizionato l'aggiornamento di `hfd_ref` (allora, e solo allora, il disaccoppiamento diventa necessario).

---

## A.2 — Controindicazioni cercate attivamente

### A.2.1 ⚠️ Falso SEEING da HFD demosso — **REGRESSIONE REALE, confermata sul codice**

È il rischio numero uno e **si concretizza** con l'Opzione A "naïve". Sequenza dei rami nel codice: SEEING è testato a **L222**, OVERCORRECTION a **L230** (dopo). Demuovendo l'HFD senza altri accorgimenti, la SEEING diventerebbe `rms_high AND jitter_high`: un loop che **oscilla** (`lag1 ≤ −0.35`) con `jitter_high` + `rms_high` verrebbe catturato dal ramo SEEING **prima** di arrivare a OVERCORRECTION.

| Frame: oscilla, `jitter_high`, `rms_high`, HFD demosso | §31 attuale | Opzione A *naïve* | Cura applicata |
|---|---|---|---|
| `oscillation=True` | OVERCORRECTION (SEEING fallisce per `hfd_high=False`) ✓ | **SEEING** ✗ | A *naïve*: `aggr−1, minmove+1` (ammorbidisce: **sbagliato**) invece di `aggr−1` |

In §31 il discriminante SEEING-vs-OVERCORRECTION è proprio `hfd_high` (SEEING lo richiede, OVERCORRECTION lo nega): i due rami sono **mutuamente esclusivi su `hfd_high`**. Demuovendo l'HFD si **perde** quel discriminante.

**Fix raccomandato (Fix 1): il SEEING demosso DEVE richiedere `not oscillation`.**

```
SEEING_demosso := rms_total > rms_high  AND  jitter_high  AND  not oscillation
```

Così SEEING e OVERCORRECTION tornano mutuamente esclusivi, stavolta **su `oscillation`** (che sostituisce il ruolo discriminante che aveva `hfd_high`). Cascata demossa completa, mutuamente esclusiva e fisicamente sensata:

```
if rms_total > rms_high AND jitter_high AND not oscillation:   → SEEING          (2 segnali, conf ~76)
elif oscillation:                                              → OVERCORRECTION  (guard not hfd_high rimosso)
elif drift:                                                    → DRIFT           (drift ha già `not jitter_high`, L219)
else:                                                          → UNCERTAIN
```

**Perché Fix 1 e non l'inversione dei rami:**
- L'inversione (testare OVERCORRECTION prima di SEEING) *funzionerebbe* anche a campionamento fine senza rompere la bit-compat — perché lì SEEING e OVERCORRECTION sono già mutuamente esclusivi su `hfd_high`, quindi l'ordine è indifferente. Ma è una modifica **strutturale globale** che obbliga il revisore a ri-dimostrare la mutua esclusività; più fragile.
- Fix 1 è **locale** al solo ramo demosso, esplicito, e **ripristina l'invariante** (mutua esclusività) che `hfd_high` garantiva. Più chirurgico e più leggibile.
- **Bonus:** la stringa di evidenza del SEEING in §31 (`_build_evidence`, L305) afferma già *"✓ Lag-1 non oscillante"* — ma il classificatore §31 **non** verifica mai `not oscillation` nel ramo SEEING. Fix 1 rende quell'evidenza **finalmente vera** (sana una micro-incoerenza latente del §31).

**Rimozione dei guard `not hfd_high` da OVERCORRECTION/DRIFT a campionamento grosso:** a `w` basso `not hfd_high` è quasi sempre vero (≈ no-op), ma rimuoverlo dà un piccolo guadagno di robustezza: protegge da un `hfd_high` **spurio** da rumore (a scala grossa l'HFD è dominato dal floor + rumore; un picco di rumore >1.25×ref non deve poter buttare un'oscillazione reale in UNCERTAIN). Quindi: **rimuovere** i guard nel ramo demosso.

### A.2.2 Effetti su confidence e soglie Guardian → OK (verificato)

- SEEING demosso a 2 segnali: `conf = min(95, 40 + 18·2) = 76` (vs 94 a 3 segnali). Riflette correttamente la minore certezza.
- `guardian_min_confidence = 60` (config.py L192, default). `76 ≥ 60` → **Guardian agisce** (review + micro). `act_min_confidence = 60` (L188) → idem in modalità jitter.
- `_is_confident()` (L173): `76 ≥ 60` → confidente. `micro_proposal()` restituisce `aggr−1, minmove+1`; `review()` opera. **Nessun blocco indesiderato.** La cautela in più a scala grossa è già codificata nella confidence più bassa (76 vs 94): è il segnale giusto, non serve altro.

### A.2.3 Casi limite di `w_measured` (CoV) → argomento per rinviare il CoV alla Fase 2

- **Stelle deboli / SNR basso:** l'errore di centroide `σ_px` cresce → l'HFD diventa **rumoroso** → CoV **alto** → `w_measured` resta **alto** = "HFD reattivo". Ma è rumore, non segnale: il CoV può essere **ingannato** dal rumore e tenere `w` alto quando non dovrebbe.
- **Esposizione di guida lunga:** media temporale → HFD **piatto** → CoV basso → `w_measured` basso → HFD demosso (corretto).

Il fallimento è **asimmetrico**: il CoV può falsamente *alzare* `w` (rumore→reattività apparente), mai falsamente abbassarlo in modo pericoloso. Due conseguenze:

1. **`w = min(w_prior, w_measured)`** è più robusto di un aggiornamento bayesiano (vedi A.3 / decisione aperta #4): il prior da pixel scale è un **tetto fisico** che il rumore non può sfondare. Con `min`, un CoV gonfiato dal rumore non porta mai `w` sopra ciò che il campionamento consente.
2. **Rinviare `w_measured` alla Fase 2** (vedi B.3): la Fase 1 usa **solo** `w_prior(s)`. È deterministico, senza nuovo stato, senza warmup, e — cruciale — **costante per sessione** (s è costante), quindi banalmente rigiocabile offline e a footprint minimo.

---

## A.3 — Opzione A (interruttore) vs B (peso continuo): preferenza sul codice reale

**Preferenza: A subito, evoluzione verso B.** Motivazioni *sul codice*:

- **A** si innesta come *wrapper* attorno ai rami esistenti: `if w >= w_min:` → esegui **il ramo §31 immutato** (L222/L230/L238 intatti); `else:` → esegui il ramo demosso. La bit-compat a campionamento fine è **garantita per costruzione**, perché il percorso fine è letteralmente il codice §31 non toccato. Rischio minimo, test diretti.
- **Scoperta che semplifica A:** con `w_min = 0.5`, l'Opzione A dipende da **un solo** parametro. Risolvendo `w_prior(s) < w_min`:
  `s_switch = s* + k_w · ln((1−w_min)/w_min)` → con `w_min=0.5`, `ln(1)=0` → **`s_switch = s*`**.
  Quindi in A **`k_w` è un parametro morto**: conta solo la soglia `s*` di pixel scale. L'Opzione A è, di fatto, *"usa il classificatore demosso quando `guide_pixel_scale > s*`"*. Calibrazione = **un numero** (`s*`), non tre. (Il rationale elenca `s*`, `k_w`, `w_min` come tutti da tarare per A: in realtà A ne usa **uno**.)
- **B** sostituisce l'AND booleano con un voto a evidenza pesata e una confidence funzione del punteggio: è una **riscrittura di `classify()`** e del modello di confidence. È il target "pulito" (niente gradino a `s*`, coerente con l'obiettivo v2.5 di raffinare la confidence), ma va fatto **dopo** aver convalidato A sui log.

**Cosa serve per evolvere A→B senza rompere la bit-compat a campionamento fine:** vincolo di progetto su B → **a `w=1` il punteggio pesato deve ridursi esattamente all'AND-a-3 del §31 e la confidence a `min(95, 40+18·signals)`**. In pratica: l'HFD entra in B come voto moltiplicato per `w`; soglia del punteggio scelta così che a `w=1` il voto HFD pesi come il booleano `hfd_high` e a `w=0` esca del tutto. Se B rispetta questo limite, `w_prior(s)≈1` su RC8 garantisce continuità col §31. In A questo è gratis (il percorso fine è il codice §31); in B va **dimostrato con un test di equivalenza a `w=1`**.

---

## A.4 — Ipotesi da NON dare per scontata + cosa misurare nel replay

**Ipotesi (plausibile, NON dimostrata):** jitter + lag-1 + RMS "reggono più a lungo" dell'HFD e bastano a diagnosticare il regime al posto suo. **Attenzione:** nella prima notte v2.4 il motore è risultato **CIECO (0 diagnosi)**: non abbiamo prova che quei segnali avrebbero diagnosticato correttamente senza l'HFD.

**Errore da evitare:** assumere che la cecità della notte #1 sia stata causata dal gate HFD. Potrebbe essere stata causata da tutt'altro (reference mai pronte per il reset EMA, oppure RMS mai sopra soglia). **Il replay deve PRIMA partizionare la causa della cecità**, poi — solo nei frame della causa giusta — misurare se §32 avrebbe diagnosticato.

**Partizione obbligatoria (per ogni frame del log Askar ≈1,6″/px), tutto ricostruibile dal CSV (vedi B.7):**

| Causa di cecità | Test sul frame | Implica |
|---|---|---|
| (a) reference non pronte | `jitter_ref == 0 OR hfd_ref == 0` (0.0 = non formata) | §32 **NON aiuta** (anche il demosso ha bisogno di `jitter_ref`) → problema = reset EMA (§9) |
| (b) gate HFD | `rms_total > rms_high_active` **AND** `jitter_high` **AND** `not oscillation` **AND** `not hfd_high` | §32 **rescue**: questi frame diventano SEEING. **METRICA CHIAVE: contali.** |
| (c) RMS mai alto | `rms_total ≤ rms_high_active` su (quasi) tutti i frame | nessun degrado da diagnosticare; né §31 né §32 agiscono (corretto) |

**Grandezze esatte da misurare nel replay (per confermare/smentire l'ipotesi):**
1. **% frame con `refs_ready`** durante la notte. Se è ~0 → la cecità è (a), e §32 **da solo** non l'avrebbe risolta. *Questo va stabilito per primo.*
2. Tra i frame con `refs_ready=True` e `rms_total > rms_high_active`: **quante volte** sarebbero scattati `jitter_high`, `oscillation`, `drift`, e con quale **stato risultante** del classificatore demosso.
3. **Conteggio dei frame di tipo (b)** (il "rescue set"): dove §31 ha dato UNCERTAIN/INSUFFICIENT ma §32 demosso darebbe SEEING/OVERCORRECTION/DRIFT confidente.
4. **Plausibilità fisica** del rescue set: la notte Askar era *davvero* una notte di seeing? Gli stati diagnosticati dal demosso coincidono con la realtà osservata? (Questo non è automatizzabile: richiede il giudizio di Alessandro sui log + ricordo della notte.)

Solo se (1) mostra reference ragionevolmente presenti **e** (3) trova un rescue set non vuoto **e** (4) lo conferma plausibile, l'ipotesi è confermata. Altrimenti la priorità si sposta sul reset EMA (§9), non sul campionamento.

---

# PARTE B — PROPOSTA CONSOLIDATA (deliverable §3 del prompt)

## B.1 — Validazione del modello fisico

**Modello (rationale §1):** `H_meas² ≈ H_atm² + H_opt² + H_pix²(s)`, con `H_pix ≈ c·s`, e guadagno di trasferimento `g(s) = ∂H_meas/∂H_atm = H_atm/H_meas`.

**Verifica:**
- **Somma in quadratura** di kernel di allargamento indipendenti (atmosfera, ottica/tracking, campionamento/detector): standard nell'analisi PSF, corretta come modello al prim'ordine. ✓
- **Calcolo di `g(s)`:** con `H_meas = √(H_atm² + C²)`, `C² = H_opt² + H_pix²`, si ha `∂H_meas/∂H_atm = H_atm/√(H_atm²+C²) = H_atm/H_meas`. **Matematicamente corretto.** ✓ Asintoti: `g→1` (fine, `H_pix→0`), `g→0` (grosso, `H_pix` domina). ✓
- **Conseguenza sul gate** (rationale §1.3): il massimo `R = H_meas/H_ref` raggiungibile in un evento di seeing **decresce con `s`** → sopra una certa `s*` la soglia fissa 1,25 è irraggiungibile. Coerente con A.1.1. ✓
- **Nota di rigore del rationale (§1.5)** — *l'ampiezza fisica del seeing è identica a ogni scala; ciò che cambia è il guadagno di trasferimento e l'SNR della misura* — è **corretta** e importante: esclude la strada delle soglie HFD adattive (abbassare τ a scala grossa farebbe scattare il gate sul rumore). ✓ Concordo nello scartare quell'opzione.

**Obiezioni / raffinamenti (costruttivi):**

1. **Forma di `w_prior(s)`: la logistica è adeguata ma non è la più fedele.** La grandezza fisica è `g(s) = H_atm/√(H_atm²+H_opt²+c²s²)`, il cui rolloff è **a legge di potenza** (`~1/s` per `s` grande), mentre la logistica decade **esponenzialmente** (coda più ripida). Una forma derivata dal guadagno, a parità di **due** parametri, è:

   ```
   w_prior(s) = 1 / (1 + (s/s*)²)        # "transfer-gain-like" (∝ g²), monotona, w(0)=1, w(s*)=0.5
   ```

   Più fedele alla fisica (coda `1/s²`) e con lo stesso costo di taratura della logistica (`s*`, esponente). **Però:** sullo span reale di Alessandro (0,51→2,11″/px, solo ~4×) logistica e forma a potenza sono **calibrazione-equivalenti**; e — punto decisivo — **in Opzione A conta solo il punto di attraversamento `s*`, non la forma** (A.3). Quindi:
   > **Raccomandazione B.1:** mantenere la **logistica** in Fase 1 (familiare, e in A la forma è irrilevante). Riconsiderare la forma a potenza **solo** passando a B, e **solo se** i residui di calibrazione mostrano misfit sistematico agli estremi.

2. **`H_opt` non è perfettamente costante:** include tracking/PE della montatura, che durante l'esposizione di guida **allunga/sfuoca** la stella (contributo variabile a `H_meas`). È un secondo ordine; l'approssimazione "costante entro sessione" è accettabile, ma va ricordata come limite del prior.

3. **L'esposizione di guida è un low-pass temporale separato.** `g(s)` cattura la parte **spaziale/campionamento**; la media temporale dell'esposizione lunga attenua ulteriormente la varianza-seeing che arriva all'HFD. Sono due attenuazioni **moltiplicative distinte**: il prior `w_prior(s)` copre il campionamento, mentre `w_measured` (CoV, Fase 2) assorbe **empiricamente** la parte temporale + tutto il resto. Questo giustifica `w = min(prior, measured)` (B.4 / decisione #4).

**Conclusione B.1:** modello fisico **solido**; la logistica è **adeguata** per A; segnalata una forma alternativa più fedele per l'eventuale B.

## B.2 — Mappa d'impatto definitiva (righe verificate)

Tutto l'intervento **logico** è in `phd2_agent/diagnostic_engine.py`; più un *lambda* in `controller.py`, chiavi in `config.py`, colonne in `logger.py`. **Diff concettuali (NON applicati):**

| # | File : funzione : riga (verificata) | Cambiamento concettuale |
|---|---|---|
| 1 | `diagnostic_engine.py` : `__init__` : **L117-122** | Nuovo parametro **opzionale** `pixel_scale_provider: Optional[Callable[[], float]] = None`. Default `None` ⇒ `w=1.0` ⇒ percorso §31 (retrocompat + i 37 test esistenti che costruiscono con 3 arg restano verdi). |
| 2 | `diagnostic_engine.py` : nuovo `_hfd_weight()` | Helper privato. Fase 1: `if not cfg.hfd_sampling_aware or provider is None: return 1.0; s = provider(); return 1/(1+exp((s−s*)/k_w))`. (Fase 2: `min(quello, w_measured)`.) |
| 3 | `diagnostic_engine.py` : `classify` : **L222** | Wrapper di regime: `if w >= w_min:` → **ramo §31 immutato**; `else:` → `rms_total>rms_high AND jitter_high AND not oscillation` (Fix 1, A.2.1). |
| 4 | `diagnostic_engine.py` : `classify` : **L230** | Nel ramo demosso (`w<w_min`): OVERCORRECTION = `oscillation` (guard `not hfd_high` **rimosso**). Nel ramo fine: invariato. |
| 5 | `diagnostic_engine.py` : `classify` : **L238** | Nel ramo demosso: DRIFT = `drift` (guard `not hfd_high` rimosso; `drift` ha già `not jitter_high`, L219). Ramo fine: invariato. |
| 6 | `diagnostic_engine.py` : `classify` : **L224-225** | Confidence SEEING demosso: `signals = 2` ⇒ `conf = min(95, 40+18·2) = 76`. Ramo fine: `signals=3 ⇒ 94`, invariato. |
| 7 | `diagnostic_engine.py` : `_build_evidence` : **L289-323** | Aggiungere evidenza esplicita nel ramo demosso: `"◦ HFD non informativo a questa scala (w=0.xx)"`. Additivo, preserva l'interpretabilità in dashboard. Per il SEEING demosso l'evidenza "Lag-1 non oscillante" diventa **verificata** (Fix 1). |
| 8 | `diagnostic_engine.py` : `hfd_high` deriv. : **L214-215** | **Invariata** nel calcolo (continua a tracciare per telemetria); cambia solo il suo *uso* (condizionato a `w`). |
| 9 | `diagnostic_engine.py` : EMA `hfd_ref` : **L198-199** | **Invariata** (continua ad aggiornarsi: serve a telemetria e all'eventuale `w_measured`). |
| 10 | `diagnostic_engine.py` : `refs_ready` : **L150-153** | **NON toccare** in Fase 1 (vedi A.1.3: non necessario, e mantiene Guardian byte-identico). |
| 11 | `diagnostic_engine.py` : `get_state` / `metrics` : **L274-283, L417-434** | Esporre `hfd_weight` (e `guide_pixel_scale`) nei metrics/stato per dashboard + CSV. Additivo. |
| 12 | `controller.py` : `_make_diagnostic_engine` : **L366-372** | Aggiungere `pixel_scale_provider=lambda: self.cfg.setup.guide_pixel_scale_arcsec`. **Unica riga d'integrazione.** Pixel scale già disponibile (vedi sotto), zero plumbing nuovo. |

**Pixel scale: già disponibile, nessuna RPC nuova.** `cfg.setup.guide_pixel_scale_arcsec` (config.py **L36-43**, property: `pixel_scale_override` da PHD2 > reduced/native da TOML). L'override è settato da `controller._apply_pixel_scale_from_phd2` (**L399-431**, via `client.get_pixel_scale()`). Il motore la legge **a `classify()`** tramite il nuovo provider. Coerente col confine §31: il motore **non** accede a `self.client`.

**Nota di scope rispettato:** nessun tocco a backlash, esposizione dinamica, CASO 1/2/3 v2.3, `review()`/`micro_proposal()`. L'intervento resta in `classify()`/config/telemetria, esattamente come richiesto.

## B.3 — Opzione A vs B + staging interno della Fase 1

Raccomandazione (vedi A.3): **Opzione A** con Fix 1. Inoltre, **staging interno di A**:

- **Fase 1a — `w = w_prior(s)` soltanto.** `w` costante per sessione (s costante) ⇒ il regime fine/grosso è deciso **una volta** all'avvio ⇒ zero overhead per-frame, ragionamento e replay banali, nessuno stato nuovo. Di fatto un *interruttore per-setup derivato dalla pixel scale*.
- **Fase 1b — aggiungere `w_measured` (CoV) via `min(prior, measured)`.** Introduce una finestra + stima CoV in NOMINAL (stato che si azzera col reset EMA): rinviata finché 1a non è validata. Cattura esposizioni lunghe / OAG / stelle deboli.
- **Fase 2 — Opzione B** (punteggio pesato), col vincolo di equivalenza a `w=1` (A.3).

**Niente config per-setup duplicata:** con un **unico `s*` globale**, ogni setup ricade nel suo regime **automaticamente** in base alla sua `guide_pixel_scale_arcsec` (già nei TOML per-setup). Vantaggio di design: la differenziazione per-setup è gratis, non serve replicare chiavi nei tre TOML.

## B.4 — Chiavi di config nuove (`DiagnosticEngineConfig`)

In `config.py` `DiagnosticEngineConfig` (**L168-197**) + parsing nel blocco §31 (**L357-379**). **Default retrocompatibili** (feature spenta ⇒ identico §31):

```python
# §32 — HFD sampling-aware (default: spento ⇒ comportamento identico §31)
hfd_sampling_aware:          bool  = False   # master switch (vedi nota)
hfd_informative_pixel_scale: float = 1.0     # s* (″/px) — PROVVISORIO, punto di switch in Opzione A
hfd_weight_softness:         float = 0.25    # k_w — PROVVISORIO (inerte in A con w_min=0.5; serve solo a B)
hfd_weight_min:              float = 0.5     # w_min — sotto: HFD demosso
hfd_responsiveness_window:   int   = 60      # frame per w_measured (solo Fase 1b/2)
hfd_min_cov:                 float = 0.05    # CoV minimo "HFD reattivo" (solo Fase 1b/2) — PROVVISORIO
```

Parsing speculare a quello §31 esistente (L363-379), tutti con `de.get(..., default)`.

> **Contestazione del default del master switch.** Il rationale propone `hfd_sampling_aware = true`. **Raccomando `false`.** Motivi: (a) coerenza con **tutte** le feature opzionali del progetto, che nascono `enabled=false` (`diagnostic_engine`, `exposure_dynamic`, `auto_calibration`); (b) la regola di retrocompat "a feature spenta = identico §31" è più robusta con opt-in esplicito; (c) si abilita per-setup dopo la validazione sui log. Flip a `true` di flotta solo a Fase 2 convalidata.

**Valori per i 3 setup (PROVVISORI — DA CALIBRARE, NON inventati):** non servono chiavi per-setup; il regime è derivato dalla pixel scale. Con `s*` provvisorio ∈ [1,0; 1,2] e `w_min=0.5`:

| Setup (OAG) | Pixel scale guida | Regime con `s*=1.0` | Regime con `s*=1.2` |
|---|---|---|---|
| RC8 @1624 mm | 0,51″ nat · 0,68″ rid | **fine** (§31) | **fine** (§31) |
| Tecnosky 115 @800 mm | 1,03″ nat · 1,29″ rid | **grosso** (demosso) | rid: **grosso** · nat: **fine** ← caso di confine |
| Askar 71F @490 mm | 1,58″ nat · 2,11″ rid | **grosso** (demosso) | **grosso** (demosso) |

La **Tecnosky** è il pivot di calibrazione (a cavallo di `s*`): è il setup su cui misurare con più cura la reattività HFD per fissare `s*`. (Le pixel scale provengono dal riferimento progetto; la camera dell'Askar nella notte analizzata — ASI120 1,58″ vs ASI220 1,68″ — è una **decisione aperta**, #1.)

## B.5 — Schema telemetria (additivo, `schema_version` 1→2)

**Campi nuovi:**

1. **CSV** (`logger.py` `_CSV_FIELDS`, **L24-57**): appendere in coda `guide_pixel_scale`, `hfd_weight` (e, Fase 1b, `hfd_cov`). Popolati in `log_snapshot` (L142-173) da `eng.get_state()`/metrics. A motore spento → `0.0` (come gli altri campi §31).
2. **`schema_version` 1→2** in **due** punti: `logger.close()` summary (**L198**) e `controller.diagnostic_summary_context()` (**L2051**).
3. **Header di sessione** (`diagnostic_summary_context`, L2050-2077): aggiungere `hfd_informative_pixel_scale (s*)`, `hfd_weight_min`, `hfd_sampling_aware` accanto agli altri fattori. (La `pixel_scale_arcsec` è **già** presente, L2054.)
4. **Record azione→esito** (`controller._open_outcome`, **L1273-1298**): aggiungere `hfd_weight` e `guide_pixel_scale` in `metrics_at_decision`/`thresholds_active`. Additivo.
5. **Status/dashboard** (`get_status`, blocco `diagnostic_engine`, **L2030-2038**): `hfd_weight` arriva gratis via `get_state()`.

**Dimostrazione di additività / log v2.4 parsabili:**
- Il CSV è scritto con `csv.DictWriter` (header-driven, L81-82). Qualunque lettore **header-aware** (`csv.DictReader`, `pandas.read_csv`) **tollera colonne in coda**: i campi v2.4 restano agli stessi nomi/posizioni logiche.
- `analyze_logs.py` **non** legge questo CSV: opera sui **log nativi di PHD2** via `phd2_log.PHD2LogParser` (verificato: nessun `DictReader`/`open` del session CSV). Quindi è **insensibile** alle nuove colonne. Il replay §32 sarà uno script offline **nuovo**.
- Il `schema_version` nel summary segnala la versione; i lettori del summary v2.4 ignorano chiavi sconosciute (dict JSON).

## B.6 — Compatibilità Guardian / Jitter

**Confine architetturale pulito (verificato, A.1.2):** `review()` (L329) e `micro_proposal()` (L373) consumano **stato** (`self._last.state`) + `_is_confident()`, **non** l'HFD. Tutta la modifica vive in `classify()`/config/telemetria ⇒ i due downstream **ereditano il miglioramento senza modifiche**.

- **Guardian** ne beneficia: oggi a scala grossa il SEEING non scatta mai ⇒ review e micro-correzioni per il SEEING sono di fatto **morte**. Con §32 il SEEING torna raggiungibile da `rms+jitter+not oscillation` ⇒ Guardian riprende a confermare/attenuare/micro-correggere. **Verifica chiave (A.2.2):** SEEING demosso conf **76 ≥ `guardian_min_confidence` 60** ⇒ Guardian **agisce**. Il fail-safe (CONFIRM se non confidente, L340-342) resta.
- **Jitter:** la proposta del SEEING (`aggr −1, minmove +1`, L226) è invariata; la modalità jitter la applica come prima. Nessun impatto.
- **Rafforzamento dal NON toccare `refs_ready`** (A.1.3): poiché `_is_confident()` dipende da `refs_ready`, lasciarlo invariato rende le decisioni Guardian/Jitter **byte-identiche** al §31 a campionamento fine, e a scala grossa cambia **solo** lo `state` prodotto da `classify()` (che è esattamente l'obiettivo). Confine rispettato senza riprogettazione.

## B.7 — Retro-compatibilità dei log / replay offline (deliverable #7)

**Conferma: una notte v2.4 già registrata è rigiocabile offline** per calcolare `w(s)` e la decisione sampling-aware, **senza ri-osservare.** Campi necessari e dove sono:

**Per-frame (CSV `session_<id>.csv`, `_CSV_FIELDS` L24-57):**
- `rms_total`, `rms_high_active`, `rms_low_active` → gate RMS
- `jitter_rms`, `jitter_ref` → `jitter_high` con qualunque `jitter_high_factor` candidato
- `hfd_avg`, `hfd_ref` → `hfd_high` con qualunque `hfd_high_factor` candidato (e CoV per `w_measured`)
- `lag1_ra`, `lag1_dec` → `oscillation`
- `trend_ra`, `trend_dec` → `drift`
- `condition`, `frame_count` → gate NOMINAL/INSUFFICIENT
- `exposure_ms` → segmentare per esposizione (interazione reset, §9)
- `diag_state`, `diag_confidence` → **ciò che §31 ha effettivamente deciso** (verità a terra del confronto)
- *Ricostruzione `refs_ready`:* `jitter_ref>0 AND hfd_ref>0` (0.0 = non formata; jitter/HFD reali non sono mai 0).

**Per-sessione (summary `…summary.json`, `diagnostic_summary_context` L2050-2077):**
- `pixel_scale_arcsec` (L2054) → `s` costante per `w_prior(s)` ✓
- `jitter_high_factor`, `hfd_high_factor`, `lag1_oscillation_thresh`, `trend_drift_min` (L2063-2066) → soglie usate quella notte ✓

⇒ **Tutto il necessario è già loggato in v2.4.** Il replay (script offline nuovo): rilegge il CSV, ricava i booleani con i fattori dell'header, applica la partizione A.4 e il classificatore demosso, e produce il "rescue set". Il commento nel CSV (L41-43) conferma che questo *threshold-sweep offline* era l'intento di progetto del §31.

**Caveat:** la notte cieca **non** ha record `experimental_*.jsonl` (quel file si scrive solo quando il motore **agisce**, L105-114). Quindi il replay **deve** basarsi sul **CSV per-frame** (loggato sempre), non sull'experimental. ✓ Il CSV c'è.

## B.8 — Piano di test unitari (`tests/test_diagnostic_engine.py`)

Aggiornare l'helper `_engine()` (L51-57) con `pixel_scale_provider` **opzionale** (default `None`/fine). Poiché il param costruttore è opzionale, **i 37 test esistenti restano verdi senza modifiche** (3-arg ⇒ `w=1` ⇒ percorso §31). I test d'integrazione controller usano già `guide_pixel_scale_arcsec_native=0.5` (L321) ⇒ percorso fine ⇒ **bit-identici**.

Nuovi casi:

1. **Fine sampling = §31 bit-identico.** `s=0.5`, `hfd_sampling_aware=true`: i casi SEEING/OVERCORRECTION/DRIFT esistenti danno **stesso stato/proposal/confidence** del §31 (SEEING richiede ancora `hfd_high`).
2. **Coarse: SEEING raggiungibile da rms+jitter.** `s=2.0`, `hfd_avg≈hfd_ref` (`hfd_high=False`), `rms_high+jitter_high+not oscillation` ⇒ **SEEING**, `conf==76`. (In §31 sarebbe UNCERTAIN.)
3. **Coarse: guard falso-SEEING (REGRESSIONE).** `s=2.0`, `rms_high+jitter_high` **MA** `lag1=−0.9` (oscillation) ⇒ **OVERCORRECTION, NON SEEING**. (Il test che blinda A.2.1.)
4. **Confidence ridotta.** Coarse SEEING ⇒ `confidence == 76` (`< 94`).
5. **Guardian eredita.** Coarse SEEING (76) ≥ 60 ⇒ `micro_proposal() == LeverProposal(aggr=-1, minmove=+1)`; `review()` opera; `_is_confident()` True.
6. **Master switch off = §31.** `hfd_sampling_aware=false`, `s=2.0` ⇒ SEEING **irraggiungibile** (identico §31), nessun rescue.
7. **`refs_ready` invariato.** Con la scelta "non disaccoppiare", asserire che `refs_ready` ha la **stessa** semantica §31 a fine e a grosso (entrambe le ref richieste). *(Se in futuro si disaccoppia, sostituire con: `jitter_high` calcolabile col solo `jitter_ref`.)*
8. **`w` da prior.** `_hfd_weight()` monotona: `w(0.5)≈1`, `w(2.0)≈0`, `w(s*)=0.5`. Con `hfd_sampling_aware=false` ⇒ `w==1.0` sempre.
9. **(Fase 1b) `w` da CoV basso.** HFD piatto in NOMINAL ⇒ `w_measured` basso ⇒ demosso **anche** a `s` fine. (Solo quando si implementa `w_measured`.)

## B.9 — Interazione col reset EMA su esposizione (deliverable #9) — **correzione al rationale**

**Fatti (verificati):** `engine.reset()` (L142-148) azzera **entrambe** le reference. Chiamato a ogni cambio esposizione in 4 punti (`controller.py` **L1492 / L1513 / L1584 / L1621**) + cambio modalità (L1411). Con `exposure_dynamic` attivo, reset frequenti ⇒ reference spesso non pronte ⇒ `refs_ready=False` ⇒ nessuna diagnosi.

**Contestazione del rationale §6.** Il rationale afferma che il disaccoppiamento di `refs_ready` e il peso `w` *"riducono il danno"* del reset. **Sul codice, NO:**
- Il reset azzera `jitter_ref` **e** `hfd_ref` **insieme**; si riformano **insieme** sullo stesso frame NOMINAL (A.1.3). Non c'è alcun differenziale di tempo di riforma che il disaccoppiamento possa sfruttare.
- Il classificatore demosso ha **comunque** bisogno di `jitter_high` ⇒ di `jitter_ref` ⇒ dopo un reset è cieco finché `jitter_ref` non si riforma, esattamente come §31.
- `w_prior(s)` non dipende dalle reference (è funzione di `s` costante): è calcolabile anche post-reset, ma **non** sblocca `jitter_high`.

⇒ **§32 e la fragilità del reset EMA sono ORTOGONALI. §32 non la mitiga.** Conflonderle rischia di mascherare la causa reale (per questo la partizione A.4 va eseguita **per prima**). Trattare il reset come **work item separato** (fuori dallo scope di questa proposta), con opzioni da valutare a parte, es.:
- riscalare le reference per il rapporto di esposizione invece di azzerarle (l'HFD/jitter scala in modo prevedibile con `dt`), oppure
- decadimento/persistenza delle reference attraverso il cambio esposizione invece dell'azzeramento netto, oppure
- una baseline jitter/HFD **per-esposizione** (già ipotizzata in NOTE_CLAUDE §31 "Validazione → v2.5").

## B.10 — Decisioni aperte (per Alessandro / Code)

1. **Camera guida dell'Askar** nella notte analizzata: ASI120MM Mini (→1,58″/px) o ASI220MM Mini (→1,68″/px)? Ininfluente sul modello (continuo in `s`), ma serve per fissare la calibrazione.
2. **`s*` iniziale: 1,0 o 1,2″/px?** Decide il regime della **Tecnosky** (1,03 nat / 1,29 rid), il pivot.
3. **Master switch default `false` (mia raccomandazione) o `true` (rationale)?** Vedi B.4.
4. **`refs_ready`: lasciare invariato (mia raccomandazione, A.1.3) o disaccoppiare comunque** per forward-compat verso Fase 1b?
5. **`w = min(prior, measured)` (mia raccomandazione, A.2.3) o aggiornamento bayesiano?** E: `w_measured` in Fase 1b o rinviato a Fase 2?
6. **Fix falso-SEEING: `not oscillation` (Fix 1, mia raccomandazione) o inversione dei rami?** Vedi A.2.1.

---

# PARTE C — Checklist

## C.1 — Da fare in fase di IMPLEMENTAZIONE (quando autorizzata) → diventa §32

- [ ] `config.py`: 6 chiavi `hfd_*` in `DiagnosticEngineConfig` (L168-197) + parsing (L357-379), default retrocompatibili, master switch `false`.
- [ ] `diagnostic_engine.py`: param costruttore opzionale `pixel_scale_provider=None` (L117-122); helper `_hfd_weight()` (Fase 1a: solo prior logistico).
- [ ] `diagnostic_engine.py`: wrapper di regime in `classify()` — ramo fine = §31 **immutato** (L222/L230/L238); ramo demosso con **Fix 1** (`not oscillation` nel SEEING; guard `not hfd_high` rimossi da OVER/DRIFT).
- [ ] `diagnostic_engine.py`: confidence SEEING demosso `signals=2`→76; evidenza demossa in `_build_evidence`; `hfd_weight`/`guide_pixel_scale` in metrics/get_state.
- [ ] `diagnostic_engine.py`: **NON** toccare `refs_ready` (L150-153) né l'EMA `hfd_ref` (L198-199).
- [ ] `controller.py`: `pixel_scale_provider=lambda: self.cfg.setup.guide_pixel_scale_arcsec` in `_make_diagnostic_engine` (L366-372). **Unica riga d'integrazione.**
- [ ] `logger.py`: colonne CSV `guide_pixel_scale`/`hfd_weight` (L24-57, L142-173); `schema_version` 1→2 (L198); fattori `s*`/`w_min` nel summary; `schema_version` 1→2 anche in `diagnostic_summary_context` (L2051).
- [ ] `controller.py`: `hfd_weight`/`guide_pixel_scale` in `_open_outcome` (L1273-1298) e blocco `get_status` (L2030-2038).
- [ ] `tests/test_diagnostic_engine.py`: 9 casi B.8 (helper con provider opzionale; verificare i 37 esistenti ancora verdi).
- [ ] `dashboard/`: mostrare `w`/regime e l'evidenza "HFD non informativo a questa scala" (interpretabilità).
- [ ] Documentazione: §32 in `NOTE_CLAUDE.md` (verificare di nuovo `## 31` = ultima) + paragrafo `CONTESTO_PROGETTO.md`. **Solo in implementazione, non ora.**
- [ ] **Non toccare**: backlash, esposizione dinamica, CASO 1/2/3, `review()`/`micro_proposal()`.

## C.2 — Da fare in fase di CALIBRAZIONE (con i log, separata)

- [ ] **Replay/partizione A.4 PER PRIMA** sulla notte cieca Askar: % `refs_ready`, conteggio rescue set (b), esclusione delle cause (a)/(c). *Decide se §32 è la cura giusta o se lo è il reset EMA (§9).*
- [ ] Misurare dinamica/CoV dell'HFD vs `s` sui 4 setup (Askar ~1,58–1,68 · Tecnosky rid ~1,29 · RC8 rid ~0,68 · RC8 nat ~0,51″/px).
- [ ] Fissare **`s*`** (e, solo per B, `k_w`); confermare `w_min`. Verificare il regime della Tecnosky.
- [ ] Validare via replay offline (decisione sampling-aware vs realtà osservata) **prima** di abilitare in campo.
- [ ] Se confermato: abilitare per-setup (grossi prima), poi valutare default di flotta a Fase 2.

---

### Riepilogo delle contestazioni al design rationale (cosa cambia rispetto al documento di partenza)

1. **`refs_ready` NON va disaccoppiato** (non necessario; le reference sono atomiche). — *§A.1.3, B.2, B.9*
2. **Serve il guard `not oscillation` nel SEEING demosso** per evitare la regressione di falso-SEEING (rami SEEING→OVER in quest'ordine). — *§A.2.1*
3. **In Opzione A conta solo `s*`** (`k_w` è morto con `w_min=0.5`): calibrazione = un numero. — *§A.3*
4. **Fase 1 con solo `w_prior(s)`**, CoV rinviato (rumore può ingannare il CoV; `min` come tetto fisico). — *§A.2.3, B.3*
5. **§32 NON mitiga il reset EMA** (ortogonali): trattare il reset come item separato; eseguire la partizione del replay per prima. — *§B.9, A.4*
6. **Master switch default `false`** (coerenza con le feature sorelle), non `true`. — *§B.4*
7. **Forma alternativa di `w(s)`** più fedele alla fisica (`1/(1+(s/s*)²)`) segnalata per l'eventuale Opzione B; logistica adeguata per A. — *§B.1*
