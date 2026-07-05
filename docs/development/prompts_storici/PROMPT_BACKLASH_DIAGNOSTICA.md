# PROMPT PER CLAUDE CODE (Antigravity) — Diagnostica Backlash DEC nell'Agent Dinamico
# Da copiare e incollare integralmente nella conversazione con Claude Code.
# Lavorare nella cartella: PHD2_Assist_PATCHED/

> **NOTA OPERATIVA PER CLAUDE CODE**: questa NON è una feature di azione
> sul backlash di PHD2. È una feature **DIAGNOSTICA** che rileva sintomi
> di backlash mal calibrato e li segnala all'utente. Vedi sezione 0 e 1
> per la motivazione tecnica.

---

## 0. PRE-FLIGHT OBBLIGATORIO (leggere PRIMA di scrivere codice)

### File da leggere

1. **`phd2-master/phd2-master/src/backlash_comp.h`**
   Capire la struttura `BacklashComp` (riga 144) e `BacklashTool`. Notare:
   - `GetBacklashPulseMinValue()` = 20 ms, `GetBacklashPulseMaxValue()` = 8000 ms
   - `EnableBacklashComp(bool)` — abilitazione interna
   - `SetBacklashPulseWidth(ms, floor, ceiling)` — modifica del valore
   - `TrackBLCResults` — meccanismo di auto-regolazione interno PHD2
   - `ApplyBacklashComp` — applicato solo a cambio direzione DEC
   - **Tutte queste funzioni sono internal C++, non esposte via JSON-RPC.**

2. **`phd2-master/phd2-master/src/backlash_comp.cpp`** righe 478-547
   Leggere `TrackBLCResults`: PHD2 osserva l'errore residuo dopo applicazione
   BL e regola autonomamente il pulse:
   - Under-shoot → `newBLC = round(min(pulse * 1.1, nominal))` (max +10%)
   - Over-shoot → `newBLC = round(max(0.8 * pulse, nominal))` (max -20%)
   - Vincolato tra `m_adjustmentFloor` e `m_adjustmentCeiling`
   - Default ceiling = 1.5 × pulse iniziale (riga 423)
   - Solo se `m_compActive == True` AND `m_fixedSize == False`

3. **`phd2-master/phd2-master/src/event_server.cpp`** — verifica con grep
   ```
   grep -i "backlash\|BLC" event_server.cpp
   ```
   **Risultato atteso: zero match.** Confermare con i propri occhi che
   non esiste alcun endpoint JSON-RPC per leggere o scrivere il BL.

4. **`phd2-master/phd2-master/src/guiding_assistant.cpp`** righe relative a backlash
   Capire come Guiding Assistant misura il BL via `BacklashTool`. È una
   procedura modale (richiede stop guida + sequenza nord/sud automatica).
   **Non replicabile via JSON-RPC durante guida normale.**

5. **`PHD2_User_Guide 2.6.14.pdf`** sezioni:
   - **"Dec Backlash"** o **"Backlash Compensation"**
   - **"Guiding Assistant"** sezione backlash measurement
   - **"Resist Switch"** algorithm — è quello che usa Alessandro su DEC
     e ha interazione specifica con il BL

### Conclusioni del pre-flight (già verificate)

A. **Non esiste API JSON-RPC per leggere o scrivere il backlash compensation**.
   Il valore è memorizzato solo in `pConfig->Profile.SetInt("/<Mount>/DecBacklashPulse", ms)`.
   Solo modificabile via GUI Brain → Algorithms → Dec → Backlash Comp,
   o via Backlash Wizard (Guiding Assistant).

B. **PHD2 ha già un'auto-regolazione interna** del BL (`TrackBLCResults`)
   che osserva i pulse history e adatta il valore ±10/-20% per ciclo.
   Replicare questo dal nostro agent sarebbe duplicato e meno preciso
   (PHD2 ha visibilità diretta sui pulse, noi solo sui GuideStep aggregati).

C. **Conseguenza operativa**: questa feature può essere SOLO diagnostica.
   Rileva sintomi, logga warning, mostra notifica in dashboard. **Non agisce
   sul BL.** L'azione resta manuale (utente che rifà Backlash Wizard o
   modifica il valore in Brain).

---

## 1. RUOLO E SCOPO DELLA FEATURE

### Cosa fa questa feature

