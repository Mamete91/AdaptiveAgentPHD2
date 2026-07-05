# Riflessioni sulla roadmap NINA dopo lo Step 0 — esperienza di campo (Alessandro) + framing tecnico (Cowork)

**Data:** 2026-06-18 · Si legge con `ROADMAP_TELEMETRIA_NINA.md` e `REVISIONE_ARCHITETTURALE_v2.6.md`.
**Scopo:** fissare, prima di procedere oltre lo Step 0, le considerazioni di campo di Alessandro e come Cowork le inquadra. Diventa la base condivisa per la sequenza N2→N1/N6/N7→N8→N3/N4. **Regola di progetto sempre attiva:** separare *qualità della guida* da *correttezza della diagnosi*; ogni item che tocca il modello decisionale passa dal gate di validazione (≥3–4 sessioni, più setup, esclusione cause manuali).

---

## N2 — Context gating: NON uniforme. Il valore vero è l'autofocus.

**Osservazione di campo (Alessandro):** durante meridian flip e slew PHD2 interrompe già la guida → l'Agente smette naturalmente di ricevere GuideStep significativi; l'autofocus è il caso interessante; plate-solve e cambio filtro sono ambigui e dipendono dalla sequenza.

**Framing Cowork — d'accordo, e il meccanismo lo conferma:**
- **Flip / slew → valore basso.** La guida si ferma (PHD2 emette GuidingStopped/StartGuiding); l'Agente è già "cieco" durante l'evento e, alla ripresa, **§39 azzera già i riferimenti** su `guiding_restart`. N2 qui aggiunge poco. Al più un controllo che il reset post-evento scatti — già coperto.
- **Autofocus → valore ALTO, e per TE in particolare.** Tutti e tre i tuoi setup sono **OAG**: la camera di guida condivide il fuoco dell'OTA principale → quando NINA muove il fuocheggiatore, **la stella di guida si sfuoca** (HFD esplode, SNR cala, a volte star-lost). E spesso **la guida CONTINUA durante l'AF** → l'Agente continua a ricevere GuideStep *contaminati* e potrebbe scambiarli per degrado di seeing. È esattamente l'opposto di flip/slew (lì la guida si ferma; qui continua su dati falsati). Per questo l'AF è il caso che giustifica N2.
- **Plate-solve / cambio filtro → valore basso, opzionale.** Brevi, spesso con guida in pausa, dipendenti dalla sequenza. Non prioritari.

**Conseguenza sul design:** N2 si restringe da "sospendi su tutti gli eventi" a **"il gate dell'autofocus"** (più, opzionale, gli eventi lunghi/ambigui). Più preciso e più economico di quanto immaginato.

**⚠️ AGGIORNAMENTO 2026-06-19 — N2 PARCHEGGIATO.** La doc ufficiale NINA (Advanced → Auto-Focus → *AF Disable Guiding*): *"For OAG or belt focuser users, it may be better to have this option set to On."* Con quel flag **ON** (raccomandato per OAG → la config di Alessandro su tutti i setup) **la guida si ferma durante l'autofocus** → l'Agente non riceve GuideStep → si ferma da solo, e §39 azzera i riferimenti alla ripresa. Quindi **N2 è ridondante nella configurazione raccomandata**: il problema non esiste. N2 resta solo un **fallback a bassa priorità** per chi tiene `AF Disable Guiding = Off` (tipico non-OAG). **Best practice (utente, non codice): per OAG tenere il flag ON.** Se un domani si farà N2, FASE 0 di verifica del segnale AF contro l'SDK installato + docs (possibile sorgente: i log AF JSON in `%LOCALAPPDATA%\NINA\Autofocus\`).

---

## N1 — Transparency Index: la latenza è OK perché i suoi consumatori sono lenti

**Osservazione (Alessandro):** PHD2 a 1–2 s, pose a 120/180/300 s → segnale decine/centinaia di volte più lento. Come si usa con questa latenza?

**Framing Cowork:** la latenza è **adatta**, perché i consumatori di N1 lavorano alla stessa cadenza lenta:
- **N6** ("avvio la prossima posa?") è una decisione **tra una posa e l'altra** → la cadenza per-posa è esatta, nessun disallineamento.
- **N7** (tag della posa) è per-posa per definizione.
- **N8** è un controllo su un **confondente lento** (le nuvole persistono per minuti) → un dato per-posa è sufficiente a dire "gli ultimi minuti erano velati".
- Il disallineamento morderebbe **solo** se usassimo la trasparenza per pilotare una leva *veloce* — e non lo facciamo (P1: fondere, non sostituire).

