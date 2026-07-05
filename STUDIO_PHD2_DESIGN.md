# PHD2 Design Study — Memoria tecnica del controllo di guida

> **Scopo.** Comprendere come PHD2 affronta i problemi del controllo di guida, **esclusivamente** per accrescere la cultura progettuale dell'Adaptive Agent e documentare le nostre scelte alla luce dell'esperienza degli sviluppatori di PHD2. **Non** è un confronto competitivo né una trasposizione di codice/algoritmi: nessuna copia. Per ogni tema: *problema affrontato · soluzione PHD2 · motivo tecnico (se deducibile dal codice) · analogie/differenze con l'Agente · eventuale spunto utile*.
>
> **Metodo e onestà di copertura.** Studio ancorato al sorgente locale `phd2-master/src`. Ho letto **il nucleo del controllo di guida**: `guide_algorithm_hysteresis.cpp`, `guide_algorithm_resistswitch.cpp`, `guiding_assistant.cpp` (statistiche + `MakeRecommendations`/`GetMinMoveRecs`), `star.cpp` (SNR/HFD/saturazione). **Restano per una passata futura:** Lowpass/Lowpass2/ZFilter, l'interno del PPEC (Gaussian Process), `guider*.cpp`, `image_math.cpp`. **Escluso per policy di progetto:** tutto ciò che riguarda la *backlash compensation* (non la tocchiamo e non la studiamo per modificarla).
>
> **Nota versione:** riferito al `phd2-master` in repo; la logica di controllo è stabile tra versioni, ma va riletta contro la versione realmente installata prima di dedurne decisioni operative.

---

## Come usare questo documento

Questo documento **non definisce** l'architettura dell'Adaptive Agent (quello è `ARCHITETTURA_MOTORE.md`). Serve **esclusivamente** come memoria tecnica dello studio svolto sul codice di PHD2. Quando dallo studio emerge un principio ritenuto valido, viene classificato in uno di tre esiti — e la scelta è tracciata a fine capitolo:

- **Adottato** → il principio entra nel progetto senza modifiche sostanziali (spesso perché già convergente col nostro).
- **Adattato** → il principio viene **reimplementato nella forma coerente con l'Outcome-First** (concetto sì, formula/codice no).
- **Non adottato** → documentato ma non implementato, con la motivazione tecnica.

Coppia con l'architettura: `ARCHITETTURA_MOTORE.md` risponde a *"com'è fatto l'Adaptive Agent"*; questo documento a *"perché quelle scelte, e quali principi abbiamo valutato lungo il percorso"*.

## 1. La legge di controllo reattiva (gli algoritmi)

PHD2 non ha un "motore adattivo": ha un insieme di **filtri reattivi** che, per ogni frame, trasformano l'errore misurato in un impulso di correzione. I due che l'Agente pilota sono Hysteresis (RA) e Resist Switch (DEC).

### 1.1 Hysteresis (default RA)
- **Problema:** correggere lo spostamento della stella senza reagire in modo nervoso al rumore.
- **Soluzione (dal codice):** l'output è una miscela tra l'errore corrente e la correzione precedente, poi scalata dall'aggressività, con una banda morta. In forma concettuale: `out = (1−hyst)·errore + hyst·ultima_correzione`, poi `out ×= aggressività`, e se `|errore| < minMove` allora `out = 0`.
- **Motivo tecnico:** il termine `hyst·ultima_correzione` è una **memoria di un passo** (momentum/passa-basso) che smorza i cambi bruschi; l'aggressività (0–1) decide *quanta parte* della correzione applicare; il `minMove` è la **banda morta** che ignora gli spostamenti sotto soglia (tipicamente seeing).
- **Analogie/differenze con l'Agente:** queste tre grandezze — aggressività, minMove, isteresi — sono **esattamente le leve che il nostro motore regola**. Ma la legge di PHD2 è **statica e per-impulso** (memoria di un solo passo): non conosce l'RMS su minuti, non ha baseline, non valuta l'esito. Il nostro Agente è **l'anello esterno** che adatta questi stessi parametri nel tempo con feedback sull'esito.
- **Spunto:** conferma che il nostro modello mentale (aggressività = "quanto correggo", minMove = "cosa ignoro") è quello giusto e coincide col cuore di PHD2. Nulla da cambiare, molto da consolidare.

