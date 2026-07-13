# Casi studio — come sono nate le idee dell'Adaptive Agent

> **Memoria storica, non documentazione tecnica.** Qui non c'è *come funziona* il codice (per quello ci sono `ARCHITETTURA_MOTORE.md` e i sorgenti), ma **come ci siamo arrivati**: l'osservazione che ha fatto scattare l'idea, cosa abbiamo capito, cosa abbiamo deciso, e com'è andata a finire. È il diario delle scelte del progetto.
>
> **Documento vivo.** Ogni volta che nasce una decisione importante — spesso da una notte sotto il cielo o da un'analisi dei log — aggiungiamo un caso. Fra un anno questo racconterà l'evoluzione dell'Adaptive Agent meglio di qualsiasi changelog.
>
> Il filo comune è sempre lo stesso: **Osservazione → Analisi → Validazione → Implementazione.** Nessuna di queste idee è nata a tavolino.

---

## 1. Il bug delle unità: pixel contro arcsec (§36)
**Osservazione.** La guida sembrava mediocre (~2″) e il motore continuava a diagnosticare SEEING e a rifiutare la baseline, come se il cielo fosse sempre brutto.

**Cosa abbiamo capito.** Le distanze `GuideStep` di PHD2 sono in **pixel**; il motore le confrontava con soglie in **arcsec**. Su una scala di guida grossolana (es. 1,58″/px), un MinMove/soglia "in pixel" diventava una **banda morta enorme** in cielo → il motore sotto-correggeva e leggeva male il proprio RMS. Era, di fatto, cieco per un problema di unità.

**Decisione.** Convertire px→arcsec **all'ingresso** (§36), così tutte le soglie ragionano in unità di cielo.

**Com'è andata.** Sull'RC8 la guida è passata da ~2″ a ~0,9″, e la saga dei "rifiuti di baseline" è finita. *Lezione: un parametro cieco alla scala è un killer silenzioso — si ragiona sempre in arcsec.*

## 2. La spirale dell'ammorbidimento e la baseline bidirezionale (§44)
**Osservazione.** In alcune notti la guida peggiorava lentamente e le leve scivolavano al pavimento morbido: aggressività DEC al minimo, MinMove gonfiato fino a ~1,34″ di cielo — più largo dell'RMS obiettivo.

**Cosa abbiamo capito.** Un anello di retroazione positivo: RMS↑ → letto come DEGRADED_SEEING → ammorbidisco → sotto-correggo → RMS↑. E la baseline RMS **non poteva salire** (il vecchio "tightest-wins" la teneva al minimo storico), quindi la soglia non si adattava a una notte che peggiorava → SEEING spurio.

**Decisione.** §44: una baseline **continua e bidirezionale**, che può **salire** col peggiorare del seeing (tolto il tightest-wins).

**Com'è andata.** La soglia ora segue la notte; il driver principale della spirale è sparito. *Lezione: un riferimento che sa solo stringere prima o poi litiga con la realtà.*

## 3. La scoperta dell'airmass
**Osservazione.** Durante una lunga sequenza, il conteggio delle stelle spesso **calava** gradualmente. Primo istinto: nubi, velature.

**Cosa abbiamo capito.** Dopo mesi di prove sotto il cielo reale è emerso che spesso non erano nubi: era semplicemente il target che **scendeva verso un airmass maggiore** (più atmosfera → meno stelle deboli). Un calo di stelle **non è sempre foschia.**

**Decisione.** Il contesto — l'altezza/airmass del target — deve entrare nel ragionamento; non si tratta ogni calo di stelle come lo stesso evento.

**Com'è andata.** È l'intuizione che ha plasmato N1 (vedi caso 4) e che gli permette di evitare falsi allarmi "nubi". *Nota: è la scoperta di campo che ha colpito anche i maintainer — nessuna simulazione te la regala, solo le ore vere.*

## 4. Come è nato N1 (trasparenza): due occhi invece di uno
**Osservazione/problema.** Il degrado della guida ha molte cause (seeing, deriva, meccanica, nubi) e un solo segnale non le distingue. PHD2 vede solo il **movimento** della stella di guida: non sa nulla della trasparenza del cielo sul frame di ripresa.