**Sintesi che risolve la latenza (due-velocità):** un proxy di trasparenza **veloce esiste già** — l'**SNR della stella di guida** di PHD2 (per-frame, 1–2 s, già nello snapshot). Quindi: **canale veloce/rumoroso (guide-SNR)** = allerta precoce; **canale lento/robusto (NINA: conteggio stelle + SNR su centinaia di stelle)** = conferma. Il guide-SNR segnala un calo improvviso in 2 s; NINA conferma se è vera perdita di trasparenza o un glitch della singola stella. N1 produce un **TransparencyIndex lento** (vs baseline per-campo) per lo *stato/trend*, non per il controllo istantaneo.

---

## N6 / N7 — Valore immediato e universale. Confermato.

**Framing Cowork — pieno accordo, sono gli item più tangibili per gli utenti finali:**
- **N6 (pausa su crollo trasparenza):** riusa il **Safety Monitor virtuale già esistente** nel plugin. Oggi il `SafetyDecisionEngine` ha **una sola condizione** (STAR_LOST) → si aggiunge la condizione "trasparenza crollata" con **isteresi** (avvio: SAFE >70% baseline, UNSAFE <50% per 2 pose, RECOVERY >70% per 2 pose). Confine invariato: **NINA mette in pausa**, il plugin fornisce solo safe/unsafe.
- **N7 (tag qualità per-posa):** gancio **verificato su GitHub** → `IImageSaveMediator.BeforeFinalizeImageSaved` espone `AddImagePattern(...)` → si inietta una keyword/pattern di qualità nella posa al salvataggio → WBPP/SubframeSelector la scartano in automatico. Complementare a N6: nube **breve** → N7 tagga e si continua; collasso **prolungato** → N6 mette in pausa.

---

## N8 — Confidence Factor: NINA come osservatore indipendente. Hai colto il principio esatto.

**Tua sintesi (corretta):** non usare NINA per pilotare le leve, ma come **osservatore indipendente** che dice se la diagnosi del motore è plausibile. RMS↑ + jitter↑ → il motore direbbe SEEING; ma se contemporaneamente stelle↓ + SNR↓ → parte del degrado è **nuvole**, non seeing.

**Framing Cowork — è esattamente il design, e aggiungo due cose:**
1. **Dove si innesta:** il motore ha già il flag `confidence_calibrated` (oggi sempre `False`, confidence = pura formula). La trasparenza diventa il **calibratore**: confidence bassa → il motore **congela le ottimizzazioni** (anti-windup applicato al confondente-nuvole). Non inietta MAI dati NINA nella matematica delle leve — modula solo *quanto fidarsi/agire*.
2. **Sottigliezza fisica che RAFFORZA N8:** trasparenza e seeing non sono perfettamente ortogonali — una velatura abbassa l'SNR → centroide più rumoroso → **jitter di guida genuinamente più alto**. Quindi "stelle↓ + jitter↑" può essere "le nuvole *causano* il jitter", non solo coincidenza. Ma l'**azione corretta è la stessa**: a trasparenza calante, abbassa la confidence e **non** ammorbidire aggressivamente le leve (il degrado è a monte/atmosferico, non lever-fixable). La conclusione di N8 è robusta a prescindere dal percorso causale. È l'item più P1 della lista.

**Disciplina:** N8 cambia il comportamento decisionale → **gate di validazione obbligatorio**. Spedirlo prima **osservativo** (logga il fattore, non agisce), poi gating reale dopo conferma multi-sessione/multi-setup. È a valle del motore-che-gira (sbloccato da §38/§39).

---

## N3 / N4 — HFR / eccentricità: hai ragione. Mai in assoluto; solo differenziale e contestualizzato.

