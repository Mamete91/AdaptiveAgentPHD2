# Roadmap — Telemetria da NINA (camera di acquisizione) → miglioramenti dell'Agente

**Stato:** item di design futuri. NESSUN codice ora. Sbloccati dal recupero del **sorgente C# del plugin NINA** (repo separato, sul PC in riparazione). Tutti valutati contro **P1** (`PRINCIPIO_CONVERGENZA_PRESTAZIONE.md`).
**Origine:** Alessandro Curci, 2026-06-12.

## Premessa architetturale (vale per tutti gli item)

- **Punto di aggancio:** il plugin NINA **esiste già** e gira nel processo di NINA → ha accesso nativo a eventi e statistiche per-posa. L'estensione naturale è che il plugin **inoltri** la telemetria al server HTTP dell'Agente (porta 8080, già attivo). Non serve riscrivere l'architettura: il plugin-display diventa anche **ponte di telemetria** NINA→Agente.
- **Dipendenza opzionale:** oggi il motore legge **solo** da PHD2. Ogni feed NINA dev'essere **facoltativo e graceful** (l'Agente senza NINA non deve risentirne).
- **Tutto va a baseline:** "sotto il range naturale" richiede un riferimento per-target/per-campo (come la baseline RMS). Filosofia P1.
- **Disallineamento di cadenza:** le pose sono lunghe (minuti), la guida gira a 1–2 s. La telemetria NINA è **robusta ma lenta**; la guida è **veloce ma rumorosa**. Regola generale: **fondere, non sostituire** — anello esterno lento (NINA) + anello interno veloce (guida).
- **Vincolo pratico:** serve il sorgente C# del plugin (repo separato). Si progetta ora, si implementa al recupero.

---

## N1 — Rilevatore di trasparenza / nuvole (priorità, già discusso)

Conteggio stelle / SNR / mediana del fondo della camera di acquisizione (ASI2600MM, centinaia di stelle) come **segnale di trasparenza** molto più robusto della singola stella di guida. Una nube → crollo netto di stelle e SNR sotto la baseline del campo.

**Valore P1:** le nuvole **non sono lever-fixable**. Riconoscerle permette al controllore di **non inseguire** l'RMS e di **non scambiare** un calo di trasparenza per seeing/over-correction → diagnosi robusta contro un confondente grosso. È la stessa logica dell'anti-windup.
**Caveat:** cadenza lenta (un dato per posa) → buono per trend di trasparenza, lento sulle nubi veloci → fondere col segnale di guida.

