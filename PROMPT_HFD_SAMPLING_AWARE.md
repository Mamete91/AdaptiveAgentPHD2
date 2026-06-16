# PROMPT per Claude Code — §32 (progettazione) Seeing Diagnostic Engine *sampling-aware*

> **Nota operativa.** Questo NON è un prompt di implementazione. È una richiesta di **analisi e progettazione architetturale** sulla §31 (Seeing Diagnostic Engine, Agente v2.4). Relazione con il lavoro precedente: estende la §31; quando verrà implementata diventerà la **§32**. In questa fase **non si tocca codice, non si compila, non si committa**: si produce solo una proposta tecnica scritta. La calibrazione numerica avverrà dopo, sui log multi-setup.
>
> Documento di riferimento già preparato: `DESIGN_RATIONALE_HFD_SAMPLING_AWARE.md` (leggilo come contesto: contiene il modello fisico, la mappa del codice e le opzioni). Il tuo compito è **verificarlo sul codice reale, contestarlo dove serve, e restituire una proposta architetturale consolidata.**

---

## 0. PRE-FLIGHT OBBLIGATORIO (solo lettura, prima di scrivere la proposta)

**File Python da leggere e verificare riga per riga:**

1. `phd2_agent/diagnostic_engine.py` — l'intero motore §31. Conferma i punti chiave:
   - test SEEING come AND a 3 (`rms_total > rms_high and jitter_high and hfd_high`) ~L222;
   - guard `not hfd_high` in OVERCORRECTION (~L230) e DRIFT (~L238);
   - derivazione `hfd_high` (~L214-215) e EMA `hfd_ref` aggiornata solo in NOMINAL (~L199);
   - `refs_ready` accoppia `_jitter_ref` E `_hfd_ref` (~L150-153) e forza `jitter_high`/`hfd_high = False` se non pronte;
   - calcolo confidence `min(95, 40 + 18*signals)` (~L225/233/241);
   - costruttore `__init__(cfg, thresholds_provider, baseline_provider)` (~L117-122);
   - `review()` (~L329), `micro_proposal()` (~L373), `_is_confident()` (~L165-173) consumano SOLO `self._last.state` e la confidence, **non** l'HFD.