**Cosa abbiamo capito.** NINA invece lo sa — conteggio stelle, fondo, HFR per ogni posa. Incrociando **due strumenti indipendenti**: una vibrazione della montatura si vede nella stella di guida (PHD2); una velatura si vede come meno stelle nel frame (NINA) ma spesso *non* nel movimento della guida → quando i due **non concordano**, è proprio quel disaccordo a identificare la causa.

**Decisione.** N1 = riconoscitore di trasparenza dalla telemetria NINA; **unico** riconoscitore delle nubi; consumato da N8 (confidence) e N6 (safety).

**Com'è andata.** Implementato e confermato sul campo: una notte N1 ha correttamente riclassificato da VELATURE a CIELO LIMPIDO (indice 0,90) mentre il cielo si schiariva e il target era basso. *Lezione: due occhi indipendenti separano ciò che un occhio solo non può.*

## 5. Perché l'Adaptive MinMove è cambiato (§51)
**Osservazione.** Serviva un tetto al MinMove perché non esplodesse in una banda morta enorme (la spirale del caso 2). Prima proposta: un **cap assoluto fisso** (es. 0,5″).

**Cosa abbiamo capito.** Alessandro (con GPT) ha obiettato giustamente: un cap fisso **reintroduce la rigidità** che il §44 aveva appena tolto. Il MinMove è una soglia di inseguimento che dipende legittimamente dal seeing/scala — su certi setup 0,8–1,0″ è corretto.

**Decisione.** cap = **k × baseline filtrata** (k<1, un rapporto → indipendente dalla scala per costruzione), con un tetto separato legato alla scala di imaging per i setup esigenti.

**Scintilla successiva.** Lo studio del sorgente di PHD2 ha rivelato che il **Guide Assistant di PHD2 fissa già il MinMove come percentile del seeing misurato** (un "tasso di attività" obiettivo) → possibile evoluzione futura: esprimere `k` come duty-cycle invece che come numero fisso.

**Com'è andata.** Cap adattivo attivo; la versione duty-cycle è sullo scaffale. *Lezione: una fix che incastra un numero fisso spesso rirompe l'adattività che avevi appena costruito.*

## 6. Come è nato §53 (il recupero simmetrico)
**Osservazione.** Una notte (2 luglio), durante una degradazione di seeing simulata, il motore ha ammorbidito bene; ma **dopo** la simulazione, con l'RMS tornato quasi alla baseline, le leve sono rimaste spalancate: l'aggressività **non è mai risalita in sessione** (0 azioni in ~21 minuti). Solo un crash della camera + INIT le ha riportate allo standard.

**Cosa abbiamo capito (nel codice).** L'ammorbidimento aveva trigger forti ed espliciti; il recupero, per l'aggressività, **non esisteva**. Il "recupero banda morta" (§32) in realtà *alzava* il MinMove (un secondo ammorbidimento), e l'aggressività risaliva solo nel CASO3, gated a RMS già ottimo. Nella banda intermedia le leve restavano inchiodate morbide: un control-law **asimmetrico**.

**Decisione.** §53 — recupero **bidirezionale guidato dall'esito**: se le leve sono morbide e la guida è stabile, prova a irrigidire verso lo standard, tieni se l'RMS regge/migliora, torna indietro altrimenti; esteso **anche all'aggressività**.

**Com'è andata.** Validato sul campo: l'aggressività ora recupera in pochi minuti e **converge a un RMS buono senza forzare il ritorno ai valori pre-simulazione** (P1 in azione). Confermato bilanciato su più notti (aggressività su ≈ giù). *Lezione: un controllore che sa solo ammorbidire non è un controllore — gli serve la strada del ritorno.*

## 7. Come è nato GUARDIAN (e perché JITTER è tramontata)
**Osservazione.** Il motore diagnostico §31 era nato con l'idea che la **diagnosi pilotasse** le leve: la modalità JITTER lo rendeva unica autorità, sospendendo la catena CASO. Nella pratica, però, il classificatore di cause si è rivelato fragile — i riferimenti di calma si formavano a fatica, l'HFD sulla camera di guida è cieco al seeing, la sovra-correzione scattava rarissimamente, e un trend di deriva veniva scambiato per oscillazione.

