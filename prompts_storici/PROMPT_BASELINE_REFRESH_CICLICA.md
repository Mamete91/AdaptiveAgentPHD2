# PROMPT PER CLAUDE CODE — REFRESH CICLICO DELLA BASELINE (TIGHTEST-WINS) + `rms_high_factor` A 1.3
# Da copiare e incollare integralmente nella conversazione con Claude Code.
# Lavorare nella cartella: PHD2_Assist_PATCHED/

> **NOTA OPERATIVA**: addendum a §22 (auto-scala + soglie adattive + config unico), §23 (clamp proporzionale +
> gate rifiuto baseline), §24 (cap 1,00" + ranges armonizzati). Due cambi distinti, entrambi maturati
> dall'osservazione sul campo della prima sessione reale (validazione §22-§24 su Askar 71F).
>
> 1. **Refresh ciclico della baseline con regola "tightest-wins"**: ogni N minuti (default 30 min) l'Agente
>    ri-misura la baseline RMS. Confronta la nuova mediana con la baseline corrente: **se più stretta** la
>    sostituisce (l'Agente diventa più reattivo perché il cielo è migliorato); **se uguale o più larga** la
>    rifiuta (mantiene le soglie correnti, NON concede terreno al peggioramento). Risolve il caso "baseline
>    misurata in cielo già compromesso → soglie troppo larghe per tutta la sessione" osservato sul campo.
>
> 2. **`rms_high_factor` default da 1.5 a 1.3**: cuscinetto sopra la baseline ridotto dal 50% al 30%, dopo
>    analisi sul caso RC8 a focale piena (0,51"/px) dove baseline tipiche di 0,55-0,60" producono con f=1,5
>    soglie DEGRADED di 0,82-0,90" — già fuori scala per "astrofotografia seria con dettagli fini" su quel
>    campionamento. Con f=1,3 le soglie diventano 0,72-0,78" — protezione reale per le focali lunghe, zero
>    effetti pratici sulle focali corte (dove l'RMS reale tipico sta comunque sotto entrambe le soglie).
>
> SCOPE: zero modifiche a §19, §20, §21. Solo aggiunte in `AutoCalibrationConfig` + nuova logica `_refresh_*`
> dentro `controller.py` + estensione `get_status()` + badge dashboard + un singolo cambio di default
> (`rms_high_factor = 1.3`). Test esistenti §22/§23/§24 mantenuti, +5 nuovi test §25.

---

## 0. PRE-FLIGHT OBBLIGATORIO (leggere PRIMA di scrivere codice)

### File Python da consultare

1. `phd2_agent/config.py` — `AutoCalibrationConfig` post-§24:
   - `rms_high_factor = 1.5` → diventa **1.3** (cambio default).
   - Verifica nomi esatti dei campi esistenti per coerenza nello stile dei nuovi.

2. `phd2_agent/controller.py` — post-§22/§23/§24:
   - `_finalize_rms_baseline()` esistente: come applica le soglie dalla baseline.
   - Stato baseline in `__init__`: `_rms_baseline_samples`, `_rms_baseline_value`, `_rms_baseline_done`,
     `_rms_baseline_rejected`, `_rms_high_cap_active`, `_rms_high_cap_value`.
   - `_invalidate_rms_baseline(reason)`: come resetta lo stato.
   - `_update_rms_baseline(snap)`: come accumula campioni (in `evaluate()`).
   - `evaluate()`: il loop principale dove inseriremo il check del timer di refresh.

3. `phd2_agent/controller.py` — `get_status()` blocco `auto_calibration`:
   campi attuali post-§23 (`enabled`, `pixel_scale_arcsec`, `pixel_scale_source`, `baseline_rms_arcsec`,
   `baseline_done`, `baseline_rejected`, `baseline_progress`, `rms_high_active`, `rms_low_active`,
   `rms_high_cap_arcsec`, `rms_high_cap_active`). Va esteso con tre campi nuovi (vedi §2E).

4. `dashboard/index.html` + `dashboard/app.js` — card "Auto-calibrazione" introdotta in §22, estesa in §23.
   Va aggiunta una riga "Refresh" + un badge per lo stato (in corso / ultimo: applicato / ultimo: rifiutato).

5. `config.toml` — sezione `[auto_calibration]` post-§24. Aggiungere 3 nuovi campi + modificare il valore
   di `rms_high_factor`.

6. `tests/test_auto_calibration.py` — verificare che i test §22/§23/§24 non assertino il vecchio default
   `rms_high_factor = 1.5` in modo non banale. La maggior parte costruisce config con valori espliciti,
   ma controlla.

### Conclusioni del pre-flight (già verificate, da confermare)

A. La struttura di stato attuale (`_rms_baseline_*` + `_rms_high_cap_*` + `_rms_baseline_rejected`) basta:
   serve aggiungere solo `_baseline_finalize_time` (timestamp monotonic dell'ultima finalizzazione applicata) e
   uno stato "in refresh" (`_baseline_refresh_in_progress: bool`).

B. Durante un refresh la nuova raccolta dei 60 campioni avviene in parallelo: le soglie correnti (dal precedente
   finalize) RESTANO ATTIVE finché il refresh non si conclude. NON resettare `cfg.thresholds` durante il refresh.

C. La regola tightest-wins è una sola riga di confronto: `if new_baseline >= current_baseline → reject`.

D. Cambio `rms_high_factor` default da 1.5 a 1.3: è una singola modifica al default della dataclass + alla
   sezione `[auto_calibration]` del TOML. Zero impatto sulla logica.

### Nessuna verifica → STOP

Se durante il pre-flight scopri che:
- La struttura attuale di `_finalize_rms_baseline` (post-§23) non separa "calcolo nuova baseline" da
  "applicazione alle soglie" in modo che si possa intercettare per la regola tightest-wins.
- Esiste già un meccanismo di scheduling/timer nel controller che potrebbe conflittare.
- Test esistenti dipendono dal valore esatto `rms_high_factor = 1.5` in modo che cambiare il default li rompa.

→ **Fermati e riportamelo** prima di procedere.

---

## OBIETTIVO TECNICO

Aggiungere a `controller.py` un meccanismo di refresh periodico della baseline (default ogni 1800s = 30 min)
governato da timer monotonic. Al termine di ogni ciclo di refresh, confrontare la nuova mediana con la baseline
corrente: applicare solo se più stretta (regola "tightest-wins"); altrimenti rifiutare e mantenere la corrente.
Esporre lo stato di refresh su `/status` e sulla dashboard. Inoltre cambiare il default di `rms_high_factor`
da 1.5 a 1.3 per maggior protezione su focali lunghe.

---

## REGOLE INDEROGABILI

- **NON toccare** la backlash compensation di PHD2.
- **NON cambiare** la logica di acquisizione baseline (filtri SNR/no-implosion/NOMINAL restano com'erano in §22).
- **NON cambiare** il calcolo del cap proporzionale §23 né il gate di rifiuto baseline §23.
- **NON cambiare** i ranges aggressività/MinMove §24.
- **MANTENERE** le soglie correnti attive durante il refresh: solo alla fine del ciclo (60 campioni nuovi
  raccolti) si decide se applicare o rifiutare la nuova baseline. Non lasciare l'Agente "senza soglie" durante
  la ri-misura.
- **MANTENERE** retrocompatibilità: nuovi campi assenti dal TOML → default; refresh disabilitato di default sul
  primo deploy va comunque considerato — ma per questa §25 partiamo con `refresh_enabled = true` (è la nuova
  feature, voluta).
- **MANTENERE** stile esistente (logging in italiano, dataclass, type hints).

### Modalità operativa

Feature LIVE, da osservare sulla dashboard. `[auto_calibration].enabled` resta `true`. La sicurezza è garantita
dalla regola tightest-wins (rifiuto automatico se la nuova baseline è più larga della corrente — l'Agente non
"concede" mai reattività al cielo che peggiora).

---

## SPECIFICA FUNZIONALE

### 2A. `config.py` — estendere `AutoCalibrationConfig`

Aggiungere tre campi nuovi e modificare il default di `rms_high_factor`:

```python
@dataclass
class AutoCalibrationConfig:
    enabled: bool = False
    use_phd2_pixel_scale: bool = True
    rms_high_factor: float = 1.3              # modificato — era 1.5 (taratura §25)
    rms_low_factor: float = 0.75              # invariato
    baseline_window_frames: int = 60
    baseline_min_snr: float = 10.0
    # Clamp proporzionale (§23, taratura §24):
    rms_high_max_factor: float = 2.0
    rms_high_min_arcsec: float = 0.70
    rms_high_max_arcsec: float = 1.00         # invariato (§24)
    rms_low_min_arcsec: float = 0.25
    baseline_reject_factor: float = 3.0
    baseline_reject_min_arcsec: float = 1.50
    # NUOVO §25 — refresh ciclico:
    refresh_enabled: bool = True              # NUOVO
    refresh_interval_seconds: float = 1800.0  # NUOVO — default 30 min
    refresh_only_if_tighter: bool = True      # NUOVO — regola "tightest wins"
```

Parsing in `load_config` esteso coerentemente per i tre nuovi campi (con `.get(...)` e i default sopra).

### 2B. `controller.py` — stato nuovo in `__init__`

Aggiungere due campi di stato:

```python
self._baseline_finalize_time: Optional[float] = None  # time.monotonic() quando la baseline è stata applicata
self._baseline_refresh_in_progress: bool = False
self._last_refresh_action: Optional[str] = None       # "applicato" / "rifiutato" / None
self._last_refresh_baseline: Optional[float] = None   # valore della baseline misurata nell'ultimo refresh
```

Aggiornare `_invalidate_rms_baseline` per resettare anche i nuovi:

```python
def _invalidate_rms_baseline(self, reason: str) -> None:
    # ... reset esistenti §22/§23 ...
    self._baseline_finalize_time = None
    self._baseline_refresh_in_progress = False
    self._last_refresh_action = None
    self._last_refresh_baseline = None
    log.info("[autocal] baseline RMS invalidata (%s)", reason)
```

### 2C. `controller.py` — modificare `_finalize_rms_baseline`

Quando finalize viene chiamato e siamo in modalità refresh, applicare la regola tightest-wins prima di
sostituire soglie e analyzer. La logica esistente §23 (calcolo cap proporzionale, gate rifiuto baseline) resta
identica. Bisogna solo intercettare il caso "refresh in corso" e decidere se applicare o rifiutare la nuova
baseline rispetto a quella corrente.

```python
def _finalize_rms_baseline(self) -> None:
    import statistics, time
    ac = self.cfg.auto_calibration
    new_baseline = statistics.median(self._rms_baseline_samples)

    # ----- GATE DI RIFIUTO BASELINE (§23) -----
    scale = self.cfg.setup.guide_pixel_scale_arcsec
    reject_threshold = max(ac.baseline_reject_min_arcsec, ac.baseline_reject_factor * scale)
    if new_baseline > reject_threshold:
        # comportamento §23 invariato: rigetto totale, soglie restano quelle correnti
        self._rms_baseline_rejected = True
        self._rms_high_cap_active = False
        self._rms_high_cap_value = None
        self._rms_baseline_done = True
        if self._baseline_refresh_in_progress:
            # rifiuto anche durante refresh: nessuna applicazione
            self._last_refresh_action = "rifiutato"
            self._last_refresh_baseline = new_baseline
            self._baseline_refresh_in_progress = False
            log.warning("[autocal] refresh: baseline %.3f\" RIFIUTATA dal gate (> %.3f\"); "
                        "soglie correnti mantenute", new_baseline, reject_threshold)
        else:
            log.warning(
                "[autocal] baseline RMS = %.3f\" RIFIUTATA (gate > %.3f\")",
                new_baseline, reject_threshold,
            )
        return

    # ----- REGOLA TIGHTEST-WINS (§25, solo se siamo in refresh) -----
    if self._baseline_refresh_in_progress and ac.refresh_only_if_tighter:
        current = self._rms_baseline_value  # baseline corrente (non None: siamo in refresh)
        if current is not None and new_baseline >= current:
            # Nuova baseline NON più stretta → rifiuto
            self._last_refresh_action = "rifiutato"
            self._last_refresh_baseline = new_baseline
            self._baseline_refresh_in_progress = False
            self._rms_baseline_samples.clear()  # liberiamo la finestra
            log.info(
                "[autocal] refresh: nuova baseline %.3f\" >= corrente %.3f\" "
                "(tightest-wins) → soglie correnti mantenute",
                new_baseline, current,
            )
            # NOTA: NON resettare _baseline_finalize_time → il timer ripartirà dall'ultima applicazione
            # In realtà sì, lo resettiamo: vogliamo riprovare tra refresh_interval_seconds dall'ULTIMO tentativo,
            # non dall'ultima applicazione. Vedi sotto.
            self._baseline_finalize_time = time.monotonic()
            return

    # ----- APPLICAZIONE (sia primo finalize sia refresh accettato) -----
    self._rms_baseline_value = new_baseline

    # Calcolo cap (§23):
    cap_proporzionale = ac.rms_high_max_factor * scale
    cap_efficace = max(ac.rms_high_min_arcsec, min(ac.rms_high_max_arcsec, cap_proporzionale))

    derived_high = ac.rms_high_factor * new_baseline
    new_high = min(cap_efficace, derived_high)
    self._rms_high_cap_active = (derived_high > cap_efficace)
    self._rms_high_cap_value = cap_efficace

    derived_low = ac.rms_low_factor * new_baseline
    new_low = max(ac.rms_low_min_arcsec, derived_low)

    self.cfg.thresholds.rms_high = new_high
    self.cfg.thresholds.rms_low = new_low
    self.analyzer.rms_high = new_high
    self.analyzer.rms_low = new_low
    self._rms_baseline_done = True
    self._rms_baseline_rejected = False
    self._baseline_finalize_time = time.monotonic()

    if self._baseline_refresh_in_progress:
        self._last_refresh_action = "applicato"
        self._last_refresh_baseline = new_baseline
        self._baseline_refresh_in_progress = False
        log.info(
            "[autocal] refresh: nuova baseline %.3f\" < corrente → APPLICATA. "
            "rms_high = %.3f\"%s, rms_low = %.3f\"",
            new_baseline, new_high, " [CAP]" if self._rms_high_cap_active else "", new_low,
        )
    else:
        log.info(
            "[autocal] baseline RMS = %.3f\" applicata: rms_high = %.3f\"%s, rms_low = %.3f\"",
            new_baseline, new_high, " [CAP]" if self._rms_high_cap_active else "", new_low,
        )
```

### 2D. `controller.py` — innesco del refresh in `evaluate()`

In `evaluate()`, prima della chiamata a `_update_rms_baseline(snap)`, aggiungere il check del timer:

```python
def _maybe_start_refresh(self) -> None:
    """Se il refresh ciclico è abilitato, la baseline è applicata e il timer è scaduto,
    avvia un nuovo ciclo di raccolta."""
    import time
    ac = self.cfg.auto_calibration
    if not ac.enabled or not ac.refresh_enabled:
        return
    if not self._rms_baseline_done or self._baseline_refresh_in_progress:
        return
    if self._baseline_finalize_time is None:
        return
    elapsed = time.monotonic() - self._baseline_finalize_time
    if elapsed < ac.refresh_interval_seconds:
        return
    # Avvia refresh: NON tocchiamo cfg.thresholds né analyzer (restano correnti),
    # ma azzeriamo i campioni e segnaliamo "in refresh".
    self._rms_baseline_samples.clear()
    self._rms_baseline_done = False        # forza la riapertura della raccolta
    self._baseline_refresh_in_progress = True
    log.info(
        "[autocal] refresh ciclico avviato (intervallo %.0fs scaduto, soglie correnti restano attive)",
        ac.refresh_interval_seconds,
    )
```

Chiamare `_maybe_start_refresh()` in `evaluate()`, subito prima della logica baseline esistente. Il resto del
flusso baseline (`_update_rms_baseline` → `_finalize_rms_baseline`) funziona automaticamente perché abbiamo
azzerato `_rms_baseline_samples` e messo `_rms_baseline_done = False`.

### 2E. `controller.py` — estendere `get_status()`

Aggiungere al blocco `auto_calibration`:

```python
"refresh_enabled": cfg.auto_calibration.refresh_enabled,
"refresh_interval_seconds": cfg.auto_calibration.refresh_interval_seconds,
"refresh_in_progress": self._baseline_refresh_in_progress,
"refresh_progress": (f"{len(self._rms_baseline_samples)}/{cfg.auto_calibration.baseline_window_frames}"
                     if self._baseline_refresh_in_progress else None),
"refresh_seconds_to_next": (
    max(0.0, cfg.auto_calibration.refresh_interval_seconds
        - (time.monotonic() - self._baseline_finalize_time))
    if (self._baseline_finalize_time is not None
        and not self._baseline_refresh_in_progress
        and cfg.auto_calibration.refresh_enabled) else None
),
"last_refresh_action": self._last_refresh_action,        # "applicato" / "rifiutato" / None
"last_refresh_baseline_arcsec": (round(self._last_refresh_baseline, 3)
                                  if self._last_refresh_baseline is not None else None),
```

### 2F. `config.toml` — aggiornare la sezione `[auto_calibration]`

```toml
[auto_calibration]
enabled                       = true
use_phd2_pixel_scale          = true
# Taratura §25: cuscinetto sopra baseline ridotto dal 50% al 30% per protezione
# focali lunghe (es. RC8 a 0,51"/px, dove 1,5×baseline tipica = soglie già fuori scala).
rms_high_factor               = 1.3        # era 1.5 (§24)
rms_low_factor                = 0.75
baseline_window_frames        = 60
baseline_min_snr              = 10.0
# Clamp proporzionale (§23, taratura §24):
rms_high_max_factor           = 2.0
rms_high_min_arcsec           = 0.70
rms_high_max_arcsec           = 1.00
rms_low_min_arcsec            = 0.25
# Gate rifiuto baseline (§23):
baseline_reject_factor        = 3.0
baseline_reject_min_arcsec    = 1.50
# Refresh ciclico (§25) — la baseline si ri-misura ogni 30 min;
# la nuova sostituisce la corrente SOLO se più stretta ("tightest-wins"):
# l'Agente non concede mai terreno al peggioramento del cielo.
refresh_enabled               = true
refresh_interval_seconds      = 1800.0     # 30 minuti
refresh_only_if_tighter       = true
```

### 2G. Dashboard — estendere la card "Auto-calibrazione"

In `dashboard/index.html`, aggiungere alla card una sezione "Refresh":

- Riga "Refresh" con valore:
  - `Spento` se `refresh_enabled === false`
  - `In corso: 12/60` se `refresh_in_progress === true`
  - `Prossimo tra 14m 30s` se calcolato da `refresh_seconds_to_next`
- Badge "Ultimo: APPLICATO" (verde) o "Ultimo: RIFIUTATO" (grigio neutro) quando `last_refresh_action` è valorizzato.

In `dashboard/app.js`, estendere `updateAutoCalibration(ac)`:

```javascript
function updateAutoCalibration(ac) {
    // ... codice esistente §22/§23 ...

    // NUOVO §25 — refresh status
    const refreshEl = document.getElementById('autocal-refresh-status');
    if (!ac.refresh_enabled) {
        refreshEl.textContent = 'Spento';
    } else if (ac.refresh_in_progress) {
        refreshEl.textContent = 'In corso: ' + ac.refresh_progress;
    } else if (ac.refresh_seconds_to_next !== null && ac.refresh_seconds_to_next !== undefined) {
        const m = Math.floor(ac.refresh_seconds_to_next / 60);
        const s = Math.floor(ac.refresh_seconds_to_next % 60);
        refreshEl.textContent = 'Prossimo tra ' + m + 'm ' + s + 's';
    } else {
        refreshEl.textContent = '—';
    }

    // Badge ultimo esito refresh
    const lastBadge = document.getElementById('autocal-last-refresh-badge');
    if (ac.last_refresh_action === 'applicato') {
        lastBadge.textContent = 'Ultimo: APPLICATO';
        lastBadge.className = 'badge-green';
        lastBadge.style.display = 'inline-block';
    } else if (ac.last_refresh_action === 'rifiutato') {
        lastBadge.textContent = 'Ultimo: RIFIUTATO';
        lastBadge.className = 'badge-neutral';
        lastBadge.style.display = 'inline-block';
    } else {
        lastBadge.style.display = 'none';
    }
}
```

CSS: badge verde stessa palette di `GREEN` (#2f9e44), badge neutro grigio MUTED (#55617a).

---

## TEST ATTESI

### Aggiornamento test esistenti

Verificare che i test §22/§23/§24 esistenti che usano `AutoCalibrationConfig()` senza argomenti continuino a
passare con il nuovo default `rms_high_factor = 1.3`. Se qualche asserzione si basava sul valore atteso
`1.5 × baseline`, aggiornarla a `1.3 × baseline`. La logica generale resta identica, solo il moltiplicatore cambia.

### Nuovi test §25

In `tests/test_auto_calibration.py`:

1. **Refresh tightest-wins applica**: baseline corrente 0.6, simulare scadenza timer + nuova raccolta che produce
   mediana 0.4 → applicata, `cfg.thresholds.rms_high` aggiornata, `_last_refresh_action == 'applicato'`,
   `_last_refresh_baseline == 0.4`.
2. **Refresh tightest-wins rifiuta (peggiore)**: baseline corrente 0.5, nuova mediana 0.8 → rifiutata,
   `cfg.thresholds.rms_high` invariata (resta quella derivata da 0.5), `_last_refresh_action == 'rifiutato'`,
   `_last_refresh_baseline == 0.8`, timer riparte.
3. **Refresh tightest-wins rifiuta (uguale)**: baseline corrente 0.5, nuova mediana 0.5 → rifiutata
   (regola `new >= current`).
4. **Refresh disabilitato**: con `refresh_enabled = false`, anche dopo timer scaduto, `_maybe_start_refresh`
   non avvia raccolta.
5. **Refresh + gate rifiuto baseline (§23)**: durante un refresh, la baseline misurata supera la soglia
   `baseline_reject_factor × scale` → gate §23 si attiva, refresh termina con `_last_refresh_action ==
   'rifiutato'`, soglie correnti mantenute.
6. **Stato `/status`**: dopo un primo finalize, `refresh_seconds_to_next` ~ `refresh_interval_seconds`;
   dopo l'inizio di un refresh, `refresh_in_progress == True` e `refresh_progress` viene popolato.

### Sanity simulator

```bash
python main.py --simulator --dry-run --config config.toml
```

Verifica:
- Nessun errore all'avvio.
- Log iniziale del controller mostra `rms_high_factor = 1.3` (nuovo default).
- `/status` espone i nuovi campi (`refresh_*`, `last_refresh_action`, ecc.).

---

## VALIDAZIONE SUL CAMPO

### Cosa osservare sulla dashboard

- Card "Auto-calibrazione" mostra una nuova riga "Refresh" col countdown ("Prossimo tra 25m 12s") dopo che la
  prima baseline si è chiusa.
- Allo scadere del timer, la riga diventa "In corso: 0/60" e il contatore sale.
- A fine ciclo: badge "Ultimo: APPLICATO" (verde) o "Ultimo: RIFIUTATO" (grigio).
- Se applicato: la riga "Baseline RMS" e "rms_high attivo" si aggiornano col nuovo valore.

### Scenari attesi

- **Cielo migliora durante la sessione**: dopo qualche refresh vedrai "Ultimo: APPLICATO" e soglie più strette.
  L'Agente diventa più reattivo.
- **Cielo stabile**: una serie di "Ultimo: RIFIUTATO" (la baseline misurata è simile alla corrente, ma
  leggermente superiore per fluttuazioni). Comportamento atteso: soglie restano quelle iniziali.
- **Cielo peggiora**: "Ultimo: RIFIUTATO" costanti. L'Agente non concede reattività. Esattamente il
  comportamento desiderato.

---

## PROCEDURA REBUILD

1. `python -m pytest tests/ -v` → tutti i test passano (esistenti aggiornati al nuovo `rms_high_factor = 1.3` +
   nuovi §25).
2. `python build_dist.py`.
3. Copiare `config.toml` e `Sblocca_Firewall_8080.bat` in `Pacchetto_Distribuzione/`.
4. Verifica residui: solo `Avvia.bat` + `Sblocca_Firewall_8080.bat`, un solo `config.toml`.
5. Ricreare `PHD2_Agent_Distribuzione.zip`.

---

## AGGIORNAMENTO DOCUMENTAZIONE

### `CONTESTO_PROGETTO.md`

Aggiornare data, aggiungere prima di "Cosa NON è stato ancora fatto":

```markdown
### Refresh ciclico baseline (tightest-wins) + rms_high_factor 1.3 (§25) — IMPLEMENTATA (YYYY-MM-DD)
Refinement architetturale di §22 dopo osservazioni sul campo della prima sessione reale: la baseline misurata
all'inizio della sessione si "congelava" anche se le condizioni meteo cambiavano (caso osservato: baseline 0,571"
con cielo già velato → soglie troppo larghe per il resto della notte). La §25 introduce un refresh periodico
(default ogni 30 min) della baseline: la nuova mediana sostituisce la corrente SOLO se è più stretta
("tightest-wins"). L'Agente non concede mai reattività al peggioramento del cielo, ma si adatta automaticamente
quando il cielo migliora. Inoltre `rms_high_factor` abbassato da 1.5 a 1.3 dopo verifica numerica sui setup:
protegge meglio le focali lunghe (RC8) senza danneggiare le corte (Askar). Dettaglio in NOTE_CLAUDE.md §25.
```

In "Cosa NON è stato ancora fatto":
```
- Validazione sul campo di §25 in 2-3 sessioni reali, idealmente almeno una con cielo che migliora durante
  la nottata: verificare che il refresh applicato sia visibile sulla dashboard e che le soglie si stringano.
```

### `NOTE_CLAUDE.md`

Verificare ultima sezione con `grep "^## [0-9]" NOTE_CLAUDE.md | tail -1` (atteso §24). Aggiungere in coda:

```markdown
## 25. Refresh ciclico baseline (tightest-wins) + rms_high_factor 1.3 (YYYY-MM-DD)

### Motivazione
Validazione sul campo della prima sessione §22-§24 (Askar 71F, baseline 0,571" misurata con cielo già velato):
le soglie derivate restavano "congelate" su una calibrazione di cielo mediocre per tutta la nottata. La feature
risolve introducendo un refresh periodico (default 30 min) della baseline, con regola "tightest-wins"
(applica solo se più stretta). L'Agente si adatta a un cielo che migliora ma non si lascia trascinare da uno
che peggiora.

Inoltre `rms_high_factor` abbassato da 1.5 a 1.3: il cuscinetto del 50% sopra la baseline produceva su RC8
(0,51"/px) soglie DEGRADED già fuori scala per il campionamento (0,82-0,90" su baseline tipica 0,55-0,60");
il 30% (= f=1.3) produce soglie 0,72-0,78" — protezione reale per le focali lunghe, zero effetti pratici sulle
focali corte (dove l'RMS reale tipico sta comunque sotto entrambe le soglie).

### Architettura
- Nuovi campi `AutoCalibrationConfig`: `refresh_enabled`, `refresh_interval_seconds`, `refresh_only_if_tighter`.
- Cambio default `rms_high_factor`: 1.5 → 1.3.
- Nuovo stato controller: `_baseline_finalize_time` (monotonic), `_baseline_refresh_in_progress`,
  `_last_refresh_action`, `_last_refresh_baseline`.
- Nuovo metodo `_maybe_start_refresh()` chiamato in `evaluate()`: se il timer è scaduto e la baseline è applicata,
  azzera samples e flag `_rms_baseline_done` per riaprire la raccolta. Le soglie correnti restano attive.
- `_finalize_rms_baseline()` esteso: se `_baseline_refresh_in_progress` e `new >= current` → rifiuta, mantiene
  soglie correnti, logga "tightest-wins". Altrimenti applica come prima.
- `get_status()` esteso con 6 nuovi campi.
- Dashboard: nuova riga "Refresh" + badge "Ultimo: APPLICATO/RIFIUTATO".

### File modificati
- `phd2_agent/config.py`: 3 nuovi campi `AutoCalibrationConfig` + cambio default `rms_high_factor`.
- `phd2_agent/controller.py`: 4 nuovi stati `__init__` + reset in `_invalidate_rms_baseline` + nuovo
  `_maybe_start_refresh()` + estensione `_finalize_rms_baseline()` + estensione `get_status()`.
- `config.toml`: sezione `[auto_calibration]` aggiornata.
- `dashboard/`: card estesa con riga refresh + badge esito.
- `tests/test_auto_calibration.py`: test esistenti aggiornati al nuovo `rms_high_factor = 1.3` + 6 nuovi test §25.

### Limiti dell'approccio
1. Il refresh è "puramente temporale": ogni `refresh_interval_seconds` ri-misura. Non c'è euristica di
   "ri-misura subito se il cielo è cambiato drasticamente" (es. fine cloud passing). Possibile evoluzione
   futura: trigger di refresh anche su cambio condizione sostenuto.
2. Se il timer scade durante un seeing molto degradato, il refresh raccoglierà 60 campioni ma in regime non
   NOMINAL (filtro §22 li scarta), quindi il refresh può richiedere molto tempo per completarsi o non
   completarsi affatto se le condizioni non migliorano.

### Validazione raccomandata
1. Sessione con cielo stabile (almeno 1h): verificare che il primo refresh dopo 30 min sia "rifiutato"
   (baseline simile o leggermente più alta per fluttuazioni naturali).
2. Sessione con cielo che migliora (es. velatura che si dirada): dovrebbe arrivare un "applicato" con
   baseline più stretta.
3. Sessione con cielo che peggiora: serie di "rifiutato", soglie iniziali mantenute.
```

### `README.md`

Aggiornare riga nelle caratteristiche se elenca la calibrazione adattiva: "soglie RMS adattive con refresh
ciclico (tightest-wins)".

---

## CHECKLIST FINALE PRIMA DI COMMIT

- [ ] Pre-flight: confermata struttura `_finalize_rms_baseline` post-§23/§24, stato `__init__` esistente.
- [ ] `AutoCalibrationConfig`: 3 nuovi campi (`refresh_enabled`, `refresh_interval_seconds`, `refresh_only_if_tighter`)
      + default `rms_high_factor` cambiato 1.5 → 1.3.
- [ ] `config.toml`: nuovi campi + commento sul razionale; `rms_high_factor = 1.3` con commento §25.
- [ ] `controller.__init__`: 4 nuovi stati (`_baseline_finalize_time`, `_baseline_refresh_in_progress`,
      `_last_refresh_action`, `_last_refresh_baseline`).
- [ ] `_invalidate_rms_baseline`: resetta anche i 4 nuovi stati.
- [ ] `_maybe_start_refresh()`: nuovo metodo che azzera samples + `_rms_baseline_done = False` quando il timer
      è scaduto. Le soglie correnti restano in `cfg.thresholds`.
- [ ] `_finalize_rms_baseline()` esteso: se in refresh e `new >= current` → rifiuto con log; altrimenti applica.
      Anche durante refresh, il gate §23 (baseline > reject_threshold) ha priorità.
- [ ] `evaluate()`: chiamata a `_maybe_start_refresh()` prima della logica baseline esistente.
- [ ] `get_status()`: 6 nuovi campi (`refresh_enabled`, `refresh_interval_seconds`, `refresh_in_progress`,
      `refresh_progress`, `refresh_seconds_to_next`, `last_refresh_action`, `last_refresh_baseline_arcsec`).
- [ ] Dashboard: nuova riga "Refresh" + badge esito; `app.js` esteso; CSS coerente con palette.
- [ ] Test §22/§23/§24 aggiornati al nuovo `rms_high_factor = 1.3` dove serve.
- [ ] Nuovi test §25: applica, rifiuta peggiore, rifiuta uguale, disabilitato, gate §23 in refresh, stato `/status`.
- [ ] `pytest tests/ -v`: tutti verdi.
- [ ] Sanity simulator OK; `/status` espone i nuovi campi; nessun errore.
- [ ] `build_dist.py` OK; `config.toml` copiato; ZIP rigenerato.
- [ ] `CONTESTO_PROGETTO.md` + `NOTE_CLAUDE.md` §25 + (opz.) `README.md` aggiornati.
- [ ] Modalità LIVE mantenuta. Nessuna modifica a backlash, §19, §21, §22, §23, §24 oltre allo stretto necessario.

---

## DOMANDE DA FARMI PRIMA DI PROCEDERE (se servono)

Se trovi:
- `_finalize_rms_baseline()` strutturato in modo che non sia banale intercettare la regola tightest-wins
  prima dell'applicazione delle soglie.
- Nomi degli ID HTML diversi da quelli ipotizzati (`autocal-refresh-status`, `autocal-last-refresh-badge`).
- Test §24 che asseriscono il vecchio `rms_high_factor = 1.5` in modo non banale.

→ **Fermati e chiedi**, non improvvisare.

Se tutto è chiaro: procedi step-by-step, mostrami i diff prima di applicarli, poi i test, poi rebuild, poi docs,
quindi un singolo commit `feat: refresh ciclico baseline tightest-wins + rms_high_factor 1.3 (NOTE_CLAUDE §25)`
includendo anche questo `PROMPT_BASELINE_REFRESH_CICLICA.md` come specifica di design.

Grazie.
