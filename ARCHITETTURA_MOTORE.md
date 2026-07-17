# Adaptive Agent for PHD2 — Architettura di sistema / System Architecture

> **Documento di riferimento dell'architettura.** Descrive l'organizzazione a strati del motore adattivo, il flusso dei dati PHD2 ↔ Agente ↔ plugin NINA, il modello di sicurezza e lo stato di validazione. Pensato per lo sviluppo continuo e per chi contribuisce (integrazione futura con NINA / GitHub).
>
> **Architecture reference document.** Describes the layered organization of the adaptive engine, the PHD2 ↔ Agent ↔ NINA-plugin data flow, the safety model and the validation status. Written for ongoing development and for contributors (future NINA / GitHub integration).
>
> **Stato / Status:** il *nucleo* (controllore + supervisione + sicurezza) è **stabile**; lo *strato di contesto NINA* (N2/N4/N7) è **in evoluzione**. Ogni affermazione qui è ancorata al codice; lo stato di validazione sul campo è indicato esplicitamente (§10). — The *core* (controller + supervision + safety) is **stable**; the *NINA context layer* is **evolving**. Every claim here is grounded in the code; field-validation status is stated explicitly (§10).

---
---

# PARTE I — ITALIANO

## 0. Perché esiste questo progetto

PHD2 è un'eccellente autoguida, ma ottimizza il **singolo impulso di correzione**: reagisce frame per frame per tenere la stella centrata, con parametri **fissi** impostati dall'utente. Ciò che PHD2 **non** fa: adattare i propri parametri al mutare delle condizioni nell'arco di minuti/ore; distinguere il *perché* la guida peggiora (seeing vs deriva vs sovra-correzione); usare il contesto reale del cielo e delle immagini (nubi, trasparenza da NINA); né valutare se una modifica dei parametri ha davvero **migliorato l'esito**.

L'Adaptive Agent aggiunge questo **anello esterno**: osserva l'evoluzione della guida su minuti, mantiene uno stato persistente (baseline, memoria delle leve nella sessione), legge il contesto esterno (telemetria NINA) e — soprattutto — **valuta l'esito** di ogni aggiustamento (l'RMS è migliorato?), tenendo ciò che aiuta e annullando ciò che non aiuta.

È **controllo adattivo, non machine learning**: nessun addestramento, nessuna scatola nera — ogni decisione è ispezionabile nei log e in dashboard.

```
      ┌───────────── contesto & sicurezza ─────────────┐
      │                                                │
    NINA ──telemetria pose──▶   ADAPTIVE AGENT   ◀──eventi guida── PHD2
  (plugin) ◀──────UNSAFE───────  osserva · valuta   ──set Aggr/MinMove──▶
                                 · adatta le leve          (stella di guida)
                                        │
                                        ▼
                                 Dashboard (osservabilità live)
```

## 1. Filosofia di progetto: Outcome-First

L'Adaptive Agent regola in tempo reale i parametri di guida di PHD2 (Aggressività e MinMove degli algoritmi Hysteresis su RA e Resist Switch su DEC) per inseguire non un valore di leva prefissato, ma **la migliore prestazione di guida ottenibile in quelle condizioni**.

Il principio guida (P1) è: **le leve sono strumenti, non obiettivi.** L'obiettivo è convergere verso un RMS vicino alla baseline raggiungibile quella notte; il valore delle leve è solo il mezzo. Da qui discende la scelta architetturale definitiva:

**Outcome-First, non Classification-First.**

- *Classification-First (superato):* Segnali → capisco la causa → muovo le leve di conseguenza.
- *Outcome-First (attuale):* Segnali → agisco → **misuro il risultato (RMS)** → se migliora continuo, se peggiora torno indietro.

La causa (SEEING, DERIVA, SOVRA-CORREZIONE) resta utile come **indicazione di direzione**, ma non è più l'autorità che pilota da sola: a decidere è l'esito misurato. Metodo operativo del progetto: **Osservazione → Analisi → Validazione → Implementazione** (mai "osservo → modifico subito il codice"); le modifiche strutturali richiedono più sessioni, più setup e conferme dal campo.

Un corollario importante, tenuto separato per disciplina: **qualità della guida** e **correttezza delle diagnosi** sono valutazioni indipendenti. Una guida buona non implica che il motore abbia diagnosticato bene; una diagnosi corretta non garantisce un miglioramento dell'RMS.

