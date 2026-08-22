# Linee guida — Trasparenza, memoria per filtro, N8

**Stato:** approvate 2026-08-22 · baseline sperimentale **v2.17.0 (§100)**
**Vale per:** Alessandro (maintainer), Claude Code (ingegneria/manutenzione), GPT (analisi)

Documento di allineamento. Fissa **cosa è già nel motore**, **cosa non va toccato**, **cosa va
studiato prima di essere implementato** e **con quali prove si accetta o si respinge** una modifica.
Nasce dall'analisi di tre notti reali (13-14/8, 17-18/8, 21-22/8) e dall'audit del sorgente.

---

## 0. Il principio che regge tutto

> Ogni nuova capacità viene **prima dimostrata sui dati** e solo dopo autorizzata a comandare.

Non è una massima di prudenza: è la regola che ha già salvato il progetto due volte. Il cricchetto
§66 fu **proposto, replayato e respinto** (a cadenza 3 s un'emivita di 25 min colma il 99,9% del
divario in 4 ore: la medicina agiva su una scala di tempi sbagliata). L'ancora §94 sembrava un buon
segnale e **la sua prima notte l'ha falsificata** (il 78% della crescita veniva dall'ancora che
scendeva, non dal jitter che saliva).

---

## 1. §100 è una baseline sperimentale, non materiale da modificare

Con il §100 il sistema è diventato **osservabile senza cambiare comportamento**. È una proprietà
rara e si spreca continuando a modificare il motore mentre si cerca di capire cosa dicono i dati.

**Regola:** finché non abbiamo notti raccolte con lo schema 7, il motore di trasparenza non si tocca.

Colonne disponibili da v2.17.0 (gruppo §94, nessuna decisione le legge):
`bkg`, `base_bkg`, `base_stars`, `base_stars_session_best`, `ref_drift_pct`.

Invariante blindato da test: `test_il_controller_non_consuma_le_colonne_nuove` **fallisce** se
`base_bkg`, `ref_drift_pct` o `base_stars_session_best` compaiono nel controller.

---

## 2. Le tre evidenze — corsie separate, mai confuse

| evidenza | sorgenti | cosa descrive |
|---|---|---|
| **guida** | PHD2: RMS, jitter, lag-1, trend RA/DEC | comportamento del loop e della meccanica |
| **seeing / fuoco** | HFD (guida), HFR (NINA) | turbolenza e messa a fuoco |
| **trasparenza** | `star_count` + `bkg`, con i rispettivi riferimenti | quanto cielo c'è fra noi e il campo |

**Non si mescolano.** In particolare `bkg` **non è** una misura di seeing, e HFR **non è** un
correttore di trasparenza — su tre notti il suo segno si ribalta fra i filtri (3 positivi, 4
negativi: una compensazione correggerebbe al contrario su O, H, R).