**Decisione progettuale — ☑ Adottato.** *Motivo:* la legge (aggressività + minMove + isteresi) è già esattamente il modello di leve che il nostro motore regola. Convergenza confermata, nessun cambio; l'Agente resta l'anello esterno adattivo sopra questa legge.

### 1.2 Resist Switch (default DEC)
- **Problema:** in DEC l'inversione di direzione è costosa (gioco meccanico) e favorisce l'oscillazione.
- **Soluzione (dal codice):** mantiene una **storia** degli ultimi errori DEC e **resiste** a cambiare la direzione di guida. Cambia lato solo se: (a) almeno ~3 campioni concordi nella nuova direzione (`abs(decHistory) < 3` → "non abbastanza convincente"), **e** (b) la situazione sta **peggiorando** (somma dei 3 più recenti in modulo > somma dei 3 più vecchi, altrimenti "not getting worse"); se si è "superato" il bersaglio, **veta** la mossa; un'escursione molto grande (>3×minMove) forza lo switch immediato.
- **Motivo tecnico:** evitare di sprecare impulsi nel gioco dell'ingranaggio e di innescare pendolamenti in DEC. È **gestione strutturale del backlash dentro la legge di controllo**.
- **Analogie/differenze:** PHD2 tratta il backlash **nell'algoritmo**; noi non abbiamo (e per policy non avremo) un controllo backlash-aware. Ma il pattern "**agisci solo con N campioni concordi + trend che peggiora**" è concettualmente **lo stesso della nostra logica** (gating a `consecutive_frames` + l'outcome-gate KEEP/STOP del §53: "torna indietro se peggiora").
- **Spunto:** l'**evidence-gate** (N-concordi + "sta peggiorando") è una regola decisionale anti-rumore robusta e generale; è confortante vederla anche in PHD2 e vale come conferma del nostro §53 e dei gate a frame consecutivi.

**Decisione progettuale — ☑ Non adottato (come controllo) · principio già convergente.** *Motivo:* il controllo backlash-aware nella legge di guida è **fuori policy** (non tocchiamo il backlash). Ma il pattern *evidence-gate* (agisci solo con N campioni concordi + trend che peggiora) è già presente nel nostro §53 (outcome KEEP/STOP) e nei gate a frame consecutivi. Confortante convergenza, nessuna nuova implementazione.

### 1.3 Gli altri algoritmi (nota)
Lowpass/Lowpass2 (filtri passa-basso), ZFilter, Identity, e soprattutto **PPEC (Gaussian Process)**: quest'ultimo è l'**unica** parte di PHD2 con memoria/apprendimento online — *modella e predice l'errore periodico della montatura* (feed-forward), un problema diverso dall'adattamento dei parametri. Interni non ancora studiati (passata futura).

## 2. Stima del seeing e del rumore (Guide Assistant)

- **Problema:** quanta parte del movimento della stella è **seeing non correggibile** e quanta è **errore correggibile**?
- **Soluzione (dal codice):**
  - Le statistiche di seeing sono calcolate su dati **filtrati passa-alto** (`m_hpfRAStats`, `m_hpfDecStats`) → isolano l'alta frequenza (seeing) togliendo la deriva lenta.
  - In DEC c'è in più una **correzione di deriva** (detrend lineare) e si calcola l'RMS corretto (`decCorrectedRMS`), con l'**R²** del fit di deriva.
  - Si prende la **sigma (deviazione standard) minima** su **finestre scorrevoli e sovrapposte di 2 minuti** (`bestEstimate = min(sigma delle finestre)`).
