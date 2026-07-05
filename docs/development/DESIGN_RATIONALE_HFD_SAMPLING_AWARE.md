# Design rationale — §31 Seeing Diagnostic Engine *sampling-aware* (proposta v2.5)

**Stato:** progettazione teorica. NESSUNA modifica al codice. La calibrazione numerica è rimandata alla fase di validazione sui log multi-setup.
**Autore analisi:** Cowork, per Alessandro Curci — 2026-06-11.
**Base:** §31 (NOTE_CLAUDE.md) — Agente v2.4. La feature, una volta implementata, sarà la **§32**.

---

## 0. Tesi in una riga

L'informatività dell'HFD come discriminante del *seeing* **non è costante tra setup**: degrada al crescere della pixel scale di guida. Il modello §31 la tratta come costante (gate booleano `hfd_high` con fattore fisso 1,25), e questo rende il motore strutturalmente cieco al seeing a campionamento grosso. La proposta introduce un **peso di informatività dell'HFD** `w ∈ [0,1]` funzione della pixel scale (prior, noto da PHD2 all'avvio) e della reattività misurata dell'HFD (raffinamento empirico).

Questo non nasce dai log: nasce dall'ottica, dalla teoria del campionamento e dalla natura della misura HFD. I log serviranno a **calibrare**, non a **scoprire**, il fenomeno.

---

## 1. Base fisica e matematica

### 1.1 Modello della misura

La dimensione stellare misurata (HFD), in unità coerenti, è la combinazione in quadratura di kernel di allargamento indipendenti:

```
H_meas² ≈ H_atm² + H_opt² + H_pix²(s)
```

- `H_atm` — componente atmosferica (il **segnale** che vogliamo; varia frame-to-frame col seeing);
- `H_opt` — ottica + montatura + tracking (≈ costante entro una sessione);
- `H_pix(s)` — **floor di campionamento/detector**, crescente con la pixel scale di guida `s`. Per una stella sottocampionata la PSF misurata è dominata dalla risposta del pixel: `H_pix ≈ c·s`, con `c ~ O(0,5–1)` da calibrare.

### 1.2 Guadagno di trasferimento

La sensibilità dell'HFD misurato a una variazione di seeing reale è:

```
g(s) = ∂H_meas/∂H_atm = H_atm / H_meas = H_atm / √(H_atm² + H_opt² + H_pix²(s))
```

- **Campionamento fine** (`s` piccolo → `H_pix → 0`): `g → 1`. Il seeing si trasferisce quasi per intero nell'HFD.
- **Campionamento grosso** (`s` grande → `H_pix` domina): `g → 0`. Il seeing **non** si trasferisce.

### 1.3 Effetto sul gate (perché 1,25 diventa irraggiungibile)

Il gate §31 confronta il rapporto `R = H_meas / H_ref` con `τ = hfd_high_factor = 1,25`. Per un'escursione di seeing `ΔH_atm`:

```
ΔR ≈ g(s) · ΔH_atm / H_ref
```

doppiamente compresso, perché anche `H_ref` è gonfiato dal floor costante (`H_opt`, `H_pix`). Quindi il **massimo R raggiungibile** durante un vero evento di seeing **decresce con `s`**: sopra una certa scala `s*`, la soglia fissa 1,25 non è più raggiungibile → SEEING mai diagnosticato.

### 1.4 Il rumore esclude la strada delle "soglie adattive"

