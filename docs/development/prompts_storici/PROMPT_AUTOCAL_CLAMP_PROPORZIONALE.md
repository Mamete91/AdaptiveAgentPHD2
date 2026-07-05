# PROMPT PER CLAUDE CODE — CLAMP PROPORZIONALE ALLA PIXEL SCALE + GATE DI RIFIUTO BASELINE
# Da copiare e incollare integralmente nella conversazione con Claude Code.
# Lavorare nella cartella: PHD2_Assist_PATCHED/

> **NOTA OPERATIVA**: addendum alla §22 (auto-scala via RPC + soglie RMS adattive da baseline + config unico).
> La §22 ha già introdotto un clamp di sicurezza sulle soglie derivate, ma con valori **fissi e assoluti**
> (`rms_high_min_arcsec = 0.50`, `rms_high_max_arcsec = 2.50`). Questo addendum sostituisce quel clamp con uno
> **proporzionale alla pixel scale rilevata** e aggiunge un **gate di rifiuto della baseline** quando la mediana
> misurata supera quanto sia fisicamente sensato per quella scala.
>
> SCELTA OPERATIVA (decisione di Alessandro): impostazione "interventista" con `rms_high_max_factor = 2.0` e
> `baseline_reject_factor = 3.0`. Sull'RC8 (0,51"/px) questo significa cap a 1,02" e rifiuto sopra 1,53" mediana,
> per privilegiare la correzione attiva del seeing rispetto alla tolleranza permissiva.
>
> SCOPE: NON tocca la macchina a stati esposizione (§19), l'escalation gate (§21), il consolidamento config/bat (§22),
> il MinMove né i range di aggressività. Si modifica esclusivamente la logica di clamp dentro
> `_finalize_rms_baseline` e si estende `AutoCalibrationConfig` con quattro nuovi campi.

---

## 0. PRE-FLIGHT OBBLIGATORIO (leggere PRIMA di scrivere codice)

### File Python da consultare (architettura attuale post-§22)

1. `phd2_agent/config.py` — `AutoCalibrationConfig` introdotta in §22 con questi campi:
   `enabled`, `use_phd2_pixel_scale`, `rms_high_factor`, `rms_low_factor`, `baseline_window_frames`,
   `baseline_min_snr`, `rms_high_min_arcsec` (=0.50), `rms_high_max_arcsec` (=2.50).
   Verificare nomi esatti e parsing in `load_config`.

2. `phd2_agent/controller.py` — `_finalize_rms_baseline()` introdotto in §22. Logica attuale:
   ```python
   baseline = statistics.median(self._rms_baseline_samples)
   new_high = max(ac.rms_high_min_arcsec, min(ac.rms_high_max_arcsec, ac.rms_high_factor * baseline))
   new_low = ac.rms_low_factor * baseline
   self.cfg.thresholds.rms_high = new_high
   self.cfg.thresholds.rms_low = new_low
   self.analyzer.rms_high = new_high
   self.analyzer.rms_low = new_low
   self._rms_baseline_done = True
   ```
   Verificare: stato `_rms_baseline_*` in `__init__`, metodo `_invalidate_rms_baseline`, chiamata da `_update_rms_baseline`.

3. `phd2_agent/controller.py` — `get_status()` blocco `auto_calibration`. Verificare nomi attuali dei campi esposti
   (post-§22): `enabled`, `pixel_scale_arcsec`, `pixel_scale_source`, `baseline_rms_arcsec`, `baseline_done`,
   `baseline_progress`, `rms_high_active`, `rms_low_active`.

4. `dashboard/index.html` + `dashboard/app.js` — card "Auto-calibrazione" introdotta in §22. Va estesa.

5. `config.toml` — sezione `[auto_calibration]` introdotta in §22. Va aggiornata.

6. `tests/test_auto_calibration.py` — 9 test esistenti, verificare quali toccano `rms_high_min_arcsec` o
   `rms_high_max_arcsec` per non romperli.

### Conclusioni del pre-flight (già verificate, da confermare)