2. `phd2_agent/controller.py` — punti d'integrazione: chiamata `classify()` (~L779-781); `_make_diagnostic_engine()` (~L363, punto d'iniezione dei provider); reset EMA su cambio esposizione (~L1491/1512/1583/1620); export pixel scale nello stato (~L1975-1977, ~L2054); record di decisione con campi HFD (~L1256-1293).
3. `phd2_agent/config.py` — `SetupConfig.guide_pixel_scale_arcsec` (property, ~L37-43: override PHD2 con fallback TOML); `DiagnosticEngineConfig` (~L168-198) e relativo parsing (~L357-369).
4. `phd2_agent/logger.py` — `_CSV_FIELDS` (logga già `hfd_avg`, `hfd_ref` e soglie attive) e `schema_version` (~L198) dell'header di sessione.
5. `NOTE_CLAUDE.md` §31 (l'ultima sezione presente; la nuova feature sarà la §32 — verifica con `grep "^## [0-9]" NOTE_CLAUDE.md | tail -1`).

**PHD2 sorgente C++:** NON necessario. La feature **non introduce alcuna chiamata JSON-RPC nuova** (la pixel scale è già disponibile via `get_pixel_scale()` / `cfg.setup.guide_pixel_scale_arcsec`). Non toccare `phd2-master/`.

**Decisione di design da prendere durante l'analisi:** confermare o smentire, sul codice reale, che (a) il confine Guardian/Jitter è davvero "stato-only" (quindi non vanno modificati), e (b) il disaccoppiamento di `refs_ready` è *necessario* perché la demozione dell'HFD sia efficace.

---

## 1. OBIETTIVO TECNICO

Progettare (NON implementare) un'architettura **sampling-aware** per la §31: il peso diagnostico dell'HFD deve diventare funzione della pixel scale di guida (prior, nota all'avvio) e della reattività misurata dell'HFD, invece di essere un gate booleano a soglia fissa. Obiettivo finale: arrivare alla fase di validazione sul campo con una proposta architetturale già formalizzata, file/funzioni/righe già individuati, e un piano di test pronto.

## 2. REGOLE INDEROGABILI

- **Read-only.** Nessuna modifica a file di codice, nessuna compilazione, nessun commit, nessun rebuild/ZIP. Solo un documento di proposta.
- **Retrocompatibilità assoluta del comportamento.** La proposta deve garantire che, a feature spenta **o** a campionamento fine (`w ≥ w_min`), il comportamento sia **identico bit-per-bit** alla §31 attuale.
- **Non toccare** la backlash compensation di PHD2, la logica esposizione dinamica, né i rami CASO 1/2/3 della v2.3.
- **Confine Guardian/Jitter.** La logica di `review()`/`micro_proposal()` non va riprogettata: l'intervento deve restare confinato a `classify()`/`refs`/config/telemetria. Se l'analisi trova che NON è possibile, segnalalo esplicitamente invece di estendere lo scope.
- **Niente invenzione di numeri.** `s*`, `k_w`, `w_min` ecc. sono **da calibrare sui log**: proponi default ragionevoli ma marcali come provvisori.

## 3. COSA ANALIZZARE E RESTITUIRE (deliverable della proposta)

1. **Validazione del modello fisico** (§1 del design rationale): è solido? Obiezioni? La forma logistica `w_prior(s)` è adeguata o ne proponi un'altra?
2. **Mappa d'impatto definitiva**: per ogni punto di codice (file:funzione:riga) cosa cambierebbe, con il diff *concettuale* (non applicato). Includi il disaccoppiamento di `refs_ready` e l'adeguamento della confidence.
3. **Opzione A (interruttore di regime) vs B (punteggio pesato)**: pro/contro sul codice reale, raccomandazione motivata, e cosa servirebbe per evolvere A→B.
4. **Chiavi di config nuove** in `DiagnosticEngineConfig` + parsing, con default retrocompatibili. Valori per i 3 setup (Askar/Tecnosky/RC8) marcati come provvisori-da-calibrare.
5. **Schema telemetria**: campi nuovi (`guide_pixel_scale`, `hfd_weight`, eventuale `hfd_cov`), bump `schema_version` 1→2, dimostrazione che è additivo e che i log v2.4 restano parsabili.
6. **Compatibilità Guardian/Jitter**: verifica sul codice che ereditano il miglioramento senza modifiche; controlla l'interazione con `guardian_min_confidence` (il SEEING senza HFD a confidence ~76 deve passare la soglia 60).
7. **Retro-compatibilità dei log**: conferma che una notte v2.4 già registrata è **rigiocabile offline** per calcolare `w(s)` e la decisione sampling-aware, senza ri-osservare. Indica esattamente quali campi servono e dove sono.
8. **Piano di test unitari** (per la futura implementazione, in `tests/test_diagnostic_engine.py`): casi a campionamento fine (comportamento invariato), a campionamento grosso (SEEING raggiungibile da rms+jitter), `refs_ready` disaccoppiato, `w` da CoV basso, confidence ridotta.
9. **Interazione con il reset EMA su esposizione** (punto correlato noto): come la proposta lo mitiga.
10. **Decisioni aperte** elencate per Alessandro.

## 4. FORMATO DELL'OUTPUT

Un unico documento Markdown di proposta (es. `PROPOSTA_§32_HFD_SAMPLING_AWARE.md`), **senza modifiche al codice**. Diff solo concettuali/inline nel testo. Alla fine: checklist di ciò che resterà da fare in fase di implementazione (quando autorizzata) e in fase di calibrazione (con i log).

## 5. COSA NON FARE

- Non implementare, non compilare, non aggiornare `CONTESTO_PROGETTO.md`/`NOTE_CLAUDE.md` (la §32 si scrive quando si implementa).
- Non tarare i parametri sui dati di una sola notte: questa è progettazione su base fisica; la taratura è una fase successiva e separata.
- Non allargare lo scope a Guardian/Jitter/esposizione se l'analisi non lo impone.

---

## 6. REVISIONE CRITICA OBBLIGATORIA — rispondi a queste domande PRIMA di qualsiasi proposta

Non limitarti a confermare il design rationale: contestalo dove serve. Rispondi esplicitamente a quattro punti.

**6.1 Il ragionamento è corretto? (verifica sul sorgente, non modifica)**
- `hfd_high` è davvero condizione OBBLIGATORIA (AND) per lo stato SEEING (~L222)? → quindi a campionamento grosso SEEING è strutturalmente irraggiungibile?
- `review()` (~L329) e `micro_proposal()` (~L373) dipendono SOLO da `self._last.state`/confidence e mai dall'HFD diretto?
- Il disaccoppiamento di `refs_ready` (~L150-153) è *davvero necessario* perché la demozione dell'HFD sia efficace, o `refs_ready=False` continuerebbe comunque a bloccare `jitter_high`? Conferma o smentisci.

**6.2 Controindicazioni che la proposta potrebbe non aver visto — cercale attivamente**
- **Falso SEEING da HFD demosso (rischio concreto, da valutare per primo):** togliendo `hfd_high` dall'AND del SEEING, il discriminante SEEING-vs-OVERCORRECTION resta solo su lag-1. E poiché il SEEING è testato PRIMA di OVERCORRECTION (~L222 prima di ~L230), un loop che **oscilla** con `jitter_high`+`rms_high` verrebbe classificato SEEING (→ ammorbidisce le leve: cura sbagliata) invece che OVERCORRECTION (→ riduce aggressività). **Valuta se il SEEING senza HFD debba richiedere `not oscillation`, oppure se vada invertito l'ordine dei rami.** Questa è la regressione più seria da scongiurare.
- Effetti collaterali su confidence (SEEING a 2 segnali ~76) e su `_is_confident()`/soglie Guardian.
- Casi limite di `w_measured` (CoV) con stelle deboli/poche o esposizione di guida lunga.

**6.3 Opzione A (interruttore) vs B (peso continuo)**
Quale preferisci sul codice reale, e perché? Cosa serve per evolvere A→B senza compromettere la retrocompatibilità bit-per-bit a campionamento fine?

**6.4 Ipotesi da NON dare per scontata**
È plausibile, ma **non ancora dimostrato**, che jitter + lag-1 + RMS "reggano più a lungo" dell'HFD e bastino a diagnosticare il regime al suo posto. Attenzione: nella prima notte v2.4 il motore è risultato **CIECO (0 diagnosi)** — quindi non abbiamo prova che quei segnali avrebbero diagnosticato correttamente senza l'HFD. Tratta questo come **ipotesi da verificare sul replay del log reale**, non come fatto. Indica esattamente quali grandezze misurare nel replay (es. quante volte `jitter_high` e `oscillation` sarebbero scattati, e con quale stato risultante) per confermarla o smentirla.
