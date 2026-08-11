# Adaptive Agent for PHD2 — Manuale Utente

**Versione 2.3**
**Autore: Alessandro Curci**
Copyright © 2026 Alessandro Curci

Community e supporto:

https://t.me/+eewRNpvElSs5OWY8

---

L'**Adaptive Agent** è il tuo copilota astrofotografico. Lavora "sotto il cofano" assieme a PHD2 e alla tua suite principale (come NINA), agendo come un utente umano molto reattivo che fissa in modo continuativo lo schermo della guida per fare micro-aggiustamenti che ti salvano la nottata. **Si configura da solo sul tuo setup**: legge dal profilo PHD2 la scala di campionamento del tuo treno ottico e tara le sue soglie sul cielo reale che sta misurando, notte per notte.

## ⚠️ Prima di iniziare (importante)

### Con quali algoritmi di guida PHD2 lavora l'Agente

L'Agente regola due "manopole" di PHD2: l'**Aggressività** e il **MinMove**. Funziona quindi al meglio con gli algoritmi che espongono entrambe — che sono anche quelli **di default** di PHD2:

* ✅ **Hysteresis** (asse RA) + **Resist Switch** (asse DEC): compatibilità piena. È la combinazione consigliata.
* ✅ **Lowpass2**: compatibilità piena.
* ⚠️ **Lowpass**: parziale. L'Agente può regolare solo il MinMove, non l'aggressività.
* ⛔ **Predictive PEC** e **Gaussian Process**: sconsigliati (soprattutto sull'asse RA). Sono algoritmi "predittivi" che costruiscono nel tempo un modello dell'errore periodico basandosi su una cadenza di posa costante: l'esposizione dinamica dell'Agente cambia il tempo di posa e ne disturba il modello. In più non espongono l'aggressività.
* ⛔ **None**: l'Agente non ha nulla da regolare.

> [!TIP]
> In dubbio? Lascia PHD2 sui suoi valori predefiniti (Hysteresis su RA, Resist Switch su DEC): è esattamente lo scenario per cui l'Agente è stato progettato.

### Cosa NON fa l'Agente (e cosa serve prima di lanciarlo)

L'Agente è un **assistente**, non un sistema di guida completo. Non calibra e non avvia la guida da solo: si appoggia a una sessione PHD2 **già calibrata e in guida attiva**. Prima di lanciarlo assicurati che:

* PHD2 stia già guidando correttamente su una stella;
* in PHD2 sia attivo il server (menu **Strumenti → Abilita Server**, porta 4400): è il canale con cui l'Agente comunica;
* nel profilo PHD2 in uso siano impostate correttamente **focale di guida** e **dimensione pixel della camera di guida**: da qui l'Agente ricava in automatico la scala di campionamento. Se questi dati non ci sono, l'Agente userà un valore di fallback e la dashboard te lo segnalerà;
* l'AI Star Finder possa scaricare le immagini di guida (serve per il recupero della stella persa).

E per tua tranquillità: l'Agente **non tocca mai** la calibrazione della montatura né la compensazione del backlash. Lavora solo su leve "morbide" e reversibili.

---

## 🤔 Perché è nato questo progetto?

Quando il cielo è perfetto, PHD2 con i suoi settaggi aggressivi di "inizio serata" guida benissimo. Il problema è che il cielo **non resta perfetto**: arrivano turbolenze, foschia, vento, nuvole di passaggio. E quei settaggi che prima erano l'ideale, ora diventano controproducenti.

Il pericolo principale è l'**iper-correzione a catena**: se il seeing peggiora, PHD2 continua a inseguire ogni piccolo tremolio della stella come se fosse un errore reale da correggere. Ma quel tremolio è solo aria che si muove. Il risultato è che la montatura "rincorre il rumore", l'errore RMS sale invece di scendere, e le stelle nei tuoi scatti vengono mosse.

C'è poi un secondo fronte: gli allarmi di `StarLost` (Stella persa). Bastano una nuvola di passaggio o un ri-puntamento (dither) e PHD2 perde la stella di guida. Spesso poi non riesce a riagganciarne una nuova da solo, oppure scarta proprio le stelle più luminose e utili perché le considera "troppo sature". A quel punto la guida si ferma e, a cascata, si ferma anche NINA.

Lasciare PHD2 da solo tutta la notte significa accettare questi due rischi. L'**Agente** è nato esattamente per stare sveglio al posto tuo: sorveglia di continuo come sta andando la guida e interviene in tre modi, sempre con un'idea precisa di **prima la mossa "economica", poi quella più importante**:

1. **Ammorbidisce la guida** quando l'aria peggiora, così PHD2 smette di rincorrere il rumore.
2. **Allunga l'esposizione** della camera di guida quando ammorbidire non basta più, per "mediare" la turbolenza.
3. **Recupera la stella persa** con un suo sistema di visione, quando PHD2 alza bandiera bianca.

Il tutto mentre tu dormi o fai altro, e senza mai sostituirsi alle tue scelte di fondo.

---

## 🛠️ Cosa fa in automatico?

### 1. 🧠 Regolazione Dinamica dei Parametri (RA / Dec)

L'Agente analizza ciclicamente (ogni *X* secondi) il trend dell'errore RMS e una stima del seeing (confrontando i picchi di spostamento).

* **Se fiuta Vento o Oscillazioni critiche**: abbassa automaticamente l'*Aggressività* (Aggressiveness) e, se l'errore continua a saltare, alza il *MinMove* di tolleranza. In pratica permette alla montatura di "scivolare" sul vento invece di reagire a ogni colpo (che peggiorerebbe l'oscillazione RMS).
* **Se il cielo torna calmo e limpidissimo**: ripristina per gradi l'aggressività, per tornare alla guida precisa tipica delle notti perfette.
* **Quando la guida è già al suo meglio** *(novità v2.3)*: l'Agente sa qual è il livello di errore tipico del tuo cielo migliore (la *mediana* che misura da solo durante la calibrazione). Appena la guida raggiunge quel livello, smette di "spingere" ulteriormente le leve verso la reattività massima e le lascia ferme sul punto buono. Il motivo è pratico: in un cielo già ottimo, leve troppo nervose inseguono il rumore atmosferico e l'RMS, paradossalmente, ricomincerebbe a salire. Se le condizioni peggiorano, l'Agente riprende automaticamente a regolare le leve come prima — non devi fare nulla. Puoi disattivare questo comportamento dal `config.toml` (`[lever_optimization]`, `enabled = false`) per tornare al modo della v2.2.

### 2. ⏱️ Esposizione Dinamica della camera di guida

Questa è la leva che entra in gioco **quando le manopole di cui sopra non bastano più**. Allungare l'esposizione della camera di guida fa una cosa molto utile: ogni fotogramma "media" su più tempo le micro-vibrazioni dell'aria, quindi il segnale arriva a PHD2 già più pulito. L'Agente la usa in due situazioni distinte:

* **Stella troppo debole (SNR basso)**: se il segnale della stella di guida crolla (nuvola sottile, foschia), l'Agente raddoppia l'esposizione per "raccogliere più luce" e non perdere la stella. È una mossa rapida e binaria (×2).
* **Seeing degradato (turbolenza)**: se l'aria è turbolenta ma la stella è ancora ben visibile, l'Agente alza l'esposizione **per gradini dolci** (passi di circa ×1,5, fino a un massimo di due gradini sopra il valore base). Più tempo di posa = meno rumore ad alta frequenza = RMS più basso.

> [!IMPORTANT]
> **L'Agente non tocca subito l'esposizione.** Prima prova sempre con le leve "economiche": abbassa l'aggressività e alza il MinMove. Solo **quando queste hanno raggiunto i loro limiti** (la cosiddetta *escalation gate*, il "cancello di escalation" si apre) e il cielo è ancora turbolento, allora — e solo allora — l'Agente decide di allungare l'esposizione. È una scala di interventi deliberata: prima il rimedio leggero, poi quello più impattante.

Per sicurezza l'esposizione **non scende mai sotto il valore base** che hai impostato tu, e ha un tetto massimo. Quando il cielo torna tranquillo, l'Agente riporta l'esposizione al valore base un gradino alla volta.

### 3. 👁️ AI Star Finder (Il Superpotere Visivo)

PHD2 ha un limite hard-coded: ignora o scarta per errore stelle valide se hanno pixel con intensità altissima ("palloni bianchi" causati da un leggero scostamento del fuoco di guida o da sensori molto sensibili).
L'**AI Star Finder** è un sistema di intelligenza visiva dell'Agente.
Quando PHD2 stacca il tracciamento e mostra "Stella Persa", invece di restare lì a strillare e piantare NINA, l'Agente:

1. Intercetta l'emergenza e richiede il download dell'immagine FITS pura appena scattata dal telescopio di guida in una frazione di secondo.
2. Usa un suo algoritmo matematico visivo, sganciato da PHD2, per ispezionare tutta l'inquadratura, bypassando il temuto *blocco della saturazione massima*.
3. Trova le coordinate della stella più consistente e ordina via RPC API a PHD2: *"Chiuditi su queste coordinate al pixel x,y!"*, costringendo PHD2 a riprendere il tracciamento e recuperando il crollo in modo forzato.

---

## ⚙️ Auto-configurazione: si tara da solo sul tuo setup

Questa è la novità che rende l'Agente "plug and play" su qualunque telescopio o camera di guida. Non devi più dirgli a mano la pixel scale, né tarare manualmente le soglie RMS per ogni rig: lo fa lui all'avvio.

**Pixel scale automatica.** All'avvio l'Agente chiede a PHD2 la scala di campionamento del profilo attivo (calcolata da focale di guida × dimensione pixel della camera, considerando il binning). Quel numero diventa la sua "regola in arcsec" per tutta la sessione. Se cambi telescopio, monti un riduttore o passi ad altro profilo PHD2, basta selezionare il profilo giusto in PHD2 prima di lanciare l'Agente: si riadatta da solo. Se PHD2 non conosce la scala (focale di guida non impostata nel profilo), l'Agente usa il valore di fallback nel file di configurazione e te lo segnala sulla dashboard con un badge esplicito.

**Soglie RMS adattive.** Le soglie che decidono quando il cielo è "degradato" o "eccellente" non sono più costanti fisse tarate a mano per ogni setup, ma si calcolano da una **baseline misurata sul tuo cielo reale**. Nei primi minuti di guida calma l'Agente raccoglie un campione di RMS in condizione normale, ne fa la mediana, e da quella deriva le soglie. In pratica: la *tua* notte sul *tuo* rig diventa il punto di riferimento, automaticamente. Una nottata "buona" tara soglie strette, una nottata mediocre soglie più larghe, sempre coerenti col cielo che hai davvero sopra la testa.

**Reti di sicurezza sulla calibrazione.** L'Agente non lascia che una serata fuori scala "promuova" valori sbagliati a normalità. Se la baseline misurata è palesemente troppo alta, la calibrazione viene **rifiutata** e l'Agente mantiene le soglie iniziali del file di configurazione (dashboard: badge **BASELINE RIFIUTATA**). Se invece la baseline è normale ma la soglia derivata supererebbe **1 arcsec** — il riferimento universale di "guida pulita" indipendente dal setup — scatta il **cap**: la soglia viene "tagliata" a 1" (dashboard: badge **CAP ATTIVO**). Entrambe le reti tengono l'Agente sempre dentro un perimetro di qualità di guida riconosciuto, sia che tu usi un OAG sia che usi un cercatore-guida.

**Refresh ciclico della baseline.** Una sessione astrofotografica può durare ore, e il cielo può cambiare nel frattempo. Per questo l'Agente non si "congela" sulla calibrazione iniziale: ogni 30 minuti la baseline viene ri-misurata silenziosamente (mentre le soglie correnti continuano a lavorare normalmente, senza buchi di copertura). Se la nuova baseline risulta **più stretta** della precedente — segno che il cielo è migliorato — viene sostituita e le soglie si stringono di conseguenza, rendendo l'Agente più reattivo. Se invece è uguale o più larga, viene **ignorata**: l'Agente non concede mai terreno al peggioramento del cielo. È la regola "tightest-wins", e ti garantisce che le soglie si tarino sempre sulle migliori condizioni della notte.

> [!TIP]
> Hai un setup diverso da quelli su cui l'Agente è stato sviluppato? Non serve toccare nulla. Crea il profilo in PHD2 col tuo telescopio e la tua camera di guida (con focale e pixel size corrette), lancia `Avvia.bat`, e l'Agente farà il resto. Niente file da modificare a mano, niente versioni "per setup".

---

## 🚀 Avvio rapido

Tutta la configurazione vive in **un solo file** e si lancia con **un solo eseguibile**:

* **`config.toml`** — l'unico file di configurazione, lo stesso per qualsiasi setup.
* **`Avvia.bat`** — l'unico file di avvio, lo stesso per qualsiasi setup.

Il workflow è in tre passi:

1. Apri PHD2 e seleziona il **profilo del telescopio** che stai usando (con focale di guida e dimensione pixel camera corrette).
2. Avvia la guida su una stella in PHD2.
3. Doppio clic su `Avvia.bat` e apri il browser su `http://localhost:8080`.

L'Agente gira **in background, senza finestra**: la conferma che è vivo è la dashboard stessa (o il badge verde nel plugin NINA). Nel pacchetto trovi altri due file di comodo:

* **`Arresta.bat`** — spegne l'Agente **in modo pulito**: prima di uscire ripristina i parametri PHD2 originali (baseline). È il modo corretto di chiuderlo a fine serata se non usi il plugin NINA.
* **`Mostra_Log.bat`** — apre una finestra che mostra il log in diretta (utile per curiosare o per il supporto); puoi chiuderla quando vuoi, l'Agente non se ne accorge nemmeno. Lo stesso log resta comunque su disco in `logs/agent.log`.

Niente più "versione ridotta" del .bat: se monti il riduttore di focale, basta che il profilo PHD2 abbia la focale ridotta inserita (puoi avere due profili distinti, uno a focale piena e uno ridotta, e scegliere quello giusto a PHD2). L'Agente legge la scala reale da PHD2 e si adatta da sé, senza che tu cambi un solo file.

---

## 🖥️ Come usare la Web Dashboard

La pagina web è la cabina di pilotaggio dove l'Agente ti espone in tempo reale la sua "mente".

* **Grafici e Numeri (RMS / HFD / SNR)**: una supervisione istantanea delle oscillazioni e della nitidezza stellare (condizione del cielo: *DEGRADED*, *OSCILLATING*, *NORMAL*).

* **Pannello "Auto-calibrazione"** *(novità)*: ti mostra come l'Agente si è tarato sul tuo setup.
  * **Pixel scale rilevata** con badge **PHD2** (letta dal profilo PHD2) oppure **TOML** (fallback se PHD2 non la conosce — significa che nel profilo PHD2 manca la focale di guida).
  * **Progresso baseline**: i frame raccolti finora (es. "42/60") finché non si completa la misura, poi il valore di mediana misurato in arcsec.
  * **Soglie attive**: `rms_high` e `rms_low` derivate dalla baseline (le soglie con cui l'Agente sta giudicando il cielo in questo momento).
  * Badge **CAP ATTIVO** (ambra): la soglia `rms_high` derivata avrebbe superato 1 arcsec (il riferimento universale di guida pulita), ed è stata "tagliata" al cap. L'Agente è in modalità più severa del normale: significa che il cielo è ai limiti di quello che si considera una guida ancora accettabile.
  * Badge **BASELINE RIFIUTATA** (rosso): la sessione è troppo compromessa per ricavarne una baseline rappresentativa. L'Agente usa le soglie iniziali del file di configurazione invece di calibrare su questa nottata.
  * **Refresh ciclico** *(novità §25)*: mostra il countdown al prossimo refresh automatico della baseline (es. "Prossimo tra 24m 12s"), oppure "In corso: 23/60" quando la ri-misura è attiva. Durante la ri-misura le soglie precedenti continuano a essere applicate normalmente — non c'è mai un buco di copertura.
  * Badge **Ultimo: APPLICATO** (verde) o **Ultimo: RIFIUTATO** (grigio): esito dell'ultimo ciclo di refresh. APPLICATO = il cielo è migliorato e le soglie si sono strette. RIFIUTATO = le condizioni sono rimaste uguali o sono peggiorate, l'Agente mantiene le soglie attive senza concedere reattività al peggioramento.

* **Pannello "Stato Esposizione & Escalation Gate"**: ti mostra a colpo d'occhio cosa sta facendo l'Agente sull'esposizione e perché.
  * **Badge di stato esposizione**: in che regime sei — `NOMINAL` (esposizione base), `BOOSTED_FOR_SNR` (alzata perché la stella era debole) o `BOOSTED_FOR_SEEING` (alzata per gradini a causa della turbolenza).
  * **Valori di esposizione**: il tempo di posa corrente in millisecondi e quanti gradini sei sopra la base.
  * **Barre di saturazione delle leve (RA e DEC)**: ti fanno vedere quanto sono "tirate" aggressività e MinMove su ciascun asse. Quando entrambe sono al limite, il *cancello di escalation* è aperto: è il segnale che l'Agente è autorizzato ad allungare l'esposizione.
  * **Cooldown residuo**: i secondi che mancano prima che l'Agente possa fare un nuovo cambio di esposizione.
  * **Marker sul grafico RMS**: ogni cambio di esposizione lascia un triangolino sul grafico (giallo = esposizione alzata, verde = riportata giù), così puoi collegare visivamente "ho cambiato esposizione qui" con l'andamento dell'RMS prima e dopo.

* **Interruttore "MODALITÀ TEST"**:
  > [!TIP]
  > Se `MODALITÀ TEST` (Dry Run) è **ATTIVA**, l'Agente emulerà le sue deduzioni nel "Log Decisioni Controller" dicendoti cosa farebbe, **ma senza agire fisicamente in PHD2**. Spegnila e passa in **`LIVE CONTROL`** per lasciare che l'Agente prenda attivamente il controllo del telescopio. Di default il pacchetto distribuito parte già in LIVE.

* **Log Decisioni Controller**: un tabellone cronologico con i messaggi (per es. *"RA Aggressività 70 → 65 | Abbasso aggressività perché Oscillazione rilevata"* oppure *"Esposizione 2000ms → 3000ms | Seeing degradato, leve sature"*). Se è vuoto, significa semplicemente che la guida sta performando in modo sano e non serve intervenire.

---

## 🧩 Bonus: usare la dashboard dentro NINA (plugin opzionale)

Se usi **NINA** come suite di acquisizione, esiste un plugin C# separato — **Adaptive Agent for PHD2 — Dashboard** — che aggiunge a NINA un pannello dockable con la stessa dashboard `http://localhost:8080` caricata via WebView2 direttamente dentro l'interfaccia NINA. Vantaggio pratico: non devi più tenere aperta una finestra del browser accanto a NINA, la dashboard è una scheda dockable come tutte le altre.

**Novità v1.1: pulsante Avvia e badge stato.** Da v1.1 il pannello mostra in alto un badge che indica a colpo d'occhio se l'Agente è raggiungibile — "Agente online vX.Y" (verde) o "Agente offline" (grigio), aggiornato automaticamente ogni 15 secondi — e un pulsante **"Avvia Adaptive Agent"** che lancia `Avvia.bat` con un click, senza aprire Esplora Risorse. Per usarlo, imposta una sola volta il percorso del `.bat` in *Options → Plugins → Adaptive Agent for PHD2 — Dashboard* (pulsante "Sfoglia..."). Quando l'Agente è già online il pulsante si disabilita: resta una pura comodità, la dashboard funziona comunque.

**Monitor delle Condizioni del Cielo (dalla v1.2, potenziato nella v1.5, rinominato nella v1.12) — il componente centrale.** Il cuore del plugin è un dispositivo virtuale che NINA usa come qualsiasi altro dispositivo di sicurezza: un unico verdetto **safe/unsafe sulla qualità dell'acquisizione**, che qualsiasi costrutto di NINA può consumare (policy in *Options → Safety*, `Wait until safe`, condizioni `Loop while safe/unsafe`, trigger personalizzati). Chi decide cosa farne è **sempre e solo il Sequence Engine di NINA** — il monitor segnala, non orchestra mai. Il driver appare nella tendina *Equipment → Safety Monitor* di NINA sotto la categoria **N.I.N.A.** col nome "Adaptive Agent for PHD2 — Condizioni del Cielo" (fino alla v1.11 si chiamava "Guide Safety": NINA salva il dispositivo per identificativo, quindi il profilo non si rompe). Il nome descrive ciò che il dispositivo *misura* — le condizioni di osservazione — mentre dichiarare unsafe è una delle sue conseguenze, non il suo intero ruolo. Selezionandolo e cliccando *Connect*, NINA riflette lo stato del cielo e della guida come flag safe/unsafe. Il driver dichiara **unsafe** in quattro casi: `STAR_LOST` persistente oltre il timeout configurato (default 5 minuti); **trasparenza degradata persistente** (nubi, misurate sulle pose di NINA con una logica ad accumulo che non si fa ingannare dalle schiarite brevi); **telemetria diventata stantia con l'ultimo cielo noto degradato**; **Agente irraggiungibile durante una sessione attiva**. Il principio (dalla v1.5, dopo una notte di validazione sul campo): *perdere l'osservazione affidabile non è mai "sicuro"* — il driver **resta connesso** anche se l'Agente sparisce, ed escala verso unsafe invece di disconnettersi in silenzio. Torna **safe** solo con evidenza positiva (cielo sereno / guida di nuovo stabile). La feature è opt-in: chi vuole solo il pannello dashboard non è toccato.

**Recovery probe (dalla v1.6/1.7): la sessione riparte da sola dopo le nubi.** Sopra quel verdetto safe/unsafe si possono costruire diversi workflow: la **Recovery probe** è quello che consigliamo per il recupero automatico. Il plugin aggiunge al *sequencer avanzato* di NINA l'istruzione **"Recovery probe (Adaptive Agent)"**. La monti una volta sola così:

```
Trigger On Unsafe
 └ Before Waiting For Safety
    └ Recovery probe (Adaptive Agent)
```

Quando il monitor dichiara unsafe (nubi), quell'unica istruzione è l'intero ciclo di recupero: a cadenza configurabile (o prima, se la SNR della stella di guida suggerisce che il cielo sta tornando) scatta **una posa di verifica non guidata** che replica il tuo ultimo light; se le stelle sono tornate, l'indice di trasparenza si rinfresca, il monitor torna safe e la sequenza riprende — **senza il tuo intervento, anche alle 3 di notte**. Se il cielo resta chiuso, la posa fallisce il test e si riprova al giro successivo.

E se la sequenza raggiunge i **suoi** criteri di fine (ora impostata, alba, limite di altezza, stop manuale) mentre il recupero è ancora in corso? **Vincono sempre i tuoi criteri**: NINA annulla immediatamente la posa di verifica — anche a metà scatto — e chiude la sequenza nei tempi decisi da te; a sequenza conclusa, un cielo tornato sereno non riavvia più nulla. È una proprietà verificata dell'architettura: il plugin non può mai ritardare o aggirare le decisioni del Sequence Engine.

**Ciclo di vita automatico (dalla v1.7, attivo di default).** Il plugin **avvia da solo l'Agente quando apri NINA** (una volta impostato il percorso di `Avvia.bat` nelle opzioni) e **lo spegne in modo pulito quando chiudi NINA**, ripristino baseline incluso — la chiusura di NINA è istantanea, del resto si occupa l'Agente. Entrambi i comportamenti si possono disattivare nelle opzioni del plugin. L'interfaccia del plugin, infine, è **in inglese o in italiano** a scelta (*Options → Plugin language*, default: segue la lingua di NINA).

> [!IMPORTANT]
> Il driver Safety **non decide** cosa fare al verificarsi dell'unsafe — **segnala soltanto**. Le reazioni concrete (pausa sequenza, parking, warm-up camera, ecc.) si configurano dentro NINA, in *Options → Safety* (policy globale) oppure nell'*Advanced Sequencer* (istruzione `Wait until safe` e Global Trigger `Trigger On Unsafe`). Per uso domestico con supervisione attiva la configurazione consigliata è abilitare "Pause sequence on unsafe" + "Resume on safe", senza azioni custom aggressive (parking, warm-up). Per uso remoto non sorvegliato, conviene aggiungere un `Trigger On Unsafe` con una sequenza custom di "safe shutdown".

> [!IMPORTANT]
> Il plugin è **opzionale**: l'Agente funziona perfettamente senza. La dashboard web su `http://localhost:8080` resta sempre il canale primario, ed è obbligatoria per chi vuole accedere da **tablet, secondo monitor o PC remoto** sulla stessa rete. Il plugin NINA non sostituisce il browser, lo affianca.

**Sequenza di avvio se usi anche il plugin NINA** (dalla v1.7 è quasi tutta automatica):

1. Apri PHD2 e seleziona il profilo del telescopio.
2. Apri NINA: il plugin **avvia l'Agente da solo** (se hai impostato il percorso di `Avvia.bat` nelle opzioni) e il pannello "Adaptive Agent for PHD2" mostra la dashboard non appena l'Agente risponde.
3. A fine serata chiudi NINA e basta: il plugin spegne l'Agente in modo pulito, baseline ripristinata.

Se preferisci gestire l'Agente a mano, disattiva l'avvio automatico nelle opzioni del plugin e usa il pulsante **"Avvia Adaptive Agent"** (o `Avvia.bat`). Se il pannello mostra "Agente non raggiungibile" con il pulsante **Riprova**, è solo questione di ordine di avvio: premi Riprova dopo che l'Agente è partito.

**Installazione del plugin** (una sola volta): la DLL del plugin va copiata in `%LOCALAPPDATA%\NINA\Plugins\3.0.0\AdaptiveAgentForPHD2.NinaPlugin\` e NINA va riavviato. Il pannello compare poi nel menu dockable di NINA. Per il dettaglio tecnico di build/install vedi il repository del plugin (progetto separato, distribuito sul gruppo Telegram della community insieme al pacchetto Agente).

> [!TIP]
> Se il pannello mostra schermo bianco al primo apertura senza messaggio di fallback, manca il **runtime Microsoft Edge WebView2**: scaricalo dal sito Microsoft e riavvia NINA. Su Windows 11 è preinstallato, su Windows 10 aggiornato di solito anche, sui Windows 10 più datati può mancare.

---

## 🤝 In Sintonia perfetta con NINA

L'Agente non calpesta le azioni di NINA. Si pone allo strato sottostante.
**Il Workflow corretto è:**
L'Agente mitiga l'RMS di PHD2 e lo mantiene stabile → NINA, non appena riceve da PHD2 la notifica che l'RMS è rimasto sotto la soglia da te dichiarata (in Opzioni Apparecchiatura → *Settle pixels* e *Settle Time*), è soddisfatta e scatta la foto.
In questo modo ottieni frame ultra-nitidi perché PHD2 è aiutato dall'Agente, e NINA aspetta ad aprire l'otturatore solo quando sa che tutto, sotto di sé, non sta sbandando.

---

## 🔒 In breve: di cosa puoi fidarti

* L'Agente **si configura da solo sul tuo setup**: pixel scale letta dal profilo PHD2, soglie RMS tarate sulla baseline misurata del tuo cielo reale.
* L'Agente **interviene per gradi**: prima le manopole leggere (aggressività, MinMove), poi l'esposizione, e solo come ultima risorsa la visione AI per recuperare la stella.
* L'esposizione **non scende mai sotto la tua base** e ha un tetto massimo: le tue scelte di partenza sono rispettate.
* Le **reti di sicurezza** sulla calibrazione (cap proporzionale + rigetto baseline) impediscono che una serata compromessa "promuova" soglie sbagliate a nuova normalità.
* Le soglie si **adattano nel tempo**: la baseline viene ri-misurata periodicamente con la regola "tightest-wins" — l'Agente si stringe se il cielo migliora, ma non concede mai terreno se peggiora.
* Se chiudi l'Agente o va in crash, un sistema di salvaguardia (*Baseline Guardian*) **ripristina i parametri originali** di PHD2, esposizione compresa.
* L'Agente **non tocca** la compensazione del backlash né altri parametri di calibrazione delicati: lavora solo sulle leve "morbide" e reversibili.