**Indice di trasparenza composito (NON solo conteggio stelle):** le stelle da sole ingannano (cambio filtro, altezza sull'orizzonte, ricchezza del campo). Usare un **blend vs-baseline** di: **conteggio stelle + SNR medio + fondo cielo** (tutti rapportati alla baseline del campo corrente — P1). Forma sensibile per rilevare la velatura sottile prima: `TransparencyIndex = (Stars/Base) × (SNR/Base)` (più reattiva → tarare la soglia di conseguenza). **CORREZIONE importante:** **l'HFR NON entra** nell'indice di trasparenza — l'HFR è un segnale di **fuoco/seeing** (dimensione stella), non di trasparenza; includerlo confonde nuvole e deriva di fuoco. HFR/eccentricità restano segnali separati di qualità/seeing (N3/N4).

## N2 — Context-gating della diagnosi (alto valore, basso rischio)

NINA sa **cosa sta facendo**: autofocus, meridian flip, cambio filtro, slew, plate-solve/centering, dithering. Oggi l'Agente sospende solo su settle PHD2; non sa degli altri eventi → rischia di **interpretare un transitorio operativo come degrado di seeing** e reagire sulle leve.

**Proposta:** il plugin inoltra gli eventi di stato; l'Agente **sospende valutazione e azioni leva** durante autofocus / flip / cambio filtro / slew / plate-solve, riprendendo a transitorio concluso.
**Valore P1:** non agire su transitori che **non sono lever-fixable**. Robustezza pura, rischio minimo. *Probabilmente il miglior rapporto valore/rischio del gruppo.*

## N3 — Anello esterno sull'obiettivo VERO: qualità delle pose (HFR / eccentricità)

L'RMS di guida è un **proxy**. L'obiettivo reale è **stelle tonde e tese nella posa**. NINA misura HFR ed eccentricità di ogni sotto-posa. L'Agente potrebbe quindi **validare le proprie decisioni leva contro l'esito di imaging reale**, non solo contro il proxy RMS.

**Architettura:** controllo **a cascata** — anello interno veloce sull'RMS di guida (vs baseline guida), anello esterno lento che verifica/aggiusta il target contro HFR/eccentricità della posa. È l'espressione più piena di **P1**: "convergere verso la prestazione", dove la prestazione ultima è l'**immagine**.
**Caveat:** cadenza molto lenta (una posa ogni minuti) e confondenti (fuoco, ottica, vento sull'OTA, non solo guida). Resta un anello esterno **lento e di conferma**, non un controllo veloce. Ma è il **nord architetturale** dell'integrazione.

## N4 — Eccentricità → diagnosi di elongazione per-asse

L'eccentricità delle stelle nella posa rivela **elongazione** che l'RMS da solo non vede (si può avere RMS basso ma elongazione da deriva lenta / PE / vento). Correlando l'eccentricità (e la sua direzione) con la guida, l'Agente può capire se le impostazioni correnti producono stelle elongate e **su quale asse** → segnale diagnostico che il proxy RMS non offre.
**Caveat:** cadenza lenta; richiede di mappare l'angolo camera → assi RA/DEC.

## N5 — Target di prestazione informato dal requisito di imaging

NINA conosce **pixel scale di imaging** e **durata della posa**. La "guida abbastanza buona" dipende da quanto l'RMS è invisibile nella posa (scala imaging + durata). L'Agente potrebbe derivare il **target di prestazione** da "quanto deve essere tesa la guida per essere invisibile in QUESTA posa", invece che da una baseline fissa.
**Valore P1:** rende il *riferimento di prestazione* legato al bisogno reale di imaging, non a un numero astratto.
**Caveat:** raffinamento concettuale; utile ma meno urgente di N1/N2.

## N6 — Safety gate sull'imaging: non riprendere light se la trasparenza è crollata (Alessandro, 2026-06-12)

Inutile riprendere/avviare una light se il conteggio stelle della camera di acquisizione è crollato (es. 100 → 30 = nube). Usa il segnale di trasparenza di N1 per **gateare la ripresa delle pose**: ferma quando le stelle scendono sotto soglia, riprendi solo quando risalgono.

**Perché calza bene — due punti:**
- **Il meccanismo esiste già:** il plugin ha il **Safety Monitor virtuale** (§29). Si tratta di **alimentarlo** col segnale trasparenza (stelle vs baseline campo), non di costruirlo.
- **Cadenza perfetta:** la decisione "riprendo la prossima posa?" è **tra una posa e l'altra** → il conteggio stelle per-posa è esattamente quella cadenza. A differenza del controllo leve, qui la lentezza di NINA **non** è un limite. È il match migliore della lista.

**Caveat:**
- **Isteresi obbligatoria:** ferma se stelle < X% baseline per N pose; riprendi se > Y% (Y>X) per M pose → niente flapping sui bordi di nube.
- **Baseline per-target:** gate su % della baseline *del campo corrente*, non su numero assoluto (un campo povero ha naturalmente poche stelle).
- **Confine:** **NINA** mette in pausa (via Safety Monitor); Agente/plugin forniscono solo il segnale safe/unsafe. Integrare, non duplicare, i meccanismi di safety nativi di NINA.

È N1 puntata su un **secondo consumatore** (il gate di sicurezza imaging) tramite il Safety Monitor virtuale esistente. Soglie d'avvio (da tarare, con isteresi): SAFE > 70% baseline · UNSAFE < 50% per 2 pose · RECOVERY > 70% per 2 pose. Il segnale è il **TransparencyIndex composito** (N1), non il solo conteggio stelle.

## N7 — Frame Quality Scoring: tag automatico delle pose (proposto da GPT, 2026-06-12)

Invece di (o **oltre a**) fermare la sequenza, **taggare ogni sotto-posa** col TransparencyIndex (es. `Frame Quality = BAD` quando stelle/SNR sotto soglia) → metadata che WBPP/AutoIntegrate usano per **scartare automaticamente** le pose cattive.

**Perché è forte:** non perdi una schiarita improvvisa, niente stop/start, classificazione oggettiva dei frame. Basso rischio (non disturba la sequenza).
**Relazione con N6 (complementari, non alternativi):** nube **breve** → N7 tagga e si continua a scattare; collasso **prolungato** → N6 mette in pausa. Due livelli, soglie diverse, si fanno entrambi.
**Caveat di fattibilità:** scrivere la qualità *dentro* la posa richiede che l'API plugin di NINA permetta di iniettare una **keyword FITS** per sotto-posa (da verificare); alternativa = file **sidecar** (filename → score) letto dal post-processing. **Integrare, non duplicare:** PixInsight (SubframeSelector/WBPP) già pesa/scarta su SNR/FWHM → il valore aggiunto è un tag **specifico-nuvole** al momento dello scatto.

## N8 — Confidence Factor al motore diagnostico (Jitter/Guardian) (GPT, 2026-06-12)

Il segnale di trasparenza (N1) come **quarto consumatore**: darlo al **motore §31** così che sappia distinguere un RMS che sale per **seeing/over-correction** (lever-fixable → agisci) da uno che sale per **nuvole/velatura** (NON lever-fixable → non agire). Forma proposta: un **Confidence Factor** `0..100` (da trasparenza + star count + SNR + stabilità fondo) che **pesa/congela** le decisioni del motore: alto → decisioni normali; medio → conservative; basso → congela le ottimizzazioni.

**Valore P1 (forte):** è l'anti-windup applicato al confondente nuvole — non agire su ciò che non si può correggere. E **unifica** in un unico scalare il peso `w` del §32 (sampling-aware) e l'outcome-tracking: "quanto mi fido dei dati ora".
**Caveat (priorità!):** (a) è **a valle del fix congelamento** — un Jitter predittivo presuppone un Jitter che gira (oggi INSUFFICIENT ~85% su 3 setup → passeggero); il Confidence Factor su un motore paralizzato non fa nulla. (b) cadenza: fondere col segnale di guida veloce. (c) per il motore la disambiguazione è binaria (lever-fixable o no); la tabella completa qualità-frame è N7.

---

## Architettura a 3 layer (framing, GPT 2026-06-12 — adottato)

- **Layer 1 — Telemetria (grezza):** star count, star SNR, sky background, HFR, eccentricità, RMS PHD2, star-lost. Ogni metrica nel suo **dominio fisico**.
- **Layer 2 — Indici (derivati):** Transparency Index (stelle+SNR+fondo, NO HFR), Seeing Index, Focus Stability, Guiding Health, **Confidence Factor**.
- **Layer 3 — Consumatori (azioni):** N1 (diagnosi nuvole), N6 (pausa), N7 (tag pose), **N8 (motore Jitter/Guardian)**, futuro Safety Monitor.
- **Vantaggio:** scalabile — un nuovo sensore entra nel Layer 1 senza riscrivere la logica. La separazione dei domini fisici (trasparenza ≠ qualità stellare; HFR = fuoco/seeing, non nuvole) è il principio chiave.

---

## Giudizio sintetico (ranking onesto)

| Item | Valore | Rischio/costo | Note |
|---|---|---|---|
| **N2** context-gating | **Alto** | **Basso** | miglior rapporto valore/rischio; robustezza pura |
| **N1** trasparenza/nuvole | Alto | Medio | risolve un confondente grosso; cadenza lenta |
| **N3** anello esterno su HFR/ecc. | **Molto alto (concettuale)** | Alto | nord architetturale di P1; lento, confuso, da fare per ultimo |
| **N4** elongazione per-asse | Medio | Medio | diagnostica che l'RMS non dà |
| **N5** target da requisito imaging | Medio | Medio-basso | raffina il concetto di baseline |
| **N6** safety gate riprendi-light | **Alto** | **Basso** | riusa N1 + Safety Monitor virtuale §29; cadenza perfetta; NINA pausa, agente segnala |
| **N7** frame quality scoring (tag pose) | **Alto** | **Basso** | tagga le pose cattive (TransparencyIndex) per scarto in WBPP; complementare a N6; integra PixInsight, non duplica |

**Sequenza consigliata quando si recupera il plugin:** N2 (subito, robustezza) → **N1 + N6 + N7** (un solo segnale, il TransparencyIndex composito, con tre consumatori: diagnosi robusta, safety-pausa, tag-qualità) → N5 → N4 → N3 (l'anello esterno, come evoluzione finale). Tutti **opzionali e graceful**; quelli sul controllo leve **fusi** col segnale di guida, mai sostitutivi.