A. Il clamp attuale è **fisso e assoluto**: 0,50"-2,50" indipendentemente dalla scala. Sull'RC8 (0,51"/px) il tetto
   2,50" è troppo permissivo (5 px imaging di mossa); su scale molto fini il pavimento 0,50" è troppo lasco.
B. Sostituire il clamp con uno **proporzionale**: `cap = clamp(k × pixel_scale, floor_assoluto, ceiling_assoluto)`.
   Conserviamo i pavimenti assoluti come safety per scale estreme.
C. Aggiungere un **gate di rifiuto baseline**: se la mediana misurata > `k_reject × pixel_scale` (con pavimento
   assoluto), non applicare la calibrazione — la sessione non è rappresentativa, mantieni le soglie attuali (TOML
   iniziali alla prima sessione, o l'ultima calibrazione buona se già fatta).
D. Esporre su `/status` e sulla dashboard due nuove informazioni: il valore del cap efficace, lo stato "cap applicato"
   (rms_high derivato avrebbe superato il cap), e "baseline rifiutata" (calibrazione non applicata in questa sessione).

### Decisioni di design (già prese — implementare così)

a. **Cap proporzionale**: `cap = clamp(rms_high_max_factor × pixel_scale, rms_high_min_arcsec, rms_high_max_arcsec)`.
   Con `k=2.0`, scale 0,51 → 1,02"; scale 1,03 → 2,06"; scale 1,58 → cap proporzionale 3,16" ma ceiling assoluto 3,00".
b. **Rifiuto baseline**: se `baseline > max(baseline_reject_min_arcsec, baseline_reject_factor × pixel_scale)`,
   la calibrazione non viene applicata. Su rifiuto: log esplicito, `_rms_baseline_rejected = True`, mantieni valori
   esistenti di `cfg.thresholds.rms_high/rms_low` e dell'analyzer.
c. **Floor su rms_low**: nuovo campo `rms_low_min_arcsec = 0.25`, applicato come pavimento assoluto.
d. **Retrocompatibilità config**: i nuovi campi hanno default sensati. I vecchi `rms_high_min_arcsec` e
   `rms_high_max_arcsec` cambiano *valore* di default (0.70 e 3.00) ma non *significato*: continuano a fungere da
   pavimento e tetto assoluti del cap. Eventuali config TOML che li hanno scritti esplicitamente vengono letti come
   override degli utenti (intenzionali).

---

## OBIETTIVO TECNICO

Sostituire in `_finalize_rms_baseline` il clamp fisso introdotto in §22 con un clamp **proporzionale alla pixel scale
rilevata**, aggiungere un gate di rifiuto baseline per sessioni non rappresentative, aggiungere un floor su `rms_low`,
ed esporre lo stato risultante (cap applicato, baseline rifiutata) su `/status` e dashboard.

---

## REGOLE INDEROGABILI

- **NON toccare** la backlash compensation di PHD2.
- **NON riscrivere mai i file TOML a runtime**: solo la *config efficace in memoria* viene aggiornata.
- **NON cambiare** la logica di acquisizione baseline (filtri `NOMINAL`/SNR/no-implosion restano com'erano in §22).
- **NON cambiare** la lettura di `get_pixel_scale` né il flusso pixel-scale-override.
- **NON cambiare** la macchina a stati esposizione (§19), l'escalation gate (§21), il MinMove, i range aggressività.
- **NON introdurre** nuove librerie esterne.
- **Mantenere** retrocompatibilità del parsing TOML: nuovi campi assenti → default.
- **Mantenere** stile esistente (logging in italiano, type hints, dataclass).

### Modalità operativa

Feature da osservare sulla dashboard in LIVE. `[auto_calibration].enabled` resta `true` (come da §22).
La sicurezza è garantita dal clamp proporzionale + ceiling assoluto + gate di rifiuto + floor su `rms_low`.

---

## SPECIFICA FUNZIONALE

### 2A. `config.py` — estendere `AutoCalibrationConfig`

Aggiungere quattro campi e cambiare i default di due esistenti:

```python
@dataclass
class AutoCalibrationConfig:
    enabled: bool = False
    use_phd2_pixel_scale: bool = True
    rms_high_factor: float = 1.5
    rms_low_factor: float = 0.75
    baseline_window_frames: int = 60
    baseline_min_snr: float = 10.0
    # Clamp proporzionale del cap su rms_high (sostituisce il clamp fisso di §22):
    rms_high_max_factor: float = 2.0       # NUOVO — k del cap proporzionale: cap = k × pixel_scale
    rms_high_min_arcsec: float = 0.70      # modificato — era 0.50; pavimento assoluto del cap
    rms_high_max_arcsec: float = 3.00      # modificato — era 2.50; tetto assoluto del cap (safety scale grossolane)
    # Floor su rms_low:
    rms_low_min_arcsec: float = 0.25       # NUOVO — pavimento assoluto su rms_low derivato
    # Gate di rifiuto baseline:
    baseline_reject_factor: float = 3.0    # NUOVO — k del rifiuto: reject se baseline > k × pixel_scale
    baseline_reject_min_arcsec: float = 1.50  # NUOVO — pavimento assoluto del rifiuto
```

Parsing in `load_config` (estendere il blocco `if "auto_calibration" in raw`):

```python
cfg.auto_calibration = AutoCalibrationConfig(
    enabled=bool(a.get("enabled", False)),
    use_phd2_pixel_scale=bool(a.get("use_phd2_pixel_scale", True)),
    rms_high_factor=float(a.get("rms_high_factor", 1.5)),
    rms_low_factor=float(a.get("rms_low_factor", 0.75)),
    baseline_window_frames=int(a.get("baseline_window_frames", 60)),
    baseline_min_snr=float(a.get("baseline_min_snr", 10.0)),
    rms_high_max_factor=float(a.get("rms_high_max_factor", 2.0)),
    rms_high_min_arcsec=float(a.get("rms_high_min_arcsec", 0.70)),
    rms_high_max_arcsec=float(a.get("rms_high_max_arcsec", 3.00)),
    rms_low_min_arcsec=float(a.get("rms_low_min_arcsec", 0.25)),
    baseline_reject_factor=float(a.get("baseline_reject_factor", 3.0)),
    baseline_reject_min_arcsec=float(a.get("baseline_reject_min_arcsec", 1.50)),
)
```

### 2B. `controller.py` — aggiornare `__init__` e `_invalidate_rms_baseline`

In `__init__`, aggiungere tre flag di stato:

```python
self._rms_baseline_rejected: bool = False
self._rms_high_cap_active: bool = False
self._rms_high_cap_value: Optional[float] = None
```

In `_invalidate_rms_baseline`, resettare anche questi:

```python
def _invalidate_rms_baseline(self, reason: str) -> None:
    self._rms_baseline_samples.clear()
    self._rms_baseline_value = None
    self._rms_baseline_done = False
    self._rms_baseline_rejected = False
    self._rms_high_cap_active = False
    self._rms_high_cap_value = None
    log.info("[autocal] baseline RMS invalidata (%s)", reason)
```

### 2C. `controller.py` — riscrivere `_finalize_rms_baseline`

Sostituire la versione §22 con la seguente:

```python
def _finalize_rms_baseline(self) -> None:
    import statistics
    ac = self.cfg.auto_calibration
    baseline = statistics.median(self._rms_baseline_samples)
    self._rms_baseline_value = baseline
    scale = self.cfg.setup.guide_pixel_scale_arcsec   # pixel scale efficace (PHD2 o TOML fallback)

    # ----- GATE DI RIFIUTO BASELINE -----
    reject_threshold = max(ac.baseline_reject_min_arcsec,
                           ac.baseline_reject_factor * scale)
    if baseline > reject_threshold:
        # Sessione non rappresentativa: NON applicare la calibrazione.
        # Mantieni i valori esistenti di cfg.thresholds (TOML iniziali alla prima sessione).
        self._rms_baseline_rejected = True
        self._rms_high_cap_active = False
        self._rms_high_cap_value = None
        self._rms_baseline_done = True
        log.warning(
            "[autocal] baseline RMS = %.3f\" RIFIUTATA "
            "(soglia rifiuto = %.3f\" = max(%.2f\", %.1f × %.3f\"/px)): "
            "sessione non rappresentativa, mantengo rms_high=%.3f\" rms_low=%.3f\"",
            baseline, reject_threshold,
            ac.baseline_reject_min_arcsec, ac.baseline_reject_factor, scale,
            self.cfg.thresholds.rms_high, self.cfg.thresholds.rms_low,
        )
        return

    # ----- CLAMP PROPORZIONALE SU rms_high -----
    cap_proporzionale = ac.rms_high_max_factor * scale
    cap_efficace = max(ac.rms_high_min_arcsec,
                       min(ac.rms_high_max_arcsec, cap_proporzionale))

    derived_high = ac.rms_high_factor * baseline
    new_high = min(cap_efficace, derived_high)
    self._rms_high_cap_active = (derived_high > cap_efficace)
    self._rms_high_cap_value = cap_efficace

    # ----- FLOOR SU rms_low -----
    derived_low = ac.rms_low_factor * baseline
    new_low = max(ac.rms_low_min_arcsec, derived_low)

    # ----- APPLICA ALLA CONFIG EFFICACE IN MEMORIA -----
    self.cfg.thresholds.rms_high = new_high
    self.cfg.thresholds.rms_low = new_low
    self.analyzer.rms_high = new_high
    self.analyzer.rms_low = new_low
    self._rms_baseline_done = True
    self._rms_baseline_rejected = False

    log.info(
        "[autocal] baseline RMS = %.3f\" su %d frame | "
        "cap = %.1f × %.3f\"/px = %.3f\" (efficace dopo bounds = %.3f\") | "
        "rms_high = %.3f\"%s | rms_low = %.3f\"%s",
        baseline, len(self._rms_baseline_samples),
        ac.rms_high_max_factor, scale, cap_proporzionale, cap_efficace,
        new_high, " [CAP APPLICATO]" if self._rms_high_cap_active else "",
        new_low, " [FLOOR APPLICATO]" if derived_low < ac.rms_low_min_arcsec else "",
    )
```

### 2D. `controller.py` — estendere `get_status()`

Aggiungere al blocco `auto_calibration` tre campi:

```python
"auto_calibration": {
    "enabled": cfg.auto_calibration.enabled,
    "pixel_scale_arcsec": round(cfg.setup.guide_pixel_scale_arcsec, 3),
    "pixel_scale_source": "phd2" if cfg.setup.pixel_scale_override is not None else "toml",
    "baseline_rms_arcsec": (round(self._rms_baseline_value, 3)
                            if self._rms_baseline_value is not None else None),
    "baseline_done": self._rms_baseline_done,
    "baseline_rejected": self._rms_baseline_rejected,                          # NUOVO
    "baseline_progress": f"{len(self._rms_baseline_samples)}/{cfg.auto_calibration.baseline_window_frames}",
    "rms_high_active": round(cfg.thresholds.rms_high, 3),
    "rms_low_active": round(cfg.thresholds.rms_low, 3),
    "rms_high_cap_arcsec": (round(self._rms_high_cap_value, 3)                 # NUOVO
                            if self._rms_high_cap_value is not None else None),
    "rms_high_cap_active": self._rms_high_cap_active,                          # NUOVO
},
```

### 2E. `config.toml` — aggiornare la sezione `[auto_calibration]`

Sostituire la sezione introdotta in §22 con la versione estesa:

```toml
[auto_calibration]
enabled                       = true
use_phd2_pixel_scale          = true
rms_high_factor               = 1.5
rms_low_factor                = 0.75
baseline_window_frames        = 60
baseline_min_snr              = 10.0
# --- Clamp proporzionale del cap su rms_high (§23) ---
# cap_efficace = clamp(rms_high_max_factor * pixel_scale, rms_high_min_arcsec, rms_high_max_arcsec)
# Esempi: RC8 (0,51"/px) -> cap 1,02"; Tecnosky (1,03"/px) -> 2,06"; Askar (1,58"/px) -> 3,00" (ceiling).
rms_high_max_factor           = 2.0
rms_high_min_arcsec           = 0.70
rms_high_max_arcsec           = 3.00
# Floor su rms_low:
rms_low_min_arcsec            = 0.25
# --- Gate di rifiuto baseline (§23) ---
# reject se baseline > max(baseline_reject_min_arcsec, baseline_reject_factor * pixel_scale)
# Esempi: RC8 reject > 1,53"; Tecnosky > 3,09"; Askar > 4,74".
baseline_reject_factor        = 3.0
baseline_reject_min_arcsec    = 1.50
```

### 2F. Dashboard — estendere la card "Auto-calibrazione"

In `dashboard/index.html`, aggiungere alla card "Auto-calibrazione" due nuovi elementi:

1. Riga con etichetta "Cap rms_high:" + valore (`rms_high_cap_arcsec` arrotondato) + badge "ATTIVO" quando
   `rms_high_cap_active === true` (colore d'avvertimento, es. ambra).
2. Badge prominente "BASELINE RIFIUTATA" (colore rosso) quando `baseline_rejected === true`, con tooltip che
   spiega "Sessione non rappresentativa: mantengo le soglie iniziali del TOML".

In `dashboard/app.js`, estendere `updateAutoCalibration(ac)` (o nome equivalente post-§22):

```javascript
function updateAutoCalibration(ac) {
    // ... codice esistente §22 (badge fonte scala, progresso baseline, rms_high/low attive) ...

    // NUOVO §23 — cap rms_high
    const capEl = document.getElementById('autocal-rms-high-cap');
    const capActiveBadge = document.getElementById('autocal-cap-active-badge');
    if (ac.rms_high_cap_arcsec !== null && ac.rms_high_cap_arcsec !== undefined) {
        capEl.textContent = ac.rms_high_cap_arcsec.toFixed(2) + '"';
        capActiveBadge.style.display = ac.rms_high_cap_active ? 'inline-block' : 'none';
    } else {
        capEl.textContent = '—';
        capActiveBadge.style.display = 'none';
    }

    // NUOVO §23 — baseline rifiutata
    const rejectedBadge = document.getElementById('autocal-baseline-rejected-badge');
    rejectedBadge.style.display = ac.baseline_rejected ? 'inline-block' : 'none';
}
```

CSS: riusare il pattern delle badge esistenti (esposizione/escalation gate dell'§21). Colore badge "CAP ATTIVO" ambra
(#d9a300, come `IMPORTANTE` dell'esposizione), badge "BASELINE RIFIUTATA" rosso (#c92a2a).

---

## TEST ATTESI

### Aggiornamento test esistenti

In `tests/test_auto_calibration.py`, il test 5 (baseline happy path) e i test che verificavano il vecchio clamp fisso
(es. test 7 "clamp con baseline anomala") vanno aggiornati ai nuovi default e alla nuova formula:

- I 9 test esistenti che costruiscono `AutoCalibrationConfig()` vanno verificati: il default `rms_high_min_arcsec`
  passa da 0.50 a 0.70 e `rms_high_max_arcsec` da 2.50 a 3.00. Aggiornare le aspettative numeriche se necessario.
- Test 7 (clamp): cambiarne la semantica per riflettere il cap proporzionale. Esempio: baseline 5.0" con scala 1.0
  → `cap_proporzionale = 2.0`, `cap_efficace = 2.0` (entro bounds 0.7-3.0), `derived_high = 7.5`, `new_high = 2.0`
  (cap applicato).

### Nuovi test (in `tests/test_auto_calibration.py`, oppure file separato `test_auto_calibration_clamp.py`)

1. **Cap proporzionale RC8**: scala 0.51, baseline 0.8 → `derived_high = 1.20`, `cap = 1.02`, applicato
   `rms_high = 1.02`, `_rms_high_cap_active = True`.
2. **Cap proporzionale Askar (ceiling)**: scala 1.58, baseline 1.4 → `cap_proporzionale = 3.16` ma `cap_efficace = 3.00`
   (ceiling), `derived_high = 2.10`, applicato `rms_high = 2.10`, `_rms_high_cap_active = False`.
3. **Pavimento cap su scala fine estrema**: scala 0.30, baseline 0.30 → `cap_proporzionale = 0.60`, `cap_efficace = 0.70`
   (floor), `derived_high = 0.45`, applicato `rms_high = 0.45`.
4. **Rifiuto baseline RC8**: scala 0.51, baseline 1.6 → `reject_threshold = 1.53`, baseline supera → rifiutato,
   `_rms_baseline_rejected = True`, `cfg.thresholds.rms_high` invariato rispetto al pre-chiamata.
5. **Rifiuto baseline con pavimento assoluto**: scala 0.20, baseline 1.6 → `reject_threshold = max(1.5, 0.6) = 1.5`,
   baseline supera → rifiutato. (Verifica che il pavimento assoluto domini su scale finissime.)
6. **Accettazione baseline borderline**: scala 0.51, baseline 1.5 → `reject_threshold = 1.53`, baseline non supera
   → applicato, `_rms_baseline_rejected = False`, cap attivo (`derived_high = 2.25 > cap 1.02`).
7. **Floor rms_low**: scala 1.0, baseline 0.25 → `derived_low = 0.1875`, applicato `rms_low = 0.25` (floor).
8. **Reset stato su invalidazione**: dopo finalize con cap attivo, chiamare `_invalidate_rms_baseline` → tutti i flag
   nuovi (`_rms_baseline_rejected`, `_rms_high_cap_active`, `_rms_high_cap_value`) tornano ai default.

### Sanity simulator

```bash
python main.py --simulator --dry-run --config config.toml
```

Verifica:
- Nessun errore all'avvio.
- `/status` ritorna i nuovi campi `baseline_rejected`, `rms_high_cap_arcsec`, `rms_high_cap_active`.
- Test esistenti (§22 + §23 nuovi) tutti verdi: `python -m pytest tests/ -v`.

---

## VALIDAZIONE SUL CAMPO

### Cosa osservare sulla dashboard

Sulla card "Auto-calibrazione" (post-§23 estesa):
- Riga "Cap rms_high: X,XX" + eventuale badge ambra **CAP ATTIVO** → se attivo, la baseline avrebbe spinto la soglia
  oltre il fisicamente sensato per la scala, e il cap l'ha tenuta bassa.
- Eventuale badge rosso **BASELINE RIFIUTATA** → la sessione non è rappresentativa, l'Agente usa i valori TOML iniziali.

### Linee guida tuning

- **Sull'RC8 il badge CAP ATTIVO compare spesso in serate normali** → cap troppo stretto: alzare `rms_high_max_factor`
  a 2.2-2.5.
- **Sull'RC8 il badge BASELINE RIFIUTATA compare in serate giudicate medie** → soglia di rifiuto troppo stretta: alzare
  `baseline_reject_factor` a 3.5.
- **Su Askar/Tecnosky il cap non è mai attivo** → comportamento atteso, le scale corte hanno cap molto largo.
- **Su scale finissime non standard l'rms_low resta inchiodato a 0.25"** → eventualmente abbassare `rms_low_min_arcsec`
  a 0.20.

---

## PROCEDURA REBUILD

1. `python -m pytest tests/ -v` → tutti i test passano prima del rebuild (esistenti + nuovi §23).
2. `python build_dist.py` (build completa).
3. Copiare manualmente `config.toml` e `Sblocca_Firewall_8080.bat` in `Pacchetto_Distribuzione/`.
4. Verifica residui: solo `Avvia.bat` + `Sblocca_Firewall_8080.bat`, un solo `config.toml`.
5. Ricreare `PHD2_Agent_Distribuzione.zip`.

---

## AGGIORNAMENTO DOCUMENTAZIONE

### `CONTESTO_PROGETTO.md`

Aggiornare la data e aggiungere, prima di "Cosa NON è stato ancora fatto":

```markdown
### Clamp proporzionale + gate rifiuto baseline (§23) — IMPLEMENTATA (YYYY-MM-DD)
Rifinitura della §22: il clamp di sicurezza sulle soglie RMS adattive non è più fisso (0,50"-2,50") ma
proporzionale alla pixel scale rilevata (cap = 2.0 × pixel_scale, con pavimento 0,70" e tetto 3,00"
come safety per scale estreme). Aggiunto un gate di rifiuto della baseline misurata quando la mediana
supera 3.0 × pixel_scale (con pavimento 1,50"): in tal caso la calibrazione non viene applicata, l'Agente
mantiene le soglie iniziali del TOML, la dashboard segnala "BASELINE RIFIUTATA". Aggiunto floor su rms_low
a 0,25". Setup di riferimento per la scelta dei parametri: RC8 (cap 1,02"; rifiuto >1,53"). Dettaglio in
NOTE_CLAUDE.md §23.
```

In "Cosa NON è stato ancora fatto":
```
- Validazione sul campo di §23 su RC8: verificare in 2-3 sessioni con seeing variabile che il cap proporzionale
  si attivi quando previsto e che il gate di rifiuto non si attivi nelle serate normali. Tarare eventualmente
  rms_high_max_factor o baseline_reject_factor sui log.
```

### `NOTE_CLAUDE.md`

Verificare l'ultima sezione con `grep "^## [0-9]" NOTE_CLAUDE.md | tail -1` (atteso §22). Aggiungere in coda:

```markdown
## 23. Clamp proporzionale + gate rifiuto baseline (YYYY-MM-DD)

### Motivazione
La §22 ha introdotto soglie RMS adattive da baseline misurata con un clamp di sicurezza fisso 0,50"-2,50".
Su focali lunghe (RC8 a 0,51"/px) il tetto 2,50" è troppo permissivo (5 px di mossa imaging); su scale
molto corte è troppo lasco. Inoltre una baseline misurata in nottata anomala (vento forte) può comunque
spostare le soglie verso valori che "promuovono" un seeing scarso a normalità. Servono: (1) clamp
proporzionale alla scala, (2) gate di rifiuto quando la baseline è palesemente non rappresentativa.

### Architettura
`_finalize_rms_baseline` (in controller.py) ora calcola:
- `cap_efficace = clamp(rms_high_max_factor * pixel_scale, rms_high_min_arcsec, rms_high_max_arcsec)`
- `reject_threshold = max(baseline_reject_min_arcsec, baseline_reject_factor * pixel_scale)`
- Se `baseline > reject_threshold` → rifiuta, `_rms_baseline_rejected = True`, soglie invariate.
- Altrimenti: `rms_high = min(cap_efficace, rms_high_factor * baseline)`, `rms_low = max(rms_low_min_arcsec, rms_low_factor * baseline)`.
- Espone su `/status`: `baseline_rejected`, `rms_high_cap_arcsec`, `rms_high_cap_active`.

### Parametri scelti (configurazione "interventista")
`rms_high_max_factor = 2.0`, `rms_high_min_arcsec = 0.70`, `rms_high_max_arcsec = 3.00`,
`rms_low_min_arcsec = 0.25`, `baseline_reject_factor = 3.0`, `baseline_reject_min_arcsec = 1.50`.

Effetto per setup di Alessandro:
| Setup | pixel scale | cap rms_high | soglia rifiuto baseline |
|---|---|---|---|
| RC8 | 0,51"/px | 1,02" | 1,53" |
| Tecnosky 115 | 1,03"/px | 2,06" | 3,09" |
| Askar 71F | 1,58"/px | 3,00" (ceiling) | 4,74" |

### File modificati
- `phd2_agent/config.py`: 4 nuovi campi in `AutoCalibrationConfig`, parsing esteso.
- `phd2_agent/controller.py`: riscritto `_finalize_rms_baseline`, aggiunti flag stato, esteso `get_status()`.
- `config.toml`: sezione `[auto_calibration]` estesa con nuovi parametri commentati.
- `dashboard/index.html`, `dashboard/app.js`: card estesa con badge CAP ATTIVO + BASELINE RIFIUTATA.
- `tests/test_auto_calibration.py`: test esistenti aggiornati ai nuovi default, +8 nuovi test per i casi §23.

### Limiti dell'approccio
1. I parametri sono tarati sull'esperienza astrofotografica su OAG: su cercatore-guida (scala disaccoppiata
   dall'imaging) il significato fisico del cap perde rigore. Per uso solo-OAG come Alessandro è ottimale.
2. Sul rigetto la calibrazione *non* viene riapplicata fino al prossimo `_invalidate_rms_baseline` (cambio
   pixel scale o reset esplicito). In sessioni che migliorano dopo un inizio cattivo, il rigetto resta sticky:
   in futuro si può valutare un meccanismo di re-tentativo periodico (non implementato in §23).

### Validazione raccomandata
1. Sessione RC8 in seeing normale (mediana attesa 0,5-0,8"): cap NON attivo, baseline accettata.
2. Sessione RC8 in seeing marginale (mediana 1,0-1,3"): cap ATTIVO, baseline accettata, rms_high a 1,02".
3. Sessione RC8 in seeing pessimo (mediana > 1,5"): baseline RIFIUTATA, fallback a rms_high TOML 1,20.
```

### `README.md`

Aggiungere una riga in sezione caratteristiche: "Soglie RMS adattive con clamp proporzionale alla pixel scale
e rigetto baseline non rappresentative (§23)".

---

## CHECKLIST FINALE PRIMA DI COMMIT

- [ ] Pre-flight: letto `AutoCalibrationConfig`, `_finalize_rms_baseline` post-§22, `get_status()`, dashboard card.
- [ ] `AutoCalibrationConfig` estesa con 4 nuovi campi + 2 default modificati; parsing esteso.
- [ ] `__init__` controller: 3 nuovi flag stato (`_rms_baseline_rejected`, `_rms_high_cap_active`, `_rms_high_cap_value`).
- [ ] `_invalidate_rms_baseline`: resetta anche i 3 nuovi flag.
- [ ] `_finalize_rms_baseline` riscritto con cap proporzionale + gate rifiuto + floor rms_low + log dettagliato.
- [ ] `get_status()` espone `baseline_rejected`, `rms_high_cap_arcsec`, `rms_high_cap_active`.
- [ ] `config.toml` aggiornato con nuovi campi commentati nella sezione `[auto_calibration]`.
- [ ] Dashboard: card estesa con campo "Cap rms_high", badge CAP ATTIVO ambra, badge BASELINE RIFIUTATA rosso.
- [ ] `tests/test_auto_calibration.py`: test esistenti aggiornati ai nuovi default, +8 nuovi test.
- [ ] `python -m pytest tests/ -v`: tutti verdi (post-§22 + nuovi §23).
- [ ] Sanity simulator: nessun errore, `/status` ritorna nuovi campi.
- [ ] `python build_dist.py` ok; `config.toml` copiato in `Pacchetto_Distribuzione/`; ZIP rigenerato.
- [ ] `CONTESTO_PROGETTO.md` aggiornato; `NOTE_CLAUDE.md` §23 aggiunta; `README.md` aggiornato.
- [ ] Nessuna modifica a backlash, esposizione dinamica (§19), escalation gate (§21), config unico (§22)
  oltre allo stretto necessario.

---

## DOMANDE DA FARMI PRIMA DI PROCEDERE (se servono)

Se durante l'implementazione trovi:
- Test esistenti che si rompono per i cambi di default `rms_high_min_arcsec` (0.50→0.70) o `rms_high_max_arcsec`
  (2.50→3.00) in modo non banale (es. test che presuppongono il vecchio valore).
- Nome diverso del metodo di update card sulla dashboard.
- Nome diverso degli ID HTML usati in `app.js` per i campi della card.

→ **Fermati e chiedi**, non improvvisare.

Se tutto è chiaro: procedi step-by-step, mostrami i diff prima di applicarli, poi i test, poi rebuild e docs.

Grazie.