- **Motivo tecnico (deducibile):** il passa-alto/detrend separa la **deriva della montatura** (bassa freq) dal **jitter atmosferico** (alta freq); la **min-sigma tra finestre** evita di contaminare la stima del seeing con raffiche/nubi transitorie (si sceglie l'intervallo più calmo); 2 minuti = abbastanza campioni per una sigma stabile ma abbastanza breve da cogliere il tratto migliore.
- **Analogie/differenze:** **forte convergenza** con la nostra §38 ("best-fraction dai frame più calmi") + il jitter detrendizzato. Stessa idea: *isola l'alta frequenza + scegli la finestra più calma*. Differenza: PHD2 lo fa **una volta** (2-3 min, statico); noi in **continuo** (baseline rolling §44).
- **Risposte alle domande "perché" (dal codice, non ipotesi):** *perché sigma e non mediana?* → perché modellano il seeing come ~normale e ne derivano i moltiplicatori percentili (vedi §3); la mediana non è usata per questa stima. *Perché finestre da 2 min?* → per la selezione della finestra più calma con campioni sufficienti. *Perché detrend?* → per togliere la deriva prima di misurare il seeing.

**Decisione progettuale — ☑ Adottato (convergenza documentata).** *Motivo:* detrend + selezione della finestra/frazione più calma è già la nostra §38 (jitter detrendizzato + best-fraction), adottata in modo indipendente. Nessun cambio; si documenta la convergenza. Differenza: PHD2 lo fa una volta (statico), noi in continuo (§44).

## 3. La filosofia del MinMove (la parte più istruttiva)

- **Problema:** tarare la banda morta così che la guida **ignori il seeing** ma **corregga l'errore vero**.
- **Soluzione (dal codice, `GetMinMoveRecs`):** `MinMove ≈ moltiplicatore × sigma(passa-alto)`, con il **moltiplicatore scelto per un TASSO DI ATTIVITÀ obiettivo** ricavato dalla distribuzione normale:
  - `multiplier_dec = 1.28` se scala < 1.5″/px, altrimenti `1.65` — commento nel codice: *"20% or 10% activity target based on normal distribution"* (1.28σ ≈ coda 10%, 1.65σ ≈ coda 5%).
  - `MinMove_RA = 0.65 × MinMove_DEC` (RA più reattivo per l'errore periodico), **100%** su montature con encoder.
  - **Tetto di credibilità:** la raccomandazione è accettata solo se `scala × stima ≤ 1.25″` ("un MinMove sotto 1.25 arcsec è credibile") + un floor e arrotondamento a unità.
- **Motivo tecnico:** esprimere la banda morta come **percentile dello scatter di seeing** controlla *direttamente ogni quanto* la guida "spara" una correzione — un modo fisicamente fondato di fissare una dead-band. Il tetto in **arcsec** (1.25″) è un controllo di sanità **scale-aware**.
- **Analogie/differenze:** è **esattamente** la nostra filosofia "MinMove = soglia di inseguimento ≈ frazione dell'RMS raggiungibile" + il cap §51. Ma PHD2 ricava la frazione da un **duty-cycle obiettivo** (quanto spesso correggere) via distribuzione normale; il nostro §51 usa un `k = 0.8` **fisso**.
- **★ SPUNTO CONCRETO (reale, fattibile — il migliore dello studio):** potremmo esprimere il `k` del cap §51 **non come numero fisso**, ma come **tasso di attività obiettivo** (es. "voglio che le correzioni scattino ~15–20% dei frame"), ricavando il moltiplicatore dalla distribuzione dell'RMS/jitter misurato. Vantaggi: più principiato, auto-esplicativo, **indipendente dalla scala per costruzione**, e allineato a un criterio fisico consolidato. Da valutare come **evoluzione del §51**, non come sostituzione (resta la nostra baseline adattiva §44 sotto). Corollari altrettanto reali: (a) l'**asimmetria RA/DEC** (banda morta RA più piccola) è una scelta di progetto che potremmo considerare nella logica per-asse; (b) il **tetto di credibilità in arcsec** è coerente col nostro §36 e con il tetto imaging del §51.

**Calibrazione sul campo (guide log PHD2 2026-07-03, Askar 71F, 1.58″/px) — Decisione ☑ Adattato (in valutazione, A/B).**
*Misura del duty-cycle reale sotto le nostre impostazioni attuali:* attività (impulso emesso) **RA 42% · DEC 20%**; attraversamenti della soglia iniziale 0.200 px RA 56% · DEC 51% → il **Resist Switch veta ~60% delle correzioni DEC** (anti-backlash visto sul campo). RMS ottimo (~0.61″ RA / 0.53″ DEC) *proprio con* questa attività. MinMove/σ ≈ 0.5 (RA/DEC) contro 1.28–1.65 di PHD2.
*Motivo della decisione:* il principio fisico (banda morta legata a una probabilità d'intervento) è valido, ma il **target fisso di PHD2 confliggerebbe col nostro §53**, che spinge *deliberatamente* verso la reattività quando l'esito è buono (filosofia in parte opposta al "basso duty-cycle"). Adattamento Outcome-First: usare il **tasso di attività come segnale validato dall'esito** — se l'alta attività non compra un RMS migliore, allora sta inseguendo il seeing → alza MinMove. **Non si copia** la formula 1.28/1.65. *Prossimo passo:* A/B (RA 42%→~20% preserva l'RMS?), non implementazione immediata; kill-switch + validazione live quando/se si procede.

## 4. Esposizione, campionamento, deriva (esclusa backlash)

- **Problema:** scegliere tempo di posa e campionamento.
- **Soluzione (dal codice):**
  - **Esposizione limitata dalla deriva:** `drift_exp ≈ ceil( sigma_HPF_RA / tasso_deriva / 0.5 ) × 0.5` → la posa deve essere abbastanza breve che la deriva RA entro un frame resti ~≤ la sigma di seeing.
  - Range ideali: 2–4 s senza encoder, 4–8 s con encoder (che tollerano pose più lunghe, niente PE da inseguire).
  - **Binning** consigliato se scala < 0.5″/px (sovracampionamento); errore polare dedotto dalla deriva DEC.
- **Motivo tecnico:** legare la posa al **rapporto seeing/deriva** (non lasciare che la deriva domini un singolo frame).
- **Analogie/differenze:** il nostro Agente ha esposizione **dinamica** (RMS-based, continua); PHD2 dà una **raccomandazione una tantum**.
- **Spunto:** il principio "posa ≤ tempo perché la deriva resti sotto la sigma di seeing" è pulito e potrebbe entrare **esplicitamente** nella nostra logica di esposizione come vincolo aggiuntivo.

**Decisione progettuale — ☑ Adattato (in valutazione).** *Motivo:* il vincolo "posa ≤ tempo perché la deriva resti sotto la sigma di seeing" è un principio pulito; da valutare come vincolo aggiuntivo nella nostra esposizione dinamica (che oggi è RMS-based). Non urgente.

## 5. Qualità della stella di guida (SNR, saturazione, HFD)

- **Problema:** la stella di guida è affidabile?
- **Soluzione (dal codice, `star.cpp`):**
  - **SNR fotometrico** (rif. Simonetti 2004): `SNR = massa / sqrt( massa/gain + sigma²_fondo · n · (1 + 1/nbg) )` — rumore misurato in un **anello** attorno alla stella (fondo), combinando rumore di shot (massa/gain) e rumore di fondo. Non è un banale picco/fondo.
  - **Rigetto falsa stella:** se il picco non supera la soglia, l'SNR viene declassato (evita falsi positivi da pochi pixel sparsi). `LOW_SNR = 3.0` come pavimento.
  - **Saturazione** rilevata via ADU di picco (`STAR_SATURATED`); **HFD** = diametro a metà flusso.
- **Motivo tecnico:** un SNR fisicamente corretto tiene conto di shot-noise + cielo; l'anello dà un fondo robusto.
- **Analogie/differenze:** noi facciamo gating su SNR (`snr_low`) e gestiamo la saturazione con la riselezione §35 (Path B). L'SNR di PHD2 ha una **definizione fotometrica precisa**.
- **Spunto:** interpretare le nostre soglie SNR **in termini della definizione esatta di PHD2** (così sappiamo a cosa corrispondono i numeri); il rigetto-falsa-stella e il rumore-in-anello sono pattern di robustezza da tenere presenti per N-series/qualità.

**Decisione progettuale — ☑ Adottato (interpretativo).** *Motivo:* ancoriamo le nostre soglie SNR alla **definizione fotometrica esatta di PHD2** (Simonetti: segnale/√(shot+fondo-in-anello)) così sappiamo a cosa corrispondono i numeri; il rigetto-falsa-stella e il rumore-in-anello restano pattern di robustezza per N-series/qualità. Nessuna nuova implementazione, solo interpretazione corretta.

## 6. Fisso vs adattivo, casi limite

- **Fisso in PHD2:** i parametri della legge di controllo (aggressività/minMove/isteresi) sono **statici** durante la sessione (impostati una volta, dall'utente o dal Guide Assistant che gira una volta sola).
- **Adattivo in PHD2:** **solo** il PPEC (Gaussian Process) si adatta online — ma *predicendo l'errore periodico*, non tarando i parametri.
- **Casi limite gestiti:** tetto di credibilità MinMove (1.25″), pavimento LOW_SNR, rigetto falsa stella, avviso "rifai calibrazione" se calibrazione sospetta/backlash-clearing, conteggi minimi di campioni, arrotondamenti/floor.
- **Differenza filosofica di fondo:** la taratura dei parametri in PHD2 è **statica e una-tantum**; l'Adaptive Agent la rende **continua e guidata dall'esito**. Il PPEC è l'unico pezzo online-adattivo, ma su un problema diverso (predizione PE).

## 7. Sintesi: analogie, differenze, dove imparare

**Osservabili/fisica condivisi:** stima del seeing con detrend + sigma; MinMove come frazione/percentile del seeing; deriva ed errore polare; SNR/HFD/saturazione della stella; **selezione della finestra/frazione più calma**.

**Convergenze indipendenti (validano le nostre scelte):**
- finestra/frazione più calma per la reference (PHD2 min-sigma 2-min ↔ nostra §38 best-fraction);
- **detrending** prima della misura del seeing;
- **evidence-gate** prima di agire (Resist Switch "N concordi + peggiora" ↔ nostri `consecutive_frames` + outcome-gate §53).

**Differenza fondamentale:** PHD2 = **raccomandazione statica una-tantum** + ottimizzazione del singolo impulso; Adaptive Agent = **controllo continuo, outcome-first**, con recupero bidirezionale (§53), contesto esterno (NINA N1/N8) e sicurezza (N6).

**Dove PHD2 può insegnarci qualcosa (spunti reali):**
1. **★ MinMove/cap come tasso-di-attività obiettivo** ricavato dalla distribuzione (vs il nostro `k` fisso) — evoluzione del §51.
2. **Asimmetria RA/DEC** della banda morta come scelta esplicita di progetto.
3. **Definizione fotometrica esatta dell'SNR** come àncora delle nostre soglie.
4. **Vincolo posa ↔ rapporto seeing/deriva** nella logica di esposizione.

**Dove l'Agente è deliberatamente diverso (e in vantaggio per il suo scopo):** adattamento continuo, outcome-gating, recupero bidirezionale, contesto NINA, sicurezza — cose che il Guide Assistant, per natura di strumento di setup una-tantum, non fa né deve fare.

## 8. Frase per l'architettura (fondata, per `ARCHITETTURA_MOTORE.md`)

> *Il progetto dell'Adaptive Agent è stato confrontato con la logica interna del PHD2 Guide Assistant e degli algoritmi di guida di PHD2. Pur condividendo diversi osservabili fisici (stima del seeing per detrend+sigma, banda morta MinMove come frazione dello scatter di seeing, deriva/errore polare, SNR/HFD della stella), l'Adaptive Agent adotta deliberatamente una strategia di controllo **continua e guidata dall'esito**, anziché il modello di **raccomandazione statica** di PHD2. Diverse scelte statistiche di PHD2 (detrending, selezione della finestra più calma, gating a evidenza) sono risultate convergenti con le nostre, adottate in modo indipendente.*

---

## Appendice — Copertura e prossimi passi

**Studiato (questo documento):** Hysteresis, Resist Switch, Guide Assistant (statistiche seeing + `MakeRecommendations`/`GetMinMoveRecs` + esposizione/binning), `star.cpp` (SNR/HFD/saturazione).
**Da studiare (passate future):** Lowpass/Lowpass2/ZFilter; interni del **PPEC** (Gaussian Process — predizione dell'errore periodico, il pezzo più sofisticato); `guider*.cpp` (selezione multistar, gestione lost-star); `image_math.cpp` (elaborazione immagine).
**Escluso per policy:** `backlash_comp.*` e ogni logica di modifica del backlash.

*Memoria tecnica — nessun codice PHD2 trasposto; solo descrizione concettuale a fini di studio. Aggiornare quando si studiano nuove parti.*
