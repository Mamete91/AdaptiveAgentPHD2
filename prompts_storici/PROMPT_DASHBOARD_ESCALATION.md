# PROMPT PER CLAUDE CODE (Antigravity) — Dashboard: Pannello "Stato Esposizione & Escalation Gate"
# Da copiare e incollare integralmente nella conversazione con Claude Code.
# Lavorare nella cartella: PHD2_Assist_PATCHED/

> **NOTA OPERATIVA**: questa è una feature **solo dashboard** (frontend + estensione minima dell'endpoint `/status` backend). NON modifica alcuna logica di controllo, NON tocca PHD2 via JSON-RPC, NON aggiunge nuove condizioni di trigger.
>
> Serve a rendere visibile sul grafico della dashboard, in tempo reale, lo stato della macchina esposizione (§19) e la saturazione delle leve aggressiveness/MinMove (escalation gate del path B). Necessaria per avere il **controllo visivo diretto su TUTTI i setup di Alessandro in modalità LIVE**, non solo su RC8 + CEM70G a Borno. La feature deve essere valida e operativa su:
> - Askar 71F + AM5 (focale piena 490mm e ridotta 367mm con 0.75x)
> - Tecnosky 115/800 + AM5/CEM70G (focale piena 800mm e ridotta 640mm con 0.80x)
> - RC8 + CEM70G (focale piena 1624mm e ridotta 1218mm con 0.75x)
>
> Tutti e 6 i `.bat` (3 nativi + 3 ridotti) devono lanciare in **modalità LIVE** (`dry_run = false`). Lo stato corrente è incoerente: solo RC8 è in LIVE, mentre i config Askar e Tecnosky sono ancora `dry_run = true` malgrado i loro `.bat` dichiarino "LIVE CONTROL" nell'echo. Questa feature **deve risolvere anche questa incoerenza**, allineando tutti i config e tutti i `.bat`.
>
> Per quanto riguarda `[exposure_dynamic].enabled` (path B esposizione dinamica), Alessandro ha richiesto di **attivarlo su tutti e 3 i setup**. Motivazione tecnica: con vento (raffiche), gli spike di guida si manifestano anche a focali corte/medie e l'integrazione via esposizione può aiutare a smussarli, non solo a focale lunga. Le soglie già differenziate per setup nei config (`spike_min` 0.30 Askar / 0.25 Tecnosky / 0.20 RC8 e `hfd_min_arcsec` 4.5 / 4.0 / 4.0) fungono da filtro naturale: su Askar serviranno eventi davvero forti per scattare un trigger, su RC8 basterà meno. È coerente e non richiede tuning aggiuntivo iniziale.
>
> La sezione precedente correlata è NOTE_CLAUDE.md §19 (esposizione dinamica RMS-based) e §20 (refactor [setup]). Questa diventa §21.

---

## 0. PRE-FLIGHT OBBLIGATORIO (leggere PRIMA di scrivere codice)

Questo refactor è puramente Python + frontend statico, non richiede di consultare il sorgente C++ di PHD2. Ti basta:

### File Python da leggere (per estensione `/status`)

1. **`server.py`** — endpoint FastAPI esistenti. Verifica:
   - Endpoint POST esistenti come pattern: `/config/dry_run` (~riga 180), `/config/ai_find` (~riga 187)
   - Endpoint `GET /status` (~riga 129) che chiama `controller.get_status()`
   - WebSocket `/ws` (~riga 199) per push real-time
   - Helper `broadcast()` async e `sync_broadcast()` thread-safe

2. **`phd2_agent/controller.py`** — il metodo `get_status()` (intorno a riga 940 nella versione attuale, dopo l'implementazione §19+§20). Verifica:
   - Blocco `"exposure"` già presente: `state`, `current_ms`, `base_ms`, `steps_above_base`
   - Blocchi `"ra"` e `"dec"` con `current_aggr`, `current_minmove`, `aggr_param`, `minmove_param`, `available_params`
   - Blocco `"saturation"` per AI Star Finder (NON confondere con la "saturazione delle leve" della nuova feature; sono due concetti diversi)
   - Riferimenti a `self.cfg.ra` e `self.cfg.dec` (AxisLimits) per leggere `aggr_min`/`aggr_max`/`minmove_min`/`minmove_max`
   - Helper esistente `_axis_levers_saturated(axis_state, limits)` (introdotto in §19) — restituisce True quando aggressiveness e MinMove di un asse sono entrambi al limite di config per almeno un cooldown
   - Attributi `_ra` e `_dec` (AxisState) con `last_action_time`, `last_minmove_action_time`
   - Attributo `last_exposure_action_time` per il cooldown del path B
   - `self.cfg.control.cooldown_seconds` (cooldown leve cheap, default 30)
   - `self.cfg.exposure_dynamic.cooldown_s` (cooldown esposizione, default 90)

### File frontend da leggere

3. **`dashboard/index.html`** — struttura HTML. Verifica:
   - Sezione `.gauges-row` con `gauge-card` per RMS RA/Dec/Total + `condition-card`
   - Sezione `.mid-row` con `chart-card` (canvas `#guide-chart` Chart.js) e `controller-card`
   - Sezione `.log-section` con `log-card`
   - Già presenti due toggle in header: AI Finder e MODALITÀ TEST (dry_run)

4. **`dashboard/app.js`** — pattern fetch + websocket esistenti. Cerca:
   - `fetch(`${API_BASE}/status`)` (~riga 184) — chiamata polling
   - `fetch(`${API_BASE}/config/dry_run`)` (~riga 400) — esempio POST toggle
   - Inizializzazione Chart.js per `#guide-chart` (usato per pannello "Grafico Guida")
   - Handler WebSocket per messaggi push (controllerare se esiste già una funzione di dispatch sui messaggi `{"type": ...}`)

5. **`dashboard/style.css`** — pattern di stile esistenti per card e badge. Riusare le classi già definite (es. `.card`, `.gauge-card`, `.controller-card`) per coerenza visiva.

### Conclusioni del pre-flight (da confermare con i propri occhi)

A. Il pattern POST endpoint + JS fetch + websocket broadcast è **già consolidato** nel progetto. Stiamo solo estendendo questa infrastruttura, non inventando nulla di nuovo.

B. La macchina a stati `ExposureState` (§19) e il sistema escalation gate (§19, helper `_axis_levers_saturated`) sono già implementati nel controller. La dashboard deve solo **esporre** queste informazioni — niente nuova logica di calcolo, solo lettura/serializzazione.

C. Chart.js è già caricato (`/static/chart.umd.min.js`) e usato nel pannello "Grafico Guida". Per i marker delle azioni esposizione sul grafico RMS, basta aggiungere un secondo dataset Chart.js di tipo `scatter` o usare `annotation` plugin (se già incluso) — verificare nel file `chart.umd.min.js` o all'inizializzazione del chart in `app.js`.

### Decisioni di design da PRENDERE in base alle verifiche

a. **Dove esattamente posizionare la nuova card "Stato Esposizione & Escalation Gate"**: due opzioni equivalenti. (1) Accanto al "Controller" nella `.mid-row` (cambiando il grid CSS da 2 colonne a 3, o riducendo proporzioni del chart); (2) In una nuova riga `.mid-row-2` sotto `.mid-row` con grid 2 colonne (card a sinistra, eventuale spazio futuro a destra). **Scelta raccomandata: opzione 2** (nuova riga). Motivo: il `chart-card` è già stretto su layout 2 colonne, ridurlo ulteriormente comprometterebbe la leggibilità del grafico RMS.

b. **Computo della "% saturazione" delle barre**: lineare tra il valore corrente e i limiti di config. Formula proposta:
   - Per **aggressiveness** (più si scende verso `aggr_min`, più è "saturato verso il basso"):
     `saturazione_aggr % = 100 * (aggr_max - current_aggr) / max(aggr_max - aggr_min, 1)`
   - Per **MinMove** (più sale verso `minmove_max`, più è "saturato verso l'alto"):
     `saturazione_mm % = 100 * (current_minmove - minmove_min) / max(minmove_max - minmove_min, 0.01)`
   - Convertire entrambe in range 0–100% (clipping). Una barra al 100% = leva esaurita.

c. **Cooldown residuo prima del prossimo trigger esposizione possibile**:
   `cooldown_residuo_s = max(0, cfg.exposure_dynamic.cooldown_s - (time.monotonic() - controller.last_exposure_action_time))`

d. **Stato gate aperto/chiuso**: usare l'helper esistente `_axis_levers_saturated(axis_state, limits)` (già implementato in §19). Restituisce True se le leve di quell'asse sono saturate da almeno 1 cooldown completo. Esporre `gate_open_ra: bool` e `gate_open_dec: bool` separati.

e. **Marker azioni esposizione sul grafico RMS**: due strategie possibili.
   - **Strategia A — verticalLines**: aggiungere annotation lines verticali (Chart.js annotation plugin) ai timestamp delle azioni. Pro: semplice. Contro: richiede il plugin annotation, potrebbe non essere già caricato.
   - **Strategia B — scatter overlay**: aggiungere un secondo dataset di tipo `scatter` sullo stesso asse temporale, con punti a `y=0` e colore distintivo per tipo (verde per UP path B, arancione per DOWN path B, giallo per path A SNR). Pro: nessun plugin extra. Contro: leggermente più codice JS.
   - **Scelta raccomandata: B** se annotation plugin non è già caricato, altrimenti A. **Verifica all'inizio** quale opzione è applicabile e procedi di conseguenza.

### Nessuna verifica → STOP

Se durante il pre-flight scopri che:
- L'helper `_axis_levers_saturated` non esiste con quella signature (è stato rinominato o spostato)
- Il blocco `exposure` in `get_status()` non è strutturato come documentato in NOTE_CLAUDE.md §19
- Chart.js è inizializzato in modo molto diverso da come ti aspetti

→ **Fermati e riporta** ad Alessandro prima di procedere.

---

## OBIETTIVO TECNICO

Aggiungere alla dashboard una card compatta "Stato Esposizione & Escalation Gate" che rende visibili in tempo reale: stato macchina esposizione, valori esposizione corrente/base/step, cooldown residuo prima del prossimo trigger possibile, barre di saturazione delle leve aggressiveness/MinMove per RA e DEC, indicatore "gate aperto" per asse. Più marker visivi delle azioni esposizione sovrapposti al grafico RMS esistente.

L'obiettivo finale è **predittività + spiegabilità**: Alessandro deve poter capire a colpo d'occhio se il path B sta per scattare (gate aperto + metriche oltre soglia) e correlare visivamente le azioni esposizione con l'effetto sull'RMS.

---

## REGOLE INDEROGABILI

- **NON toccare** la backlash compensation di PHD2 (regola assoluta).
- **NON modificare** la logica del controller (analyzer, evaluate, _evaluate_exposure_*, escalation gate). Solo aggiungere lettura/serializzazione di campi già esistenti nel blocco `get_status()`.
- **NON modificare** la logica delle decisioni di trigger del path A o B. Questa feature è puro visual.
- **NON introdurre** nuove librerie esterne. Resta su FastAPI + Chart.js già presenti. Eventualmente Chart.js annotation plugin SOLO se già nel `chart.umd.min.js` bundle (verificare).
- Mantenere lo stile coerente con dashboard esistente: classi CSS esistenti, palette colori coerente, font Inter + JetBrains Mono già caricati.
- Logging Python in italiano come nel resto del progetto.

### MODALITÀ OPERATIVA — TUTTI i setup in LIVE, non solo RC8

Alessandro vuole avere il **controllo visivo diretto su tutti e tre i setup in modalità LIVE**, sia a focale piena che con riduttore. La feature deve essere immediatamente operativa qualunque `.bat` venga lanciato, su qualsiasi sito (Borno o postazione mobile).

**Stato attuale (incoerente, da correggere)**:
- `config_rc8.toml`: `dry_run = false`, `[exposure_dynamic].enabled = true` ✓ già LIVE
- `config_askar71f.toml`: `dry_run = true` ✗ ma `Avvia_Askar71F.bat` dichiara erroneamente "Modalita: LIVE CONTROL (Attivo)" — **incoerenza da risolvere**
- `config_tecnosky115.toml`: `dry_run = true` ✗ ma `Avvia_Tecnosky115.bat` dichiara erroneamente "Modalita: LIVE CONTROL (Attivo)" — **incoerenza da risolvere**
- `.bat` ridotti (Askar 71F Ridotto, Tecnosky 115 Ridotto): **non dichiarano alcuna modalità** nell'echo — da uniformare

**Stato richiesto da Alessandro**:
- Tutti e 3 i config (root + Pacchetto_Distribuzione = 6 file) con `dry_run = false`
- `[exposure_dynamic].enabled = true` su **tutti e 3 i setup** (path B attivo ovunque per gestire spike da vento + seeing degradato; le soglie già differenziate per setup fungono da filtro naturale)
- Tutti e 6 i `.bat` (3 nativi + 3 ridotti) coerenti nell'echo: ognuno dichiara *"MODALITA: LIVE (dry_run=false)"* + *"exposure_dynamic.enabled: true (path B attivo)"*

**Sicurezza in LIVE su tutti i setup**:
- Le regole di sicurezza già implementate proteggono in qualsiasi configurazione: Baseline Guardian v3 (ripristina parametri su Ctrl+C e su crash), escalation gate (path B non scatta senza saturazione leve), max_steps_above_base = 2, max_exposure_ms in `[emergency]`, RMS implosion detector (analisi sospesa 60s su garbage frame).
- Su Askar 71F + AM5 in LIVE: agiscono path standard (aggressiveness/MinMove) + path A (LOW_SNR) + path B (RMS-based). Path B con soglie alte (spike_min=0.30, hfd_min_arcsec=4.5) scatterà solo su raffiche di vento o seeing davvero degradato.
- Su Tecnosky 115 in LIVE: idem Askar, soglie intermedie (spike_min=0.25, hfd_min_arcsec=4.0).
- Su RC8 + CEM70G in LIVE: soglie più sensibili (spike_min=0.20), path B si attiverà più facilmente.

**Pannello dashboard universale**:
- Il pannello deve aggiornarsi in tempo reale (~ogni 1-2 s polling o tramite WebSocket push se l'infrastruttura esistente lo permette).
- Sempre visibile, su qualsiasi setup. Niente flag di abilitazione UI separato.
- Su tutti e 3 i setup il pannello mostra tutto: badge stato che evolve (NOMINAL → BOOSTED_FOR_SEEING / BOOSTED_FOR_SNR), valori esposizione che cambiano sui trigger, cooldown che si riempie, gate aperto/chiuso, marker rombi colorati sul grafico RMS. Frequenza degli eventi diversa per setup (più rari su Askar per via delle soglie alte), ma comportamento identico.

---

## SPECIFICA FUNZIONALE

### 2A. Estensione di `controller.get_status()` con escalation gate metrics

Nel metodo `AdaptiveController.get_status()` di `phd2_agent/controller.py`, **aggiungere** (non modificare i blocchi esistenti) un nuovo blocco `escalation_gate` e arricchire il blocco `exposure` esistente con il cooldown residuo:

```python
# Calcoli helper (in get_status, prima del return)
now = time.monotonic()

# Cooldown residuo path B esposizione
ed_cooldown = self.cfg.exposure_dynamic.cooldown_s
elapsed_exp = now - self.last_exposure_action_time
cooldown_residuo_s = max(0.0, ed_cooldown - elapsed_exp)

# Saturazione % per asse (formula b da pre-flight)
def _saturation_pct(axis_state, limits):
    aggr_range = max(limits.aggr_max - limits.aggr_min, 1.0)
    mm_range = max(limits.minmove_max - limits.minmove_min, 0.01)
    sat_aggr = 100.0 * (limits.aggr_max - axis_state.current_aggr) / aggr_range
    sat_mm   = 100.0 * (axis_state.current_minmove - limits.minmove_min) / mm_range
    return (max(0.0, min(100.0, sat_aggr)), max(0.0, min(100.0, sat_mm)))

sat_ra_aggr, sat_ra_mm = _saturation_pct(self._ra, self.cfg.ra)
sat_dec_aggr, sat_dec_mm = _saturation_pct(self._dec, self.cfg.dec)

gate_open_ra = self._axis_levers_saturated(self._ra, self.cfg.ra)
gate_open_dec = self._axis_levers_saturated(self._dec, self.cfg.dec)
```

Aggiungere al dict di ritorno:

```python
"exposure": {
    # ... campi esistenti (state, current_ms, base_ms, steps_above_base) ...
    "cooldown_residuo_s": round(cooldown_residuo_s, 1),
    "cooldown_total_s": ed_cooldown,
},
"escalation_gate": {
    "ra": {
        "aggr_saturation_pct": round(sat_ra_aggr, 1),
        "minmove_saturation_pct": round(sat_ra_mm, 1),
        "gate_open": gate_open_ra,
        "current_aggr": self._ra.current_aggr,
        "current_minmove": self._ra.current_minmove,
        "aggr_min": self.cfg.ra.aggr_min,
        "aggr_max": self.cfg.ra.aggr_max,
        "minmove_min": self.cfg.ra.minmove_min,
        "minmove_max": self.cfg.ra.minmove_max,
    },
    "dec": {
        "aggr_saturation_pct": round(sat_dec_aggr, 1),
        "minmove_saturation_pct": round(sat_dec_mm, 1),
        "gate_open": gate_open_dec,
        "current_aggr": self._dec.current_aggr,
        "current_minmove": self._dec.current_minmove,
        "aggr_min": self.cfg.dec.aggr_min,
        "aggr_max": self.cfg.dec.aggr_max,
        "minmove_min": self.cfg.dec.minmove_min,
        "minmove_max": self.cfg.dec.minmove_max,
    },
},
```

**Importante**: il metodo `_axis_levers_saturated` è già implementato (§19, controller.py ~riga 860). Se è una `method` invece di `staticmethod`, accessibile via `self._axis_levers_saturated(axis_state, limits)`. Verifica la signature esatta prima di chiamarla.

### 2B. Modifica `server.py` (minima — solo verifica)

Il GET `/status` già chiama `controller.get_status()`, quindi non serve toccare il server.py se non per **opzionalmente** aggiungere un broadcast dedicato dei cambi escalation_gate. **Sconsigliato per ora** — il polling/WebSocket esistente è sufficiente.

### 2C. Modifica `dashboard/index.html` — nuova card

Aggiungere **dopo la `<section class="mid-row">` e prima della `<section class="log-section">`** una nuova sezione:

```html
<!-- Stato Esposizione & Escalation Gate -->
<section class="mid-row-2">
  <div class="exposure-card" id="exposure-escalation-card">
    <h2>Esposizione & Escalation Gate</h2>

    <!-- Riga 1: badge stato + valori -->
    <div class="exp-header">
      <div class="exp-state-badge" id="exp-state-badge">
        <span id="exp-state-label">NOMINAL</span>
      </div>
      <div class="exp-values">
        <span class="exp-current" id="exp-current">— ms</span>
        <span class="exp-base">base <span id="exp-base">— ms</span></span>
        <span class="exp-steps" id="exp-steps">+0/2 step</span>
      </div>
    </div>

    <!-- Riga 2: cooldown -->
    <div class="exp-cooldown">
      <span class="cooldown-label">Cooldown al prossimo trigger:</span>
      <span class="cooldown-value" id="exp-cooldown-val">— s</span>
      <div class="cooldown-bar-wrap">
        <div class="cooldown-bar" id="exp-cooldown-bar"></div>
      </div>
    </div>

    <!-- Riga 3: saturazione leve RA -->
    <div class="lever-block">
      <div class="lever-axis">RA</div>
      <div class="lever-row">
        <span class="lever-label">Aggr</span>
        <div class="lever-bar-wrap"><div class="lever-bar" id="ra-aggr-bar"></div></div>
        <span class="lever-pct" id="ra-aggr-pct">—%</span>
      </div>
      <div class="lever-row">
        <span class="lever-label">MinM</span>
        <div class="lever-bar-wrap"><div class="lever-bar" id="ra-mm-bar"></div></div>
        <span class="lever-pct" id="ra-mm-pct">—%</span>
      </div>
      <div class="gate-badge" id="ra-gate-badge"></div>
    </div>

    <!-- Riga 4: saturazione leve DEC -->
    <div class="lever-block">
      <div class="lever-axis">DEC</div>
      <div class="lever-row">
        <span class="lever-label">Aggr</span>
        <div class="lever-bar-wrap"><div class="lever-bar" id="dec-aggr-bar"></div></div>
        <span class="lever-pct" id="dec-aggr-pct">—%</span>
      </div>
      <div class="lever-row">
        <span class="lever-label">MinM</span>
        <div class="lever-bar-wrap"><div class="lever-bar" id="dec-mm-bar"></div></div>
        <span class="lever-pct" id="dec-mm-pct">—%</span>
      </div>
      <div class="gate-badge" id="dec-gate-badge"></div>
    </div>
  </div>
</section>
```

### 2D. Modifica `dashboard/style.css` — stile della card

Aggiungere in coda al CSS esistente. Riusa palette e font già definiti nel file (non importare font nuovi). Stile sobrio coerente con il resto.

```css
/* === Pannello Esposizione & Escalation Gate === */
.mid-row-2 {
  display: grid;
  grid-template-columns: 1fr;
  gap: 1rem;
  margin-top: 1rem;
}
.exposure-card {
  background: var(--card-bg, #1a2332);
  border: 1px solid var(--card-border, #2a3a4f);
  border-radius: 8px;
  padding: 1.25rem;
  color: #d5dae3;
  font-family: 'Inter', sans-serif;
}
.exposure-card h2 {
  margin: 0 0 1rem 0;
  font-size: 1rem;
  font-weight: 600;
  color: #a9b5c7;
  letter-spacing: 0.5px;
  text-transform: uppercase;
}
.exp-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 1rem;
  margin-bottom: 1rem;
}
.exp-state-badge {
  padding: 0.4rem 0.85rem;
  border-radius: 4px;
  font-weight: 600;
  font-size: 0.85rem;
  letter-spacing: 0.5px;
  background: #2a4a3a;  /* verde tenue NOMINAL default */
  color: #b4e0b4;
}
.exp-state-badge.boosted-snr {
  background: #4a4422;
  color: #e8d97c;
}
.exp-state-badge.boosted-seeing {
  background: #5a3520;
  color: #f0a674;
}
.exp-values {
  display: flex;
  gap: 1.2rem;
  align-items: baseline;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.9rem;
}
.exp-current {
  font-size: 1.1rem;
  font-weight: 600;
  color: #e5ebf2;
}
.exp-base {
  color: #8c98ac;
  font-size: 0.8rem;
}
.exp-steps {
  color: #c0c8d6;
  font-size: 0.85rem;
  padding: 0.15rem 0.5rem;
  border: 1px solid #3a4a60;
  border-radius: 3px;
}
.exp-cooldown {
  margin-bottom: 1rem;
  display: grid;
  grid-template-columns: auto auto 1fr;
  gap: 0.6rem;
  align-items: center;
}
.cooldown-label {
  font-size: 0.8rem;
  color: #8c98ac;
}
.cooldown-value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.9rem;
  color: #c5cdda;
  min-width: 50px;
}
.cooldown-bar-wrap {
  height: 6px;
  background: #2a3a4f;
  border-radius: 3px;
  overflow: hidden;
}
.cooldown-bar {
  height: 100%;
  background: linear-gradient(90deg, #3a6a99, #4a8abf);
  width: 0%;
  transition: width 0.3s ease;
}
.lever-block {
  display: grid;
  grid-template-columns: 60px 1fr auto;
  gap: 0.5rem 0.8rem;
  margin-bottom: 0.85rem;
  align-items: center;
}
.lever-axis {
  grid-column: 1;
  grid-row: 1 / span 2;
  font-weight: 700;
  font-size: 0.95rem;
  color: #e5ebf2;
  font-family: 'JetBrains Mono', monospace;
  align-self: center;
}
.lever-row {
  grid-column: 2 / span 2;
  display: grid;
  grid-template-columns: 50px 1fr 50px;
  gap: 0.6rem;
  align-items: center;
}
.lever-label {
  font-size: 0.75rem;
  color: #8c98ac;
  font-family: 'JetBrains Mono', monospace;
}
.lever-bar-wrap {
  height: 8px;
  background: #2a3a4f;
  border-radius: 4px;
  overflow: hidden;
}
.lever-bar {
  height: 100%;
  background: linear-gradient(90deg, #4a7a4a, #6ab06a);
  width: 0%;
  transition: width 0.3s ease, background 0.3s ease;
}
.lever-bar.saturating { background: linear-gradient(90deg, #b39d3a, #e0c450); }
.lever-bar.saturated  { background: linear-gradient(90deg, #b0552a, #d97540); }
.lever-pct {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.8rem;
  color: #c5cdda;
  text-align: right;
}
.gate-badge {
  grid-column: 3;
  grid-row: 1 / span 2;
  font-size: 0.75rem;
  font-weight: 600;
  padding: 0.3rem 0.5rem;
  border-radius: 4px;
  text-align: center;
  align-self: center;
  min-width: 80px;
  background: #2a3a4f;
  color: #6a7a90;
  border: 1px solid #3a4a60;
}
.gate-badge.open {
  background: #5a3520;
  color: #f0a674;
  border-color: #b0552a;
}
.gate-badge.open::before {
  content: "🔓 ";
}
.gate-badge.closed::before {
  content: "🔒 ";
}
```

### 2E. Modifica `dashboard/app.js` — populate del pannello + marker grafico

In `app.js`, **dentro la funzione che processa il payload `/status` ricevuto** (probabilmente quella che oggi aggiorna i gauges e la card Controller), aggiungere il codice di update del pannello:

```javascript
function updateExposureEscalation(status) {
  // --- Esposizione ---
  const exp = status.exposure || {};
  const stateEl = document.getElementById('exp-state-label');
  const stateBadge = document.getElementById('exp-state-badge');
  const currentEl = document.getElementById('exp-current');
  const baseEl = document.getElementById('exp-base');
  const stepsEl = document.getElementById('exp-steps');
  const cooldownVal = document.getElementById('exp-cooldown-val');
  const cooldownBar = document.getElementById('exp-cooldown-bar');

  const state = exp.state || 'NOMINAL';
  stateEl.textContent = state;
  stateBadge.classList.remove('boosted-snr', 'boosted-seeing');
  if (state === 'BOOSTED_FOR_SNR') stateBadge.classList.add('boosted-snr');
  if (state === 'BOOSTED_FOR_SEEING') stateBadge.classList.add('boosted-seeing');

  currentEl.textContent = exp.current_ms != null ? `${exp.current_ms} ms` : '— ms';
  baseEl.textContent = exp.base_ms != null ? `${exp.base_ms} ms` : '— ms';
  const stepsAbove = exp.steps_above_base ?? 0;
  // Limite atteso (max_steps_above_base) — fissato a 2 per coerenza con default config;
  // se in futuro diventa dinamico, esporre anche quello in get_status.
  stepsEl.textContent = `+${stepsAbove}/2 step`;

  const cdRes = exp.cooldown_residuo_s ?? 0;
  const cdTot = exp.cooldown_total_s ?? 90;
  cooldownVal.textContent = `${cdRes.toFixed(1)} s`;
  // Barra: si "riempie" mentre il cooldown scade (0% appena fatto, 100% pronto al prossimo trigger)
  const cdProgress = cdTot > 0 ? Math.max(0, Math.min(100, 100 * (1 - cdRes / cdTot))) : 100;
  cooldownBar.style.width = `${cdProgress}%`;

  // --- Escalation gate ---
  const gate = status.escalation_gate || {};
  for (const axis of ['ra', 'dec']) {
    const data = gate[axis] || {};
    const aggrBar = document.getElementById(`${axis}-aggr-bar`);
    const mmBar = document.getElementById(`${axis}-mm-bar`);
    const aggrPct = document.getElementById(`${axis}-aggr-pct`);
    const mmPct = document.getElementById(`${axis}-mm-pct`);
    const gateBadge = document.getElementById(`${axis}-gate-badge`);

    const sa = data.aggr_saturation_pct ?? 0;
    const sm = data.minmove_saturation_pct ?? 0;
    aggrBar.style.width = `${sa}%`;
    mmBar.style.width = `${sm}%`;
    aggrPct.textContent = `${sa.toFixed(0)}%`;
    mmPct.textContent = `${sm.toFixed(0)}%`;

    // Colore barre: verde < 60%, giallo 60-90%, arancione > 90%
    for (const bar of [aggrBar, mmBar]) {
      bar.classList.remove('saturating', 'saturated');
    }
    if (sa >= 90) aggrBar.classList.add('saturated');
    else if (sa >= 60) aggrBar.classList.add('saturating');
    if (sm >= 90) mmBar.classList.add('saturated');
    else if (sm >= 60) mmBar.classList.add('saturating');

    gateBadge.classList.remove('open', 'closed');
    if (data.gate_open) {
      gateBadge.classList.add('open');
      gateBadge.textContent = 'Gate aperto';
    } else {
      gateBadge.classList.add('closed');
      gateBadge.textContent = 'Gate chiuso';
    }
  }
}
```

**Chiamare `updateExposureEscalation(status)`** subito dopo (o accanto a) le funzioni esistenti che aggiornano i gauges/condizione/controller.

### 2F. Marker azioni esposizione sul grafico RMS esistente

In `app.js`, dove viene inizializzato il Chart.js per `#guide-chart`, aggiungere un secondo dataset di tipo `scatter` overlay sullo stesso asse temporale:

```javascript
// Dentro la config di Chart.js, nei datasets:
{
  label: 'Azioni esposizione',
  type: 'scatter',
  data: [],  // popolato dinamicamente: { x: timestamp, y: 0, kind: 'snr_up' | 'seeing_up' | ... }
  pointRadius: 6,
  pointStyle: 'rectRot',  // rombo
  backgroundColor: (ctx) => {
    const kind = ctx.raw?.kind;
    if (kind === 'seeing_up') return '#d97540';   // arancione
    if (kind === 'seeing_down') return '#6ab06a'; // verde
    if (kind === 'snr_up' || kind === 'snr_down') return '#e0c450'; // giallo
    return '#888';
  },
  yAxisID: 'y',  // stesso asse RMS
  showLine: false,
}
```

Quando arriva una nuova `last_action` con `axis === 'camera'` e `param === 'exposure_snr' | 'exposure_seeing'`:
```javascript
function recordExposureAction(action) {
  const kind = action.param === 'exposure_seeing'
    ? (action.new_value > action.old_value ? 'seeing_up' : 'seeing_down')
    : (action.new_value > action.old_value ? 'snr_up' : 'snr_down');
  exposureActionsDataset.data.push({
    x: action.timestamp * 1000,  // Chart.js usa ms se time scale
    y: 0,  // sull'asse RMS, posizione fissa baseline
    kind,
    reason: action.reason
  });
  // Trim per evitare crescita illimitata
  if (exposureActionsDataset.data.length > 200) {
    exposureActionsDataset.data.shift();
  }
  guideChart.update('none');
}
```

Tooltip sul marker che mostra `reason` (Chart.js callback `tooltip.callbacks.label`):
```javascript
tooltip: {
  callbacks: {
    label: (ctx) => {
      if (ctx.dataset.label === 'Azioni esposizione') {
        return ctx.raw.reason || ctx.raw.kind;
      }
      return `${ctx.dataset.label}: ${ctx.formattedValue}`;
    }
  }
}
```

Per popolarli all'avvio (recupero storico), aggiungere una chiamata one-shot a `GET /history` (endpoint esistente) e filtrare le azioni `camera/exposure_*`.

### 2G. Allineamento di TUTTI i config e i `.bat` in modalità LIVE

Questa sezione è **funzionale all'obiettivo "tutti i setup in LIVE"** indicato da Alessandro nella NOTA OPERATIVA. Le modifiche sono semplici ma vanno fatte con cura per evitare incoerenze residue.

#### Modifica `config_askar71f.toml` (root + Pacchetto_Distribuzione = 2 file)

Due cambi necessari:

```toml
# Nella sezione [control]
dry_run = false       # LIVE — comandi reali a PHD2

# Nella sezione [exposure_dynamic]
enabled = true        # path B attivo anche qui: gestione spike da vento a focale corta
```

Aggiungere subito sopra `[control]` un commento esplicativo:

```toml
# MODALITÀ LIVE per controllo visivo diretto sulla dashboard
# - dry_run = false → comandi reali a PHD2
# - [exposure_dynamic].enabled = true → path B attivo per gestire raffiche di vento
#   e seeing degradato anche a focale corta (490mm, pixel scale 1.58"/px nativo).
#   Le soglie alte (spike_min=0.30, hfd_min_arcsec=4.5) fungono da filtro naturale:
#   scatta solo su eventi davvero forti, non su rumore ordinario.
```

#### Modifica `config_tecnosky115.toml` (root + Pacchetto_Distribuzione = 2 file)

Stessi cambi del precedente:

```toml
# Nella sezione [control]
dry_run = false       # LIVE — comandi reali a PHD2

# Nella sezione [exposure_dynamic]
enabled = true        # path B attivo per gestione vento/seeing a focale media
```

Commento esplicativo sopra `[control]`:

```toml
# MODALITÀ LIVE per controllo visivo diretto sulla dashboard
# - dry_run = false → comandi reali a PHD2
# - [exposure_dynamic].enabled = true → path B attivo per gestire raffiche di vento
#   e seeing degradato a focale media (800mm, pixel scale 1.03"/px nativo).
#   Soglie intermedie (spike_min=0.25, hfd_min_arcsec=4.0): scatto su eventi
#   moderati-forti, meno frequenti di RC8 ma più frequenti di Askar.
```

#### `config_rc8.toml` — già in LIVE con path B attivo, **non toccare**

Resta com'è (§19/§20): `dry_run = false`, `[exposure_dynamic].enabled = true`.

#### Verifica/uniformazione dei 6 `.bat` in `Pacchetto_Distribuzione/`

I `.bat` esistenti hanno echo incoerenti. Va uniformato il blocco echo di **tutti i 6 file** con un formato standard:

**`Avvia_Askar71F.bat`** (focale piena):
```batch
@echo off
cd /d "%~dp0"
echo.
echo  ======================================
echo   PHD2 Adaptive Agent - Askar 71F
echo   Focale piena: 490mm  Montatura: AM5
echo   Pixel scale guida: 1.58 "/px
echo   MODALITA: LIVE (dry_run=false)
echo   exposure_dynamic.enabled: true  (path B attivo)
echo  ======================================
echo.
echo  Apri il browser su: http://localhost:8080
echo.
PHD2_Agent.exe --config config_askar71f.toml
pause
```

**`Avvia_Askar71F_Ridotto.bat`**:
```batch
@echo off
cd /d "%~dp0"
echo.
echo  ======================================
echo   PHD2 Adaptive Agent - Askar 71F
echo   Focale ridotta: 367mm (riduttore 0.75x)
echo   Pixel scale guida: 2.11 "/px
echo   MODALITA: LIVE (dry_run=false)
echo   exposure_dynamic.enabled: true  (path B attivo)
echo  ======================================
echo.
echo  Apri il browser su: http://localhost:8080
echo.
PHD2_Agent.exe --config config_askar71f.toml --with-reducer
pause
```

**`Avvia_Tecnosky115.bat`**:
```batch
@echo off
cd /d "%~dp0"
echo.
echo  ======================================
echo   PHD2 Adaptive Agent - Tecnosky 115/800
echo   Focale piena: 800mm  Montatura: AM5/CEM70G
echo   Pixel scale guida: 1.03 "/px
echo   MODALITA: LIVE (dry_run=false)
echo   exposure_dynamic.enabled: true  (path B attivo)
echo  ======================================
echo.
echo  Apri il browser su: http://localhost:8080
echo.
PHD2_Agent.exe --config config_tecnosky115.toml
pause
```

**`Avvia_Tecnosky115_Ridotto.bat`**:
```batch
@echo off
cd /d "%~dp0"
echo.
echo  ======================================
echo   PHD2 Adaptive Agent - Tecnosky 115/800
echo   Focale ridotta: 640mm (riduttore 0.80x)
echo   Pixel scale guida: 1.29 "/px
echo   MODALITA: LIVE (dry_run=false)
echo   exposure_dynamic.enabled: true  (path B attivo)
echo  ======================================
echo.
echo  Apri il browser su: http://localhost:8080
echo.
PHD2_Agent.exe --config config_tecnosky115.toml --with-reducer
pause
```

**`Avvia_RC8.bat`** (focale piena):
```batch
@echo off
cd /d "%~dp0"
echo.
echo  ======================================
echo   PHD2 Adaptive Agent - RC8
echo   Focale piena: 1624mm  Montatura: CEM70G
echo   Pixel scale guida: 0.51 "/px
echo   MODALITA: LIVE (dry_run=false)
echo   exposure_dynamic.enabled: true  (path B attivo)
echo  ======================================
echo.
echo  Apri il browser su: http://localhost:8080
echo.
PHD2_Agent.exe --config config_rc8.toml
pause
```

**`Avvia_RC8_Ridotto.bat`**:
```batch
@echo off
cd /d "%~dp0"
echo.
echo  ======================================
echo   PHD2 Adaptive Agent - RC8
echo   Focale ridotta: 1218mm (riduttore 0.75x)
echo   Pixel scale guida: 0.68 "/px
echo   MODALITA: LIVE (dry_run=false)
echo   exposure_dynamic.enabled: true  (path B attivo)
echo  ======================================
echo.
echo  Apri il browser su: http://localhost:8080
echo.
PHD2_Agent.exe --config config_rc8.toml --with-reducer
pause
```

#### Aggiornamento `LEGGIMI_PER_AVVIARE.txt` in `Pacchetto_Distribuzione/`

Sostituire con (mantenere l'attuale stile, ma aggiornare la tabella):

```
PHD2 Adaptive Agent — Pacchetto Distribuzione
==============================================

Modalità: LIVE OPERATIVA su tutti i setup.
Dashboard: http://localhost:8080

Doppio click sul .bat corrispondente al tuo setup:

  Avvia_Askar71F.bat              490mm    Askar 71F + AM5            (path B attivo)
  Avvia_Askar71F_Ridotto.bat      367mm    + riduttore 0.75x          (path B attivo)
  Avvia_Tecnosky115.bat           800mm    Tecnosky 115/800 + AM5/CEM (path B attivo)
  Avvia_Tecnosky115_Ridotto.bat   640mm    + riduttore 0.80x          (path B attivo)
  Avvia_RC8.bat                   1624mm   RC8 + CEM70G               (path B attivo)
  Avvia_RC8_Ridotto.bat           1218mm   + riduttore 0.75x          (path B attivo)

Path B (esposizione dinamica RMS-based) attivo su tutti i setup. Le soglie
spike_min e hfd_min_arcsec sono differenziate per setup: scatta più di frequente
su RC8 (soglie sensibili 0.20/4.0), più raramente su Askar (soglie alte 0.30/4.5).

Nota sicurezza:
- Tutti i setup partono in modalità LIVE: l'agent invia comandi reali a PHD2.
- Le regole di sicurezza (Baseline Guardian, escalation gate, RMS implosion
  detector) proteggono il loop di guida.
- Per ripristinare valori originali: Ctrl+C → Baseline Guardian ripristina.
- Per kill brutale: il file baseline.json viene rilevato come orfano al
  prossimo avvio e ripristinato automaticamente.
```

---

## TEST ATTESI

### Sanity check simulator (non-regressione)

```bash
python main.py --simulator --dry-run --config config_rc8.toml
```

Verifica:
- Nessun `ImportError` o `AttributeError` all'avvio (controller.get_status() restituisce ancora un dict valido con i nuovi campi)
- La dashboard si carica su `http://localhost:8080` e mostra la nuova card vuota/inattiva (simulator non genera azioni esposizione reali, ma le barre saturazione devono mostrare valori coerenti col config)
- Le altre card e il grafico esistenti continuano a funzionare senza regressioni
- `curl http://localhost:8080/status | python -m json.tool` mostra i nuovi blocchi `escalation_gate` e i campi `cooldown_residuo_s`/`cooldown_total_s` dentro `exposure`

### Test unitari

Per questa feature i test unitari **non sono strettamente necessari** perché:
- La logica nuova è puro view/serializzazione (`get_status()` arricchito) + frontend
- Il calcolo della saturazione percentuale è matematicamente banale e visualmente verificabile
- Il pattern dashboard è UI, difficile da unit-testare in modo significativo

**Opzionale ma consigliato**: un test minimo per `get_status()` che verifichi presenza dei nuovi campi:

```python
def test_get_status_includes_escalation_gate(self):
    ctrl = _make_controller()
    status = ctrl.get_status()
    self.assertIn("escalation_gate", status)
    self.assertIn("ra", status["escalation_gate"])
    self.assertIn("aggr_saturation_pct", status["escalation_gate"]["ra"])
    self.assertIn("gate_open", status["escalation_gate"]["ra"])
    self.assertIn("cooldown_residuo_s", status["exposure"])
```

Aggiungere in `tests/test_setup_config.py` o creare `tests/test_get_status.py` (a tua discrezione, basta che `python -m pytest tests/ -v` passi tutto).

### Test esistenti — verificare zero regressioni

`tests/test_exposure_dynamic.py` (5 test §19) e `tests/test_setup_config.py` (3 test §20): devono passare invariati. La firma di `get_status()` è arricchita, non modificata.

---

## VALIDAZIONE LIVE SUL CAMPO (procedure per TUTTI i setup)

La validazione avviene in LIVE su tutti e 3 i setup, sia native che ridotti. Le verifiche dipendono dal tipo di setup: su RC8 (path B attivo) si osservano anche i trigger esposizione e i marker; sugli altri si osserva il comportamento del controller standard (aggressiveness/MinMove) e la saturazione delle leve.

### Verifica iniziale comune (dopo qualsiasi `.bat`)

Indipendentemente dal setup avviato:

1. PHD2 connesso al telescopio corrispondente, guida normalmente in stato stabile da almeno 5 min
2. Doppio click sul `.bat` appropriato
3. Verificare nell'output console che la prima riga dichiari coerentemente: `MODALITA: LIVE (dry_run=false)` e lo stato di `exposure_dynamic.enabled` corretto per il setup
4. Aprire dashboard `http://localhost:8080`
5. **Verifica visiva immediata** (entro 30 s dall'avvio):
   - Card "Esposizione & Escalation Gate" visibile sotto il grafico/controller
   - Badge stato verde "NOMINAL"
   - Valori esposizione corrente = base (es. "2000 ms (base 2000 ms)", "+0/2 step")
   - Cooldown "0.0 s" inizialmente
   - Barre saturazione RA/DEC mostrano la % corrente in base ai valori letti da PHD2
   - Badge gate: "Gate chiuso" su entrambi gli assi

### Procedura per setup RC8 + CEM70G (sessione primaria a Borno, path B attivo)

Su questo setup si validano sia il pannello dashboard che il path B esposizione dinamica:

- **Quando il seeing si degrada**: le barre aggressiveness/MinMove saturano gradualmente. Aggressiveness scende verso `aggr_min`, MinMove sale verso `minmove_max`. Le barre cambiano colore (verde < 60% → giallo 60-90% → arancione ≥ 90%).
- **Quando un asse satura entrambe le leve da ≥ 1 cooldown** (30 s): badge diventa "🔓 Gate aperto". Se le metriche seeing peggiorano ancora, l'agent può scattare trigger esposizione UP.
- **Quando scatta trigger esposizione**: badge stato → "BOOSTED_FOR_SEEING" (arancione) o "BOOSTED_FOR_SNR" (giallo); valori esposizione aggiornati; rombo colorato sul grafico RMS al timestamp; barra cooldown ricomincia da 0%.
- **Quando esposizione torna a base**: badge → NOMINAL; valori resettati; rombo opposto sul grafico.

Per il riduttore: `Avvia_RC8_Ridotto.bat`, comportamento identico ma con pixel scale 0.68"/px effettiva.

### Procedura per setup Askar 71F + AM5 (focale corta, path B attivo con soglie alte)

Su questo setup path B è attivo con soglie alte (`spike_min=0.30`, `hfd_min_arcsec=4.5`), quindi i trigger scatteranno **solo su raffiche di vento davvero forti o seeing molto degradato**. In nottata calma probabilmente vedrai poco/nulla; in nottata ventosa vedrai i trigger.

- Doppio click su `Avvia_Askar71F.bat` (native) o `Avvia_Askar71F_Ridotto.bat` (ridotto)
- Badge stato: parte NOMINAL, passa a BOOSTED_FOR_SEEING su raffica di vento + saturazione leve
- Barre saturazione RA/DEC variano col controller, gate aperto/chiuso coerente
- Marker sul grafico RMS appariranno per azioni path B (vento) o path A (LOW_SNR)
- Cooldown si riempie dopo ogni trigger

**Cosa validare specificamente su Askar**:
- Pannello carica correttamente, no errori JS, tutti i campi popolati
- Le soglie alte (0.30/4.5) effettivamente fungono da filtro: niente trigger spuri su nottate calme
- Modalità LIVE coerente: controller emette `[LIVE]` non `[TEST]`
- Su nottata ventosa: trigger esposizione visibili sulla dashboard + nei log `decisions_*.jsonl` con `param="exposure_seeing"`

### Procedura per setup Tecnosky 115/800 + AM5 o CEM70G (focale media, path B attivo con soglie intermedie)

Comportamento intermedio tra Askar e RC8 (`spike_min=0.25`, `hfd_min_arcsec=4.0`): trigger più frequenti di Askar ma meno di RC8.

- Doppio click su `Avvia_Tecnosky115.bat` (native, 800mm) o `Avvia_Tecnosky115_Ridotto.bat` (ridotto, 640mm)
- Badge stato evolve sui trigger come per RC8 ma con frequenza minore
- Marker sul grafico per azioni path B (vento/seeing) e path A (LOW_SNR raro)

**Cosa validare specificamente su Tecnosky**:
- Stesso check di Askar (pannello carica, barre leggibili, comandi LIVE reali)
- Confronto AM5 vs CEM70G se hai modo di farlo: saturazioni DEC diverse (CEM70G ha backlash misurabile, AM5 no)
- Frequenza trigger path B coerente con le condizioni meteo: pochi in nottate calme, di più in nottate ventose

### Cosa cercare nei log dopo la sessione (tutti i setup)

In `Pacchetto_Distribuzione\logs\decisions_*.jsonl`:
- **Tutti i setup**: decisioni `axis="camera" param="exposure_seeing"` e `param="exposure_snr"` (path A + path B attivi ovunque). Frequenza prevista: RC8 più alta, Askar più bassa per via delle soglie differenziate.
- **Tutti**: decisioni `axis="ra"` / `axis="dec"` con `param` aggressiveness o MinMove (controller standard). Verificare che il controller stia effettivamente agendo in LIVE (`dry_run: false` nei record JSONL).
- **Tutti**: verificare che i record `[LIVE]` siano dominanti rispetto ai `[TEST]` (eventuali `[TEST]` indicano errori RPC silenti, da investigare).

In `session_*.summary.json`:
- `mean_rms_total_arcsec` per ogni setup → base per ritarare soglie `rms_high`/`rms_low` (formula `rms_high = 1.5 × mean`, `rms_low = 0.7 × mean`)

### Linee guida tuning post-prima-sessione (pannello dashboard)

Sintomi attesi e rimedi (validi su tutti i setup):

- **Le barre saturazione "saltano" continuamente**: refresh troppo aggressivo. Aumentare polling interval da 1s a 2s, o passare a WebSocket push solo su cambi rilevanti.
- **Il pannello occupa troppo spazio verticale rispetto al grafico**: ridurre padding interno della `.exposure-card` o passare a layout a 2 colonne (RA sinistra, DEC destra).
- **I rombi sul grafico RMS sovraffollati**: aumentare il trim (`> 200` → `> 100` azioni mantenute in dataset). Più probabile su RC8 ma possibile anche su altri setup in nottate ventose.
- **Marker non visibili**: probabilmente l'asse Y del grafico parte da > 0 (es. 0.3), quindi `y=0` dei marker è fuori dal range. Cambiare `y: 0` in un valore visibile (es. limite inferiore corrente del grafico).
- **Trigger path B troppo frequenti su Askar / Tecnosky** (più di 5/ora): alzare `spike_min` di 0.05 nel config del setup specifico. Le soglie attuali (Askar 0.30, Tecnosky 0.25) sono stime iniziali, vanno tarate sui log reali.
- **Trigger path B che non scatta mai su un setup pur con vento evidente**: abbassare `spike_min` o `hfd_min_arcsec`. Anche `peak_to_rms_ratio_min = 3.0` può essere abbassato a 2.5 se troppo restrittivo.

---

## PROCEDURA REBUILD (obbligatoria post-modifica)

1. `python build_dist.py`
2. Copiare in `Pacchetto_Distribuzione/` i **4 config TOML aggiornati** (root → Pacchetto_Distribuzione):
   - `config.toml` (default, invariato)
   - `config_askar71f.toml` (con `dry_run = false` aggiornato)
   - `config_tecnosky115.toml` (con `dry_run = false` aggiornato)
   - `config_rc8.toml` (già LIVE, invariato)
3. Sostituire i **6 `.bat`** in `Pacchetto_Distribuzione/` con le versioni uniformate della sezione 2G:
   - `Avvia_Askar71F.bat`, `Avvia_Askar71F_Ridotto.bat`
   - `Avvia_Tecnosky115.bat`, `Avvia_Tecnosky115_Ridotto.bat`
   - `Avvia_RC8.bat`, `Avvia_RC8_Ridotto.bat`
   - `Sblocca_Firewall_8080.bat` (invariato)
4. **Verificare che `dashboard/` sia stato incluso nel build** (PyInstaller dovrebbe già includerlo via spec file). Se la dashboard non si aggiorna, copiare manualmente `dashboard/index.html`, `dashboard/app.js`, `dashboard/style.css` in `Pacchetto_Distribuzione/dashboard/`.
5. Aggiornare `LEGGIMI_PER_AVVIARE.txt` con il contenuto della sezione 2G (tabella 6 .bat + nota sicurezza LIVE).
6. Ricreare ZIP `PHD2_Agent_Distribuzione.zip` con `[System.IO.Compression.ZipFile]::CreateFromDirectory(...)`.

**Verifica finale post-rebuild** (importante per garantire la coerenza LIVE):

```bash
# In Pacchetto_Distribuzione/, controlla che TUTTI i config siano LIVE
grep -E "^dry_run" config_*.toml
# Atteso: tutti i risultati con "dry_run = false"

# Controlla che TUTTI i .bat dichiarino LIVE nell'echo
grep -l "MODALITA: LIVE" Avvia_*.bat
# Atteso: tutti i 6 .bat (3 nativi + 3 ridotti) elencati
```

---

## AGGIORNAMENTO DOCUMENTAZIONE (procedura collaudata)

### `CONTESTO_PROGETTO.md`

Nella sezione `## Stato attuale — aggiornato al ...`:
- Aggiornare la data alla data di completamento della feature
- Aggiungere paragrafo **subito prima** di "Cosa NON è stato ancora fatto":

```markdown
### Dashboard: Pannello "Stato Esposizione & Escalation Gate" + LIVE su tutti i setup — IMPLEMENTATO (YYYY-MM-DD)
Aggiunta card alla dashboard che rende visibili in tempo reale: stato macchina
esposizione (§19), valori esposizione corrente/base/step, cooldown residuo
al prossimo trigger possibile, barre di saturazione delle leve aggressiveness/MinMove
per RA e DEC, indicatore visivo "🔓 Gate aperto" quando le leve cheap di un asse
sono saturate da ≥ 1 cooldown. Più marker (rombi colorati) sovrapposti al grafico
RMS esistente ai timestamp delle azioni `camera/exposure_*`, con tooltip che
mostra la reason.

Estensione minima di `controller.get_status()` con nuovo blocco `escalation_gate`
(RA/DEC con saturation_pct + gate_open) e arricchimento del blocco `exposure`
esistente con `cooldown_residuo_s` e `cooldown_total_s`. Nessuna modifica
alla logica di controllo.

**Estensione modalità LIVE a tutti i setup + path B attivo ovunque**: corretta
l'incoerenza precedente in cui solo RC8 era in LIVE (`dry_run = false`) mentre
Askar 71F e Tecnosky 115 erano ancora in DRY_RUN nonostante i loro `.bat`
dichiarassero "LIVE CONTROL" nell'echo. Ora tutti e 4 i config TOML (root +
Pacchetto_Distribuzione) hanno `dry_run = false` e `[exposure_dynamic].enabled = true`,
e tutti i 6 `.bat` (3 nativi + 3 ridotti) dichiarano coerentemente
`MODALITA: LIVE` + `exposure_dynamic.enabled: true (path B attivo)` nell'echo.

Motivazione tecnica per path B attivo su tutti i setup: il vento (raffiche)
genera spike di guida anche a focali corte/medie. L'integrazione via esposizione
può aiutare ovunque, non solo su focali lunghe. Le soglie differenziate per
setup (`spike_min` 0.30/0.25/0.20 e `hfd_min_arcsec` 4.5/4.0/4.0) fungono da
filtro naturale: trigger frequenti su RC8, rari su Askar.

Vedere NOTE_CLAUDE.md §21 per il dettaglio.
```

In `## Cosa NON è stato ancora fatto`:
- Aggiungere:
  ```
  - Validazione LIVE del pannello "Esposizione & Escalation Gate" su tutti
    e 3 i setup:
    - RC8 + CEM70G a Borno (sessione primaria, path B attivo): verifica
      trigger esposizione, marker rombi sul grafico, gate aperto/chiuso
      coerente con le saturazioni
    - Askar 71F + AM5: verifica pannello attivo, barre di saturazione delle
      leve leggibili, modalità LIVE coerente (controller emette [LIVE] non [TEST])
    - Tecnosky 115/800 + AM5/CEM70G: idem Askar, validare anche su CEM70G
      se disponibile per confronto saturazioni DEC
    Eventuali tuning refresh rate/layout solo dopo le prime sessioni reali.
  ```

### `NOTE_CLAUDE.md`

Aggiungere in coda **sezione 21**:

```markdown
---

## 21. Dashboard: Pannello "Esposizione & Escalation Gate" + Estensione LIVE a tutti i setup (YYYY-MM-DD)

### Motivazione
Due esigenze convergenti emerse dalla discussione con Alessandro:

1. **Visibilità sull'esposizione e l'escalation gate**: le sessioni §19 (esposizione
   dinamica RMS-based) e §20 (refactor [setup]) hanno introdotto la macchina a stati
   esposizione e l'escalation gate, ma la dashboard mostrava solo i parametri RA/DEC
   senza dare visibilità su stato esposizione, saturazione leve, cooldown residuo,
   correlazione visiva azione/effetto sull'RMS.

2. **Controllo diretto su tutti i setup**: Alessandro ha esplicitato di voler
   operare in LIVE su tutti e tre i setup (Askar 71F + AM5, Tecnosky 115/800 +
   AM5/CEM70G, RC8 + CEM70G), sia native che ridotti. Lo stato precedente era
   incoerente: solo RC8 in LIVE (§19), mentre Askar e Tecnosky avevano `dry_run = true`
   nei TOML ma i loro `.bat` dichiaravano erroneamente "LIVE CONTROL (Attivo)"
   nell'echo. Discrepanza da risolvere.

### Architettura

**Backend** (controller.py): `get_status()` arricchito con:
- Blocco `exposure` esteso: aggiunti `cooldown_residuo_s` e `cooldown_total_s`
- Nuovo blocco `escalation_gate` con sotto-blocchi `ra` e `dec`, ciascuno con
  `aggr_saturation_pct`, `minmove_saturation_pct`, `gate_open`, e valori
  correnti/limiti config per debug

Il calcolo della % saturazione è lineare:
- aggr: `(aggr_max - current_aggr) / (aggr_max - aggr_min)` → 100% quando current = aggr_min
- minmove: `(current - minmove_min) / (minmove_max - minmove_min)` → 100% quando current = minmove_max

Il `gate_open` riusa l'helper esistente `_axis_levers_saturated` (§19) — nessuna
nuova logica di calcolo.

**Frontend** (dashboard/): nuova `<section class="mid-row-2">` dopo la mid-row
esistente, con card `.exposure-card` che contiene 4 blocchi visivi (badge stato,
valori esposizione, cooldown, blocchi leve RA/DEC con gate badge). Stile CSS
coerente con palette/font esistenti (Inter + JetBrains Mono).

Sul Chart.js del "Grafico Guida" aggiunto secondo dataset di tipo `scatter`
overlay (rombi colorati) per i timestamp delle azioni `camera/exposure_*`,
con tooltip che mostra la reason.

### Allineamento LIVE su tutti i setup

Modifiche ai config TOML (root + Pacchetto_Distribuzione = 4 file aggiornati):
- `config_askar71f.toml`: `dry_run` true → false (LIVE)
- `config_tecnosky115.toml`: `dry_run` true → false (LIVE)
- `config_rc8.toml`: invariato (già LIVE da §19)

Decisione esplicita per `[exposure_dynamic].enabled`: **true su tutti e 3 i setup**.
Motivazione: il vento genera spike che possono essere integrati via esposizione
anche a focali corte/medie. Le soglie differenziate per setup fungono da filtro:
- Askar 71F: enabled=true, soglie alte (`spike_min=0.30`, `hfd_min_arcsec=4.5`) → trigger raro, solo eventi forti
- Tecnosky 115: enabled=true, soglie intermedie (`spike_min=0.25`, `hfd_min_arcsec=4.0`) → trigger moderato
- RC8: enabled=true, soglie sensibili (`spike_min=0.20`, `hfd_min_arcsec=4.0`) → trigger frequente

Uniformazione dei 6 `.bat` in `Pacchetto_Distribuzione/`: ognuno dichiara
coerentemente nell'echo `MODALITA: LIVE (dry_run=false)` + lo stato di
`exposure_dynamic.enabled` per quel setup. I `.bat` ridotti (Askar/Tecnosky/RC8
Ridotto) ora hanno lo stesso formato dei nativi, con la riga focale aggiornata.

Aggiornato anche `LEGGIMI_PER_AVVIARE.txt` con la nuova tabella di 6 `.bat` e
una nota sulla sicurezza in modalità LIVE (Baseline Guardian protegge, Ctrl+C
ripristina, kill brutale rilevato come baseline orfana).

### Comportamento del pannello su ciascun setup
Tutti i setup hanno path B attivo, comportamento identico ma con frequenza eventi diversa:
- **RC8 + CEM70G** (soglie sensibili 0.20/4.0): trigger esposizione frequenti
  su seeing degradato e/o vento. Badge passa spesso per BOOSTED_FOR_SEEING,
  marker rombi numerosi sul grafico RMS.
- **Tecnosky 115 + AM5/CEM70G** (soglie intermedie 0.25/4.0): trigger moderati,
  scattano su vento o seeing decisamente brutto.
- **Askar 71F + AM5** (soglie alte 0.30/4.5): trigger rari, solo su raffiche
  di vento davvero forti o seeing molto compromesso. Stato NOMINAL prevalente
  in nottate calme.

### Comportamento UI generale
- Update tramite polling esistente di `/status` (~ogni 1-2 s) oppure WebSocket
  push se l'infrastruttura lo permette
- Barre saturazione cambiano colore: verde < 60%, giallo 60-90%, arancione ≥ 90%
- Gate badge: "🔒 Gate chiuso" (grigio) di default, "🔓 Gate aperto" (arancione)
  quando l'helper `_axis_levers_saturated` ritorna True
- Cooldown bar: si "riempie" mentre il cooldown scade (0% appena dopo azione,
  100% pronto per il prossimo trigger)
- Marker grafico RMS: rombi colorati al timestamp dell'azione, colore per tipo
  (arancione=seeing_up, verde=seeing_down, giallo=snr)

### File modificati
- `phd2_agent/controller.py` — `get_status()` arricchito (lettura, no logica nuova)
- `dashboard/index.html` — nuova `<section class="mid-row-2">` con `.exposure-card`
- `dashboard/style.css` — stili per `.exposure-card`, `.lever-*`, `.gate-badge`, etc.
- `dashboard/app.js` — funzione `updateExposureEscalation(status)` chiamata dal
  loop di update, gestione dataset marker su Chart.js, popolamento iniziale da
  `/history`
- `config_askar71f.toml` (root + Pacchetto_Distribuzione) — `dry_run = false`, `[exposure_dynamic].enabled = true`
- `config_tecnosky115.toml` (root + Pacchetto_Distribuzione) — `dry_run = false`, `[exposure_dynamic].enabled = true`
- 6 `.bat` in `Pacchetto_Distribuzione/` — formato echo uniformato con `MODALITA: LIVE`
- `LEGGIMI_PER_AVVIARE.txt` — tabella aggiornata
- (opzionale) `tests/test_get_status.py` — test minimo presenza nuovi campi

### Limiti dell'approccio
1. Polling vs WebSocket: il design corrente usa polling esistente. In sessioni
   lunghe (>2 ore) il refresh continuo a 1s consuma banda inutilmente quando
   nulla cambia. Tuning futuro: passare a push WebSocket solo su cambi rilevanti.
2. Marker sul grafico RMS sono posizionati a `y=0`, potrebbero risultare fuori
   dall'asse visibile se l'RMS minimo della finestra è > 0 (es. 0.3"). Tuning
   futuro: posizione dinamica al limite inferiore corrente del grafico.
3. Max steps above base è hardcodato a "2" nel testo "+N/2 step" del frontend.
   Se in futuro `max_steps_above_base` diventa configurabile per setup oltre il
   default, va esposto anche nel payload `/status`.
4. LIVE + path B su Askar e Tecnosky: il controller invia comandi reali a PHD2
   anche su questi setup, e il path B può scattare modificando l'esposizione.
   La sicurezza è garantita dalle stesse difese di RC8 (Baseline Guardian,
   escalation gate, RMS implosion detector, max_steps_above_base=2, cap a
   max_exposure_ms). Le soglie alte di Askar (`spike_min=0.30`, `hfd_min_arcsec=4.5`)
   limitano i trigger spuri al minimo.

### Validazione raccomandata
1. Sanity check simulator (non-regressione): `python main.py --simulator --dry-run`
2. Sessione LIVE su ciascun setup, almeno 30-60 min:
   - **RC8 + CEM70G** (a Borno): osservare aggiornamento fluido delle barre,
     trigger gate aperto/chiuso coerente, marker rombi visibili sul grafico
   - **Askar 71F + AM5**: verificare pannello attivo (no errori), barre delle
     leve si muovono col controller, `[LIVE]` nei log invece di `[TEST]`.
     Path B raramente attivo (soglie alte 0.30/4.5) — eventuali trigger solo
     su raffiche di vento forti.
   - **Tecnosky 115**: idem Askar, soglie intermedie (0.25/4.0). Confronto
     saturazioni DEC su CEM70G se disponibile vs AM5.
3. Eventuali tuning post-sessione: refresh rate, posizione marker, layout card,
   ricalibrazione soglie spike_min/hfd_min_arcsec per setup in base alla
   frequenza dei trigger osservata nei log `decisions_*.jsonl`.
```

### `README.md` — non toccare a meno di tabella feature esistente

---

## CHECKLIST FINALE PRIMA DI COMMIT

### Implementazione pannello dashboard
- [ ] Pre-flight eseguito: letti i file Python e dashboard indicati in §0
- [ ] `controller.get_status()` arricchito con `escalation_gate` (RA + DEC) e `cooldown_residuo_s`/`cooldown_total_s` in `exposure`
- [ ] Helper `_axis_levers_saturated` chiamato correttamente (signature verificata)
- [ ] **Nessuna modifica alla logica del controller** oltre alla lettura/serializzazione
- [ ] `dashboard/index.html` ha nuova `<section class="mid-row-2">` con card e tutti gli ID DOM richiesti
- [ ] `dashboard/style.css` ha tutti gli stili nuovi (palette coerente, no font esterni nuovi)
- [ ] `dashboard/app.js` ha la funzione `updateExposureEscalation(status)` chiamata dal loop di update + dataset marker su Chart.js + popolamento iniziale da `/history`
- [ ] Sanity check simulator: dashboard carica, nuova card visibile e popolata, no regressioni su gauge/controller/grafico/log
- [ ] `curl /status | python -m json.tool` mostra i nuovi campi
- [ ] Test esistenti (`tests/test_exposure_dynamic.py` 5/5 + `tests/test_setup_config.py` 3/3) passano invariati
- [ ] (opzionale) Test minimo `test_get_status_includes_escalation_gate` aggiunto e passa

### Allineamento LIVE su tutti i setup (sezione 2G)
- [ ] `config_askar71f.toml` (root + Pacchetto_Distribuzione): `dry_run = false` AND `[exposure_dynamic].enabled = true` con commento esplicativo
- [ ] `config_tecnosky115.toml` (root + Pacchetto_Distribuzione): `dry_run = false` AND `[exposure_dynamic].enabled = true` con commento esplicativo
- [ ] `config_rc8.toml`: invariato (già `dry_run = false` + `enabled = true` da §19)
- [ ] `[exposure_dynamic].enabled = true` su **tutti e 3 i setup** (path B attivo ovunque per gestione vento + seeing)
- [ ] 6 `.bat` allineati al formato standard: tutti dichiarano `MODALITA: LIVE (dry_run=false)` + `exposure_dynamic.enabled: true (path B attivo)`
- [ ] `LEGGIMI_PER_AVVIARE.txt` aggiornato con tabella 6 `.bat` (tutti con "path B attivo") + nota sicurezza LIVE
- [ ] Verifica finale grep: tutti i `config_*.toml` con `dry_run = false`, tutti i `[exposure_dynamic]` con `enabled = true`, tutti i 6 `.bat` con `MODALITA: LIVE`

### Rebuild e documentazione
- [ ] `python build_dist.py` completato senza errori
- [ ] Tutti i 4 config TOML copiati in Pacchetto_Distribuzione/
- [ ] Tutti i 6 `.bat` copiati/aggiornati in Pacchetto_Distribuzione/
- [ ] Dashboard inclusa nel ZIP
- [ ] ZIP rigenerato
- [ ] `CONTESTO_PROGETTO.md`: data aggiornata + paragrafo nuovo (pannello dashboard + LIVE su tutti) + voce validazione "non fatto"
- [ ] `NOTE_CLAUDE.md`: sezione §21 aggiunta in coda con struttura completa, inclusa la sotto-sezione sull'allineamento LIVE

### Regole di sicurezza
- [ ] Nessuna modifica alla backlash compensation di PHD2
- [ ] Nessuna modifica alla logica delle feature §19 (esposizione dinamica) e §20 (riduttore)
- [ ] Nessuna modifica al comportamento dell'analyzer o degli algoritmi PHD2
- [ ] Modalità LIVE estesa a tutti i setup, con `[exposure_dynamic].enabled = true` ovunque (gestione vento + seeing su tutti i telescopi). Le soglie differenziate per setup (`spike_min`, `hfd_min_arcsec`) fungono da filtro naturale.

---

## DOMANDE DA FARMI PRIMA DI PROCEDERE (se servono)

Se durante l'implementazione trovi:
- L'helper `_axis_levers_saturated` ha una signature diversa da quella documentata
- Chart.js è inizializzato in modo diverso da quello atteso e l'aggiunta del secondo dataset richiede refactor consistente
- Il pattern WebSocket esistente per push real-time è strutturato in modo che `updateExposureEscalation` può essere triggerato anche su eventi push (non solo polling)
- Conflitti con altri elementi UI esistenti

→ **Fermati e chiedi**, non improvvisare.

Se invece tutto è chiaro: procedi step-by-step, mostrami i diff prima di applicarli ai file (preferisco vederli), poi esegui il sanity check simulator e il rebuild, infine aggiorna la documentazione.

Grazie.