L'errore di misura dell'HFD è ≈ costante **in pixel** (`σ_px`, da fit/centroide sub-pixel, funzione dell'SNR). A campionamento grosso la variazione-seeing in pixel può essere ≲ `σ_px`: l'**SNR della misura HFD-seeing crolla**. Conseguenza progettuale decisiva: **abbassare la soglia `τ` a campionamento grosso farebbe scattare il gate sul rumore** (falsi SEEING). Per questo la prima delle quattro opzioni di Alessandro — soglie HFD adattive — è la più fragile e va scartata.

### 1.5 Nota di rigore (correzione a una spiegazione diffusa)

È falso che "a campionamento grosso la variazione fisica del seeing diventa più piccola": è **identica** (es. 0,8 px × 0,50″/px = 0,40″ = 0,16 px × 2,5″/px). Ciò che cambia è (a) il **guadagno di trasferimento** `g(s)` della misura e (b) l'**SNR** della misura. Il segnale fisico c'è sempre; è lo strumento che, a scala grossa, non lo trasduce.

### 1.6 Le pixel scale di guida reali di Alessandro

| Setup (OAG) | Camera guida | Pixel scale guida |
|---|---|---|
| Askar 71F @490 mm | ASI120MM Mini 3,75 µm¹ | **1,58″/px** nativo · 2,11″/px ridotto |
| Tecnosky 115 @800 mm | ASI220MM Mini 4,0 µm | 1,03″/px nativo · **1,29″/px** ridotto |
| RC8 @1624 mm | ASI220MM Mini 4,0 µm | **0,51″/px** nativo · 0,68″/px ridotto |

Span ~4× (0,51″ → 2,11″/px): è esattamente l'asse lungo cui calibrare `w(s)`.
¹ *Da verificare:* Alessandro ha indicato l'ASI220MM Mini sull'Askar per la notte analizzata (→ ~1,68″/px). Il riferimento progetto associa l'Askar all'ASI120MM Mini (→ 1,58″/px). Ininfluente sul modello (continuo in `s`), ma va fissato per la calibrazione.

---

## 2. Architettura proposta

### 2.1 Il peso di informatività `w`

`w ∈ [0,1]`: 1 = HFD pienamente affidabile (ben campionato), 0 = HFD non informativo.

**Prior da pixel scale** (noto all'avvio da PHD2, già in `cfg.setup.guide_pixel_scale_arcsec`):

```
w_prior(s) = 1 / (1 + exp((s − s*) / k_w))     # logistica decrescente
```

con punto di flesso `s* ≈ 1,0–1,2″/px` e morbidezza `k_w` (da calibrare). `w_prior ≈ 1` a 0,5″/px (RC8), `≈ 0` a 2″/px (Askar ridotto).

**Raffinamento empirico** (misurato in NOMINAL durante il warmup): dispersione robusta di `H_meas/H_ref` (es. CoV) o suo SNR rispetto al rumore HFD per-frame. Se l'HFD **di fatto non si muove** (CoV basso), `w` scende a prescindere da `s`. Combinazione: `w = min(w_prior(s), w_measured)` (o prior bayesiano aggiornato dalla misura).

**Perché è la soluzione più elegante:** auto-calibrante, assorbe in un colpo *tutti* i confondenti — pixel scale, media temporale dell'esposizione di guida (esposizioni lunghe → HFD piatto → `w` basso), OAG, SNR di stelle deboli, regime di seeing — non solo la focale.

### 2.2 Come `w` entra nel classificatore

**Opzione A — interruttore di regime (passo 1, basso rischio).**
Soglia `w_min`. Se `w ≥ w_min` (campionamento fine): comportamento **identico all'attuale §31** (piena retrocompatibilità). Se `w < w_min` (grosso):
- SEEING = `rms_high AND jitter_high` (l'HFD esce dall'AND);
- nei rami OVERCORRECTION/DRIFT il guard `not hfd_high` viene **disattivato** (a `w` basso `not hfd_high` è quasi sempre vero → non informativo): la discriminazione resta su `oscillation`/`jitter` (OVERCORRECTION) e `trend` (DRIFT);
- confidence del SEEING senza HFD: 2 segnali → ~76 invece di ~94 (riflette correttamente la minore certezza).

**Opzione B — punteggio pesato (target finale).**
Si sostituisce l'AND booleano con un voto a evidenza pesata, dove l'HFD contribuisce con peso `w` continuo e la confidence diventa funzione del punteggio. Niente gradino a `s*`. Più pulito e coerente con l'obiettivo v2.5 di raffinare le metriche di confidence, ma è una riscrittura di `classify()` e del modello di confidence → da fare dopo aver convalidato A.

**Raccomandazione:** A subito (chirurgico, retrocompatibile), evoluzione verso B.

### 2.3 Companion change necessario: disaccoppiare `refs_ready`

Oggi `refs_ready = (_jitter_ref is not None AND _hfd_ref is not None)` (diagnostic_engine.py L150-153) e `jitter_high`/`hfd_high` sono entrambi forzati `False` se `refs_ready` è falso. Se demoto l'HFD ma lascio `refs_ready` accoppiato, la demozione è inefficace (la mancanza di `hfd_ref` blocca comunque tutto). **`refs_ready` deve richiedere sempre `jitter_ref`, e `hfd_ref` solo quando `w ≥ w_min`.** L'EMA di `hfd_ref` continua comunque ad aggiornarsi (serve a telemetria e a `w_measured`).

---

## 3. Impatto sull'attuale §31 (mappa esatta del codice)

Tutto l'intervento logico è confinato in `phd2_agent/diagnostic_engine.py`. Punti:

| Punto | File:riga | Cosa cambia |
|---|---|---|
| Costruttore motore | `diagnostic_engine.py` L117-122 | aggiungere `pixel_scale_provider: Callable[[], float]` (specchio di `thresholds_provider`/`baseline_provider`) |
| Derivazione `hfd_high` | L214-215 | invariata nel calcolo, ma il suo **uso** diventa condizionato a `w` |
| Test SEEING (AND a 3) | **L222** | `rms_high AND jitter_high AND (hfd_high OR w<w_min-bypass)` → vedi Opzione A |
| Guard OVERCORRECTION | **L230** (`oscillation and not hfd_high`) | a `w` basso togliere il `not hfd_high` |
| Guard DRIFT | **L238** (`drift and not hfd_high`) | idem |
| Confidence | L225/233/241 | `signals` ridotto di 1 nel SEEING senza HFD |
| `refs_ready` | L150-153 | disaccoppiare HFD (vedi §2.3) |
| EMA `hfd_ref` | L199 | invariata (continua a tracciare) |
| `_build_evidence` | L289-323 | aggiungere evidenza esplicita: "HFD non informativo a questa scala (w=…)" → interpretabilità preservata in dashboard |
| Iniezione provider | `controller.py` **L363** `_make_diagnostic_engine()` | passare `lambda: self.cfg.setup.guide_pixel_scale_arcsec` |

**Pixel scale: già disponibile, zero plumbing nuovo.** `cfg.setup.guide_pixel_scale_arcsec` (config.py L37-43) restituisce l'override da PHD2 (`get_pixel_scale()`, settato in `controller._apply_pixel_scale_from_phd2`, L399-430) con fallback TOML. Letta a `classify()` via il nuovo provider.

**Config** (`config.py` `DiagnosticEngineConfig` L168-198 + parsing L357-369): nuove chiavi, con default che **preservano il comportamento attuale** (feature spenta o campionamento fine):
```
hfd_sampling_aware          = true      # master switch della feature
hfd_informative_pixel_scale = 1.0       # s* (flesso della logistica, ″/px)
hfd_weight_softness         = 0.25      # k_w
hfd_weight_min              = 0.5       # w_min sotto cui l'HFD è demosso
hfd_responsiveness_window   = 60        # frame per stimare w_measured (NOMINAL)
hfd_min_cov                 = 0.05      # CoV minimo per ritenere l'HFD reattivo
```

---

## 4. Compatibilità con Guardian e Jitter

**Confine architetturale pulito:** `review()` (L329) e `micro_proposal()` (L373) consumano **lo stato diagnostico** (`self._last.state`) e `_is_confident()`, **non l'HFD**. Quindi tutta la modifica vive in `classify()`/`refs` e i due downstream **ereditano il miglioramento senza modifiche**.

- **Guardian:** ne beneficia. Oggi a campionamento grosso il SEEING non scatta mai → la review e le micro-correzioni per il SEEING sono di fatto morte. Con la feature, il SEEING torna raggiungibile da `rms+jitter` → Guardian riprende a confermare/attenuare/micro-correggere il seeing. Il fail-safe (CONFIRM quando non confidente) resta. Verifica chiave: il SEEING senza HFD ha confidence ~76 ≥ `guardian_min_confidence` (60) → Guardian **agisce** (corretto: è meno certo ma sopra soglia). Se Alessandro vorrà più cautela a scala grossa, la confidence più bassa è già il segnale giusto.
- **Jitter:** la proposta del SEEING (`aggr −1, minmove +1`) è invariata; la modalità jitter la applica come prima. Nessun impatto.

---

## 5. Compatibilità con i log già prodotti

- **Log v2.4 esistenti:** il CSV logga già per-frame `hfd_avg`, `hfd_ref` e le **soglie attive** (logger.py `_CSV_FIELDS`), proprio per "ricostruire offline `jitter_high`/`hfd_high` con qualsiasi fattore candidato"; la pixel scale è nello stato/header (`controller` L1975-1977, L2054). Poiché `s` è **costante per sessione**, i log già prodotti sono **retro-calibrabili**: si può rigiocare offline una notte, calcolare `w(s)` e verificare cosa avrebbe deciso il classificatore sampling-aware **senza ri-osservare**. La prima notte Askar (≈1,6″/px) è il caso di test ideale (predizione: `w` basso → HFD demosso → SEEING raggiungibile da rms+jitter → verificare se sarebbero comparse diagnosi dove §31 è rimasto cieco).
- **Log nuovi:** aggiungere i campi `guide_pixel_scale`, `hfd_weight` (ed eventuale `hfd_cov`) per-frame e portare `schema_version` 1 → **2**. Modifica **additiva e retrocompatibile**: i parser dei log v2.4 continuano a funzionare; i log v2.5 abilitano la validazione diretta.

---

## 6. Interazione con la fragilità nota (reset EMA su esposizione)

La validazione notte #1 ha mostrato anche il reset di `_jitter_ref`/`_hfd_ref` a ogni cambio esposizione (controller L1491/1512/1583/1620). Con `exposure_dynamic` attivo, reset frequenti → reference mai stabili → `refs_ready` spesso falso → nessuna diagnosi. È **distinto** dal tema campionamento ma vi **interagisce**: il disaccoppiamento di `refs_ready` (§2.3) e il peso `w` riducono il danno (un `hfd_ref` non pronto declassa l'HFD invece di bloccare tutto). Da trattare come punto correlato, non come oggetto primario di questa proposta.

---

## 7. Piano in due fasi

- **Fase 1 — teorica, indipendente dai log (questo documento):** modello `H_meas²=H_atm²+H_opt²+H_pix²(s)`, guadagno `g(s)`, forma di `w(s)` (logistica) + statistica di reattività, architettura A/B, chiavi config, schema telemetria. Fatto ora.
- **Fase 2 — calibrazione empirica (con i log):** sui 4 setup (Askar ~1,58–1,68″ · Tecnosky ridotto ~1,29″ · RC8 ridotto ~0,68″ · RC8 nativo ~0,51″/px), catena di acquisizione invariata: misurare la dinamica/CoV dell'HFD vs `s`, fissare `s*` e `k_w`, validare via replay offline, e solo allora abilitare in campo.

---

## 8. Decisioni aperte (per Alessandro / Code)

1. Camera guida effettiva sull'Askar nella notte analizzata (ASI120 → 1,58″/px vs ASI220 → 1,68″/px)?
2. Punto di flesso `s*` iniziale: 1,0 o 1,2″/px? (la Tecnosky ridotta a 1,29″/px è il caso di confine più interessante)
3. Opzione A (interruttore) come primo passo, o saltare direttamente a B (punteggio pesato)?
4. `w` come `min(prior, measured)` o prior bayesiano aggiornato dalla misura?

---

## 9. Riconciliazione con la revisione di Code (v2 — 2026-06-11)

Code ha verificato questo documento riga per riga sul codice reale (`PROPOSTA_§32_HFD_SAMPLING_AWARE.md`). **Accetto integralmente le sue 7 contestazioni**; due erano errori veri di questo rationale. Versione consolidata:

1. **`refs_ready` NON va disaccoppiato (§2.3 RITIRATO).** Le due reference si formano in modo atomico nello stesso frame NOMINAL (`diagnostic_engine.py` L198-199): lo scenario "manca `hfd_ref` ma c'è `jitter_ref`" non esiste, quindi il disaccoppiamento è un no-op. Il §2.3 era anche internamente incoerente. **Lasciare `refs_ready` invariato** (mantiene Guardian byte-identico). → chiude la decisione aperta #4.
2. **Fix falso-SEEING = `not oscillation` (confermato).** Il SEEING demosso deve essere `rms_high AND jitter_high AND not oscillation`, per ripristinare la mutua esclusività con OVERCORRECTION che prima dava `hfd_high`. Bonus (visto da Code): rende finalmente vera l'evidenza "Lag-1 non oscillante" già scritta in L305. Preferito all'inversione dei rami. → chiude #6.
3. **In Opzione A conta solo `s*`.** Con `w_min=0.5` la soglia di switch è esattamente `s*`; `k_w` è inerte in A (serve solo a B). La calibrazione di A è **un numero**, non tre. (Il §2.1/§3 indicava erroneamente 3 parametri da tarare per A.)
4. **Fase 1 = solo `w_prior(s)`; CoV rinviato.** Il CoV può essere **gonfiato dal rumore** (stelle deboli → falsa reattività → `w` falsamente alto): fallimento asimmetrico. Quindi `w = min(w_prior, w_measured)` con il prior come **tetto fisico** (non bayesiano), e `w_measured` rimandato alla Fase 1b, definito come responsività **normalizzata sul rumore** (non CoV grezzo). → chiude #5.
5. **§32 NON mitiga il reset EMA (§6 CORRETTO).** Il reset azzera entrambe le reference insieme; il classificatore demosso ha comunque bisogno di `jitter_ref`. Sono **ortogonali**: il reset è un work-item separato (riscalare/persistere le reference al cambio dt, o baseline per-esposizione). Il §6 di questo doc affermava il contrario: era sbagliato.
6. **Master switch default `false`** (coerenza con tutte le feature sorelle: opt-in esplicito), non `true` come scrivevo in §3.
7. **Forma di `w(s)`:** la logistica va bene per A (dove la forma è irrilevante). Per la futura B, la forma fisicamente fedele è `w(s)=1/(1+(s/s*)²)` — cioè `w∝g²`, che **discende direttamente** dal modello del §1.2 (rolloff a potenza ~1/s², non esponenziale). Adottarla in B.

**Aggiunta metodologica fondamentale di Code (§A.4/B.9 della proposta):** prima di attribuire al gate HFD la cecità della notte #1, il replay deve **partizionare la causa** frame-per-frame — (a) reference mai pronte (= problema reset EMA, non §32), (b) gate HFD (= ciò che §32 cura), (c) RMS mai sopra soglia (= nessun degrado). §32 è giustificato **solo se (b) è non vuoto**. Questa partizione va eseguita **per prima**, perché potrebbe spostare la priorità sul reset EMA.

**Stato decisioni aperte dopo riconciliazione:** #3 (Opzione A primo passo) ✓ concordato; #4 (refs_ready invariato) ✓ chiuso; #5 (`min` + CoV in 1b) ✓ chiuso; #6 (`not oscillation`) ✓ chiuso. **Restano solo:** #1 (camera Askar — fattuale, da confermare) e #2 (`s*` 1,0 vs 1,2 — lo decidono i log della Tecnosky; lean provvisorio 1,0).

**Documento di riferimento per l'implementazione:** la `PROPOSTA_§32_HFD_SAMPLING_AWARE.md` di Code è ora la base operativa (mappa righe + piano test + checklist). Questo rationale resta la base fisico-teorica.
