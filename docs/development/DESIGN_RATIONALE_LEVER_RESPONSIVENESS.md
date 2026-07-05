# Design rationale — Reattività delle leve: il MinMove "congelato" (proposta v2.5, item B)

**Stato:** progettazione teorica fondata sui log di campo. NESSUNA modifica al codice.
**Autore analisi:** Cowork, per Alessandro Curci — 2026-06-11.
**Base:** §31 (Agente v2.4). Item gemello di `DESIGN_RATIONALE_HFD_SAMPLING_AWARE.md` (§32). Entrambi nascono dalla cecità dell'HFD a campionamento grosso, ma questo riguarda l'**azione** (gestione delle leve), non la **diagnosi**.

---

## 0. Il sintomo, dalle parole di Alessandro

Notte 2026-06-11 (Askar 490 mm, OAG, ASI120MM Mini, 1,579″/px, vento). Osservazione sul campo: *"MinMove si congela al floor (0,15) e non si rialza, anche quando dovrebbe alzarsi per ammorbidire il vento."* Preferenza dichiarata: il floor 0,15 va bene; il problema è **solo** che la leva si **gela e non si adatta** — non serve più reattività, serve una leva **viva**.

---

## 1. Il sintomo è confermato dai dati

Sessione `session_20260611_222057` (JITTER, 2280 frame, 89 min di guida):

- Il motore ha fatto **tutti i suoi 9 cambi-leva nei primi ~10 minuti** (23:09→23:19, in aria calma), spingendo MinMove a 0,15 e RA aggression verso il tetto.
- Per i restanti **~79 minuti: zero cambi-leva** — inclusa la coda ventosa dove l'RMS è salito a 1,04″. MinMove è rimasto inchiodato a 0,15 mentre il vento peggiorava.

Quindi la leva non "decide" di restare a 0,15: il motore **smette del tutto di toccarla**. La domanda vera è: *perché smette?*

---

## 2. Causa prossima: il motore è in INSUFFICIENT_DATA per l'82% della sessione

`diag_state` sui 2280 frame: **INSUFFICIENT_DATA 1872 (82%)**, UNCERTAIN 352, NOMINAL 53, OVERCORRECTION 3, SEEING 0. Quando il motore è in INSUFFICIENT non produce proposte → nessun cambio leva → la leva resta all'ultimo valore impostato (0,15). Il "congelamento" è il sintomo diretto di questo 82%.

## 3. Causa radice — e qui i dati CORREGGONO l'assunzione precedente

Avevamo (io e Code, sulla 1ª notte) ipotizzato che la causa fosse il **reset EMA su cambio esposizione**. **Sui dati di questa notte NON regge.** Partizione dei 1872 frame INSUFFICIENT contro le 5 condizioni di `classify()` (diagnostic_engine.py L185-191):

| Causa di INSUFFICIENT | Test | Frame |
|---|---|---|
| `frame_count < min_frames` (30) — *l'effetto del reset* | frame_count<30 | **261** |
| `jitter_n < 2` | jitter_n<2 | 18 |
| `condition == STAR_LOST` | — | 0 |
| **nessuna delle precedenti** → `implosion_detected`/`implosion_suspended` o altra via | per esclusione | **1611** |

E il contatore frame si è resettato **solo 8 volte** in tutta la sessione. Quindi il reset EMA spiega **261 frame su 1872 (14%)**, non il grosso. **Il blocco dominante (1611 frame, 86% degli INSUFFICIENT) ha un'altra origine.**

Cosa NON è: non è implosione RMS vera. Questi 1611 frame hanno `rms_total` medio **0,493″** (min 0,29, max 0,96): **nessuno** con RMS collassato (<0,05). La guida era buona. Il detector di implosione (§18, NOTE_CLAUDE) scatta quando `rms_total > 8 × reference` (un picco ENORME, ~3-4″ qui): non è successo. Quindi la guida sana **non** giustifica un INSUFFICIENT.

Cosa rimane (ipotesi da confermare sul sorgente, vedi §6): per esclusione resta `implosion_suspended` (la finestra di 60 s post-implosione, che potrebbe restare appesa) **oppure** un'interazione tra la **cadenza di valutazione** del controller (`[control] interval_seconds = 10`, `window_frames = 30`) e il **logging per-frame** (CSV scritto a ogni GuideStep ~2 s): i frame "tra una valutazione e l'altra" potrebbero loggare uno stato di default/non-pronto. Distinguere tra queste vie richiede di leggere `analyzer.py`/`controller.py`, ed è la prima cosa che chiediamo a Code.

> **Conseguenza importante:** la "keystone = reset EMA" indicata in `DESIGN_RATIONALE_HFD_SAMPLING_AWARE.md §9` e nella proposta §32 di Code **va ridimensionata**. Su questa notte il reset pesa il 14% del blocco. La vera keystone del *congelamento delle leve* è **qualunque cosa metta il motore in INSUFFICIENT per il 70% di frame a guida buona** — ed è ancora da identificare con certezza.

## 4. Causa radice n°2 — LA principale storicamente: asimmetria strutturale di recupero delle leve, PRE-§31