**Il ciclo decisionale, in sintesi** (è il cuore dell'Outcome-First):

```
GuideStep(PHD2) ─▶ Analyzer ─▶ Controllore (propone una mossa)
                                     │
                                     ▼
                          Guardian §31 (conferma / attenua / blocca)
                                     │
                                     ▼
                         applica la leva ─▶ misura l'ESITO (RMS)
                                     │
                        ┌────────────┴────────────┐
                 RMS migliora / regge?        RMS peggiora?
                        │                          │
                 KEEP → continua            STOP → torna indietro
```

## 2. Architettura a strati (vista d'insieme)

```
 ┌──────────────────────────────────────────────────────────────────────┐
 │  LAYER 0 — PHD2 (stella di guida)                                      │
 │  Come si MUOVE la stella. Sorgente di verità del comportamento di guida.│
 │  Eventi GuideStep via TCP JSON-RPC (porta 4400).                       │
 └──────────────────────────────────────────────────────────────────────┘
              │  (distanze in PIXEL → convertite in ARCSEC all'ingresso, §36)
              ▼
 ┌──────────────────────────────────────────────────────────────────────┐
 │  LAYER 1 — CONTROLLORE DI BASE (outcome-first)          controller.py  │
 │  Pilota Aggressività / MinMove. Gira in modalità OFF e GUARDIAN.       │
 │   • CASO 1/2/3 (reazione a RMS/regime)                                 │
 │   • §44 baseline continua e BIDIREZIONALE (la soglia sale/scende)      │
 │   • §50 INIT ai valori standard PHD2 (stato iniziale noto)             │
 │   • §51 cap MinMove ADATTIVO (k × baseline filtrata)                   │
 │   • §53 recupero SIMMETRICO guidato dall'esito (banda morta)           │
 │   • §30 satisfaction-gate (guida buona = non toccare)                  │
 │   • Baseline Guardian (persistenza valori leve + orphan recovery)      │
 └──────────────────────────────────────────────────────────────────────┘
              │  proposta leve
              ▼
 ┌──────────────────────────────────────────────────────────────────────┐
 │  LAYER 2 — MOTORE DIAGNOSTICO §31 (supervisione)   diagnostic_engine.py│
 │  Diagnosi causale: NOMINAL / SEEING / OVERCORRECTION / DRIFT + confidence│
 │  Modalità: OFF (assente) · GUARDIAN (conferma/attenua/blocca + micro)  │
 │            · JITTER (deprecata, §54 — motore unica autorità, CASO sospesi)│
 └──────────────────────────────────────────────────────────────────────┘
              │  leve applicate → PHD2                ▲
              ▼                                       │ contesto (confidence)
 ┌──────────────────────────────────────────────────────────────────────┐
 │  LAYER 3 — CONTESTO & SICUREZZA NINA                                    │
 │   • N1 trasparenza (nubi) — nina_indices.py (Layer-2 riconoscitore)    │
 │   • N8 fusione confidence — modula la diagnosi SEEING con N1           │
 │   • N6 sicurezza nubi — nel PLUGIN NINA (SafetyMonitor → UNSAFE)       │
 │   • N2/N4/N7 — contesto acquisizione / eccentricità / qualità (futuri) │
 └──────────────────────────────────────────────────────────────────────┘
```

**Chiave di lettura (correzione di un equivoco comune):** "GUARDIAN" **non è** l'intero controllore. Baseline, INIT, cap, recovery, CASO stanno nel **Layer 1** e girano anche in **OFF**. "GUARDIAN" è solo la **modalità del Layer 2** in cui il motore §31 supervisiona il Layer 1. I tre strati sono ortogonali: la sicurezza (N6) e il contesto (N1) funzionano indipendentemente dalla modalità del motore.

## 3. Componenti (moduli)

| Modulo | Ruolo |
|---|---|
| `client.py` | Connessione TCP a PHD2 (JSON-RPC 2.0, porta 4400): eventi GuideStep, comandi set-parametro. |
| `analyzer.py` | Analisi statistica in tempo reale degli eventi: RMS (RA/DEC/totale), jitter, trend, lag-1, HFD, SNR, spike. Finestre e reset su dither/settle/cambio esposizione. |
| `controller.py` | **Layer 1** — macchina a stati adattiva: CASO, §44/§50/§51/§53, satisfaction-gate, Baseline Guardian, `_apply_with_guardian`. |
| `diagnostic_engine.py` | **Layer 2** — motore §31: diagnosi causale + confidence + riferimenti di calma (jitter_ref/hfd_ref); modalità OFF/GUARDIAN/JITTER. |
| `nina_telemetry.py` | Store in memoria della telemetria per-posa di NINA (§41, Step 0). |
| `nina_indices.py` | **Layer 3** — N1 `TransparencyTracker` (§45): indice/stato di trasparenza + freschezza; unico riconoscitore delle nubi. |
| `star_finder.py` | AI Star Finder per emergenze StarLost (riselezione stella). |
| `config.py` | Caricamento/validazione di **`config.toml` unico** (§22); tutti i kill-switch. |
| `server.py` | Backend FastAPI (porta 8080): `/status` (incl. `recovery_hint` §57), `/history`, `/config/dry_run`, `/config/ai_find`, `/config/diagnostic_mode`, `/nina/telemetry`, `POST /shutdown` (spegnimento graceful con restore baseline + watchdog di auto-terminazione, §58/§59), WebSocket `/ws`. |
| `logger.py` | Logging strutturato di sessione (`session_*.csv`, `decisions_*.jsonl`, `experimental_*.jsonl`). |
| Plugin NINA (C#, repo separato) | Invia la telemetria per-posa all'Agente; ospita **N6** (SafetyDecisionEngine). Build su **SDK NINA 3.2** (minimo comune); campi 3.3 (eccentricità/FWHM) letti via reflection. |

## 4. Flusso dei dati

```
 PHD2 ──GuideStep(px)──▶ client.py ──▶ analyzer.py ──snapshot(arcsec)──┐
                                                                        ▼
 plugin NINA ──POST /nina/telemetry──▶ nina_telemetry ─▶ nina_indices(N1) ──┐
                                                                            ▼
                                                        diagnostic_engine(§31)
                                                        + controller(Layer 1)
                                                                            │
                                                        proposta leve → client.py → PHD2
                                                                            │
                          server.py /status ◀── stato motore/leve/diagnosi ─┘
                                   │
                          dashboard (poll + WS /ws)   ← osservabilità live
```

Punti chiave del flusso:
- **Unità (§36):** le distanze GuideStep di PHD2 sono in **pixel**; vengono convertite in **arcsec all'ingresso**, perché tutte le soglie del motore sono in arcsec. È il bug storico più importante risolto (una soglia in pixel diventa enorme in arcsec su scale grossolane).
- **Telemetria NINA:** il plugin invia per ogni posa conteggio stelle, fondo cielo, HFR, ADU, filtro, ecc. N1 la trasforma in un indice di trasparenza; N8 la usa per modulare la confidence del motore.
- **Osservabilità live:** ogni logica nuova è visibile in tempo reale su `/status` e in dashboard **prima** di essere considerata validata (metodologia di validazione live).

## 5. Il controllore di base (Layer 1)

### 5.1 Catena CASO
Il controllore classico reagisce al regime dell'RMS d'asse:
- **CASO 1 — Seeing degradato** (RMS > `rms_high`): ammorbidisce (Aggr giù, MinMove su).
- **CASO 2 — Oscillazione:** riduce l'Aggressività (storicamente fragile; oggi il progetto reagisce all'esito, vedi §5.5).
- **CASO 3 — Guida ottima** (RMS < `rms_low`): ottimizza verso la reattività (Aggr su, MinMove giù), **gated** dal satisfaction-gate §30.

### 5.2 §44 — Baseline continua e bidirezionale
La soglia di riferimento (`rms_high`/mediana baseline) **traccia continuamente** le condizioni della notte e può **salire con il peggiorare del seeing** (rimosso il vecchio "tightest-wins" che la teneva sempre al minimo storico). Un cap agisce solo da tetto di sicurezza superiore.

### 5.3 §50 — INIT ai valori standard PHD2
All'avvio della guida (dopo la calibrazione, prima della baseline) le leve vengono portate a valori noti: **RA Hysteresis** Aggr 70 / MinMove 0.20; **DEC Resist Switch** Aggr 100 / MinMove 0.20 (scala nativa 0.70 / 1.00). Beneficio principale: **stato iniziale riproducibile** → log confrontabili tra sessioni e tra beta-tester. Algorithm-aware (solo algoritmi a scala frazionaria); i valori utente precedenti sono salvati/ripristinati dal Baseline Guardian; kill-switch `init_to_phd2_standard`.

### 5.4 §51 — Cap MinMove adattivo
Il MinMove massimo non è un valore assoluto fisso ma **`min( k × baseline_§44_filtrata , soglia_imaging )`**, con `k = 0.8` (universale, essendo un rapporto è indipendente dalla scala) e la baseline filtrata con EMA (τ ≈ 18 min). Impedisce che il MinMove diventi una banda morta più larga dell'RMS obiettivo (che "fabbricherebbe" RMS). Applicato solo in salita; il floor `minmove_min` resta intatto.

### 5.5 §53 — Recupero SIMMETRICO guidato dall'esito
Chiude l'asimmetria storica "ammorbidisce bene ma non torna reattivo". Nella banda morta (RMS tra `rms_low` e `rms_high`), se le leve sono più morbide dello standard §50 **e** la guida è stabile, il controllore **prova a irrigidire verso lo standard** (Aggr su, MinMove giù), poi **misura l'esito**: se l'RMS regge/migliora continua (KEEP), se peggiora si ferma (STOP → era seeing vero, torna ad ammorbidire). Estende il recupero **anche all'Aggressività** (prima recuperava solo il MinMove). Limiti: mai oltre il nominale §50, mai sotto il floor; un gradino per cooldown; anti-flapping; kill-switch `symmetric_recovery_enabled`; visibile su `/status.recovery`. È la realizzazione concreta del controllo **bidirezionale outcome-first**.

### 5.6 Baseline Guardian
Persistenza dei valori delle leve (`baseline.json`), ripristino su shutdown pulito, e **orphan recovery** se una sessione precedente non si è chiusa correttamente.

## 6. Il motore diagnostico §31 (Layer 2)

Costruisce riferimenti di calma dai frame più tranquilli (`jitter_ref`, `hfd_ref`; §38 formazione robusta best-fraction, §39 sopravvivenza a dither) e classifica il regime corrente in quattro cause, con una **confidence**:

| Diagnosi | Firma | Azione (indicativa) |
|---|---|---|
| **NOMINAL** — guida stabile | regime calmo | nessun intervento (o micro-ottimizzazione se non soddisfatto) |
| **SEEING** — seeing degradato | RMS alto **+** jitter alto | ammorbidisce (Aggr giù, MinMove su) |
| **OVERCORRECTION** — sovra-correzione | lag-1 fortemente negativo | riduce l'Aggressività |
| **DRIFT** — deriva sistematica | trend elevato, jitter normale | **nessun** ammorbidimento (non risolvibile con le leve) |

L'HFD della camera di guida è **cieco al seeing** e dal §37 è declassato a informativo (non gatea le diagnosi).

**Le tre modalità (selezionabili — vedi §9):**
- **OFF:** motore §31 non istanziato → gira il solo Layer 1 (con §44/§50/§51/§53). Modalità A/B legittima e sicura.
- **GUARDIAN (ufficiale):** il Layer 1 pilota; il §31 **conferma / attenua / blocca** ogni mossa (in base alla confidence) e aggiunge micro-correzioni nei buchi. Stesso cervello diagnostico, rischio limitato.
- **JITTER (deprecata, §54):** il §31 diventa **unica autorità** sulle leve e la catena CASO viene **sospesa** → verrebbero bypassati §44/§50/§51/§53. Mai validata sul campo; incarna il paradigma Classification-First superato. In deprecazione: rimossa dal toggle dashboard e protetta da guard-rail backend (`allow_experimental_jitter`, default false). **Il codice resta** (dormiente) per un'eventuale validazione futura deliberata.

> Nota storica: le idee del motore §31 (i quattro stati, `jitter_ref`, la confidence) sono nate nel prototipo "jitter" e **sono sopravvissute dentro GUARDIAN**. Non è la diagnosi ad essere superata, ma lo *schema di controllo* in cui la diagnosi pilotava da sola.

## 7. Il thread NINA (Layer 3): contesto e sicurezza

Architettura a 3 livelli: **telemetria → riconoscitori → consumatori.**
- **Telemetria (Step 0, §41):** il plugin invia per-posa (conteggio stelle, fondo, HFR, ADU, filtro…) a `/nina/telemetry`.
- **N1 — trasparenza (§45/§48):** `TransparencyTracker` produce un indice continuo + stato discreto (incluso CLOUD) con flag di freschezza. **Unico riconoscitore delle nubi.**
- **N8 — fusione confidence (§46):** primo consumatore di N1; usa il contesto per modulare la confidence della diagnosi SEEING (nubi = non lever-fixable → non inseguire).
- **N6 — sicurezza nubi (§49):** consumatore di N1 nel **plugin NINA** (`SafetyDecisionEngine`): su nubi persistenti porta il Safety Monitor a **UNSAFE**, fermando la ripresa **prima** di STAR_LOST. Isteresi propria; fail-safe su telemetria non fresca. Lato sequenza NINA si integra con il trigger **Trigger On Unsafe** (NINA 3.3): ferma la posa **senza muovere il telescopio** e riprende al ritorno del sereno (per NINA 3.2: `Wait Until Safe` nel loop).
- **Futuri:** **N2** contesto di acquisizione (frame di riferimento per confronti like-with-like), **N4** eccentricità/FWHM del light frame (verifica dell'esito reale = stelle tonde), **N7** qualità immagine.

**N1 è definito una volta;** N6/N8 (e in futuro N4) consumano lo stesso stato, ciascuno con la propria decisione/isteresi. Nessuna duplicazione del riconoscitore nubi.

## 8. Modello di sicurezza

- **N6 / Safety Monitor:** ferma la ripresa su nubi persistenti (vedi §7).
- **Baseline Guardian:** orphan recovery + ripristino valori utente su shutdown pulito.
- **Emergency / StarLost:** `star_finder.py` per la riselezione della stella; recovery automatico configurabile.
- **Ampiezza limitata + kill-switch:** ogni feature che tocca le leve è a gradini limitati, reversibile via kill-switch, e nata operativa ma osservabile in diretta.
- **Limiti assoluti (mai violati):** l'Agente **non tocca mai la backlash compensation di PHD2** (nessun endpoint esposto, e per policy di progetto). `dry_run` non si modifica senza autorizzazione. Il target di build del plugin resta **SDK NINA 3.2**.

## 9. Configurazione e modalità

- **`config.toml` unico** (§22): un solo file auto-configurante; tutti i parametri e i kill-switch.
- **Toggle Modalità (dashboard):** OFF / GUARDIAN (JITTER in deprecazione, §54 → resterà OFF/GUARDIAN).
- **Kill-switch principali:** `init_to_phd2_standard` (§50), `minmove_cap_adaptive_enabled` (§51), `symmetric_recovery_enabled` (§53), `allow_experimental_jitter` (§54), oltre a quelli del motore §31 e del thread NINA.

## 10. Stato di validazione (onesto)

| Intervento | Stato |
|---|---|
| §36 unità px→arcsec | ✅ Validato sul campo (RC8, guida ~0.83″) |
| §44 baseline bidirezionale | ✅ Attivo, validato (più sessioni) |
| §38/§39 formazione/persistenza riferimenti | ✅ Validato sul campo (71F: jitter_ref 12%→87%) |
| N1/N8 (§45/§46/§48) trasparenza + fusione | ✅ Implementati; telemetria validata sul campo (Step 0) |
| N6 (§49) sicurezza nubi (plugin) | ✅ Implementato (plugin v1.4), verificato sul sorgente NINA |
| §50 INIT standard | ✅ Implementato; validato (stato iniziale deterministico) |
| §51 cap MinMove adattivo | ✅ Implementato; osservato in campo |
| **§53 recupero simmetrico** | ⚠️ **Validato sul campo — solo percorso felice** (1 sessione, 2026-07-03): l'Aggressività recupera, converge a RMS ottimo. **Da verificare:** il percorso STOP (irrigidimento che peggiora) e la conferma su più sessioni/setup. |
| §54 deprecazione JITTER | ⏳ Prompt pronto, non ancora implementato |
| N2 / N4 / N7 | ⏳ Progettati, non implementati |

## 11. Roadmap

1. **Consolidare §53** su più notti/setup e cogliere un caso di STOP (chiude il *field-watch* sul blocco recupero post-STOP).
2. **§54:** deprecare JITTER (dashboard OFF/GUARDIAN + guard-rail backend).
3. **N2 — contesto di acquisizione** (fondazione prima di N4/N7): descrive target/filtro/camera/scala/esposizione per confronti like-with-like.
4. **N4 — eccentricità/FWHM** (verifica dell'esito reale: stelle tonde), osservativo in v1.
5. **N7 — qualità immagine.**
6. **Integrazione NINA upstream (obiettivo dichiarato):** percorso a tappe — (a) **validazione dalla community su GitHub**, (b) **integrazione con NINA**, (c) **possibile contributo upstream**. Oggi l'Agente è un processo Python separato + un plugin companion; l'integrazione nel processo NINA è un **traguardo futuro**, non l'architettura attuale.

## 12. Vocabolario diagnostico

Le quattro diagnosi perseguite dal progetto: **Guida stabile**, **Seeing degradato**, **Sovra-correzione**, **Deriva sistematica**. Sono cause di degrado da distinguere — ma nell'ottica Outcome-First servono a *orientare* l'azione, mentre a decidere se tenerla è l'esito misurato.

---
---

# PART II — ENGLISH

## 0. Why this project exists

PHD2 is an excellent guider, but it optimizes the **single correction pulse**: it reacts frame-by-frame to keep the star centered, with **fixed** user-set parameters. What PHD2 does **not** do: adapt its own parameters as conditions change over minutes/hours; distinguish *why* guiding degrades (seeing vs drift vs over-correction); use the real sky/image context (clouds, transparency from NINA); or judge whether a parameter change actually **improved the outcome**.

The Adaptive Agent adds this **outer loop**: it observes guiding evolution over minutes, keeps persistent state (baseline, lever memory within the session), reads external context (NINA telemetry) and — crucially — **evaluates the outcome** of each adjustment (did RMS improve?), keeping what helps and reverting what doesn't.

It is **adaptive control, not machine learning**: no training, no black box — every decision is inspectable in the logs and dashboard.

```
      ┌───────────── context & safety ─────────────────┐
      │                                                │
    NINA ──exposure telemetry──▶ ADAPTIVE AGENT  ◀──guide events── PHD2
  (plugin) ◀──────UNSAFE───────  observe · evaluate  ──set Aggr/MinMove──▶
                                 · adapt the levers        (guide star)
                                        │
                                        ▼
                                 Dashboard (live observability)
```

## 1. Design philosophy: Outcome-First

The Adaptive Agent tunes PHD2's guiding parameters in real time (Aggressiveness and MinMove of the Hysteresis algorithm on RA and Resist Switch on DEC) to chase not a fixed lever value, but **the best guiding performance achievable under the current conditions**.

The guiding principle (P1): **levers are instruments, not objectives.** The goal is to converge toward an RMS near the baseline achievable that night; the lever values are only the means. Hence the settled architectural choice:

**Outcome-First, not Classification-First.**

- *Classification-First (superseded):* signals → identify the cause → move the levers accordingly.
- *Outcome-First (current):* signals → act → **measure the result (RMS)** → keep if it improves, revert if it worsens.

The cause (SEEING, DRIFT, OVERCORRECTION) is still useful as a **direction hint**, but is no longer the sole authority driving the levers: the measured outcome decides. Project method: **Observe → Analyze → Validate → Implement** (never "observe → change code immediately"); structural changes require multiple sessions, multiple setups and field confirmation.

An important corollary, kept separate by discipline: **guiding quality** and **diagnosis correctness** are independent assessments. Good guiding does not imply the engine diagnosed correctly; a correct diagnosis does not guarantee an RMS improvement.

**The decision loop, in brief** (the heart of Outcome-First):

```
GuideStep(PHD2) ─▶ Analyzer ─▶ Controller (proposes a move)
                                     │
                                     ▼
                          Guardian §31 (confirm / attenuate / block)
                                     │
                                     ▼
                         apply the lever ─▶ measure the OUTCOME (RMS)
                                     │
                        ┌────────────┴────────────┐
                 RMS improves / holds?        RMS worsens?
                        │                          │
                 KEEP → continue            STOP → revert
```

## 2. Layered architecture (overview)

```
 ┌──────────────────────────────────────────────────────────────────────┐
 │  LAYER 0 — PHD2 (guide star)                                           │
 │  How the star MOVES. Source of truth for guiding behavior.             │
 │  GuideStep events over TCP JSON-RPC (port 4400).                       │
 └──────────────────────────────────────────────────────────────────────┘
              │  (distances in PIXELS → converted to ARCSEC at ingest, §36)
              ▼
 ┌──────────────────────────────────────────────────────────────────────┐
 │  LAYER 1 — BASE CONTROLLER (outcome-first)              controller.py  │
 │  Drives Aggressiveness / MinMove. Runs in OFF and GUARDIAN modes.      │
 │   • CASO 1/2/3 (reaction to RMS/regime)                                │
 │   • §44 continuous, BIDIRECTIONAL baseline (threshold can rise/fall)   │
 │   • §50 INIT to PHD2 standard values (known initial state)             │
 │   • §51 ADAPTIVE MinMove cap (k × filtered baseline)                   │
 │   • §53 SYMMETRIC outcome-gated recovery (dead-band)                   │
 │   • §30 satisfaction gate (good guiding = leave it alone)              │
 │   • Baseline Guardian (lever-value persistence + orphan recovery)      │
 └──────────────────────────────────────────────────────────────────────┘
              │  lever proposal
              ▼
 ┌──────────────────────────────────────────────────────────────────────┐
 │  LAYER 2 — DIAGNOSTIC ENGINE §31 (supervision)     diagnostic_engine.py│
 │  Causal diagnosis: NOMINAL / SEEING / OVERCORRECTION / DRIFT + confidence│
 │  Modes: OFF (absent) · GUARDIAN (confirm/attenuate/block + micro)      │
 │         · JITTER (deprecated, §54 — engine sole authority, CASO suspended)│
 └──────────────────────────────────────────────────────────────────────┘
              │  levers applied → PHD2                ▲
              ▼                                       │ context (confidence)
 ┌──────────────────────────────────────────────────────────────────────┐
 │  LAYER 3 — NINA CONTEXT & SAFETY                                        │
 │   • N1 transparency (clouds) — nina_indices.py (Layer-2 recognizer)    │
 │   • N8 confidence fusion — modulates SEEING diagnosis with N1          │
 │   • N6 cloud safety — in the NINA PLUGIN (SafetyMonitor → UNSAFE)      │
 │   • N2/N4/N7 — acquisition context / eccentricity / quality (future)   │
 └──────────────────────────────────────────────────────────────────────┘
```

**Key clarification (correcting a common misconception):** "GUARDIAN" **is not** the whole controller. Baseline, INIT, cap, recovery, CASO live in **Layer 1** and run in **OFF** too. "GUARDIAN" is only the **Layer 2 mode** in which the §31 engine supervises Layer 1. The three layers are orthogonal: safety (N6) and context (N1) work independently of the engine mode.

## 3. Components (modules)

| Module | Role |
|---|---|
| `client.py` | TCP connection to PHD2 (JSON-RPC 2.0, port 4400): GuideStep events, set-parameter commands. |
| `analyzer.py` | Real-time statistics of guide events: RMS (RA/DEC/total), jitter, trend, lag-1, HFD, SNR, spike. Windows reset on dither/settle/exposure change. |
| `controller.py` | **Layer 1** — adaptive state machine: CASO, §44/§50/§51/§53, satisfaction gate, Baseline Guardian, `_apply_with_guardian`. |
| `diagnostic_engine.py` | **Layer 2** — §31 engine: causal diagnosis + confidence + calm references (jitter_ref/hfd_ref); modes OFF/GUARDIAN/JITTER. |
| `nina_telemetry.py` | In-memory store of NINA per-exposure telemetry (§41, Step 0). |
| `nina_indices.py` | **Layer 3** — N1 `TransparencyTracker` (§45): transparency index/state + freshness; the only cloud recognizer. |
| `star_finder.py` | AI Star Finder for StarLost emergencies (star re-selection). |
| `config.py` | Load/validate the **single `config.toml`** (§22); all kill-switches. |
| `server.py` | FastAPI backend (port 8080): `/status`, `/history`, `/config/dry_run`, `/config/ai_find`, `/config/diagnostic_mode`, `/nina/telemetry`, WebSocket `/ws`. |
| `logger.py` | Structured session logging (`session_*.csv`, `decisions_*.jsonl`, `experimental_*.jsonl`). |
| NINA plugin (C#, separate repo) | Sends per-exposure telemetry to the Agent; hosts **N6** (SafetyDecisionEngine). Built against **NINA SDK 3.2** (lowest common denominator); 3.3 fields (eccentricity/FWHM) read via reflection. |

## 4. Data flow

```
 PHD2 ──GuideStep(px)──▶ client.py ──▶ analyzer.py ──snapshot(arcsec)──┐
                                                                        ▼
 NINA plugin ──POST /nina/telemetry──▶ nina_telemetry ─▶ nina_indices(N1) ─┐
                                                                           ▼
                                                       diagnostic_engine(§31)
                                                       + controller(Layer 1)
                                                                           │
                                                       lever proposal → client.py → PHD2
                                                                           │
                         server.py /status ◀── engine/lever/diagnosis state─┘
                                  │
                         dashboard (poll + WS /ws)   ← live observability
```

Key points:
- **Units (§36):** PHD2 GuideStep distances are in **pixels**; they are converted to **arcsec at ingest**, because all engine thresholds are in arcsec. This was the most important historical bug fixed (a pixel threshold becomes huge in arcsec on coarse scales).
- **NINA telemetry:** the plugin sends per-exposure star count, sky background, HFR, ADU, filter, etc. N1 turns it into a transparency index; N8 uses it to modulate the engine's confidence.
- **Live observability:** every new logic is visible in real time on `/status` and in the dashboard **before** being considered validated (live-validation methodology).

## 5. The base controller (Layer 1)

### 5.1 CASO chain
The classic controller reacts to the per-axis RMS regime:
- **CASO 1 — Degraded seeing** (RMS > `rms_high`): softens (Aggr down, MinMove up).
- **CASO 2 — Oscillation:** reduces Aggressiveness (historically fragile; today the project reacts to the outcome, see §5.5).
- **CASO 3 — Optimal guiding** (RMS < `rms_low`): optimizes toward reactivity (Aggr up, MinMove down), **gated** by satisfaction gate §30.

### 5.2 §44 — Continuous, bidirectional baseline
The reference threshold (`rms_high` / baseline median) **continuously tracks** the night's conditions and can **rise as seeing worsens** (the old "tightest-wins" that pinned it to the historical minimum was removed). A cap acts only as an upper safety ceiling.

### 5.3 §50 — INIT to PHD2 standard values
At guide-start (after calibration, before baseline) the levers are set to known values: **RA Hysteresis** Aggr 70 / MinMove 0.20; **DEC Resist Switch** Aggr 100 / MinMove 0.20 (native scale 0.70 / 1.00). Main benefit: **reproducible initial state** → logs comparable across sessions and beta-testers. Algorithm-aware (fractional-scale algorithms only); the user's previous values are saved/restored by the Baseline Guardian; kill-switch `init_to_phd2_standard`.

### 5.4 §51 — Adaptive MinMove cap
The maximum MinMove is not a fixed absolute but **`min( k × filtered_§44_baseline , imaging_ceiling )`**, with `k = 0.8` (universal — being a ratio it is scale-independent) and the baseline EMA-filtered (τ ≈ 18 min). Prevents MinMove from becoming a dead-band wider than the target RMS (which would "manufacture" RMS). Applied on the way up only; the `minmove_min` floor is untouched.

### 5.5 §53 — Symmetric outcome-gated recovery
Closes the historical asymmetry "softens well but doesn't return to reactive". In the dead-band (RMS between `rms_low` and `rms_high`), if the levers are softer than the §50 standard **and** guiding is stable, the controller **attempts to stiffen toward standard** (Aggr up, MinMove down), then **measures the outcome**: if RMS holds/improves it continues (KEEP), if it worsens it stops (STOP → it was real seeing, resume softening). Extends recovery **to Aggressiveness too** (previously only MinMove recovered). Bounds: never above the §50 nominal, never below the floor; one step per cooldown; anti-flapping; kill-switch `symmetric_recovery_enabled`; visible on `/status.recovery`. This is the concrete realization of **bidirectional outcome-first control**.

### 5.6 Baseline Guardian
Persistence of lever values (`baseline.json`), restore on clean shutdown, and **orphan recovery** if a previous session did not close cleanly.

## 6. The diagnostic engine §31 (Layer 2)

It builds calm references from the quietest frames (`jitter_ref`, `hfd_ref`; §38 robust best-fraction formation, §39 survival across dither) and classifies the current regime into four causes, with a **confidence**:

| Diagnosis | Signature | Action (indicative) |
|---|---|---|
| **NOMINAL** — stable guiding | calm regime | no intervention (or micro-optimization if not satisfied) |
| **SEEING** — degraded seeing | high RMS **+** high jitter | softens (Aggr down, MinMove up) |
| **OVERCORRECTION** | strongly negative lag-1 | reduces Aggressiveness |
| **DRIFT** — systematic drift | high trend, normal jitter | **no** softening (not lever-fixable) |

The guide-camera HFD is **blind to seeing** and since §37 is demoted to informational (does not gate diagnoses).

**The three modes (selectable — see §9):**
- **OFF:** §31 engine not instantiated → only Layer 1 runs (with §44/§50/§51/§53). A legitimate, safe A/B mode.
- **GUARDIAN (official):** Layer 1 drives; §31 **confirms / attenuates / blocks** each move (based on confidence) and adds micro-corrections in the gaps. Same diagnostic brain, bounded risk.
- **JITTER (deprecated, §54):** §31 becomes the **sole authority** on the levers and the CASO chain is **suspended** → §44/§50/§51/§53 would be bypassed. Never field-validated; embodies the superseded Classification-First paradigm. Being deprecated: removed from the dashboard toggle and protected by a backend guard-rail (`allow_experimental_jitter`, default false). **The code remains** (dormant) for a possible future deliberate validation.

> Historical note: the §31 engine's ideas (the four states, `jitter_ref`, confidence) were born in the "jitter" prototype and **survived inside GUARDIAN**. It is not the diagnosis that is superseded, but the *control scheme* in which the diagnosis drove the levers alone.

## 7. The NINA thread (Layer 3): context and safety

3-level architecture: **telemetry → recognizers → consumers.**
- **Telemetry (Step 0, §41):** the plugin sends per-exposure data (star count, background, HFR, ADU, filter…) to `/nina/telemetry`.
- **N1 — transparency (§45/§48):** `TransparencyTracker` produces a continuous index + discrete state (including CLOUD) with a freshness flag. **The only cloud recognizer.**
- **N8 — confidence fusion (§46):** first consumer of N1; uses the context to modulate the SEEING diagnosis confidence (clouds = not lever-fixable → don't chase).
- **N6 — cloud safety (§49):** consumer of N1 in the **NINA plugin** (`SafetyDecisionEngine`): on persistent clouds it drives the Safety Monitor to **UNSAFE**, stopping capture **before** STAR_LOST. Own hysteresis; fail-safe on stale telemetry. On the NINA sequence side it integrates with the **Trigger On Unsafe** trigger (NINA 3.3): stops the exposure **without moving the mount** and resumes when safe (for NINA 3.2: `Wait Until Safe` in the loop).
- **Future:** **N2** acquisition context (reference frame for like-with-like comparisons), **N4** light-frame eccentricity/FWHM (verification of the real outcome = round stars), **N7** image quality.

**N1 is defined once;** N6/N8 (and later N4) consume the same state, each with its own decision/hysteresis. No duplication of the cloud recognizer.

## 8. Safety model

- **N6 / Safety Monitor:** stops capture on persistent clouds (see §7).
- **Baseline Guardian:** orphan recovery + restore of user values on clean shutdown.
- **Emergency / StarLost:** `star_finder.py` for star re-selection; configurable auto-recovery.
- **Bounded amplitude + kill-switches:** every lever-touching feature is stepped and bounded, reversible via kill-switch, and born operational but live-observable.
- **Absolute limits (never violated):** the Agent **never touches PHD2's backlash compensation** (no exposed endpoint, and by project policy). `dry_run` is not changed without authorization. The plugin build target stays **NINA SDK 3.2**.

## 9. Configuration and modes

- **Single `config.toml`** (§22): one self-configuring file; all parameters and kill-switches.
- **Mode toggle (dashboard):** OFF / GUARDIAN (JITTER being deprecated, §54 → will remain OFF/GUARDIAN).
- **Main kill-switches:** `init_to_phd2_standard` (§50), `minmove_cap_adaptive_enabled` (§51), `symmetric_recovery_enabled` (§53), `allow_experimental_jitter` (§54), plus the §31 engine and NINA thread switches.

## 10. Validation status (honest)

| Change | Status |
|---|---|
| §36 px→arcsec units | ✅ Field-validated (RC8, ~0.83″ guiding) |
| §44 bidirectional baseline | ✅ Active, validated (multiple sessions) |
| §38/§39 reference formation/persistence | ✅ Field-validated (71F: jitter_ref 12%→87%) |
| N1/N8 (§45/§46/§48) transparency + fusion | ✅ Implemented; telemetry field-validated (Step 0) |
| N6 (§49) cloud safety (plugin) | ✅ Implemented (plugin v1.4), verified against NINA source |
| §50 INIT standard | ✅ Implemented; validated (deterministic initial state) |
| §51 adaptive MinMove cap | ✅ Implemented; observed in the field |
| **§53 symmetric recovery** | ⚠️ **Field-validated — happy path only** (1 session, 2026-07-03): Aggressiveness recovers, converges to good RMS. **To verify:** the STOP path (stiffening that worsens) and confirmation across sessions/setups. |
| §54 JITTER deprecation | ⏳ Prompt ready, not yet implemented |
| N2 / N4 / N7 | ⏳ Designed, not implemented |

## 11. Roadmap

1. **Consolidate §53** across nights/setups and capture a STOP case (closes the *field-watch* on the post-STOP recovery block).
2. **§54:** deprecate JITTER (dashboard OFF/GUARDIAN + backend guard-rail).
3. **N2 — acquisition context** (foundation before N4/N7): describes target/filter/camera/scale/exposure for like-with-like comparisons.
4. **N4 — eccentricity/FWHM** (verification of the real outcome: round stars), observational in v1.
5. **N7 — image quality.**
6. **Upstream NINA integration (declared goal):** staged path — (a) **community validation on GitHub**, (b) **integration with NINA**, (c) **possible upstream contribution**. Today the Agent is a separate Python process + a companion plugin; integrating into the NINA process is a **future goal**, not the current architecture.

## 12. Diagnostic vocabulary

The four diagnoses pursued by the project: **Stable guiding**, **Degraded seeing**, **Over-correction**, **Systematic drift**. They are degradation causes to be distinguished — but under Outcome-First they serve to *orient* action, while the measured outcome decides whether to keep it.

---

*Documento vivo / Living document. Ancorato al codice alla data di stesura; aggiornare insieme alle modifiche del motore. — Grounded in the code at time of writing; update alongside engine changes.*