`airmass` e Luna restano **contesto diagnostico**, non correttori. Motivi misurati, non opinioni:
sopra i 30° l'effetto dell'airmass è sotto il rumore (R² 0,01–0,10 contro 0,68 dell'HFR) e sotto i
30° **non abbiamo un solo campione** (massimo osservato X 1,56); i campioni "Luna sopra l'orizzonte"
della notte 21-22 coincidono **esattamente** con il ciclo 1 per tutti i filtri, quindi il confronto
è indistinguibile da qualunque altra deriva temporale.

---

## 3. Risposte ai sette quesiti dell'audit

### 3.1 Il decadimento per evidenza è preferibile a quello temporale?

**Sì, ma non può essere l'unico meccanismo.**

La ragione non è "le sessioni cicliche hanno buchi lunghi" — è più profonda: **il riferimento
rappresenta com'era il cielo l'ultima volta che ne abbiamo avuto prova.** Il tempo non porta prove;
le portano le osservazioni. Con il decadimento per campione, a parità di osservazioni il riferimento
è identico che tu abbia 1 filtro o 10 — che è esattamente l'invariante voluto.

**Il contro-argomento, che va messo agli atti:** alcuni cambiamenti legittimi sono funzione del
tempo di calendario e avvengono *mentre non stiamo guardando quel filtro* (Luna che sorge, target
che scende). Un decadimento puramente per evidenza li applica come se non fosse passato tempo, e il
riferimento resta vecchio.

**Risoluzione:** il decadimento per evidenza governa il **cricchetto** (che esiste per non inseguire
il degrado); l'assorbimento dei cali legittimi resta al **pavimento di sessione** (già presente) e,
quando sarà misurata, alla **geometria**. Il decadimento deve comunque restare *limitato*: un
riferimento che non si muove mai ricrea lo stallo che la regola 3 fu scritta per evitare — stallo
trovato al banco di prova prima del rilascio, come dice il docstring di `_ratchet`.

### 3.2 Come applicarlo simmetricamente a stars e bkg

**Oggi i due non sono simmetrici**, e va detto prima di progettare:

| | stelle | fondo cielo |
|---|---|---|
| finestra mobile per chiave | `_stars_by_filter` ✅ | `_bkg_by_filter` ✅ |
| riferimento a cricchetto | `_ref_stars_by_filter` ✅ | `_ref_bkg_by_filter` ✅ |
| meglio di sessione | `_best_stars_by_filter` ✅ | **assente** (`_best_bkg`: 0 occorrenze) |
| pavimento (regola 4) | ✅ | **assente** — `if ... and higher_is_better` |

Per la simmetria servirebbero: un **contatore di campioni per chiave** (naturalmente condiviso: un
solo `ingest()` alimenta entrambi), `_best_bkg_by_filter`, e la regola 4 generalizzata — per il
fondo il "pavimento" diventa un **soffitto**, perché lì `higher_is_better=False`.

### 3.3 `star_ratio + bkg_factor` come Transparency Evidence per N8

**Architetturalmente corretto, e la forma minima non duplica nulla: è una riga.**

```python
index   = star_ratio * bkg_factor      # già composito, già calcolato
deficit = max(0.0, 1.0 - star_ratio)   # ← oggi N8 legge SOLO questo
```

`deficit` potrebbe diventare `1 - index` senza scrivere una sola formula nuova. Ma **eredita i
confondenti del fondo cielo**, e il primo è la Luna: un cielo limpido con Luna alta alza `bkg` senza
alcuna perdita di trasparenza.

**Questo non è un dettaglio, ed è il rischio principale di tutta la strada** — vedi §5.

### 3.4 Gate, dead-band, persistenza e fail-safe da mantenere

Tutti quelli di §46, e qualunque nuova evidenza deve passare **dagli stessi**:

| meccanismo | valore | perché esiste |
|---|---|---|
| `confidence_use_nina` | true | kill-switch: false = confidence PHD2-only, pre-N8 |
| provider assente / dato vuoto | penalità 0 | graceful: NINA che tace non deve alterare nulla |
| gate di freschezza §46 | a monte | telemetria stantia non decide |
| `nina_deadband` | 0.10 | il rumore frame-to-frame non deve penalizzare |
| rampa → `nina_max_penalty` | 40 punti | proporzionalità, non gradino |
| `nina_persist_subs` | 2 pose | anti singolo frame anomalo |
| applicazione | **solo al SEEING** | è il confine fra le corsie |

Se il fondo cielo entra in N8, gli serve una **dead-band propria**: il rumore del fondo non ha la
stessa ampiezza del rumore sul conteggio stelle, e riusare 0.10 sarebbe una taratura per analogia.

### 3.5 Come impedire che una perdita di trasparenza sia letta come SEEING_DEGRADED

**Il meccanismo esiste già e funziona — ma è molto più forte di quanto la parola "confidence"
suggerisca.** Numeri:

```
diagnosi SEEING a 75%  −  penalità N8 piena (40)  =  35%
act_min_confidence      = 60   →  il motore NON agisce
guardian_min_confidence = 60   →  il Guardian CONFERMA sempre (fail-safe)
```

Quindi N8 non "abbassa la fiducia": a penalità piena **zittisce** la diagnosi SEEING. È il
comportamento voluto quando il cielo è davvero degradato — e diventa un difetto se l'evidenza è
sbagliata.

### 3.6 Quali dati della v2.17.0 raccogliere

Tre tipi di notte, tutte con lo schema 7:

1. **notte ciclica limpida** — ripete la 21-22 ma *con* `bkg`. Prova dei falsi positivi.
2. **notte con degrado reale** (velatura, nubi in transito) — **è il caso che ci manca**, e senza di
   esso il mascheramento resta una previsione da simulazione, non un fatto osservato.
3. **notte limpida con Luna alta** — economica e preziosa: `bkg` sale senza perdita di trasparenza.
   È il **test del confondente**, e senza di essa il punto 3.3 non è decidibile.

### 3.7 Quali replay accettano o respingono la modifica

Un modello si accetta **solo se passa tutte e tre**:

| prova | criterio di accettazione | criterio di rifiuto |
|---|---|---|
| notte limpida ciclica | resta CLEAR; le stelle a fine notte sono al ~100% dell'inizio | qualunque HAZE non transitorio |
| notte con degrado | raggiunge HAZE **non più tardi** del modello attuale | il degrado resta CLEAR (mascheramento) |
| notte limpida con Luna | trasparenza **non** dichiarata degradata; confidence SEEING non depressa | il motore smette di agire sul seeing per ore |

Riferimenti già disponibili per le prime due: la 21-22 (CLEAR 98,2%, stelle 101% a fine notte) e la
17-18 (degrado vero 306→218 stelle, HAZE alle 03:00 con indice 0,71). Entrambe **senza `bkg`**, e
per questo non bastano.

**Limite duro, aritmetico e non negoziabile:** il classificatore *"stelle ↓ + fondo ↑ = velatura"*
**non è testabile su alcun log anteriore alla v2.17.0**. `index = star_ratio × bkg_factor` è una
equazione in due incognite: dai log vecchi si conosce `index` e `star_count`, non `base_stars` né
`bkg`. La ricostruzione fatta per la 21-22 valeva **solo** assumendo `bkg_factor = 1`, cioè
assumendo che il fondo non contasse — che è l'ipotesi da verificare.

---

## 4. Invarianti da preservare

Non si toccano senza una prova sul campo che li smentisca:

1. **separazione `(target, filtro)`** — nessun filtro è mai confrontato con un altro
2. **regola 1** del cricchetto: il miglioramento si adotta subito (le nubi non creano stelle)
3. **regola 2**: riferimento congelato durante un evento degradato, con tetto `ref_freeze_max_min`
4. **regola 4**: pavimento di sessione — impedisce l'erosione infinita
5. **N8 applicato solo al SEEING** — mai a DRIFT o OVERCORRECTION, che sono le diagnosi affidabili
6. **fail-safe del Guardian**: sotto soglia di confidence, CONFERMA
7. **degradazione graziosa**: NINA assente o stantia ⇒ comportamento PHD2-only, mai peggiore

---

## 5. Rischi dichiarati

- **Il confondente Luna su `bkg`** (rischio principale). Un cielo limpido con Luna alta alza il
  fondo. Se `bkg` entra in N8 senza un discriminante, la diagnosi SEEING può restare zittita per ore
  su cielo perfetto — e con `act_min_confidence = 60` significa un motore inerte.
- **Lo stallo del riferimento.** Un decadimento per evidenza troppo lento ricrea la soglia
  irraggiungibile che la regola 3 fu scritta per evitare.
- **Il doppio consumatore.** `index` alimenta il latch UNSAFE del plugin (accumula sotto 0.5, UNSAFE
  a 8 poll) *e* la diagnostica. Una modifica al numeratore comune si scarica su entrambi: falso
  UNSAFE = notte ferma a cielo sereno; nessun UNSAFE = pose sprecate sotto le nubi.
- **L'asimmetria stars/bkg** (§3.2): finché il fondo è secondario non pesa; se diventa portante,
  quell'asimmetria va chiusa *prima*, non dopo.

---

## 6. Ordine dei lavori — concordato

```
§100 (fatto, committato)
  → raccolta notti reali con schema 7
    → replay: il fondo cielo si comporta come previsto?
      → progetto memoria (decadimento per evidenza, simmetrico)
        → replay a tre facce
          → progetto N8 (deficit a una o due gambe)
            → replay a tre facce
              → eventuale azione del Guardian
```

Non si salta un passo, e **non si procede in ordine inverso**. Il primo punto d'innesto è N8 e non
il controllo motore: lì l'informazione migliora una *confidence*, non diventa un comando alla
montatura.

---

## 7. Domande ancora aperte

### S +20% e R +14% nella notte 21-22 — parzialmente spiegato

**Causa documentata, trovata nel log NINA:** un **autofocus alle 02:25**, cioè esattamente
nell'intervallo fra il ciclo 2 e il ciclo 3 (trigger `AutofocusAfterHFRIncreaseTrigger`,
`TrendPerFilter: True`; gli altri due sono alle 22:51 e alle 00:22). L'HFR migliora su 5 filtri su 6,
e l'unico peggiorato (B, +0,22) e' anche quello che perde piu' stelle (-9,2%). Correlazione
`d.HFR / d.stelle` fra i filtri: **r = -0,49**, nel verso atteso.

