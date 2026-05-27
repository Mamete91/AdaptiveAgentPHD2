# 🌌 Manuale Rapido: PHD2 Adaptive Agent

L'**Adaptive Agent** è il tuo copilota astrofotografico. Lavora "sotto il cofano" assieme a PHD2 e alla tua suite principale (come NINA), agendo come un utente umano molto reattivo che fissa in modo continuativo lo schermo della guida per fare micro-aggiustamenti che ti salvano la nottata.

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

## 🔭 Un Agente, tre telescopi (e i riduttori di focale)

Lo stesso Agente lavora con tutti e tre i tuoi setup, perché sa che ognuno ha una "scala" diversa (quanti secondi d'arco vede ogni pixel di guida). Questo è importante: a focale lunga ha senso intervenire sull'esposizione per il seeing, a focale corta molto meno.

Non devi configurare nulla a mano: per ogni setup esiste un file di avvio (`.bat`) già pronto. Ti basta fare doppio clic su quello giusto. In tutto sono **sei file di avvio**, una coppia per ciascun telescopio:

* **Askar 71F** → `Avvia_Askar71F.bat` (focale piena) / `Avvia_Askar71F_Ridotto.bat` (con riduttore 0,75x)
* **Tecnosky 115/800** → `Avvia_Tecnosky115.bat` (focale piena) / `Avvia_Tecnosky115_Ridotto.bat` (con riduttore 0,80x)
* **RC8** → `Avvia_RC8.bat` (focale piena) / `Avvia_RC8_Ridotto.bat` (con riduttore 0,75x)

> [!TIP]
> Monti il riduttore di focale? Avvia il `.bat` con la dicitura **"_Ridotto"**. Lo smonti? Torna a quello normale. L'Agente ricalcola da solo la scala in secondi d'arco e adatta tutte le sue soglie. **Niente più modifiche manuali al file di configurazione.**

> [!NOTE]
> **Vuoi usare l'Agente con un altro setup (telescopio o camera di guida diversi)?**
> L'Agente è preconfigurato per i tre setup qui sopra. Per adattarlo a una combinazione diversa occorre aggiornare la *scala di campionamento* della camera di guida, che si calcola così:
>
> **scala (arcsec/px) = 206,3 × (dimensione pixel in µm) ÷ (focale di guida in mm)**
>
> Attenzione: un valore errato fa lavorare male la logica dell'esposizione **senza dare alcun avviso**. Per questo, prima di modificare la configurazione, ti consiglio di **richiedere all'autore dell'Agente la procedura guidata e i valori corretti** per il tuo setup.

---

## 🖥️ Come usare la Web Dashboard

La pagina web è la cabina di pilotaggio dove l'Agente ti espone in tempo reale la sua "mente".

* **Grafici e Numeri (RMS / HFD / SNR)**: una supervisione istantanea delle oscillazioni e della nitidezza stellare (condizione del cielo: *DEGRADED*, *OSCILLATING*, *NORMAL*).

* **Pannello "Stato Esposizione & Escalation Gate"** *(novità)*: ti mostra a colpo d'occhio cosa sta facendo l'Agente sull'esposizione e perché.
  * **Badge di stato esposizione**: ti dice in che regime sei — `NOMINAL` (esposizione base), `BOOSTED_FOR_SNR` (alzata perché la stella era debole) o `BOOSTED_FOR_SEEING` (alzata per gradini a causa della turbolenza).
  * **Valori di esposizione**: il tempo di posa corrente in millisecondi e quanti gradini sei sopra la base.
  * **Barre di saturazione delle leve (RA e DEC)**: ti fanno vedere quanto sono "tirate" aggressività e MinMove su ciascun asse. Quando entrambe sono al limite, il *cancello di escalation* è aperto: è il segnale che l'Agente è autorizzato ad allungare l'esposizione.
  * **Cooldown residuo**: i secondi che mancano prima che l'Agente possa fare un nuovo cambio di esposizione (serve a evitare che si agiti troppo).
  * **Marker sul grafico RMS**: ogni cambio di esposizione lascia un triangolino sul grafico (giallo = esposizione alzata, verde = riportata giù), così puoi collegare visivamente "ho cambiato esposizione qui" con l'andamento dell'RMS prima e dopo.

* **Interruttore "AI Finder (Forzato)"**:
  * **Attivo**: ordina all'Agente di intervenire in caso d'emergenza o perdita stella, forzando la visione AI sui sensori (accettando i famosi palloni saturi se non c'è nient'altro a cui aggrapparsi).
  * **Spento**: l'emergenza stella si comporta come il classico PHD2 limitato.

* **Interruttore "MODALITÀ TEST"**:
  > [!TIP]
  > Se `MODALITÀ TEST` (Dry Run) è **ATTIVA**, l'Agente emulerà le sue deduzioni logiche nel "Log Decisioni Controller" dicendoti cosa farebbe, **ma senza agire fisicamente in PHD2**.
  > Spegnila e passa in **`LIVE CONTROL`** per lasciare che l'Agente prenda attivamente il controllo del telescopio.
  >
  > 📌 **Nota**: tutti e tre i setup sono ormai configurati per partire **già in LIVE**, proprio perché il valore dell'esposizione dinamica si vede solo osservandone l'effetto reale sul grafico, non nei log di una simulazione.

* **Log Decisioni Controller**: un tabellone cronologico con i messaggi. Ad esempio: *"RA Aggressività 70 → 65 | Abbasso aggressività perché Oscillazione rilevata"* oppure *"Esposizione 2000ms → 3000ms | Seeing degradato, leve sature"*. Se è vuoto, significa semplicemente che la guida sta performando in modo sano e non serve intervenire.

---

## 🤝 In Sintonia perfetta con NINA

L'Agente non calpesta le azioni di NINA. Si pone allo strato sottostante.
**Il Workflow corretto è:**
L'Agente mitiga l'RMS di PHD2 e lo mantiene stabile → NINA, non appena riceve da PHD2 la notifica che l'RMS è rimasto sotto la soglia da te dichiarata (in Opzioni Apparecchiatura → *Settle pixels* e *Settle Time*), è soddisfatta e scatta la foto.
In questo modo ottieni frame ultra-nitidi perché PHD2 è aiutato dall'Agente, e NINA aspetta ad aprire l'otturatore solo quando sa che tutto, sotto di sé, non sta sbandando.

---

## 🔒 In breve: di cosa puoi fidarti

* L'Agente **interviene per gradi**: prima le manopole leggere (aggressività, MinMove), poi l'esposizione, e solo come ultima risorsa la visione AI per recuperare la stella.
* L'esposizione **non scende mai sotto la tua base** e ha un tetto massimo: le tue scelte di partenza sono rispettate.
* Se chiudi l'Agente o va in crash, un sistema di salvaguardia (*Baseline Guardian*) **ripristina i parametri originali** di PHD2, esposizione compresa.
* L'Agente **non tocca** la compensazione del backlash né altri parametri di calibrazione delicati: lavora solo sulle leve "morbide" e reversibili.