Alessandro osserva il fenomeno **fin dalla 2.2/2.3**: quindi non può dipendere solo dal §31. **Confermato sul codice, ed è IDENTICO in v2.3 (`PHD2_Assist_PATCHED/phd2_agent/controller.py`, CASO 1 L809-841 / CASO 3 L878-926) e in v2.4** (controller.py CASO 1 L903-945 / CASO 3 L970-1029). La logica leve v2.3 (CASO 1/2/3 — attiva a motore spento e in guardian; sospesa solo in jitter) ha **trigger asimmetrici con un'ampia banda morta**:

| | MinMove GIÙ (più reattivo) | MinMove SU (ammorbidisce) |
|---|---|---|
| Ramo | CASO 3 "guida ottima" | CASO 1 "seeing degradato" |
| Trigger | `rms < rms_low` per N frame consec. | `rms > rms_high` per N frame consec. |
| Passo | `minmove_step` (0,05) | `minmove_step` (0,05) — **simmetrico** |
| Cooldown | `minmove_cooldown × 2` (3× base) | `minmove_cooldown` (1,5× base) — **più rapido!** |

Il passo è simmetrico e il cooldown **favorisce** la salita: quindi **non sono questi** il problema (importante, per non aggiustare la cosa sbagliata). L'asimmetria vera è nei **trigger + banda morta**:

- MinMove **scende** quando `rms < rms_low`: su una notte buona accade di continuo → arriva al floor.
- MinMove **risale solo** quando `rms > rms_high`: soglia molto più alta e rara.
- Tra `rms_low` e `rms_high` c'è una **banda morta**: nessuno dei due scatta → MinMove resta dov'è, cioè al floor.

Ed ecco il punto che spiega **precisamente** la tua frase: la condizione **DEGRADED dell'analyzer NON coincide con `rms > rms_high`**. Si può essere in DEGRADED con RMS nella banda morta → CASO 1 non scatta → MinMove **non recupera**, esattamente come osservi. Una volta al floor ci resta finché l'RMS non supera davvero `rms_high` per N frame consecutivi — cosa che il vento moderato spesso non raggiunge.

**Aggression: asimmetria DOPPIA.** Oltre allo stesso schema di trigger, ha anche il passo asimmetrico **`aggr_step_down = 5` vs `aggr_step_up = 2`** (L912/L1000): indurisce piano (su), ammorbidisce in fretta (giù). Per la tua "aggr che non recupera" agiscono *sia* il trigger asimmetrico *sia* il passo asimmetrico. (Nota: il passo asimmetrico è una scelta **deliberata e prudente** — "rapido ad ammorbidire, lento a indurire" — da preservare; il problema è la banda morta, non la prudenza.)

**Il ramo NOMINAL del §31 eredita la stessa monodirezionalità** (diagnostic_engine.py L197-209): `proposal = None if satisfied else LeverProposal(aggr=+1, minmove=-1)` — solo giù o fermo, **mai su**. Il ramo soft (`minmove+1`) sta solo nel SEEING, che a 1,58″/px è cieco (§32). Quindi l'asimmetria attraversa **v2.3 (CASO) e v2.4/jitter (NOMINAL)** in modo coerente: **è il filo storico che cercavi**, e va trattata come causa radice a sé, indipendente dalla cecità HFD e dal congelamento (§3).

## 5. Comportamento desiderato

Una leva **viva e bidirezionale**, governata da un segnale affidabile a campionamento grosso (il **jitter**, centroide-based):

1. **Restare attiva:** il motore non deve passare il 70% del tempo in INSUFFICIENT su guida buona. Risolvere la causa §3.
2. **Salire nel vento:** quando il jitter è elevato rispetto al suo riferimento — anche **sotto** la soglia SEEING (1,6×) — l'RMS basso è "fragile": NON abbassare MinMove, e anzi **alzarlo** verso un valore più morbido (lasciando il floor 0,15 invariato come limite inferiore, da preferenza esplicita di Alessandro).
3. **Scendere quando è davvero calmo:** jitter basso e stabile → la spinta verso 0,15 resta legittima.

### 5bis — Principio di convergenza: verso la PRESTAZIONE, non verso un numero (Alessandro, 2026-06-11)

Il riferimento finale delle leve **non** deve essere un valore storico (MinMove iniziale) né un valore neutro prefissato, ma la **qualità della guida misurata come RMS vs baseline**. Le leve convergono verso una *prestazione*, non verso un numero. Conseguenze:

- Se l'RMS resta **sopra la mediana baseline** (anche dentro la banda morta, sotto `rms_high`), la guida è comunque peggiorata rispetto alle condizioni che hanno definito la baseline → il sistema deve poter **continuare** ad ammorbidire (MinMove ↑, Aggr ↓) **oltre** i valori iniziali, fino ai limiti config (`minmove_max`, `aggr_min`), finché l'RMS rientra nel corridoio (idealmente **≤ mediana**).
- Viceversa, quando l'RMS è **stabilmente sotto** la baseline, recuperare reattività (MinMove ↓, Aggr ↑).
- La mediana baseline è la **soglia da non superare stabilmente**; il MinMove iniziale è un riferimento storico, non un tetto.

