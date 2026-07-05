# Revisione architetturale completa — Adaptive Agent for PHD2 v2.6

**Data:** 2026-06-18 · **Autore analisi:** Cowork (analista tecnico) · **Per:** Alessandro Curci
**Si legge insieme a:** `PUNTO_FOCALE_E_PRIORITA_2026-06-16.md`, `ROADMAP_TELEMETRIA_NINA.md`, `PRINCIPIO_CONVERGENZA_PRESTAZIONE.md` (P1), `CONTESTO_PROGETTO.md`, `NOTE_CLAUDE.md` (fino a §40).

> **Ruolo e perimetro.** Questo è un documento d'analisi: nessuna modifica al codice. Le raccomandazioni operative vanno a Code. Dove propongo cambiamenti strutturali al motore matematico, segnalo esplicitamente il **gate di validazione** (almeno 3–4 sessioni / più setup / esclusione di cause manuali), come da regola fondamentale del progetto. I cambiamenti che sono **infrastruttura** (ponte di telemetria, endpoint, logging) hanno una soglia più bassa perché non toccano il modello decisionale.

---

## 0. Metodo e fonti

Ricostruzione fatta su: memoria di progetto (principio P1, storia §31→§40, roadmap NINA), i sorgenti reali dei due repository GitHub — `github.com/Mamete91/AdaptiveAgentPHD2` (Agente Python) e `github.com/Mamete91/AdaptiveAgentPHD2-NinaPlugin` (plugin C#) — e i documenti di progetto. Ho verificato le affermazioni leggendo direttamente `server.py`, `diagnostic_engine.py`, `controller.get_status()`, `config.toml` e i file C# del plugin (`AgentServices`, `AgentHealthChecker`, `AdaptiveAgentSafetyMonitor`, `SafetyDecisionEngine`).

L'evoluzione che porta a oggi, in una riga per fase: **v1.x** patch di correttezza (bug `os`, MinMove dinamico vero, Baseline Guardian, saturation, DEC) → **v2.2–2.4** auto-calibrazione, baseline adattiva, satisfaction gate §30, motore diagnostico §31, plugin NINA §27 → **v2.5–2.6** la grande pulizia delle fondamenta (§36 unità RMS, §34 cadenza, §33/§38/§40 "il riferimento si forma sempre", §37 HFD declassato, §39 reset disciplinato). Il filo conduttore della v2.6 è uno solo: **prima di costruire intelligenza nuova, rendere sana la misura.** Ora è sana.

---

## 1. Stato attuale v2.6 — sintesi

La fase bug-fix è chiusa e validata sul campo. I tre risultati che cambiano tutto:

| # | Cosa | Perché conta architettonicamente |
|---|---|---|
| §36 | RMS finalmente in **arcsec veri** (prima pixel etichettati arcsec) | I tre setup sono ora **confrontabili**; soglie/cap/baseline hanno senso fisico; qualunque fusione con un segnale esterno (NINA) è ora **sana** — prima sarebbe stata "su sabbia" |
| §34 | Il "motore congelato all'85%" era **artefatto di cadenza/logging**, non paralisi | Il motore gira davvero (INSUFFICIENT ~21% sui frame valutati; baseline ~5 min) |
| §33/§38/§40 | **Il riferimento si forma sempre** — baseline, `jitter_ref`, baseline a SNR basso | Il controllore non resta mai "senza àncora" proprio quando serve (notti brutte, SNR basso, reset frequenti) |

Campo 71F @490mm, 2026-06-17: `jitter_ref` 12%→87%, motore che diagnostica, baseline che si forma. Versione `__about__.py` = **2.6**. Entrambi i repo su GitHub.

**Distinzione da tenere ferma (regola di progetto).** Che il motore *giri e produca diagnosi* (validato) **non** equivale a che le sue diagnosi siano *corrette* né che le micro-correzioni guardian *migliorino l'RMS*. La prima è qualità del dato; la seconda è correttezza diagnostica; la terza è esito. Vanno tenute separate — ed è esattamente il motivo per cui la telemetria NINA non è "una feature in più" ma **lo strumento con cui validare la correttezza del motore** (vedi §7).

---

## 2. Mappa architetturale (chi parla con chi)

Tre processi indipendenti, accoppiati solo via HTTP/TCP, con lifecycle separati:

```
   PHD2  ──TCP 4400 JSON-RPC──▶  AGENTE (Python 3.12)  ──HTTP :8080──▶  Dashboard web (browser/tablet)
 (guida)   GuideStep/eventi      controller+analyzer+         REST /status /history /about
                                 diagnostic_engine            WS /ws  ·  POST /config/*
                                       ▲
                                       │  HTTP :8080  (oggi: GET /about + GET /status)
                                       │
                            PLUGIN NINA (C#, .NET 8, WebView2)
                            · pannello dashboard embedded in NINA
                            · Health poller  · Safety Monitor virtuale
                                       ▲
                                       │  (oggi NESSUN canale)  ◀── il vuoto da colmare in v2.7
                            NINA (camera di ripresa ASI2600MM, sequencer, autofocus…)
```

Osservazioni strutturali importanti:

- **Il flusso plugin→Agente è oggi monodirezionale e di sola lettura**: il plugin fa `GET /about` (versione) e `GET /status` (`controller.guiding_state`). Non esiste alcun endpoint **in ingresso** sull'Agente per ricevere dati da NINA. È precisamente il "vuoto" della freccia in basso: lo Step 0 della roadmap NINA.
- **Disaccoppiamento sano**: l'Agente funziona senza plugin e senza NINA; il plugin funziona come pura shell anche senza l'Agente (badge offline + fallback). Va preservato: ogni feed NINA deve restare **opzionale e graceful**.
- **Due repo = un contratto da versionare.** Da quando plugin e Agente comunicano con payload strutturati, il JSON tra loro è un'API. Oggi è informale (il plugin legge un solo campo, `guiding_state`). Appena introduciamo la telemetria diventa un contratto vero: **va versionato** (vedi §9, rischio trasversale).

---

## 3. Il motore diagnostico §31 — "Guardian" e "Jitter"

### 3.1 Chiarimento di nomenclatura (importante)

Quelli che chiami **Guardian Engine** e **Jitter Engine** non sono due motori: sono **due modalità di un unico modulo**, `SeeingDiagnosticEngine` (`diagnostic_engine.py`). È un bene — un solo nucleo diagnostico, due politiche d'azione — ma il naming nasconde due insidie da tenere a mente:

1. **Collisione "Guardian".** Nel progetto "Guardian" indica già il **Baseline Guardian** (persistenza baseline.json: save/restore/orphan recovery/shutdown, dalla v1.1). La *modalità* guardian del motore §31 è un'altra cosa. Sono due concetti diversi con lo stesso nome → in doc, dashboard e log conviene chiamarli sempre per esteso: **"Baseline Guardian"** (persistenza) vs **"motore §31 in modalità GUARDIAN"** (review delle leve).
2. **"Jitter" è anche una metrica.** `jitter_rms` (RMS frame-to-frame) è il segnale; **JITTER** è la modalità in cui il motore ha autorità piena. Tenere distinti segnale e modalità.

### 3.2 Cosa fa il motore, in concreto

Classifica il **regime causale** della guida combinando RMS + jitter frame-to-frame + autocorrelazione lag-1 + trend (HFD ora informativo, §37):

- **SEEING** — firma dinamica: `rms_total > rms_high AND jitter_high AND not oscillation` → leve morbide (aggr↓, MinMove↑)
- **OVERCORRECTION** — il loop si ribalta: `lag-1 ≤ soglia` → aggr↓
- **DRIFT** — trend direzionale senza jitter → **nessuna leva soft** (la deriva è meccanica/allineamento, non si cura ammorbidendo)
- **NOMINAL** — regime stabile; ottimizza solo sopra la mediana baseline (satisfaction gate §30)
- **UNCERTAIN / INSUFFICIENT_DATA** — niente azione

Il motore esprime solo la **direzione** della mossa (`LeverProposal`: −1/0/+1); ampiezza, limiti e cooldown li decide il controller. **Non tocca mai esposizione/backlash, non accede al client PHD2.** Le reference (`jitter_ref`/`hfd_ref`) si formano col best-fraction su finestra mobile (§38) e sopravvivono al dither (§39).

### 3.3 Le due modalità

| Modalità | Autorità | Uso | Distribuibile? |
|---|---|---|---|
| **GUARDIAN** (default, `mode="guardian"`) | La logica leve v2.3 pilota; il motore **rivede** le sue mosse (CONFIRM / ATTENUATE / BLOCK) e fa micro-correzioni proprie ad ampiezza ridotta solo quando la v2.3 è ferma. **Fail-safe**: in dubbio → CONFIRM | Assistito, prudente | **Sì** (è ciò che spedisci) |
| **JITTER** (`mode="jitter"`) | Il motore è **unica autorità** su Aggr/MinMove (CASO 1/2/3 sospesi). Logging azione→esito | Ricerca | No (gated da `allow_dashboard_mode_switch` + conferma UI) |

**Valutazione.** L'impianto è solido e coerente con P1: GUARDIAN è conservativo per costruzione (i soli BLOCK sono CASO1-in-DRIFT e CASO3-aggr-su-in-OVERCORRECTION; il resto è CONFIRM), quindi sicuro da distribuire a ~1000 utenti del gruppo Telegram. La maturità reale oggi è: **"il motore forma le reference e classifica"** (validato §38/§39). Restano da maturare, su più sessioni e setup: (a) che le classificazioni siano *corrette* (serve il canale ortogonale NINA, §7); (b) che le micro-correzioni guardian *riducano* davvero l'RMS (anti-windup `recovery_no_progress_k` aiuta, ma va misurato l'esito); (c) la taratura di `jitter_high_factor`, `lag1_oscillation_thresh`, `guardian_min_confidence` per-setup.

### 3.4 Debiti tecnici del motore (piccoli, non urgenti)

- **`confidence_calibrated` è sempre `False`** — la confidence è una formula `40 + 18·n_segnali`, non calibrata su esito reale. È il gancio naturale per il **Confidence Factor N8** (§7): quando arriverà la trasparenza NINA, quel campo diventa vero.
- **HFD ancora calcolato e loggato** benché informativo (§37). Giusto tenerlo per i replay, ma sulla dashboard la card HFD rischia di suggerire un segnale che non guida più alcuna decisione: etichettarla "informativo".
- **Trigger `rms_high` troppo zelante** (notato nel focal point): con soglie ora strette, il motore reagisce al quartile alto pur con guida buona. Cura = rendere il *trigger* meno reattivo (es. ~1,4–1,5× baseline), **non** allargare i limiti leva. Da fare come A/B, una variabile per volta.

---

## 4. Dashboard e superficie API (`server.py`)

Mini-server FastAPI/uvicorn su `0.0.0.0:8080`, frontend statico (`dashboard/`: `index.html`, `app.js`, `style.css`, Chart.js bundled). Superficie attuale:

| Metodo | Endpoint | Cosa restituisce / fa |
|---|---|---|
| GET | `/` | la dashboard HTML |
| GET | `/about` | identità: nome, autore, **versione**, copyright, Telegram |
| GET | `/status` | stato completo: `controller` (guiding_state, leve RA/DEC, saturation, exposure, escalation_gate, **auto_calibration** con baseline/soglie, lever_optimization, **diagnostic_engine** completo) + `analyzer` (rms_ra/dec/total, peak, snr_avg, hfd_avg, spike, trend, condition, frame_count) + `ai_find_enabled` |
| GET | `/history?limit=N` | ultime N azioni del controller |
| POST | `/config/dry_run` · `/config/ai_find` · `/config/diagnostic_mode` | toggle a runtime (dry-run, AI star finder, OFF/jitter/guardian) |
| WS | `/ws` | stream real-time (GuideStep processati + azioni + ping) |

**Valutazione.** `/status` è già un **bus di telemetria ricco** dell'Agente — sorprendentemente completo. È la fonte da cui la dashboard, il plugin e qualunque futuro consumatore leggono. Note:

- **CORS `allow_origins=["*"]` e bind `0.0.0.0`**: adatto a un rig su rete privata, ma quando aggiungeremo un endpoint *in ingresso* (POST telemetria NINA) va messo un minimo di validazione/limite (non per ostilità di rete, ma per robustezza: payload malformati non devono poter disturbare il loop di guida). Vedi §9.
- **Colori-soglia della dashboard fissi, non per-setup** (cosmetico ma reale per "tutti gli utenti"): un RC8 a 0,9″ si accende rosso pur essendo guida ottima. Con utenti a pixel scale molto diverse è una falsa allerta diffusa. Win a basso costo (vedi §8).
- La versione del titolo FastAPI è hard-coded `"1.0.0"` (cosmetico): l'unica fonte di verità della versione è `__about__.py`, allinearla.

---

## 5. Plugin NINA v1.2 — cosa fa oggi (più di quanto dica il README)

Il README parla di v1.1 (shell WebView + badge + launch), ma il **sorgente è già a v1.2** e contiene molto di più. Componenti reali:

- **Shell dashboard** (`AdaptiveAgentDashboardVM`): pannello dockable WebView2 su `http://localhost:8080`, badge online/offline, pulsante "Avvia Adaptive Agent", Reload.
- **`AgentHealthChecker`** (poller): `GET /about` ogni 5–120 s per il badge; e — quando abilitato — `GET /status` a ogni tick estraendo `controller.guiding_state`. Solleva `StatusChanged` (transizioni) e `StatusUpdated` (ogni tick). Non propaga mai eccezioni (timeout/refused → offline).
- **`AdaptiveAgentSafetyMonitor`** (`ISafetyMonitor` virtuale, categoria "N.I.N.A."): NINA lo vede come un Safety Monitor. Dichiara **unsafe** quando `STAR_LOST` persiste oltre il timeout (default 5 min), **safe** dopo 3 tick `NORMAL`. Auto-disconnessione se l'Agente smette di rispondere. Boundary corretto: **NINA decide cosa fare** (pausa/parking/alert); il plugin fornisce solo il segnale safe/unsafe.
- **`SafetyDecisionEngine`**: logica a **singola condizione** (solo `STAR_LOST`), con isteresi asimmetrica (lento verso unsafe, rapido verso safe). Commento esplicito nel codice: *"nessun'altra condizione entra qui: per design"*.

**Implicazione architetturale fortissima per la roadmap.** Tre pezzi dell'infrastruttura più difficile **esistono già**:

1. `HttpClient` verso l'Agente (oggi GET; basta aggiungere POST nell'altra direzione).
2. Un **Safety Monitor virtuale funzionante** → il gancio per **N6** (pausa su crollo trasparenza) è già lì: si tratta di *alimentare* il `SafetyDecisionEngine` con un secondo segnale, non di costruire il meccanismo.
3. Un poller con cadenza e gestione errori già collaudata.

Quel che **manca** è solo la direzione NINA→Agente: il plugin oggi **non** è iscritto agli eventi di imaging di NINA e **non** inoltra nulla. È esattamente lo Step 0.

> **Vincolo di progetto:** il plugin è dichiarato congelato (v1.2.x) fino al ripristino del PC principale. Lo Step 0 tocca il plugin → va pianificato ora, implementato al ripristino. La parte **lato Agente** (nuovo endpoint in ingresso) si può invece preparare e testare **da subito**, perché non dipende dal plugin (graceful: se nessuno POSTa, l'Agente lavora come oggi).

---

## 6. Metriche esposte da NINA + API/eventi pubblici

### 6.1 Cosa misura NINA, per-posa, che la camera di guida non vede

NINA, sulla camera di **ripresa** (ASI2600MM, centinaia di stelle), calcola a ogni sotto-posa salvata: **HFR** medio (e deviazione), **conteggio stelle rilevate**, statistiche ADU (Mean/Median/StDev → proxy di **fondo cielo** e **SNR**), e — via star detection — **eccentricità/FWHM**. Sono gli stessi campi che plugin maturi come *Session Metadata* e *Target Scheduler* (image grader) leggono per pesare/scartare le pose. Il punto chiave: **il campo largo di ripresa è un segnale di trasparenza e di qualità stellare incomparabilmente più robusto della singola stella di guida.**

### 6.2 Per quale via il plugin le prende

NINA inietta nei plugin un set di **mediator** (.NET). I rilevanti:

| Esigenza | Mediator/evento NINA | Dato |
|---|---|---|
| Metriche per-posa | **`IImageSaveMediator.ImageSaved`** (evento) → `ImageSavedEventArgs` | HFR, n. stelle, statistiche ADU, eccentricità, durata, filtro, path |
| Context-gating autofocus | `IFocuserMediator` (autofocus in corso) | sospendi diagnosi |
| Context-gating slew / meridian flip | `ITelescopeMediator` (slewing) | sospendi diagnosi |
| Context-gating cambio filtro | `IFilterWheelMediator` | sospendi diagnosi |
| Dither/settle | `IGuiderMediator` | già gestito lato PHD2, utile come conferma |

> **Nota di accuratezza (per Code).** Le firme esatte di `ImageSavedEventArgs` e dei mediator vanno verificate contro l'SDK della **NINA installata (3.x)** durante lo Step 0: l'API è stabile ma i campi precisi (es. dove vive l'eccentricità nello `StarDetectionAnalysis`) cambiano tra minor version. È coerente con la filosofia del progetto (verificare sul sorgente prima di implementare).

### 6.3 API/eventi pubblici disponibili (e una scelta architetturale)

- **Superficie dell'Agente** (oggi): `/status` + `/history` + `/ws` + i POST `/config/*`. È già abbastanza per esporre la telemetria *in uscita*.
- **Quel che serve aggiungere**: un canale *in ingresso* — `POST /nina/telemetry` (o `/ingest/nina`) — più un piccolo store in memoria, opzionale.
- **Alternativa da conoscere, non da adottare ora:** esiste un *Advanced API* di NINA di terze parti (webapi/websocket per controllare NINA). Potrebbe in teoria far leggere all'Agente le metriche *senza* passare dal plugin. **Sconsiglio**: aggiunge una dipendenza esterna non controllata, ribalta il modello (l'Agente dovrebbe pollare NINA invece che ricevere push dal plugin), e il plugin nostro è già il ponte naturale (gira nel processo di NINA, ha accesso nativo agli eventi). Tenere il plugin come unico ponte mantiene un solo contratto da versionare.

---

## 7. Il fronte strategico: telemetria NINA (architettura a 3 layer)

Questo è l'unico vero fronte aperto, oggi **sbloccato** (sorgente plugin recuperato) e **su base solida** (§36/§34). L'obiettivo **non** è "misurare il seeing": è **disambiguare** la causa quando l'RMS peggiora — *atmosfera*, *meccanica*, o *trasparenza*? L'RMS di guida da solo non può dirlo (jitter e lag-1 nascono dagli stessi dati di posizione). Serve un canale **ortogonale**: la forma reale delle stelle sul light frame.

**Architettura adottata, a 3 layer** (separa i domini fisici — è il principio che evita di confondere una nube con una deriva di fuoco):

```
Layer 1 — Telemetria grezza   star count · SNR · sky background · HFR · eccentricità · (RMS/star-lost da PHD2)
Layer 2 — Indici derivati     TransparencyIndex (stelle+SNR+fondo, NO HFR) · Seeing · Focus · Guiding Health · Confidence
Layer 3 — Consumatori          N1 diagnosi nuvole · N6 pausa · N7 tag pose · N8 motore · Safety Monitor
```

Gli item, con il ruolo di ciascuno (ranking onesto: valore × basso rischio × cadenza adatta):

| Item | Cosa | Valore | Rischio | Cadenza |
|---|---|---|---|---|
| **N2** Context-gating | Sospendi diagnosi/leve durante autofocus, flip, cambio filtro, slew, plate-solve | **Alto** | **Basso** | eventi |
| **N1** Trasparenza | `TransparencyIndex` = blend vs-baseline di stelle+SNR+fondo (NO HFR) | Alto | Medio | per-posa |
| **N6** Safety gate "riprendi-light" | Crollo trasparenza → unsafe via Safety Monitor esistente (isteresi) | **Alto** | **Basso** | per-posa (perfetta) |
| **N7** Frame quality scoring | Tag per-posa col TransparencyIndex → scarto auto in WBPP | **Alto** | **Basso** | per-posa |
| **N8** Confidence Factor | Trasparenza al motore §31: distingue RMS↑-da-seeing (agisci) da RMS↑-da-nubi (congela) | Alto (P1) | Medio | fuso col veloce |
| **N4/N3** HFR/eccentricità outer loop | Anello esterno sull'obiettivo VERO (stelle tonde nella posa); disambigua atmosfera vs meccanica | **Molto alto (concettuale)** | Alto | lento, confuso |

**Sequenza consigliata** (invariata, confermata dall'analisi del codice): **N2 → N1+N6+N7 (un solo segnale, tre consumatori) → N8 → N4/N3.** Tutto opzionale/graceful; sul controllo leve **fuso** col segnale di guida, mai sostitutivo.

**Il punto che voglio sottolineare e che lega tutto.** N3/N4 (HFR/eccentricità) non sono solo "la destinazione strategica": sono **lo strumento di validazione della correttezza del motore §31**. Oggi sappiamo che il motore *classifica*; non sappiamo (con un secondo canale) se classifica *giusto*. RMS↑ + HFR↑ = seeing (il motore ha ragione a chiamare SEEING); RMS↑ + HFR piatto = meccanica (se il motore dice SEEING, sbaglia). Quindi la telemetria NINA chiude anche il debito di validazione del §3.3. È il motivo per cui ha senso farla **anche se** la guida è già buona.

---

## 8. Aree di massimo valore **per tutti gli utenti** (la domanda chiave)

Filtro qui non per "quanto è affascinante" ma per **beneficio diffuso × basso attrito di adozione × zero rischio sul telescopio altrui**. Distinguo ciò che aiuta chiunque scarichi lo ZIP dal gruppo Telegram (~1000 utenti, setup ignoti) da ciò che è raffinatezza per i tuoi 3 setup.

**Massimo valore per tutti (consigliati per primi):**

1. **N2 — Context-gating.** Ogni utente NINA+PHD2 fa autofocus, flip, cambio filtro. Oggi l'Agente può scambiare quei transitori per degrado e muovere le leve. Eliminarlo è **robustezza pura, zero taratura per-setup, rischio nullo**. È il miglior rapporto valore/rischio in assoluto e migliora la qualità della guida per chiunque, su qualunque montatura.
2. **N6 + N7 — Sicurezza e qualità da trasparenza.** "Non riprendere/non sprecare pose sotto le nuvole" e "tagga le pose cattive per lo scarto" sono benefici che **chiunque** capisce e vuole, indipendentemente dall'ottica. Il meccanismo (Safety Monitor virtuale) **esiste già nel plugin**: costo marginale basso, valore percepito altissimo. N7 in più non disturba la sequenza (tag passivo).
3. **N1 — TransparencyIndex** è il segnale unico che alimenta 1–3: farlo bene una volta serve tre consumatori.
4. **Colori-soglia della dashboard per-setup** (cosmetico ma trasversale): oggi una guida ottima a lunga focale si accende rossa. Con utenti a pixel scale diverse è una falsa allerta diffusa. Derivare i colori dalla baseline/pixel-scale viva (che l'Agente già conosce) è **basso costo, beneficio per tutti**.
5. **Già fatto e di beneficio universale**: §36 (unità), §33/§38/§40 (il riferimento si forma sempre), §34 (cadenza). Sono le fondamenta che fanno funzionare l'Agente sul cielo di chiunque, non solo sul tuo. Vanno valorizzate come tali nel changelog pubblico.

**Alto valore ma con attrito (sequenziare dopo):**

- **N8 — Confidence Factor**: alto valore P1 (anti-windup sul confondente-nuvole), ma tocca il **modello decisionale del motore** → richiede il gate di validazione multi-sessione/multi-setup prima di spedirlo attivo. Spedibile dapprima come *osservativo* (logga il fattore, non agisce), poi gating reale dopo conferma.
- **N3/N4 — HFR/eccentricità outer loop**: massimo valore concettuale e strumento di validazione (§7), ma richiede **baseline per-target** e **mappatura angolo camera→assi RA/DEC** → più attrito per "tutti gli utenti", e cadenza lenta. Va trattato come anello esterno di conferma, per ultimo.

**A basso valore-per-tutti (tuo, non prioritario):** N5 (target derivato dal requisito di imaging), HFR per-filtro. Utili sul tuo workflow, poco urgenti per la flotta.

---

## 9. Rischi architetturali trasversali

1. **Contratto di telemetria da versionare.** Appena plugin e Agente si scambiano payload ricchi, quel JSON è un'API tra due binari di rilascio indipendenti (due repo GitHub). Serve un campo `schema_version` nel payload NINA→Agente (come già fatto per il CSV, §39) e tolleranza ai campi mancanti su entrambi i lati. Senza, un aggiornamento di un repo rompe l'altro per gli utenti.
2. **Endpoint in ingresso = nuova superficie.** `POST /nina/telemetry` deve essere **difensivo**: validare/troncare il payload, non bloccare mai il loop di guida, degradare a "nessuna telemetria" su input malformato. Con CORS `*` e bind `0.0.0.0` la regola è: la telemetria può solo *informare*, mai *poter degradare* la guida.
3. **Cadenza eterogenea.** Pose lente (minuti) vs guida veloce (1–2 s). Regola ferma: gli indici NINA sono anello **esterno lento**; non devono mai pilotare da soli una leva veloce. **Fondere, non sostituire.**
4. **Dipendenza opzionale, sempre.** Il rischio peggiore sarebbe rendere l'Agente *dipendente* da NINA. Ogni feed va dietro un flag, con fallback al comportamento odierno. Questo protegge i ~1000 utenti che magari non usano NINA, o lo usano senza il plugin.
5. **Plugin congelato.** Lo Step 0 tocca il plugin → vincolato al ripristino del PC principale. Mitigazione: spezzare lo Step 0 in **lato-Agente (subito, testabile a tavolino con un POST simulato)** e **lato-plugin (al ripristino)**. Il contratto JSON definito ora permette di sviluppare i due lati in parallelo.
6. **Naming "Guardian".** Collisione Baseline Guardian vs modalità GUARDIAN (§3.1): basso impatto tecnico, alto impatto di chiarezza nei doc/dashboard pubblici. Disambiguare nelle etichette.

---

## 10. Roadmap v2.7 e oltre

**v2.7 — "L'Agente inizia a vedere il cielo" (telemetria NINA, fondamenta).**

- **Step 0 (gating di tutto):** ponte di telemetria. *Lato Agente*: `POST /nina/telemetry` + store opzionale in memoria + esposizione su `/status` (born-operative ma inerte senza dati). *Lato plugin*: iscrizione a `IImageSaveMediator.ImageSaved` + mediator di stato, inoltro per-posa. Contratto JSON versionato. **È infrastruttura, non modello matematico → soglia di validazione bassa; il lato-Agente è sviluppabile subito.**
- **N2 context-gating**: primo consumatore, robustezza per tutti.
- **N1 TransparencyIndex** + **N6 safety gate** + **N7 frame tagging**: un segnale, tre consumatori; il valore-per-tutti più alto.

**v2.8 — "L'Agente si fida del dato giusto."**

- **N8 Confidence Factor**, prima **osservativo** (logga, non agisce), poi gating reale **dopo** 3–4 sessioni su più setup (gate di validazione obbligatorio: tocca il modello decisionale).
- Taratura del trigger `rms_high` (A/B, una variabile per volta) e dei fattori guardian sulla base dei log accumulati.

**v2.9+ — "L'anello esterno sull'obiettivo vero."**

- **N3/N4 HFR/eccentricità**: outer loop di conferma + validazione della correttezza diagnostica del motore (§7). Richiede baseline per-target e mappatura angolo camera. È il "nord architetturale" — per ultimo, perché lento/confuso e con più attrito.
- **N5** e HFR per-filtro: raffinamenti.

**Trasversale (qualunque versione):** colori-soglia per-setup in dashboard; disambiguazione naming Guardian; etichetta "informativo" sulla card HFD; allineare la versione FastAPI a `__about__.py`.

**Gate di validazione (regola di progetto, esplicito).** Tutto ciò che modifica il **modello matematico/decisionale** (N8 attivo, taratura trigger, qualunque nuova logica leva) richiede: ripetibilità su ≥3–4 sessioni, su più setup, ed esclusione di cause manuali/restart/config/ambientali. Tutto ciò che è **infrastruttura** (Step 0, endpoint, logging, tag passivi, context-gating come semplice sospensione) ha soglia più bassa: basta non-regressione + un campo di conferma.

---

## 11. Sintesi operativa

1. Le fondamenta (v2.6) sono sane: misura in arcsec veri, riferimenti che si formano sempre, motore che gira. **Prerequisito chiuso.**
2. "Guardian" e "Jitter" sono due **modalità** di un motore solido; GUARDIAN è distribuibile e fail-safe. Maturità reale: *classifica*; resta da provare che *classifichi giusto* e che *migliori l'esito* → lo prova la telemetria NINA.
3. Il plugin v1.2 ha **già** l'infrastruttura più difficile (HttpClient, Safety Monitor virtuale, poller). Manca solo la direzione NINA→Agente.
4. Il fronte ad alto valore **per tutti gli utenti** è, in ordine: **N2 context-gating → N1+N6+N7 (trasparenza/sicurezza/tag) → colori dashboard per-setup**. N8 e N3/N4 dopo, con gate di validazione.
5. Prossimo passo concreto e a basso rischio: **Step 0**, spezzato in lato-Agente (subito) e lato-plugin (al ripristino del PC), con **contratto JSON versionato**.

> **P1.** Le leve sono strumenti, non obiettivi. La telemetria NINA serve lo stesso principio un livello più su: l'obiettivo ultimo non è l'RMS basso ma **stelle tonde nella posa**. L'RMS è un proxy; HFR/eccentricità sono l'obiettivo vero. v2.7→v2.9 è il percorso che porta l'Agente a convergere verso la prestazione *reale*, non verso il suo proxy.