**Ma non basta:** l'HFR di S migliora di soli -0,09 contro il -0,31 di R, eppure S guadagna il 21,8%
e R il 6,4%. Il fuoco spiega la direzione, non la magnitudine.

**Ipotesi di Alessandro (sito di Borno), valutata col test di banda:**

| meccanismo | natura | verdetto |
|---|---|---|
| spegnimento luci domestiche e luminarie comunali | continuo a banda larga | **non torna**: predice L/R/G/B > S/H/O, osservato il contrario |
| target che scende verso il settore del Giovetto, meno inquinato | banda larga | stessa obiezione |
| **inversione termica che ripulisce foschia e umidita'** | **trasparenza vera, tutte le bande** | **compatibile** — e' la gamba che sopravvive |

Il dato SQM piu' alto a notte fonda che in prima serata e' coerente con tutti e tre; solo il terzo
spiega perche' a guadagnarci di piu' sia un filtro a banda stretta.

**Previsione falsificabile per le prossime notti (ora misurabile grazie al §100):**
piu' stelle **+** `bkg` in calo ⇒ compatibile con inquinamento luminoso o cielo che si ripulisce;
piu' stelle **+** `bkg` invariato ⇒ il fondo non c'entra, la causa e' altrove.

### L'autofocus e' un confondente che il sistema potrebbe gia' leggere

Osservazione architetturale emersa da qui. Dei quattro confondenti individuati, l'autofocus e'
l'unico che **NINA registra con un timestamp**: la Luna va calcolata, l'inquinamento luminoso va
inferito, l'airmass va modellato — l'autofocus **si legge**, esattamente come il dither si legge da
`SettleBegin`/`SettleDone` (main.py:580/588).

Se un rifocus puo' produrre un gradino del 20% nel conteggio stelle di un filtro, il riferimento di
trasparenza e' esposto a un cambiamento **non atmosferico** che il sistema potrebbe riconoscere
invece di subire. Da valutare **dopo** la raccolta dati, non prima: e' una quinta variabile e vale
la stessa regola delle altre quattro.
- Il decadimento per evidenza va misurato in campioni, in tempo di posa cumulato, o in "minuti di
  cielo sereno osservati su quella chiave"? Le tre forme divergono su sequenze non uniformi come
  SHO 300 s + LRGB 120 s.
- Sotto i 30° la curva di estinzione è costruibile? Serve un target che scenda davvero (X > 2), lo
  stesso filtro lungo la discesa e l'HFR come covariata. I dati necessari li registriamo già.