Aggiunge al `phd2_agent` una **classe di diagnostica DEC step response**
che osserva il comportamento dell'asse DEC nei frame successivi a un cambio
di segno della deriva (cioè quando PHD2 inverte la direzione di guida DEC).
Classifica il comportamento in tre categorie:

- **NORMAL** — risposta DEC simmetrica e proporzionale, BL ben calibrato
- **OVERSHOOT_PERSISTENT** — la stella va oltre il target dopo cambio dir,
  poi torna indietro. Sintomo di **BL eccessivo** (PHD2 sovracompensa).
- **DEADBAND_PERSISTENT** — la stella resta ferma per N frame dopo cambio dir,
  PHD2 deve ripetere correzioni nello stesso senso. Sintomo di **BL insufficiente**
  o disabilitato.

Il classificatore richiede ≥ 5 cambi di direzione DEC nella sessione per
produrre un verdetto attendibile. Sotto soglia: stato `INSUFFICIENT_DATA`.

### Cosa NON fa questa feature

- **Non modifica** il backlash di PHD2 (impossibile via JSON-RPC).
- **Non sostituisce** il Guiding Assistant / Backlash Wizard (resta lo
  strumento di misurazione di riferimento).
- **Non duplica** `TrackBLCResults` di PHD2 (che lavora sui pulse interni,
  noi lavoriamo sui GuideStep aggregati).
- **Non è un trigger di azione** — è un sensore + notificatore.

### Output della feature

1. Log `WARNING` su `app.log` quando viene classificato persistentemente
   `OVERSHOOT_PERSISTENT` o `DEADBAND_PERSISTENT` per ≥ N occorrenze.
2. Campo nuovo nel `decisions_*.jsonl` con `axis="dec"`,
   `param="backlash_diagnostic"`, `reason` descrittiva.
3. Blocco nuovo nel `controller.get_status()` per la dashboard:
   ```json
   "backlash_diag": {
     "state": "NORMAL" | "OVERSHOOT_PERSISTENT" | "DEADBAND_PERSISTENT" | "INSUFFICIENT_DATA",
     "direction_changes_observed": 12,
     "overshoot_count": 1,
     "deadband_count": 0,
     "last_classification": "2026-05-09T22:15:33Z",
     "suggestion": "BL ben calibrato" | "Considera di rifare Backlash Wizard, BL probabilmente alto" | ...
   }
   ```
4. Riepilogo finale nel `session_*.summary.json` con conteggi e verdetto.

---

## 2. APPLICABILITÀ PER SETUP

| Setup | Ha senso? | Motivo |
|---|---|---|
| Askar 71F + AM5 | **No** | AM5 è encoder strain wave, BL trascurabile. Disattivare di default. |
| Tecnosky 115 + AM5 o CEM70G | **Marginale** | Solo se su CEM70G; con AM5 sopra, no. |
| RC8 + CEM70G | **Sì** | CEM70G ha BL misurabile, RC8 a 0.51"/px lo evidenzia bene. **Setup primario candidato.** |

Configurazione per-setup nel TOML:
```toml
[backlash_diagnostic]
enabled                       = false   # default OFF; attivare manualmente
min_direction_changes         = 5       # min cambi di segno DEC per classificazione
deadband_frames_threshold     = 3       # frame consecutivi senza correzione DEC dopo cambio dir
overshoot_arcsec_threshold    = 0.30    # px overshoot in arcsec per qualificare overshoot
classification_window_minutes = 30      # finestra rolling per il verdetto
warning_threshold_count       = 3       # N occorrenze persistenti per WARNING
```

Per RC8 (`config_rc8.toml`):
- `enabled = false` di default (attivare manualmente per i test)
- `overshoot_arcsec_threshold = 0.25` (scala fine)
- `deadband_frames_threshold = 3`

Per Askar 71F (`config_askar71f.toml`):
- `enabled = false` (lasciare disattivato anche per i test, AM5 senza BL)

Per Tecnosky 115 (`config_tecnosky115.toml`):
- `enabled = false`
- `overshoot_arcsec_threshold = 0.40`
- `deadband_frames_threshold = 3`

---

## 3. ARCHITETTURA PROPOSTA

### Nuovo modulo `phd2_agent/backlash_diagnostic.py`