**Cosa abbiamo capito.** Dare l'**autorità esclusiva** a un classificatore fragile ne **amplifica gli errori**. Ma la *diagnosi* in sé aveva valore. Quindi la svolta: tenere il **cervello diagnostico** e farlo **vigilare** invece di pilotare. Nasce **GUARDIAN**: il controllore di base validato pilota, e il motore §31 conferma / attenua / blocca ogni mossa e aggiunge micro-correzioni nei buchi. Stesso cervello, rischio limitato. Ed è coerente con l'Outcome-First: reagisci all'esito, non lasciare che un classificatore non validato guidi da solo.

**Decisione.** GUARDIAN diventa la **modalità ufficiale**. JITTER resta la strada non presa — e più tardi viene **deprecata** (§54): scavalca tutta la macchina validata (compreso il §53) e stava a un clic dalla dashboard. Codice non cancellato, solo dormiente e irraggiungibile per sbaglio.

**Com'è andata.** GUARDIAN è la modalità su cui gira e si valida tutto il lavoro recente; sul campo fa il vigile giusto — sotto buon seeing non fa nulla, e interviene solo quando serve. *Lezione: una diagnosi può consigliare senza avere il permesso di guidare da sola.*

## 8. La pivot fondativa: da Classification-First a Outcome-First
*(la scoperta che sta sotto tutte le altre)*

**Osservazione.** All'inizio il motore ragionava così: capisco la causa del degrado → muovo le leve di conseguenza. Ma un classificatore di cause, sul campo, sbaglia; e ogni suo errore diventava un'azione sbagliata sulle leve.

**Cosa abbiamo capito.** Un problema *vero* si manifesta comunque come **esito peggiore**. E se una causa presunta non peggiora il risultato, per il motore **non dovrebbe esistere**. Quindi: reagire all'**esito misurato**, non alla causa pre-classificata. Le etichette di causa (SEEING, DERIVA, nubi) diventano *consigli sulla direzione da provare*, non ordini.

**Decisione.** **Outcome-First**: prova un aggiustamento, misura se l'RMS migliora, tieni ciò che aiuta, **torna indietro** ciò che non aiuta. Da qui discendono il satisfaction-gate (guida buona = non toccare), il recupero §53, la supervisione GUARDIAN, il "default = non fare nulla".

**Com'è andata.** È diventata l'**identità** del progetto — ed è esattamente ciò che il confronto con Dale ci ha costretto a mettere in parole. *Lezione: misura il risultato, non fidarti dell'etichetta.*

## 9. Il ruolo del Guide SNR: il segnale veloce contro le metriche lente di NINA
**Osservazione.** Due fonti di informazione hanno **cadenze diverse**. PHD2 dà dati a ogni frame di guida (ogni paio di secondi), incluso l'**SNR della stella di guida**. NINA (HFR, conteggio stelle, statistiche immagine) arriva solo a **fine posa**, cioè dopo minuti.

**Cosa abbiamo capito.** Non si può aspettare NINA per reagire a un evento rapido: si arriverebbe minuti in ritardo. Il **segnale veloce** (la stella di guida, il suo SNR) serve per **reagire**; NINA è il **contesto lento e ricco** che *conferma e classifica* ciò che il segnale veloce ha già intercettato. Da qui anche la gestione della "freschezza": tra una posa e l'altra la telemetria NINA è stantia → fail-safe, niente falsi allarmi.

**Decisione.** Reazione sul segnale rapido di PHD2; contesto e classificazione sul segnale lento di NINA. I due lavorano su scale temporali diverse, per progetto.

**Com'è andata.** È il motivo per cui il motore non "dorme" aspettando la posa successiva, e insieme non impazzisce quando NINA tace tra un light e l'altro. *Lezione: abbina il segnale alla scala temporale — una reazione veloce vuole un segnale veloce.*

## 10. NINA osserva, PHD2 controlla, il motore decide
**Osservazione.** All'inizio NINA era vista come "telemetria aggiuntiva", un di più.

