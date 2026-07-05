# Validazione di campo v2.6 — registro progressivo (Step 0 NINA + motore §31)

**Regola di progetto:** una sessione non basta per modificare il modello; servono 3–4 sessioni / più setup, escludendo cause manuali/restart/config/ambiente. Questo è un registro di evidenze, non un mandato di modifica.

---

## Sessione 1 — 2026-06-18, Minixz100 (NINA 3.3), Askar 71F @490 (pixel scale 1.579″/px PHD2)

**Fonti:** `…/2026-06-18/logs/session_20260618_223204.csv` (926 frame, 176 valutati, 23:22→23:57) + snapshot `/status` ore 00:11.

### ✅ §42 — Telemetria NINA validata END-TO-END su 3.3
Il blocco `nina` di `/status` riceve dati reali dal plugin (`source:"nina-plugin"`, `schema_version:1`):
`hfr 1.91` · `hfr_std 0.249` · `star_count 122` · `mean_adu 718.6` · `median_adu 714` · `stdev_adu 177.8` · `exposure_s 300` · `filter "ULTIMATE"`. **`eccentricity: null` — esattamente come previsto** (DLL compilata su SDK 3.2 → non legge il campo, anche girando su 3.3). Il canale NINA→Agente è **aperto e funzionante**.

### ⚠️ Unico aggiustamento, nato dai dati: `staleness_seconds` (180) < durata posa (300)
`/status` mostra `nina.connected:false` con `last_age_s:197.9`. Non è un guasto: l'ultima telemetria è arrivata 198 s fa, ma le pose sono **300 s** e la finestra di freschezza è **180 s** → fra una posa e l'altra il blocco va "stantio" per ~120 s di ogni ciclo **pur funzionando**. Fix corretto: rendere la finestra **adattiva alla posa** (`connected = age < max(staleness_seconds, k × exposure_s)`, usando l'`exposure_s` già nel payload), oppure stopgap: alzare `staleness_seconds` sopra la durata massima della posa (es. 420). Config-only, basso rischio.

### ✅ Il motore §31 DIAGNOSTICA e AGISCE sul regime giusto (GUARDIAN)
- Reference formate (`refs_ready:true`), `jitter_ref` si forma e sopravvive ai 2 switch di modalità (`mode_transition`, §39). § 38/§39 validati sul campo su 3.3.
- counts: UNCERTAIN 163 · NOMINAL 56 · **SEEING 4** · OVERCORRECTION 2 · DRIFT 0 · INSUFFICIENT 28.
- **Episodio SEEING reale** (RMS 0.757″ > soglia 0.704, jitter sopra riferimento, lag-1 non oscillante, conf 76%): il GUARDIAN ha eseguito una **micro-correzione su RA** — `aggr 70→68`, `MinMove 0.2→0.22` (ammorbidimento, direzione corretta), **LIVE, dry_run=false**, `guardian_counts.micro:1`. → Il "0 azioni" della prima mezz'ora era solo seeing buono; **appena è degradato, il motore è intervenuto come da design**.
- Controller in LIVE (NORMAL/DEGRADED, `dry_run:false`) → attua davvero.

### Interpretazione "0 azioni a seeing buono" (prima parte sessione) = CORRETTA
Con guida a/ sotto la mediana baseline (0.541″) il satisfaction-gate §30 tiene ferme le leve (P1); UNCERTAIN nella banda morta → nessuna proposta. Un motore che funziona **sembra inerte sotto cielo buono**; si attiva sul degrado (visto: SEEING → micro). NOMINAL ("guida stabile") quando RMS < rms_low (0.406), UNCERTAIN ("quadro incerto") nella banda morta — l'alternanza osservata è coerente.

### Da osservare nelle prossime sessioni (NON modifiche)
1. `jitter_ref` nello snapshot era 0.504 (più basso del CSV 0.63–0.91): verificare che non si "incolli" basso (renderebbe SEEING troppo facile). SEEING 4/176 → per ora non over-fire.
2. Le micro GUARDIAN sono volutamente piccole (`guardian_action_factor 0.4`): tracciare se su episodi SEEING sostenuti **riducono davvero l'RMS** (outcome).
3. Tenere **una modalità fissa** (GUARDIAN) per sessione: gli switch resettano e sporcano la lettura.
4. Catturare una notte di seeing mediocre per esercitare SEEING/OVER/DRIFT sostenuti.

### Stato item
- §42 telemetria: **validato** (flusso reale). Restano da spuntare i micro-test: Agente spento→graceful, toggle off→no POST (design-verificati, non ancora osservati). Fix `staleness` da fare.
- Motore §31 GUARDIAN: **prima azione corretta su SEEING reale registrata.** Continuare l'accumulo (sessione 1/4).

---

## Ipotesi APERTA da verificare — Cap baseline su notte peggiorata (Alessandro, 2026-06-18)
**Osservazione di campo (sessione NON ancora nei log — DA ESPORTARE):** con seeing progressivamente peggiore + oggetto che scende (airmass), la baseline si è formata alta e il **cap `rms_high_max_arcsec=1.00`** ha pinnato `rms_high` a 1,0″ → RMS successivi letti come degradati contro una soglia assoluta troppo bassa per la notte → ammorbidimento leve su scala sbagliata.
**Meccanismo confermato dal config** (per 71F, pixel 1,579: cap=1,00; `rms_high=min(1,3×baseline, 1,00)` → pinnato se baseline>0,769). **Plausibile e tecnicamente fondato.**
**Avvertenza di metodo (regola di progetto):** è UNA osservazione, **verbale, su sessione non loggata** → non basta per togliere un meccanismo di sicurezza alla flotta. Inoltre il cap protegge da: (a) complacency se la baseline è alta per causa FIXABILE (allineamento/bilanciamento), (b) caso cercatore-guida §24 (moot su OAG). Il motore non distingue "seeing (non fixabile)" da "setup (fixabile)" senza il **segnale ortogonale N3/N8** → il cap è un surrogato grezzo di quella logica.
**Azione presa:** prompt §44 = cap reso **disabilitabile via kill-switch** (`rms_high_cap_enabled`, default flotta INVARIATO). Alessandro proverà cap-OFF sui suoi setup OAG (≥3–4 sessioni) col gate di rifiuto §23 come backstop. **DA FARE:** esportare il log della sessione peggiorata per verificare l'over-softening sui dati. **Collegamento roadmap:** questa osservazione è il miglior argomento finora per N3 (co-movimento HFR↔RMS) + N8 (confidence) → la sostituzione "pulita" del cap.

> NOTA: §44 è poi evoluto (decisione 2026-06-19): il cap **resta** (non era lui il driver nei log), e la fix è la **baseline bidirezionale** che traccia la scala reale della notte. Vedi NOTE_CLAUDE §44.

---

## Sessione di validazione PREDISPOSTA — §45 N1 + §46 N8 (da eseguire)

**Cosa validare (metodologia live):** la trasparenza NINA (N1) e la sua **modulazione della confidence** sul SEEING (N8). Born-operative: `[nina_indices] enabled=true`, `[diagnostic_engine] confidence_use_nina=true`. Tenere GUARDIAN fisso per la sessione.

**Preparazione:** Agente + plugin attivi (telemetria che arriva, `/status.nina.transparency.available:true`). Verificare in dashboard che compaia la card **"Trasparenza (NINA)"** con stato CLEAR a cielo limpido.

**Osservazioni da raccogliere (verificabilità a vista):**
1. **N1 a cielo limpido:** card CLEAR, indice ~1.0, stelle corrente/base ~uguali. Su campo povero ma stabile (poche stelle) deve restare **CLEAR** (NON HAZE/CLOUD) — è il test anti-soglia-assoluta sul campo.
2. **N1 su velatura/nube reale:** all'arrivo di velature il conteggio stelle cala → indice scende → stato **HAZE/CLOUD**, `deficit_pct` cresce. Annotare se la cadenza per-posa (120–300s) è abbastanza pronta sul tipo di nube osservato.
3. **N8 — modulazione visibile:** quando il motore diagnostica **SEEING** e la trasparenza è in calo confermato (≥2 pose), in dashboard il badge confidence mostra la **decomposizione** `X% (PHD2 a − NINA b)` e sul **grafico** compare il **marcatore rombo viola**. Verificare che la confidence scenda **dolcemente** (proporzionale al calo %), non a gradino.
4. **Seeing vero senza nubi:** SEEING con trasparenza CLEAR → **nessuna penalità** (NINA non sopprime il seeing legittimo) → il motore agisce come §31.
5. **Solo SEEING:** su episodi OVERCORRECTION/DRIFT la confidence **non** deve mostrare contributo NINA (nessun marcatore, badge senza decomposizione).
6. **Reversibilità:** `confidence_use_nina=false` (o telemetria assente) → comportamento identico al pre-§46.

**Log da esportare:** CSV di sessione (colonne `transparency_index`, `transparency_state`, `nina_penalty`, `diag_state`, `diag_confidence`) per ricostruire offline quanto la trasparenza ha pesato. **Taratura:** se la penalità risulta troppo timida/aggressiva sul campo, agire su `nina_deadband` / `nina_full_deficit` / `nina_max_penalty` / `nina_persist_subs` (curva tarabile, nessuna ricompilazione del modello).

**Esito atteso v1 (mano leggera):** osservare *quanto pesa davvero* la trasparenza prima di rafforzare l'effetto. Nessun hard-freeze finché i dati reali non lo giustificano.

---

## Sessione di validazione PREDISPOSTA — §47 esperimento outcome-first (ramo oscillazioni DISATTIVO)

**Cosa validare:** se, con il ramo oscillazioni spento (`oscillation_branch_enabled=false`, default), la **spirale di sotto-correzione** e il **MinMove DEC fuori scala** spariscono (→ l'oscillazione era il driver) **oppure persistono** (→ il driver è il SEEING-softening + §32, e il passo giusto è renderli outcome-gated/bidirezionali, NON un cap). In entrambi i casi: primo dato **pulito** non più influenzato dal ramo oscillazioni.

**Preparazione:** una modalità motore FISSA per la sessione (GUARDIAN). Verificare in dashboard il badge **"ramo oscillazioni: DISATTIVO (sperimentale)"**.

**Osservazioni da raccogliere (attribuzione — il cuore dell'esperimento):**
1. **Breakdown sorgenti softening** (dashboard + `/status.oscillation_experiment.softening_sources`): a fine sessione, quale sorgente domina le azioni di ammorbidimento? `SEEING` / `minmove_recovery_§32` / `guardian_micro`. È la risposta a "chi guida la spirale".
2. **MinMove efficace in arcsec** (`minmove_arcsec` su ogni azione, colonna/azione): tracciare se il MinMove DEC sale fuori scala e con quale `softening_source`.
3. **Shadow would-have-fired** (`osc_would_fire` / `osc_would_fire_degraded`): quante volte il ramo oscillazioni AVREBBE agito, e in quante di quelle l'RMS stava **davvero** peggiorando. Se `osc_would_fire_degraded ≈ 0` → conferma "se non peggiora l'outcome, non esiste" (l'oscillazione era rumore).
4. **Spirale presente/assente:** confrontare l'andamento RMS/MinMove con la sessione `223204` (pre-esperimento).

**Log da esportare:** CSV di sessione (azioni con `softening_source` + `minmove_arcsec`, `diag_state`, RMS per-frame) + snapshot `/status.oscillation_experiment`. **Reversibilità:** se serve il confronto A/B, `oscillation_branch_enabled=true` ripristina il comportamento legacy bit-identico.

**Decisione successiva (dopo 3–4 sessioni):** se la spirale persiste con ramo spento → prossimo passo = SEEING-softening/§32 **outcome-gated e bidirezionale** (non un cap MinMove). Solo allora si valuta di rimuovere strutturalmente il ramo oscillazioni.

---

## Sessione PREDISPOSTA — §48 N1 (trasparenza) + §49 N6 (safety su nubi)

**Motivazione:** nella notte nuvolosa del 2026-06-21 il Safety Monitor NON ha fermato la ripresa (andava unsafe solo su STAR_LOST) e il modulo SEEING ha letto le nubi come seeing. N6 chiude questo buco.

**Preparazione:** Agente + plugin **v1.4** attivi; inoltro telemetria ON; `[nina_indices] enabled=true`. In NINA: **"Wait Until Safe" DENTRO il loop** di ripresa (altrimenti la protezione non è continua). Verificare in dashboard la card **"Trasparenza (NINA)"** su CLEAR a cielo sereno.

**Osservazioni (verificabilità a vista, come da metodologia):**
1. **N1 riconosce:** all'arrivo di velature/nubi la card passa CLEAR → HAZE → **CLOUD** (calo % del conteggio stelle vs riferimento del campo). Un campo povero ma **stabile** deve restare CLEAR.
2. **N6 ferma:** dopo che CLOUD persiste per `CloudUnsafePolls` poll → il Safety Monitor NINA va **UNSAFE (causa: nubi)** → NINA mette in pausa la sequenza (notifica del plugin distingue `CLOUD` da `STAR_LOST`). Verificare che avvenga **prima** dello STAR_LOST di guida.
3. **Recovery:** al ritorno CLEAR/HAZE per `ClearSafePolls` poll → SAFE → NINA riprende.
4. **HAZE breve** (velatura transitoria) → NON deve mandare unsafe.
5. **Fail-safe:** spegnendo l'Agente (telemetria non fresca) → la condizione nubi diventa neutra, **nessun unsafe spurio**; STAR_LOST resta il backstop.
6. **Kill-switch:** `CloudSafetyEnabled=false` → solo STAR_LOST (comportamento pre-N6).

**Taratura:** se N6 ferma troppo presto/tardi, agire su `CloudUnsafePolls` (N, verso unsafe) e `ClearSafePolls` (M, verso safe) nelle settings del plugin — nessuna ricompilazione. Regola: N > M (lento verso unsafe, più rapido verso safe), N ~ a coprire 2–3 pose.

**Esito atteso:** le nubi che il 2026-06-21 hanno sprecato light e confuso il SEEING vengono ora **intercettate da N6** che mette in pausa; il segnale è **visibile in diretta** (card trasparenza + notifica safety con causa).

---

## Sessione PREDISPOSTA — §50 INIT standard PHD2 + §51 cap MinMove adattivo (fondamenta motore)

**§50 (stato iniziale noto):** all'avvio della guida, nel log dell'Agente compare `[init-std] Asse RA/DEC ... ai valori standard: aggr=70/100 (native 0.70/1.00) minmove=0.20`. In PHD2 (Brain → Algorithms) verificare RA Hysteresis Aggr 70 / MinMove 0.20 e DEC Resist Switch Aggr 100 / MinMove 0.20. Se un asse usa un altro algoritmo → log `WARNING [init-std] ... SALTATO` e i valori restano quelli dell'utente (nessun valore a scala sbagliata). **Allo shutdown pulito** i valori utente vengono ripristinati (log `restore baseline`). → I log dei tester partono tutti dallo stesso stato: confrontabili.

**§51 (cap MinMove):** su `/status.controller.minmove_cap` osservare `cap_arcsec`, `cap_px`, `winning` (guiding vs imaging), `baseline_filtered_arcsec`, e il MinMove efficace per asse (arcsec). Verificare che:
1. il MinMove non superi mai `cap_px` (né 1,3" fuori scala come nelle notti problematiche);
2. **baseline sale lentamente** (seeing peggiore in nottata) → il cap **sale con essa** (k<1 → resta sotto l'RMS);
3. **baseline scende** → il cap **si stringe**;
4. su setup esigente (imaging_ceiling basso) → `winning=imaging` (vince il tetto di ripresa);
5. il cap usa il **filtrato** (EMA ~18 min), non insegue gli spike istantanei.
**Taratura:** `minmove_cap_baseline_factor` (k), `minmove_imaging_ceiling_arcsec` (per-setup), `baseline_filter_tau_minutes`. **Reversibilità:** `minmove_cap_adaptive_enabled=false` / `init_to_phd2_standard=false` → legacy, per confronto A/B. I due kill-switch sono **separati** (una sezione per volta).

**Visibilità in dashboard (§52):** ora la card **"Adaptive MinMove"** (accanto ad Auto-calibrazione) mostra in tempo reale il badge **ACTIVE/IDLE** (ACTIVE arancione = il cap ha tagliato una richiesta di salita; guidato dal flag `clamping_active`, non da "MinMove==cap"), il **cap** arcsec/px, la **baseline filtrata**, il **termine vincente GUIDING/IMAGING** e il **MinMove efficace RA/DEC**. Così il §51 si valida **a vista** durante la notte (cap che sale/scende con la baseline filtrata, quando interviene, quale limite domina) senza aprire i log. La card **"Oscillation"** è stata rimossa dalla vista (Outcome-First); il dato `/status.oscillation_experiment` resta nel JSON per l'analisi. Dopo l'update: **hard-refresh** (il WebView2 di NINA può restare su cache).

---

## Sessione `20260702_215202` — EVIDENZA dell'asimmetria di recupero → fix §53

**Evidenza (prova con simulazione).** Seeing degradato simulato + recupero + crash camera. **Degradazione:** motore corretto (leve ammorbidite senza derive, aggr al pavimento 35/35). **Recupero (RMS ~0,75", niente più SEEING):** le leve restano aperte e **l'aggressività non risale MAI** in sessione continua (DEC = 10 azioni GIÙ / 0 SU nell'intera notte). Solo il **crash→INIT §50** ha riportato lo standard, dopo di che il motore ha guidato bene → **conferma: il problema è la logica di RECUPERO, non i valori**. Causa: banda morta = ratchet unidirezionale (§32 *alzava* il MinMove; l'aggr risaliva solo nel CASO3, mai nella banda morta).

**Fix §53 (recupero simmetrico) — cosa validare sul campo.** Lanciare il `.bat` (es. RC8) LIVE, riprodurre lo scenario (seeing degradato simulato, poi **terminare la simulazione**). Osservare in `/status.recovery` e nei log:
- **durante la degradazione:** ammorbidimento come prima (nessuna regressione);
- **a simulazione finita, RMS poco sopra baseline:** `state=RECOVERING`, `direction=stiffen` → **l'aggressività e il MinMove RIENTRANO verso lo standard §50** (verdetti KEEP), il gap RMS si chiude. **Confronto atteso vs `215202`: l'aggr NON deve più restare inchiodata al pavimento dopo il recupero.**
- **se irrigidire peggiora l'RMS oltre tolleranza:** STOP visibile (`stiffen_blocked=true`, `state=HOLDING`) e l'ammorbidimento §32 riprende → era seeing vero, comportamento corretto.
**Taratura:** `recovery_outcome_window_frames`, `recovery_outcome_tolerance_factor`, `recovery_stiffen_aggression`. **Reversibilità:** `symmetric_recovery_enabled=false` → §32 legacy (solo-MinMove verso il morbido), per confronto A/B.
