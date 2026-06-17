# Punto focale del progetto e priorità — 2026-06-16

Bussola dello stato attuale dopo la chiusura della fase bug-fix (§32→§36), con le priorità che avevamo accantonato. Si legge insieme a `ROADMAP_TELEMETRIA_NINA.md` (che aggiorna nei vincoli) e a `PRINCIPIO_CONVERGENZA_PRESTAZIONE.md` (P1).

## 1. Dove siamo

La fase di correzione bug è **chiusa e validata sul campo** (RC8/CEM70G, notte 2026-06-16). La catena di misura della guida è ora sana e affidabile:

- **§36** — l'RMS è finalmente in arcsec veri (prima erano pixel etichettati arcsec). Conseguenza enorme: le tre ottiche sono ora **confrontabili tra loro**, le soglie assolute (cap, reject) hanno senso fisico, e la baseline è reale. RC8: mediana 0,83″ stabile per 3 ore.
- **§34** — il "motore congelato all'85%" era un artefatto di cadenza/logging, non una paralisi. Ora INSUFFICIENT è ~21% sui frame valutati e la baseline si forma in ~5 minuti.
- **§32/§33/§35** — recupero MinMove dalla banda morta, baseline che si forma sempre, riselezione stella su saturazione Path B. Tutti default-on.
- Entrambi i repo (Agente Python + plugin C#) sono su GitHub.

In una riga: **l'Agente ora misura bene e ragiona su numeri reali.** Era il prerequisito per tutto il resto.

## 2. Chiusura del lato guida (residui piccoli, da fare prima di aprire il fronte NINA)

- **§37 — HFD declassato a informativo** (prompt pronto). Toglie un gate cieco; basso rischio. Da eseguire e validare una notte.
- **Trigger rms_high troppo zelante.** Con le soglie ora correttamente strette (rms_high ≈ 0,88″), l'Agente reagisce al quartile alto di RMS e ammorbidisce fino alla sponda (MinMove ~0,8, DEC aggression al pavimento) pur con guida buona. La cura **non** è allargare i limiti leva (rischio sotto-correzione/deriva DEC), ma rendere il *trigger* meno reattivo (es. rms_high a ~1,4–1,5× baseline invece di 1,3×) **e** la disciplina P1 "ammorbidisci solo se migliora davvero". Da tarare come A/B, una variabile per volta.
- **§35 Path B** — implementato ma **non ancora esercitato in campo** (stanotte esposizione ferma a 2s, niente saturazione). Da verificare in una notte in cui Path B scatta.
- **Cosmetico:** colori-soglia fissi della dashboard non per-setup (un RC8 a 0,9″ si accende rosso pur essendo buono).
- **Da archiviare:** la proposta **§32 HFD sampling-aware** è di fatto **superata** — l'HFD della camera di guida è cieco al seeing a queste scale (deciso §37); il segnale di seeing vero arriverà dalla camera di ripresa (sotto). Non serve più il modello di weighting sampling-aware.

## 3. La svolta strategica: telemetria dalla camera di ripresa (NINA)

Questo è il vero fronte aperto, e oggi è **sbloccato e su base solida**:

- **Sbloccato:** il sorgente C# del plugin è stato recuperato e messo su GitHub. La roadmap NINA non è più "in attesa del plugin".
- **Su base solida:** §36 (RMS in arcsec, confrontabile) e §34 (motore che gira davvero) erano prerequisiti — fondere un segnale NINA con un RMS in unità sbagliate, o darlo a un motore paralizzato, sarebbe stato costruire sulla sabbia. Ora la fusione ha senso.

**L'obiettivo NON è "misurare il seeing".** È **disambiguare**: quando l'RMS peggiora, è *atmosfera*, *meccanica* (vento/backlash/bilanciamento/cavo) o *trasparenza* (velature/nubi)? L'RMS di guida da solo non lo può dire — jitter e lag1 nascono dagli stessi dati di posizione. Serve un canale **ortogonale**, e quel canale è la **forma reale delle stelle sul light frame** (camera di ripresa), che la camera di guida non vede.

## 4. Step 0 obbligatorio (gating di tutto N1–N8)

Prima di qualunque feature NINA serve estendere il **plugin C#** perché, a ogni light salvato, catturi le metriche che NINA già calcola (HFR medio, conteggio stelle, SNR, fondo cielo, eccentricità) e le **inoltri al server :8080 dell'Agente** (il plugin è già un ponte WebView su quel server — diventa anche ponte di telemetria). Feed **opzionale e graceful**: senza NINA l'Agente lavora come oggi. È la prima cosa concreta da fare, ora possibile.

## 5. Priorità NINA consigliate (aggiorna il ranking della roadmap)

Ordino per **valore × basso rischio × cadenza adatta**, non per "metrica più affascinante".

1. **N2 — Context-gating** (il miglior rapporto valore/rischio). Il plugin dice all'Agente quando NINA sta facendo autofocus / meridian flip / cambio filtro / slew / plate-solve → l'Agente **sospende** valutazione e azioni leva durante quei transitori, invece di scambiarli per degrado. Pulisce molti falsi "peggioramenti" a costo quasi nullo.
2. **N1 — Indice di trasparenza** = blend vs-baseline di **conteggio stelle + SNR + fondo cielo** (NON l'HFR: la trasparenza è un dominio fisico diverso dalla dimensione stellare). Un solo segnale che alimenta tre consumatori: **N6** (pausa di sicurezza se la trasparenza crolla, via Safety Monitor virtuale §29 già esistente) e **N7** (tag di qualità per-posa per lo scarto in WBPP). Cadenza per-posa perfetta per questi usi.
3. **N8 — Confidence Factor al motore** — **ora sbloccato** (prima era a valle del fix congelamento, fatto col §34). Dà la trasparenza al motore §31 perché distingua un RMS che sale per seeing/over-correction (lever-fixable → agisci) da uno che sale per nubi (NON lever-fixable → congela). È l'anti-windup applicato al confondente-nuvole.
4. **N4/N3 — HFR + eccentricità (l'anello esterno, il "nord" architetturale).** Qui sta la disambiguazione vera atmosfera-vs-meccanica (RMS↑+HFR↑ = seeing; RMS↑+HFR piatto = meccanica) e l'elongazione per-asse (stelle tonde-ma-grosse = seeing; allungate = guida/PE/flessione). **Massimo valore concettuale, ma lento e confuso** (cadenza per-posa, confondenti: fuoco, ottica, vento sull'OTA; serve mappare angolo camera→assi RA/DEC). Va trattato come **anello esterno di conferma e contesto**, non come controllo veloce → si fa **dopo** le vittorie economiche sopra.
5. **Più avanti:** N5 (target derivato dal requisito di imaging) e HFR per-filtro (fuoco/tilt/cromatismo). Non prioritari.

## 6. Dove sfumo il parere di GPT

GPT mette **HFR medio come priorità #1**. Sono d'accordo che l'HFR/eccentricità siano il **segnale di maggior valore** per la disambiguazione — è la stessa intuizione del progetto. Ma come **priorità di esecuzione** non è il primo passo, per tre motivi: (a) è **lento e confuso** → utile come anello esterno, non come driver veloce delle leve; (b) le vittorie a basso rischio (context-gating, trasparenza) tolgono prima i confondenti grossi a costo minore; (c) richiede baseline per-target + mappatura angolo camera. E soprattutto: **l'HFR non è un segnale di trasparenza** — tenere separati i domini fisici (trasparenza = stelle/SNR/fondo; qualità stellare = HFR/eccentricità) è il principio che evita di confondere una nube con una deriva di fuoco. Quindi: HFR/eccentricità = **la destinazione strategica**, ma sequenziata dopo context-gating e trasparenza.

---

**Sintesi operativa:** chiudi il lato guida (§37 + ritocco trigger rms_high, validazione §35), poi apri il fronte NINA con lo **Step 0** (plugin che inoltra le metriche per-posa), e procedi **N2 → N1+N6+N7 → N8 → N4/N3**. Tutto opzionale/graceful e, sul controllo leve, **fuso** col segnale di guida, mai sostitutivo (P1).