**Caveat di controllabilità (il limite del loop puro-RMS).** L'RMS sopra la mediana è solo **in parte** lever-fixable: ammorbidire cura il loop che insegue l'atmosfera (seeing-chasing), non l'RMS atmosferico in sé. Se il cielo è genuinamente peggiore, l'RMS resta sopra la mediana per qualunque valore di leva → un closed-loop puro-RMS andrebbe in **windup** verso i limiti, inseguendo un target irraggiungibile (l'inseguimento che vogliamo evitare, in forma lenta). Quindi il loop "verso la prestazione" è corretto come **principio**, ma per essere robusto richiede:
1. **anti-windup** — continuare ad ammorbidire solo finché l'azione **riduce davvero** l'RMS; se K passi non aiutano, fermarsi (RMS atmosferico). Questo è già fattibile in puro-RMS.
2. **segnale di regime (jitter/lag-1)** — per sapere *a priori* quando ulteriore softening non serve, e per distinguere "RMS alto da loop troppo reattivo" (lever-fixable) da "RMS alto da seeing/drift". Questo **accoppia il loop al §32**.

Questo principio si estende **a entrambe le leve** (MinMove e Aggressività) ed è il **target architetturale** dell'item. Nota di staging: il **fix minimo** (`PROMPT_FIX_LEVE_BANDA_MORTA.md`) ne implementa la parte sicura e puro-RMS sul **solo MinMove** (recupero oltre il valore iniziale, fermato dall'anti-windup, in OFF/GUARDIAN); il closed-loop completo a due leve, jitter-aware, è il design pieno qui descritto.

## 6. Impatto sul codice (punti da verificare/toccare)

| Area | File:riga | Nota |
|---|---|---|
| **Causa del blocco (da diagnosticare PER PRIMA)** | `analyzer.py` (`_compute`, campi `implosion_detected`/`implosion_suspended`, §18) + `controller.py` loop di valutazione/log | Perché 1611 frame a guida buona risultano INSUFFICIENT? `implosion_suspended` appeso? cadenza valutazione vs log per-frame? |
| Condizioni INSUFFICIENT | `diagnostic_engine.py` L185-191 | dove `implosion_*`/`frame_count` entrano |
| Ramo NOMINAL (spinta mono-direzionale) | `diagnostic_engine.py` **L197-209** | aggiungere percorso che ALZA MinMove in regime turbolento (jitter elevato) |
| Reset EMA su esposizione | `controller.py` L1491/1512/1583/1620 + L1411 | 14% del blocco; correlato ma non dominante stanotte |
| Cadenza/soglie controllo | `config.py [control]` interval_seconds=10, window_frames=30 | possibile co-fattore del logging INSUFFICIENT |
| Limiti leve (preferenza Alessandro) | `config.toml [limits.*]` minmove_min=0.15, aggr_max=90 (verificati, ripo+pacchetto identici) | **floor 0,15 da NON alzare**; serve dinamica, non un floor più alto |

## 7. Relazione con gli altri item

- **§32 (HFD sampling-aware):** gemello. §32 dà al motore la capacità di **vedere** il regime ventoso (jitter al posto dell'HFD); questo item gli dà la capacità di **agire** di conseguenza (alzare MinMove). Si rinforzano: senza §32 il motore non sa quando alzare; senza questo item non saprebbe come.
- **Reset EMA:** rimane un work-item, ma **declassato** da "keystone" a co-fattore (14% stanotte). Da rivalutare insieme alla causa §3.
- **Gerarchia rivista, onesta (tre cause distinte):**
  1. **Asimmetria strutturale di recupero leve (§4)** — la **causa storica** (v2.2/2.3/2.4): banda morta `rms_low`–`rms_high`, recupero solo su `rms>rms_high`, DEGRADED che non basta a far risalire MinMove. È quella che spiega ciò che Alessandro vede da anni, **indipendente** da §31/HFD.
  2. **Congelamento del motore (§3)** — layer specifico 2.4/jitter (INSUFFICIENT 82%, causa dei 1611 frame ancora da identificare). Aggrava l'asimmetria perché toglie anche i pochi recuperi possibili.
  3. **Reset EMA** — co-fattore minore (14% stanotte), declassato da "keystone".
  - **§32** è ortogonale ma abilitante: dà il segnale (jitter) per far scattare il recupero di MinMove *prima* di `rms>rms_high`, sanando la banda morta.

## 8. Decisioni aperte

1. Qual è la via reale dell'INSUFFICIENT sui 1611 frame? (`implosion_suspended` vs cadenza/log) — **da risolvere sul sorgente, è il primo compito di Code.**
2. Forma del rialzo di MinMove nel vento: a gradini (come la discesa, `minmove_step=0.05`) o proporzionale al jitter/jitter_ref?
3. Soglia di "regime turbolento" per il NOMINAL: riusare `jitter_high_factor` (1,6) o una soglia dedicata più bassa (es. 1,2-1,3) per intervenire prima del SEEING?
4. Conferma: è lo stesso meccanismo che ha reso cieca anche la 1ª notte? (rieseguire la partizione §3 sul log Askar precedente).