Classe singleton `BacklashDiagnostic` che:
- riceve i frame DEC (dec_raw, dec_duration) dall'analyzer
- mantiene una sliding window degli ultimi N frame (per la rilevazione cambio direzione)
- mantiene un buffer rolling dei direction changes osservati negli ultimi `classification_window_minutes`
- per ciascun cambio direzione, registra la "step response" (i 5 frame post-cambio)
- classifica la step response in NORMAL / OVERSHOOT / DEADBAND
- aggrega i conteggi e produce uno stato corrente

Pseudocodice:

```python
@dataclass
class DirectionChangeEvent:
    timestamp: float
    direction_before: int  # +1 (north) o -1 (south)
    direction_after: int
    response_frames: list[float]  # dec_raw dei 5 frame successivi
    classification: str  # NORMAL / OVERSHOOT / DEADBAND

class BacklashDiagnostic:
    def __init__(self, cfg: BacklashDiagnosticConfig, pixel_scale: float):
        self.cfg = cfg
        self.pixel_scale = pixel_scale
        self._dec_history: deque[float] = deque(maxlen=10)
        self._events: deque[DirectionChangeEvent] = deque(maxlen=200)
        self._pending_event: Optional[DirectionChangeEvent] = None
        self._frames_collected: int = 0

    def ingest_frame(self, dec_raw: float, dec_duration: float, ts: float):
        # 1. Se c'è un pending event, accumula i frame post-cambio
        if self._pending_event:
            self._pending_event.response_frames.append(dec_raw)
            if len(self._pending_event.response_frames) >= 5:
                self._classify_pending()
                self._events.append(self._pending_event)
                self._pending_event = None

        # 2. Rileva cambio di direzione (sign change su dec_raw "centrato")
        self._dec_history.append(dec_raw)
        if len(self._dec_history) >= 6 and not self._pending_event:
            recent = list(self._dec_history)[-6:]
            sign_before = sign_majority(recent[:3])
            sign_after  = sign_majority(recent[3:])
            if sign_before != 0 and sign_after != 0 and sign_before != sign_after:
                self._pending_event = DirectionChangeEvent(
                    timestamp=ts,
                    direction_before=sign_before,
                    direction_after=sign_after,
                    response_frames=[dec_raw],
                    classification="PENDING",
                )

    def _classify_pending(self):
        e = self._pending_event
        # OVERSHOOT: il primo frame post-cambio è già oltre target nella nuova direzione
        max_excursion = max(abs(f) for f in e.response_frames)
        first_frame = e.response_frames[0]
        last_frame = e.response_frames[-1]

        # Convert to arcsec
        max_excursion_arcsec = max_excursion * self.pixel_scale

        # OVERSHOOT: max excursion > soglia AND ultimo frame è di segno opposto al primo
        if (max_excursion_arcsec > self.cfg.overshoot_arcsec_threshold
                and sign(last_frame) != sign(first_frame)):
            e.classification = "OVERSHOOT"
            return

        # DEADBAND: i primi N frame sono tutti dello stesso segno (PHD2 deve ripetere)
        first_n = e.response_frames[:self.cfg.deadband_frames_threshold]
        if all(sign(f) == sign(first_n[0]) for f in first_n):
            e.classification = "DEADBAND"
            return

        e.classification = "NORMAL"

    def get_state(self) -> dict:
        # Filtra eventi nella finestra rolling
        cutoff = time.time() - self.cfg.classification_window_minutes * 60
        recent = [e for e in self._events if e.timestamp >= cutoff]
        n = len(recent)
        if n < self.cfg.min_direction_changes:
            return {
                "state": "INSUFFICIENT_DATA",
                "direction_changes_observed": n,
                "overshoot_count": 0,
                "deadband_count": 0,
            }

        overshoot = sum(1 for e in recent if e.classification == "OVERSHOOT")
        deadband  = sum(1 for e in recent if e.classification == "DEADBAND")
        normal    = n - overshoot - deadband

        # Maggioranza relativa con soglia minima
        if overshoot >= self.cfg.warning_threshold_count and overshoot > deadband:
            state = "OVERSHOOT_PERSISTENT"
            suggestion = ("BL probabilmente alto. Considera di rifare il "
                          "Backlash Wizard di PHD2 (Tools > Guiding Assistant > "
                          "Measure Dec backlash). Valori suggeriti: ridurre "
                          "DecBacklashPulse del 10–20%.")
        elif deadband >= self.cfg.warning_threshold_count and deadband > overshoot:
            state = "DEADBAND_PERSISTENT"
            suggestion = ("BL probabilmente basso o disabilitato. Verifica in "
                          "Brain > Algorithms > Dec che 'Backlash Comp' sia "
                          "abilitato. Considera di rifare il Backlash Wizard.")
        else:
            state = "NORMAL"
            suggestion = "BL ben calibrato (campione attuale)."

        return {
            "state": state,
            "direction_changes_observed": n,
            "overshoot_count": overshoot,
            "deadband_count": deadband,
            "normal_count": normal,
            "last_classification": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "suggestion": suggestion,
        }
```