**Cosa abbiamo capito.** Era una descrizione debole. La chiarezza è arrivata come **principio a strati**: **NINA osserva** (il lato imaging — trasparenza, qualità delle stelle); **PHD2 controlla** (il loop di guida); **il motore decide** e regola *solo* le sue due leve. NINA non comanda mai la montatura né la guida — porta solo contesto. È anche la risposta onesta al "perché NINA?": non per sostituire i dati di PHD2, ma per aggiungere l'unica cosa che PHD2 non può vedere.

**Decisione.** Separare i ruoli in modo netto e tenerli ortogonali (controllore base + supervisione + contesto NINA). Ha guidato anche la ridefinizione di N2 come "contesto di acquisizione".

**Com'è andata.** L'architettura è leggibile e difendibile proprio perché ognuno fa una cosa sola. *Lezione: separa chi osserva, chi decide, chi controlla — e tienili puliti.*

## 11. Il Safety Monitor come dispositivo virtuale (riportare, non comandare)
**Osservazione.** Quando il motore riconosce le nubi (via N1), c'era la tentazione di farlo **comandare** direttamente NINA — "fermati".

**Cosa abbiamo capito.** Un plugin che comanda l'attrezzatura è invasivo e toglie il controllo all'utente. Molto meglio esporre un **Safety Monitor virtuale** (un device ASCOM che NINA consulta come qualsiasi altro): il motore **riporta** lo stato ("unsafe", con la causa), e **NINA decide** cosa fare secondo la *policy di sicurezza dell'utente*. Fail-safe: se il motore è offline o la telemetria è stantia, la condizione resta neutra — niente falsi "unsafe".

**Decisione.** N6 = Safety Monitor che *segnala*, non che *comanda*. Si integra col trigger nativo di NINA (Trigger On Unsafe su 3.3), fermando la ripresa senza muovere il telescopio.

**Com'è andata.** L'utente resta al comando, e il plugin rispetta il modello di sicurezza di NINA invece di scavalcarlo. *Lezione: riporta lo stato, lascia decidere all'host — non prenderti il controllo.*

## 12. La metodologia di validazione live (invece dello shadow mode)
**Osservazione.** Per una logica nuova la tentazione era tenerla in "shadow mode" (solo log) per lunghi periodi prima di fidarsi.

**Cosa abbiamo capito.** Una logica che puoi **vedere decidere in diretta**, con **rollback istantaneo** e **passi piccoli**, è più sicura *e* più veloce da validare di uno shadow mode che non puoi verificare fino in fondo. NINA è un secondo occhio, non una fonte di rischio.

**Decisione.** Le feature che toccano il motore nascono **operative + visibili in tempo reale + reversibili (kill-switch) + ad ampiezza limitata**, e si validano **sul cielo reale**, non log-only.

**Com'è andata.** È il metodo con cui sono nati §44/§50/§51/§53 e il filone NINA — ed è anche un buon argomento di serietà verso i maintainer: validazione live *bounded*, con rollback, non azzardi. *Lezione: una validazione live limitata, osservabile e reversibile batte uno shadow mode opaco.*

## 13. §50 INIT: partire da uno stato noto per log confrontabili
**Osservazione.** Il motore ereditava le leve che trovava in PHD2 all'avvio (sessione precedente, ritocchi manuali, diverse per ogni tester) → uno start **non riproducibile**.

**Cosa abbiamo capito.** Tutto il nostro metodo si basa sul **validare-sui-log**: se ogni sessione parte da un punto diverso, i log **non sono confrontabili** tra notti e tra beta-tester. Serviva un punto di partenza comune.

**Decisione.** §50 INIT: all'avvio guida, porta le leve ai **valori standard PHD2** (stato noto), poi forma la baseline. Il Baseline Guardian salva e ripristina i valori dell'utente, così non si sovrascrivono scelte deliberate.

**Com'è andata.** I log delle diverse notti e dei diversi setup sono finalmente confrontabili — la base su cui poggia tutta l'analisi. *Lezione: non puoi confrontare esperimenti che non partono dallo stesso posto.*

---
*Come aggiungere un caso: quando una notte o un'analisi fa nascere una decisione, scrivi un nuovo blocco con lo stesso schema — Osservazione · Cosa abbiamo capito · Decisione · Com'è andata · Lezione. Corto, umano, vero. È il racconto del progetto, non il suo manuale.*