> **⚠️ Compatibilità NINA 3.2 vs 3.3 (chiarito 2026-06-18):** `Eccentricity` e `FWHM` **esistono solo in NINA 3.3** (beta), **non in 3.2.0.9001** (stable; il compilatore di Code, che builda sul PC dev Lenovo/3.2, l'ha confermato). MA gli utenti dell'Agente sono **divisi tra 3.2 e 3.3** (3.2 ufficiale, 3.3 beta scaricabile) → il plugin deve girare su **entrambe**. Quindi N4 **non è bloccato dall'hardware** (il PC di campo Minixz100 È già 3.3): serve solo che il plugin legga `Eccentricity`/`FWHM` via **reflection con fallback** (presenti su 3.3 → letti; assenti su 3.2 → `null`), costruendo contro l'SDK 3.2 (lowest common denominator → una sola DLL per tutti). Quindi: **N3 (HFR↔RMS) ora su entrambe**; **N4 (eccentricità) appena il plugin aggiunge la lettura reflection** — su 3.3 funziona, su 3.2 degrada a null. Il campo `fwhm`/`eccentricity` lato Agente è già nullable (forward-ready).

**Tua perplessità (giusta):** HFR è potente ma contaminato (seeing, fuoco, altezza, dispersione, filtro, trasparenza, durata posa, qualità ottica nel campo). Difficile usarlo come indicatore causale "pulito". Come normalizzarlo prima che diventi input decisionale?

**Framing Cowork — concordo in pieno; il progetto ha GIÀ imparato questa lezione** con l'HFD della camera di guida (§37: declassato a informativo perché l'HFD *assoluto* a quella scala non dice nulla). Non ripeterla con l'HFR di ripresa. La contestualizzazione che propongo, in 4 mosse:

1. **Mai assoluto, sempre relativo a baseline per-target E per-filtro** (come la baseline RMS §33). Conta la **deviazione** dell'HFR dal valore recente di *questo* campo/filtro, non il numero.
2. **Differenziale e correlato nel TEMPO con la guida.** Il potere diagnostico non è il valore di HFR, è il **co-movimento HFR↔RMS nella stessa finestra**: RMS↑ **e** HFR↑ (entrambi vs baseline) = **atmosferico/seeing**; RMS↑ con **HFR piatto** = **meccanico** (guida/PE/flessione/vento sull'OTA). Il differenziale **cancella** i confondenti lenti (la deriva di fuoco è lenta/monotòna → si detrenda; altezza/dispersione cambiano piano; il filtro è noto).
3. **L'eccentricità è il segnale più pulito per la domanda di guida:** stelle tonde-ma-grosse = seeing/fuoco; stelle **allungate** = tracking/PE/flessione. La **direzione** dell'eccentricità → RA vs DEC (richiede la mappatura angolo camera→assi, un costo reale). Meno contaminata dall'SNR/trasparenza dell'HFR per la domanda di elongazione.
4. **Segmenta per i confondenti noti, non combatterli:** filtro **noto** (baseline per-filtro); durata posa **nota** (normalizza); fuoco **lento** (detrend/high-pass).

**Ruolo e staging (P1 + "osserva→analizza→valida→implementa"):** N3/N4 nasce come **anello esterno di VALIDAZIONE**, non come driver di leve. Il suo primo compito è **validare le diagnosi del motore** (chiude il debito di correttezza §3.3 della revisione), misurato in modo osservativo su più sessioni, **prima** di diventare input decisionale.
- **Fase A — osservativa:** logga HFR/ecc vs baseline per-target/filtro accanto alle diagnosi del motore; **misura** se RMS↑+HFR↑ coincide davvero con motore=SEEING, e se l'eccentricità segnala i casi DRIFT/meccanici.
- **Fase B — solo dopo conferma multi-sessione:** usalo come input di confidence/validazione. **Mai** cablare l'HFR grezzo in una decisione.

**Bottom line:** è l'area più promettente E più delicata, esattamente come la senti. La disciplina che la rende sicura è una sola: **differenziale + per-contesto + osservativa-prima**.

---

## Sintesi della sequenza, aggiornata

| Item | Valore per tutti | Azione | Note di framing |
|---|---|---|---|
| **N2** | Medio (alto solo sull'**autofocus**, OAG) | gate AF; flip/slew già coperti da §39 | si restringe al gate autofocus |
| **N1** | Alto (alimenta 3) | TransparencyIndex lento + **fuso col guide-SNR veloce** | latenza adatta ai consumatori lenti |
| **N6/N7** | **Alto, universale** | pausa (Safety Monitor esistente) + tag (`AddImagePattern`) | i più tangibili per gli utenti |
| **N8** | Alto (P1) | confidence al motore, **osservativo→gated** | osservatore indipendente; robusto anche se le nuvole causano jitter |
| **N3/N4** | Molto alto concettuale, delicato | **validazione osservativa** prima di tutto | differenziale + per-target/filtro; mai HFR assoluto |

> **P1.** L'obiettivo ultimo non è l'RMS basso ma **stelle tonde nella posa**. NINA porta finalmente una sorgente informativa **indipendente da PHD2**: prima la si usa per *capire e validare* (N8, N3/N4 osservativi), solo dopo — e solo se i dati lo confermano su più sessioni — per *agire*.