### Integrazione nell'analyzer e controller

**`phd2_agent/analyzer.py`**:
- Nessuna modifica strutturale all'AnalysisSnapshot.
- Aggiungere a `StatisticsAnalyzer.__init__()`: `self._backlash: Optional[BacklashDiagnostic] = None`
- Setter: `set_backlash_diagnostic(bd)` chiamato dal controller.
- In `ingest_guide_step()`, dopo l'append in `_window`:
  ```python
  if self._backlash is not None:
      self._backlash.ingest_frame(
          dec_raw=frame.dec_raw,
          dec_duration=frame.dec_duration,
          ts=frame.timestamp,
      )
  ```

**`phd2_agent/controller.py`**:
- In `__init__()` o `initialize()`:
  ```python
  if self.cfg.backlash_diagnostic.enabled:
      self.backlash_diag = BacklashDiagnostic(
          self.cfg.backlash_diagnostic,
          pixel_scale=self.cfg.setup.guide_pixel_scale_arcsec,
      )
      self.analyzer.set_backlash_diagnostic(self.backlash_diag)
  else:
      self.backlash_diag = None
  ```
- In `evaluate()` (alla fine, dopo le altre evaluate): chiamare
  `self._evaluate_backlash_warning()` ogni N evaluate (non ogni frame!).
  Funzione che:
  - Legge `self.backlash_diag.get_state()`
  - Se state cambia da NORMAL/INSUFFICIENT a OVERSHOOT_PERSISTENT/DEADBAND_PERSISTENT:
    log `WARNING` con `suggestion`
  - Emette ControlAction con `axis="dec"`, `param="backlash_diagnostic"`,
    `dry_run=True` sempre (è una notifica, non un'azione)
- In `get_status()` aggiungere il blocco `backlash_diag`.

**`phd2_agent/config.py`**:
- Aggiungere dataclass `BacklashDiagnosticConfig` e parsing.

### Persistenza nel summary

In `logger.py` o equivalente, al chiusura sessione aggiungere a
`session_*.summary.json`:
```json
"backlash_diagnostic": {
  "enabled": true,
  "final_state": "OVERSHOOT_PERSISTENT",
  "direction_changes_total": 17,
  "overshoot_count": 11,
  "deadband_count": 1,
  "normal_count": 5,
  "suggestion": "BL probabilmente alto. ..."
}
```

Questo permette a Alessandro di rivedere la diagnostica a freddo il giorno
dopo la sessione, senza dover guardare i log live.

---

## 4. METRICHE DI TRIGGER (riepilogo)

### Trigger OVERSHOOT (suggerimento "ridurre BL")
- ≥ `warning_threshold_count` direction change events classificati OVERSHOOT
  nella finestra rolling `classification_window_minutes`
- `overshoot_count > deadband_count`

Singolo evento OVERSHOOT richiede:
- Cambio di segno DEC rilevato (3 frame con segno A, poi 3 con segno B)
- Max excursion DEC nei 5 frame post-cambio > `overshoot_arcsec_threshold`
- Ultimo frame di segno opposto al primo (la stella ha attraversato lo zero)

### Trigger DEADBAND (suggerimento "aumentare BL o verificare se abilitato")
- ≥ `warning_threshold_count` direction change events classificati DEADBAND
- `deadband_count > overshoot_count`

Singolo evento DEADBAND richiede:
- Cambio di segno DEC rilevato
- I primi `deadband_frames_threshold` frame post-cambio sono **tutti dello
  stesso segno** (PHD2 sta correggendo nella stessa direzione, non riesce a
  invertire effettivamente l'asse)

### Esclusioni di sicurezza
- Durante settling/dithering: ignorare frame
- Durante `implosion_suspended`: ignorare
- Durante STAR_LOST: clear pending event, no classificazione

---

## 5. AVVERTENZA OPERATIVA — limiti dell'approccio

Devi includere nel log all'avvio del modulo (una sola volta) un INFO esplicito:

```
INFO: Backlash diagnostic ATTIVO. Solo sensore + notifica, NON modifica BL.
INFO: Per modificare il BL effettivo, usare PHD2 GUI:
INFO:   - Brain > Algorithms > Dec > Backlash Comp (modifica diretta valore)
INFO:   - Tools > Guiding Assistant (misurazione automatica)
INFO: PHD2 ha già un meccanismo interno di auto-regolazione del BL
INFO: (TrackBLCResults), che agisce sui pulse history quando BL e' enabled
INFO: e non e' impostato come Fixed in Brain.
```

Questo serve a evitare che in futuro si dimentichi che la feature è solo
diagnostica e non azione.

---

## 6. TEST ATTESI (sanity check)

Test unitari (in `test_backlash_diagnostic.py`):

1. **Test direction change detection**: feed di 6 frame con segno alternato
   3+3, verifica che pending event venga creato.

2. **Test classificazione OVERSHOOT**: pending event con response_frames =
   `[+0.5, +0.4, +0.1, -0.6, -0.3]` (excursion forte oltre zero) →
   classification == "OVERSHOOT".

3. **Test classificazione DEADBAND**: pending event con response_frames =
   `[+0.3, +0.4, +0.5, +0.4, +0.3]` (resta su stesso segno) →
   classification == "DEADBAND".

4. **Test classificazione NORMAL**: pending event con response_frames =
   `[+0.2, +0.1, 0.0, -0.1, -0.05]` → classification == "NORMAL".

5. **Test soglia min_direction_changes**: get_state() con n < soglia →
   "INSUFFICIENT_DATA".

6. **Test maggioranza OVERSHOOT_PERSISTENT**: 5 OVERSHOOT, 1 DEADBAND, 0 NORMAL →
   "OVERSHOOT_PERSISTENT".

7. **Test rolling window**: eventi più vecchi di
   classification_window_minutes vengono filtrati.

Sanity test simulator (DRY_RUN, ovviamente — qui non c'è LIVE perché non agisce):
```bash
python main.py --simulator --dry-run --config config_rc8.toml
```
Con `[backlash_diagnostic].enabled = true` temporaneamente. Il simulatore
non genera direction changes realistici, quindi NON vedrai classificazione
attiva — è OK. Verifica solo:
- Modulo importato senza errori
- `controller.get_status()` ritorna il blocco `backlash_diag` con stato
  `INSUFFICIENT_DATA`
- Nessuna regressione su altri trigger

## 7. VALIDAZIONE LIVE (procedura raccomandata)

A differenza del trigger esposizione, qui LIVE non è strettamente necessario
per validare la feature (perché la feature non agisce). Ma è utile per
raccogliere dati reali di direction change su CEM70G.

Procedura per Alessandro:

1. Sessione **LIVE** RC8 + CEM70G, `dry_run = false`,
   `[backlash_diagnostic].enabled = true`.
2. Almeno 2 ore di guida (per accumulare ≥ 5 direction change DEC).
3. Apertura dashboard, verifica blocco `backlash_diag` aggiornato.
4. A fine sessione, leggere `session_*.summary.json` sezione
   `backlash_diagnostic`.
5. Confronto manuale: Alessandro lancia il Backlash Wizard di PHD2
   (Tools > Guiding Assistant > Measure Dec backlash). Confrontare il
   verdetto della diagnostica con la misura del Wizard:
   - Se diagnostica dice OVERSHOOT_PERSISTENT e BL_misurato < BL_attuale → conferma
   - Se diagnostica dice DEADBAND_PERSISTENT e BL_misurato > BL_attuale → conferma
   - Se discordi → tarare le soglie del config (overshoot_arcsec_threshold,
     deadband_frames_threshold)

Dopo 2-3 sessioni con conferma del Wizard, la diagnostica è validata e si
può lasciare attiva permanentemente come "alert system" senza dover misurare
ogni volta.

---

## REGOLE INDEROGABILI

- **NON modificare** il backlash di PHD2 in alcun modo (è impossibile via
  JSON-RPC e va contro la regola di sicurezza in `CONTESTO_PROGETTO.md`).
- **NON disabilitare** Backlash Compensation di PHD2 dal nostro agent.
- **NON suggerire** valori specifici di pulse_ms — solo direzione "alza" o
  "abbassa" — perché senza misurazione attiva non possiamo essere precisi.
- **NON interferire** con il path A/B esposizione (sono feature ortogonali).
- **NON** chiamare `analyzer.reset()` quando si registra un direction change
  (a differenza del cambio esposizione, qui non serve).

---

## PROCEDURA REBUILD (obbligatoria post-modifica)

1. `python build_dist.py`
2. Copiare in `Pacchetto_Distribuzione/`:
   - `config_rc8.toml`, `config_tecnosky115.toml`, `config_askar71f.toml`
   - `Avvia_Askar71F.bat`, `Avvia_Tecnosky115.bat`, `Avvia_RC8.bat`
3. Ripristinare `LEGGIMI_PER_AVVIARE.txt`
4. Ricreare ZIP

---

## AGGIORNAMENTO DOCUMENTAZIONE (procedura collaudata)

### `CONTESTO_PROGETTO.md`

Nella sezione `## Stato attuale — aggiornato al ...`:
- Aggiornare la data
- Aggiungere paragrafo:

```markdown
### Backlash Diagnostic DEC — IMPLEMENTATA (YYYY-MM-DD)
Aggiunta classe `BacklashDiagnostic` in `phd2_agent/backlash_diagnostic.py`
che osserva la step response DEC nei frame successivi a cambi di segno
della deriva. Classifica in NORMAL / OVERSHOOT_PERSISTENT / DEADBAND_PERSISTENT.
**Funzione SOLO diagnostica**: nessuna modifica al BL di PHD2 (impossibile
via JSON-RPC e contraria alla regola di sicurezza). Output: log WARNING +
blocco `backlash_diag` in dashboard + sezione in `session_*.summary.json`.
Default `enabled = false`. Setup primario candidato: RC8 + CEM70G.
Vedere NOTE_CLAUDE.md sezione 20 per dettaglio completo.
```

In `## Cosa NON è stato ancora fatto`:
- Aggiungere:
  ```
  - Validazione diagnostica BL su RC8 + CEM70G: confronto verdetto della
    classificazione (OVERSHOOT/DEADBAND/NORMAL) con misurazione del
    Backlash Wizard di PHD2. Almeno 2-3 sessioni di confronto per
    tarare le soglie overshoot_arcsec_threshold e deadband_frames_threshold.
  ```

### `NOTE_CLAUDE.md`

Aggiungere sezione 20 (o quella successiva):

```markdown
---

## 20. Backlash Diagnostic DEC (YYYY-MM-DD)

### Motivazione
Discussione con Alessandro sulla possibilità di un trigger backlash. Verifica
sul sorgente PHD2 ha mostrato che:
1. Non esiste API JSON-RPC per leggere/scrivere il backlash compensation
   (grep su event_server.cpp: zero match)
2. PHD2 ha già un meccanismo interno di auto-regolazione (TrackBLCResults
   in backlash_comp.cpp:478-547) che adatta il pulse ±10/-20% per ciclo
3. Il Backlash Wizard è una procedura modale offline, non chiamabile
   durante guida normale

Quindi un trigger di azione è tecnicamente impossibile e logicamente
duplicato. Resta utile una feature DIAGNOSTICA che osserva i sintomi
e suggerisce all'utente di rifare il Wizard.

### Architettura
Modulo `phd2_agent/backlash_diagnostic.py` con classe `BacklashDiagnostic`.
Riceve i frame DEC dall'analyzer, mantiene una sliding window di 10 frame
recenti per rilevare cambi di segno deriva. Per ciascun cambio direzione,
registra i 5 frame successivi come "step response" e li classifica:
- OVERSHOOT: max excursion > soglia + ultimo frame segno opposto al primo
- DEADBAND: primi N frame tutti dello stesso segno (PHD2 non riesce a invertire)
- NORMAL: né l'uno né l'altro

Aggregazione su rolling window 30 minuti, verdetto richiede ≥ 5 cambi
direzione e maggioranza ≥ warning_threshold_count.

### Output
- Log WARNING su transizione di stato a OVERSHOOT_PERSISTENT/DEADBAND_PERSISTENT
- ControlAction con axis="dec", param="backlash_diagnostic", dry_run=True sempre
- Blocco backlash_diag in get_status() per dashboard
- Sezione backlash_diagnostic in session_*.summary.json a fine sessione

### Setup applicabili
- Askar 71F + AM5: enabled=false (encoder, BL trascurabile)
- Tecnosky 115 + AM5: idem
- Tecnosky 115 + CEM70G: marginale, soglie permissive
- RC8 + CEM70G: setup primario, soglie fini

### File modificati
- `phd2_agent/backlash_diagnostic.py` — nuovo modulo
- `phd2_agent/analyzer.py` — hook ingest_frame nel BacklashDiagnostic
- `phd2_agent/controller.py` — istanziazione, _evaluate_backlash_warning,
  blocco backlash_diag in get_status
- `phd2_agent/config.py` — dataclass BacklashDiagnosticConfig
- `phd2_agent/logger.py` — sezione backlash_diagnostic in summary
- `config_*.toml` — sezione [backlash_diagnostic]

### Limiti dell'approccio
1. NON misuriamo il BL effettivo (impossibile senza fermare la guida)
2. NON modifichiamo il valore in PHD2 (no API)
3. NON sostituiamo il Wizard (resta la misurazione di riferimento)
4. La classificazione richiede ≥ 5 cambi direzione DEC, che possono richiedere
   ore in nottata stabile. Su mount con backlash piccolo o assente potrebbe
   non scattare mai (è OK).

### Validazione
Procedura: confronto verdetto vs Backlash Wizard. 2-3 sessioni RC8+CEM70G
in LIVE con feature attiva, poi misurazione manuale Wizard, confronto.
Tuning soglie se discordanze.
```

---

## CHECKLIST FINALE PRIMA DI COMMIT

- [ ] Pre-flight eseguito: confermato che event_server.cpp non ha API per BL
- [ ] Pre-flight eseguito: letto TrackBLCResults in backlash_comp.cpp:478
- [ ] Modulo `backlash_diagnostic.py` creato con classi e tipi
- [ ] Hook in analyzer.ingest_guide_step() funzionante
- [ ] Controller istanzia il modulo solo se enabled=true
- [ ] `get_status()` ritorna blocco `backlash_diag`
- [ ] `session_*.summary.json` include sezione `backlash_diagnostic`
- [ ] Log WARNING emesso a transizione di stato (non ad ogni evaluate)
- [ ] ControlAction con axis="dec" param="backlash_diagnostic" dry_run=True sempre
- [ ] **Nessuna chiamata** a `set_algo_param` o equivalente per backlash
- [ ] Configurazioni TOML aggiornate per i 3 setup (tutti enabled=false)
- [ ] Test unitari coprono i 7 casi listati
- [ ] Sanity test simulator: nessuna regressione, blocco backlash_diag in /api/status
- [ ] CONTESTO_PROGETTO.md e NOTE_CLAUDE.md aggiornati
- [ ] Rebuild + ZIP rigenerati

---

## NOTA FINALE PER ALESSANDRO

Questa feature ha **valore moderato** rispetto al trigger esposizione.
Il motivo: l'azione resta manuale (Backlash Wizard di PHD2 o Brain). La
feature ti dice solo "guarda che il BL probabilmente è fuori range".

**Pro:**
- Ti accorgi di un BL mal calibrato senza dover rifare il Wizard ad ogni
  sessione (che richiede ~15 minuti e interruzione della guida)
- Trend a lungo termine: vedi se il BL della CEM70G si sta degradando
  nel tempo (usura meccanica)
- Documentazione automatica nella session summary

**Contro:**
- Nessuna azione automatica (limite tecnico, non di design)
- Richiede ≥ 5 cambi direzione DEC per dare un verdetto, che in nottata
  stabile possono essere pochissimi
- Falsi positivi possibili: vento gusty può simulare overshoot DEC
- Su Askar+AM5 inutile

**Verdetto onesto:** vale la pena solo se usi la CEM70G regolarmente.
Su AM5 (encoder) è praticamente disattivata sempre. Per il setup RC8+CEM70G
è una feature di valore moderato che fornisce diagnostica passiva utile
per monitorare la salute meccanica della montatura nel tempo.

Se preferisci concentrare gli sforzi sul trigger esposizione (più impattante
e di valore più immediato), questa feature può aspettare.
