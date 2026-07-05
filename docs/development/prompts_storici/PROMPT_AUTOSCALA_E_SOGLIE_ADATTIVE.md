# PROMPT PER CLAUDE CODE (Antigravity) — AUTO-SCALA DI GUIDA VIA RPC + SOGLIE RMS ADATTIVE + CONFIG UNICO
# Da copiare e incollare integralmente nella conversazione con Claude Code.
# Lavorare nella cartella: PHD2_Assist_PATCHED/

> **NOTA OPERATIVA**: questa feature rende l'agente completamente auto-configurante e collassa la
> configurazione a **un solo `config.toml` + un solo `Avvia.bat`**.
> Oggi la pixel scale di guida è hard-coded per setup in `[setup]` (vedi NOTE_CLAUDE.md §20), le soglie RMS
> sono costanti tarate a mano in `[thresholds]`, ed esistono 3 TOML per-setup + 6 `.bat` (focale piena/ridotta).
> L'obiettivo è triplice:
> 1. leggere la pixel scale reale da PHD2 via JSON-RPC `get_pixel_scale`, con fallback ai valori TOML;
> 2. derivare le soglie RMS (`rms_high`/`rms_low`) da una **baseline misurata** sul campo;
> 3. **unificare** tutto in un singolo `config.toml` (valori costanti condivisi + auto-config) e un singolo
>    `Avvia.bat`, eliminando i 3 TOML per-setup e i 6 `.bat`. La scelta del telescopio avviene selezionando il
>    profilo dentro PHD2 (che contiene camera, focale, binning → da cui deriva la pixel scale).
>
> SCOPE: NON si tocca il MinMove (resta in pixel, range fisso — già scale-independent), NON si toccano i range
> di aggressività, NON si tocca la macchina a stati esposizione (§19) né l'escalation gate (§21).
> Si agisce solo su: pixel scale efficace, soglie RMS adattive, e consolidamento config/bat.

---

## 0. PRE-FLIGHT OBBLIGATORIO (leggere PRIMA di scrivere codice)

### File sorgente PHD2 da consultare

1. **`phd2-master/phd2-master/src/event_server.cpp`**
   - Funzione `get_pixel_scale` (cercare `static void get_pixel_scale`): chiama `pFrame->GetCameraPixelScale()`.
     Se la scala vale `1.0` restituisce `jrpc_result(NULL_VALUE)` (JSON `null`), altrimenti il numero.
     **Conseguenza critica**: la risposta RPC può essere `null`. Va gestita, non assunta numerica.
   - (Facoltativo) `get_current_equipment` per leggere il nome del profilo attivo, utile solo come etichetta in dashboard.

2. **`phd2-master/phd2-master/src/myframe.cpp`**
   - `MyFrame::GetCameraPixelScale()` (~riga 2837): ritorna `1.0` se `!pCamera`, o se `pixelSize == 0.0` o
     `m_focalLength == 0`; altrimenti `GetPixelScale(pixelSize, m_focalLength, binning)`.
     **Quindi `1.0` = "scala sconosciuta"**: camera non connessa, focale non impostata nel profilo, driver senza
     pixel size. Caso limite: scala reale di esattamente 1,00"/px → PHD2 risponde `null` (indistinguibile). Documentarlo.

### File Python da consultare (architettura attuale)

1. `phd2_agent/client.py` — **riga ~232**: `get_pixel_scale()` fa già `return float(self.call("get_pixel_scale"))`.
   **Bug latente**: `float(None)` solleva `TypeError` quando PHD2 risponde `null`. Va reso null-safe. Verificare anche
   come `call()` segnala errori RPC (timeout/metodo assente).
2. `phd2_agent/config.py` — `SetupConfig` (riga ~25) con property `guide_pixel_scale_arcsec` (single source of truth,
   già usata ovunque), `ThresholdsConfig` (riga ~62), `EmergencyConfig`, `ExposureDynamicConfig` (riga ~102),
   `AgentConfig` (riga ~114), `load_config` (riga ~128).
3. `phd2_agent/analyzer.py` — `StatisticsAnalyzer.__init__` riceve `rms_high`/`rms_low`/`snr_low`/`spike_ratio_high`
   come attributi di istanza e li usa in `_compute()` per classificare `SeeingCondition`. `AnalysisSnapshot` espone
   `rms_total`, il campo SNR (verificare nome esatto), `spike_score`, `implosion_detected`, `condition`.
4. `phd2_agent/controller.py` — `initialize()` (dove leggere la pixel scale dopo la connessione), il loop di valutazione
   che usa `thresh = self.cfg.thresholds` (riga ~552 `thresh.rms_high`), e la gestione eventi PHD2
   (cercare `GuidingResumed`, avvio guida, reconnect).
5. `main.py` — riga ~96 `StatisticsAnalyzer(...)` costruito con `rms_high=cfg.thresholds.rms_high` ecc.; argparse
   con `--config` (default `config.toml`) e gli override `--with-reducer`/`--no-reducer` applicati dopo `load_config`.
6. `server.py` — endpoint `/status`: struttura JSON per aggiungere il blocco `auto_calibration`.
7. `build_dist.py` — righe ~55-71: copie dei 4 config TOML e lista `bat_files` dei 6 `.bat`. Da semplificare (vedi 2F).

### Conclusioni del pre-flight (già verificate, da confermare)

A. `get_pixel_scale` esiste già lato RPC e lato client, ma il client **crasha su `null`**: primo fix.
B. La property `SetupConfig.guide_pixel_scale_arcsec` è il single source of truth: tutte le feature leggono da lì.
   Far ritornare a questa property la scala rilevata quando disponibile è il modo pulito per l'auto-scala.
C. Le soglie RMS vivono in **due posti**: `cfg.thresholds.rms_high/rms_low` (usate dal controller) e negli attributi
   dell'analyzer. Vanno aggiornate **entrambe** quando si applica la calibrazione adattiva.
D. MinMove nei 3 TOML è già costante in pixel (0,15–0,80) a scale molto diverse: scale-independent, NON va derivato.
E. Le uniche differenze residue tra i 3 TOML sono: `max_exposure_ms` (4000/5000/6000), `snr_low` (9/9/8),
   `spike_min` (0,30/0,25/0,20), `hfd_min_arcsec` (4,5/4,0/4,0). Vengono **unificate a costanti** (vedi 2F), così i
   file per-setup diventano superflui e si collassa a un config unico.

### Decisioni di design (già prese — implementare così)

a. **Pixel scale efficace**: campo runtime `SetupConfig.pixel_scale_override: Optional[float] = None` (NON parsato dal
   TOML). La property ritorna l'override se valorizzato, altrimenti native/reduced. Il controller lo imposta col valore
   di `get_pixel_scale` quando valido; `null`/errore → resta `None` → fallback TOML.
b. **Soglie RMS adattive**: da baseline misurata, NON dalla pixel scale. `rms_high = factor_high * baseline`,
   `rms_low = factor_low * baseline`; baseline = mediana di `rms_total` su una finestra di frame "buoni" (SNR sopra
   soglia, no implosion, condizione stabile). Clamp di sicurezza.
c. **Config efficace in memoria**: i valori calcolati aggiornano `cfg.thresholds` + analyzer a runtime e si mostrano in
   dashboard. **I file TOML non vengono mai riscritti.**
d. **Timing**: leggere la pixel scale all'`initialize()`, di nuovo all'avvio guida (primo GuideStep dopo connessione) e
   su `GuidingResumed`/riconnessione; se la scala cambia, invalidare e ricalcolare la baseline.
e. **Config unico**: un solo `config.toml` con valori costanti unificati + `[auto_calibration].enabled = true`. Si
   eliminano i 3 TOML per-setup e i 6 `.bat`, sostituiti da un solo `Avvia.bat`. La scelta del telescopio avviene
   selezionando il profilo in PHD2 (focale → pixel scale auto-rilevata). Il flag `--with-reducer` resta nel codice per
   retrocompatibilità ma il `.bat` unico non lo usa (con auto-scala è ininfluente: la focale del profilo PHD2 comanda).

### Nessuna verifica → STOP

Se durante il pre-flight scopri che il campo SNR nello snapshot ha un nome diverso, o che l'enum `SeeingCondition` non
ha `NORMAL`, o che non esiste un hook per `GuidingResumed`/reconnect, **fermati e riportamelo** prima di procedere.

---

## OBIETTIVO TECNICO

Rendere l'agente auto-configurante e a config unico: `controller.py` legge `get_pixel_scale` (fallback TOML), un
calibratore deriva `rms_high`/`rms_low` da una baseline misurata, e l'intera configurazione si riduce a un solo
`config.toml` + un solo `Avvia.bat` con costanti unificate. Selezionando il profilo in PHD2, lo stesso pacchetto
funziona su qualunque telescopio/camera senza taratura manuale.

---

## REGOLE INDEROGABILI

- **NON toccare** la backlash compensation di PHD2 (regola assoluta).
- **NON riscrivere mai i file TOML a runtime**: la calibrazione produce una *config efficace in memoria*.
- **NON modificare** il MinMove né i range di aggressività (scale-independent, già corretti).
- **NON modificare** la macchina a stati esposizione (§19), l'escalation gate (§21), il Baseline Guardian, il RMS
  implosion detector, oltre allo stretto necessario per integrazione.
- **NON introdurre** nuove librerie esterne (Python 3.12 stdlib + numpy/scipy/fastapi/uvicorn già presenti).
- **Mantenere** retrocompatibilità del parsing: sezione `[auto_calibration]` assente → default (feature OFF).
- **Mantenere** stile e convenzioni esistenti (logging in italiano, docstring, dataclass, type hints, Enum `auto()`).

### MODALITÀ OPERATIVA

Feature da osservare **sul grafico della dashboard** in LIVE:

> - `config.toml` unico con `[control] dry_run = false`, `[auto_calibration].enabled = true`,
>   `[exposure_dynamic].enabled = true`.
> - Sicurezza garantita da: clamp sulle soglie derivate, baseline misurata solo in condizione stabile, e fallback ai
>   valori `[thresholds]` del TOML finché la baseline non è pronta.

---

## SPECIFICA FUNZIONALE

### 2A. `client.py` — `get_pixel_scale` null-safe

```python
def get_pixel_scale(self) -> Optional[float]:
    """Pixel scale di guida (arcsec/px) dal profilo PHD2 attivo.
    Ritorna None se PHD2 risponde `null` (camera non connessa, focale non impostata,
    driver senza pixel size, o scala reale == 1.00"/px) o se la chiamata RPC fallisce."""
    try:
        result = self.call("get_pixel_scale")
    except Exception as e:
        log.warning("get_pixel_scale: chiamata RPC fallita (%s)", e)
        return None
    if result is None:
        return None
    try:
        return float(result)
    except (TypeError, ValueError):
        return None
```

(Adattare al nome reale del logger e al modo in cui `call()` segnala gli errori.)

### 2B. `config.py` — pixel scale override runtime + sezione `[auto_calibration]`

```python
@dataclass
class SetupConfig:
    profile_name: str = ""
    guide_pixel_scale_arcsec_native:  float = 1.0
    guide_pixel_scale_arcsec_reduced: float = 1.0
    reducer_active: bool = False
    pixel_scale_override: Optional[float] = None   # runtime: da get_pixel_scale (None = usa TOML)

    @property
    def guide_pixel_scale_arcsec(self) -> float:
        """Pixel scale effettiva. Priorità: override runtime (da PHD2) > reduced/native (da TOML)."""
        if self.pixel_scale_override is not None:
            return self.pixel_scale_override
        return (self.guide_pixel_scale_arcsec_reduced
                if self.reducer_active
                else self.guide_pixel_scale_arcsec_native)
```

```python
@dataclass
class AutoCalibrationConfig:
    enabled: bool = False
    use_phd2_pixel_scale: bool = True
    rms_high_factor: float = 1.5
    rms_low_factor: float = 0.75
    baseline_window_frames: int = 60
    baseline_min_snr: float = 10.0
    rms_high_min_arcsec: float = 0.50    # clamp inferiore su rms_high derivato
    rms_high_max_arcsec: float = 2.50    # clamp superiore su rms_high derivato
```

Parsing retrocompatibile in `load_config` (sezione assente → default) + campo `auto_calibration` in `AgentConfig`
con default factory:

```python
if "auto_calibration" in raw:
    a = raw["auto_calibration"]
    cfg.auto_calibration = AutoCalibrationConfig(
        enabled=bool(a.get("enabled", False)),
        use_phd2_pixel_scale=bool(a.get("use_phd2_pixel_scale", True)),
        rms_high_factor=float(a.get("rms_high_factor", 1.5)),
        rms_low_factor=float(a.get("rms_low_factor", 0.75)),
        baseline_window_frames=int(a.get("baseline_window_frames", 60)),
        baseline_min_snr=float(a.get("baseline_min_snr", 10.0)),
        rms_high_min_arcsec=float(a.get("rms_high_min_arcsec", 0.50)),
        rms_high_max_arcsec=float(a.get("rms_high_max_arcsec", 2.50)),
    )
```

### 2C. `controller.py` — auto-scala + calibratore baseline

#### (i) Lettura pixel scale

```python
def _apply_pixel_scale_from_phd2(self, context: str = "init") -> None:
    ac = self.cfg.auto_calibration
    if not ac.enabled or not ac.use_phd2_pixel_scale:
        self.cfg.setup.pixel_scale_override = None
        log.info("[autocal/%s] auto-scala OFF -> pixel scale TOML = %.3f\"/px",
                 context, self.cfg.setup.guide_pixel_scale_arcsec)
        return
    scale = self.client.get_pixel_scale()
    prev = self.cfg.setup.pixel_scale_override
    if scale is not None and scale > 0.0:
        self.cfg.setup.pixel_scale_override = scale
        log.info("[autocal/%s] pixel scale da PHD2 = %.3f\"/px (fonte: RPC)", context, scale)
        if prev is not None and abs(prev - scale) > 1e-3:
            self._invalidate_rms_baseline("cambio pixel scale rilevato")
    else:
        self.cfg.setup.pixel_scale_override = None
        log.warning("[autocal/%s] PHD2 non conosce la pixel scale (null) -> fallback TOML = %.3f\"/px",
                    context, self.cfg.setup.guide_pixel_scale_arcsec)
```

Chiamare `_apply_pixel_scale_from_phd2("init")` in `initialize()` dopo la connessione, e di nuovo al primo GuideStep
dopo l'avvio guida (`"guide_start"`) e su `GuidingResumed`/riconnessione (`"resume"`), usando gli hook eventi esistenti.

#### (ii) Calibratore baseline RMS

Stato in `__init__`:

```python
self._rms_baseline_samples: list[float] = []
self._rms_baseline_value: Optional[float] = None
self._rms_baseline_done: bool = False
```

```python
def _invalidate_rms_baseline(self, reason: str) -> None:
    self._rms_baseline_samples.clear()
    self._rms_baseline_value = None
    self._rms_baseline_done = False
    log.info("[autocal] baseline RMS invalidata (%s): ricalibrazione al prossimo periodo stabile", reason)

def _update_rms_baseline(self, snap) -> None:
    ac = self.cfg.auto_calibration
    if not ac.enabled or self._rms_baseline_done:
        return
    if (snap.snr is not None and snap.snr >= ac.baseline_min_snr
            and not snap.implosion_detected
            and snap.condition == SeeingCondition.NORMAL):   # confermare nome enum
        self._rms_baseline_samples.append(snap.rms_total)
    if len(self._rms_baseline_samples) >= ac.baseline_window_frames:
        self._finalize_rms_baseline()

def _finalize_rms_baseline(self) -> None:
    import statistics
    ac = self.cfg.auto_calibration
    baseline = statistics.median(self._rms_baseline_samples)
    self._rms_baseline_value = baseline
    new_high = max(ac.rms_high_min_arcsec, min(ac.rms_high_max_arcsec, ac.rms_high_factor * baseline))
    new_low = ac.rms_low_factor * baseline
    self.cfg.thresholds.rms_high = new_high      # config efficace in memoria
    self.cfg.thresholds.rms_low = new_low
    self.analyzer.rms_high = new_high
    self.analyzer.rms_low = new_low
    self._rms_baseline_done = True
    log.info("[autocal] baseline RMS = %.3f\" su %d frame -> rms_high=%.3f\" rms_low=%.3f\"",
             baseline, len(self._rms_baseline_samples), new_high, new_low)
```

Chiamare `_update_rms_baseline(snap)` nel loop di valutazione, **prima** della logica adattiva esistente.

**Note di sicurezza**: con `enabled=false` nessuna raccolta/modifica (comportamento identico a oggi); baseline solo in
`NORMAL` con SNR adeguato (no taratura su seeing cattivo); clamp impediscono soglie assurde; su cambio scala →
invalidazione + ricalcolo, soglie restano agli ultimi valori validi (o TOML) nel frattempo.

### 2D. `server.py` + dashboard — visibilità config efficace

`/status`, blocco `auto_calibration`:

```python
"auto_calibration": {
    "enabled": cfg.auto_calibration.enabled,
    "pixel_scale_arcsec": round(cfg.setup.guide_pixel_scale_arcsec, 3),
    "pixel_scale_source": "phd2" if cfg.setup.pixel_scale_override is not None else "toml",
    "baseline_rms_arcsec": (round(self._rms_baseline_value, 3) if self._rms_baseline_value is not None else None),
    "baseline_done": self._rms_baseline_done,
    "baseline_progress": f"{len(self._rms_baseline_samples)}/{cfg.auto_calibration.baseline_window_frames}",
    "rms_high_active": round(cfg.thresholds.rms_high, 3),
    "rms_low_active": round(cfg.thresholds.rms_low, 3),
},
```

dashboard: card "Auto-calibrazione" con pixel scale efficace + badge fonte (PHD2 / TOML fallback), progresso baseline
(es. "42/60") o valore misurato a completamento, e soglie RMS attive. Riusare il pattern card esistente (`.exposure-card`
dell'§21). Niente grafici nuovi, solo testo/badge.

### 2E. CONFIG UNICO — un solo `config.toml`

Sostituire il contenuto di `config.toml` (root) con la versione unificata seguente. Questo diventa l'**unico** file di
configurazione. I valori `[setup]` pixel scale sono solo fallback (la scala reale arriva da PHD2).

```toml
# =============================================================================
# CONFIG UNICO — PHD2 Adaptive Agent (auto-configurante)
# Pixel scale: auto da PHD2 (get_pixel_scale); valori sotto = solo fallback.
# Soglie RMS: auto da baseline misurata (vedi [auto_calibration]).
# La scelta del telescopio si fa selezionando il PROFILO in PHD2.
# =============================================================================

[setup]
profile_name                     = "auto"
guide_pixel_scale_arcsec_native  = 1.0    # fallback se PHD2 non riporta la scala
guide_pixel_scale_arcsec_reduced = 1.0    # fallback
reducer_active                   = false

[phd2]
host = "localhost"
port = 4400

[dashboard]
host = "0.0.0.0"
port = 8080

[control]
dry_run          = false
interval_seconds = 10
window_frames    = 30
cooldown_seconds = 30

[thresholds]
rms_high           = 1.20   # iniziale/fallback; sovrascritto dall'auto-calibrazione
rms_low            = 0.60   # iniziale/fallback
snr_low            = 8.0    # unificato: sopra il cuscinetto PHD2 (6.0) e il reject (3.0),
                            #            sotto la fascia sana 15-40 -> scatta solo a degrado reale
spike_ratio_high   = 0.30
consecutive_frames = 5

[emergency]
auto_recovery        = true
max_exposure_ms      = 4000   # unificato a 4s per tutti i setup
find_star_delay      = 10
saturation_timeout_s = 300

[limits.ra]
aggr_min       = 40
aggr_max       = 80
aggr_step_down = 5
aggr_step_up   = 2
minmove_min    = 0.15
minmove_max    = 0.80
minmove_step   = 0.05

[limits.dec]
aggr_min       = 35
aggr_max       = 75
aggr_step_down = 5
aggr_step_up   = 2
minmove_min    = 0.18
minmove_max    = 0.85
minmove_step   = 0.05

[logging]
csv_dir   = "logs"
log_level = "INFO"

[phd2_log]
log_dir     = ""
output_dir  = "phd2_log"
auto_import = true

[exposure_dynamic]
enabled               = true
step_factor           = 1.5
max_steps_above_base  = 2
cooldown_s            = 90
spike_min             = 0.25   # unificato (mediana dei 3 setup: 0.30/0.25/0.20)
hfd_min_arcsec        = 4.0    # unificato (mediana dei 3 setup: 4.5/4.0/4.0)
peak_to_rms_ratio_min = 3.0
nominal_for_seconds   = 60

[auto_calibration]
enabled                = true
use_phd2_pixel_scale   = true
rms_high_factor        = 1.5
rms_low_factor         = 0.75
baseline_window_frames = 60
baseline_min_snr       = 10.0
rms_high_min_arcsec    = 0.50
rms_high_max_arcsec    = 2.50
```

### 2F. Eliminazione file per-setup + `.bat` unico + `build_dist.py`

1. **Eliminare** (root e `Pacchetto_Distribuzione/`):
   `config_askar71f.toml`, `config_tecnosky115.toml`, `config_rc8.toml` e i 6 `Avvia_*.bat`
   (`Avvia_Askar71F.bat`, `Avvia_Askar71F_Ridotto.bat`, `Avvia_RC8.bat`, `Avvia_RC8_Ridotto.bat`,
   `Avvia_Tecnosky115.bat`, `Avvia_Tecnosky115_Ridotto.bat`). Mantenere `Sblocca_Firewall_8080.bat`.

2. **Creare** `Avvia.bat` (root):

```batch
@echo off
cd /d "%~dp0"
echo  ==========================================
echo   PHD2 Adaptive Agent - Config unico
echo   Pixel scale: AUTO da PHD2 (fallback TOML)
echo   Soglie RMS:  AUTO da baseline misurata
echo   MODALITA: LIVE (dry_run=false)
echo  ==========================================
echo  Seleziona il PROFILO del telescopio in PHD2 prima di avviare.
echo  Apri il browser su: http://localhost:8080
echo.
PHD2_Agent.exe --config config.toml
pause
```

3. **`build_dist.py`**: nella copia config tenere solo `config.toml`; sostituire la lista `bat_files` con
   `["Avvia.bat", "Sblocca_Firewall_8080.bat"]`. Rimuovere le copie di `config_askar71f/tecnosky115/rc8.toml` e i 6 .bat.

4. **`LEGGIMI_PER_AVVIARE.txt`**: riscrivere per il flusso a file unico (avvia PHD2, scegli il profilo, lancia
   `Avvia.bat`, apri la dashboard). Niente più tabella dei 6 .bat.

5. **`main.py`**: il default di `--config` è già `config.toml` (confermare). I flag `--with-reducer`/`--no-reducer`
   restano per retrocompatibilità ma non sono più necessari: documentarlo nell'help.

---

## TEST ATTESI

### Sanity check simulator (non-regressione)

```bash
python main.py --simulator --dry-run --config config.toml
```

Verifica:
- Nessun `ImportError`/`AttributeError`/`TypeError` all'avvio.
- Con `[auto_calibration].enabled = false` (test manuale temporaneo): soglie = valori TOML (comportamento legacy).
- `/status` ritorna il blocco `auto_calibration` ben formato.
- Baseline Guardian salva/ripristina senza interferenze.

### Test unitari (in `tests/test_auto_calibration.py`)

`unittest` + `MagicMock` per il client, snapshot fittizi.

1. Pixel scale da PHD2: `get_pixel_scale` → `1.03` → property `1.03`, source "phd2".
2. Fallback su null: `get_pixel_scale` → `None` → override `None`, property = valore TOML.
3. Fallback su feature OFF: `enabled=false` → override sempre `None`.
4. client null-safe: `call(...)` ritorna `None` o solleva → `get_pixel_scale()` ritorna `None`, nessuna eccezione.
5. Baseline happy path: N snapshot NORMAL con rms_total noti → `rms_high == clamp(1.5*mediana)`, `rms_low == 0.75*mediana`
   sia in `cfg.thresholds` sia in `analyzer`.
6. Baseline ignora frame cattivi: SNR basso / implosion / DEGRADED non campionati.
7. Clamp: baseline 5,0" → `rms_high` limitato a `rms_high_max_arcsec`.
8. Invalidazione su cambio scala: baseline done, nuova scala diversa → stato azzerato.
9. Retrocompatibilità: TOML senza `[auto_calibration]` → default (enabled false), parsing non solleva.

### Aggiornamento test esistenti

- `tests/test_setup_config.py`: aggiungere test che con `pixel_scale_override = X` la property ritorna `X`; i test
  esistenti passano invariati (override default `None`). **Nota**: i test che caricavano `config_rc8.toml` o altri TOML
  per-setup vanno reindirizzati a `config.toml` (i file per-setup non esistono più).
- `tests/test_exposure_dynamic.py`: se `_make_config()` o i test usano `config_*.toml` per-setup o costruiscono
  `AgentConfig`, aggiornare a `config.toml` / aggiungere il default `auto_calibration`. Aggiornamento solo sintattico.

---

## VALIDAZIONE SUL CAMPO

### Sequenza operativa per Alessandro

1. Avviare PHD2, **selezionare il profilo del telescopio in uso** (es. "RC8" o "Askar 71F ridotto"), far partire la guida.
2. Lanciare `Avvia.bat` (unico).
3. Aprire `http://localhost:8080`, card "Auto-calibrazione":
   - pixel scale reale con badge **PHD2** (se la focale è nel profilo);
   - progresso baseline (es. 12/60 → 60/60) durante i primi minuti di guida calma;
   - a baseline completata: `rms_high`/`rms_low` attive derivate.
4. Se il cielo parte turbolento la baseline non si completa (campiona solo `NORMAL`): atteso, non un bug.
5. Ripetere con un profilo diverso (altro telescopio / riduttore): la pixel scale e le soglie devono cambiare da sole,
   senza toccare alcun file.

### Cosa verificare nei log

In `Pacchetto_Distribuzione\logs\` cercare `[autocal]`: `pixel scale da PHD2 = ...` / `fallback TOML = ...`;
`baseline RMS = ... -> rms_high=... rms_low=...`; eventuali `baseline invalidata (...)`.

### Linee guida tuning

- Troppi DEGRADED in cielo normale → alzare `rms_high_factor` (1,5 → 1,7).
- Non reagisce mai → abbassare `rms_high_factor` (1,5 → 1,3).
- Baseline troppo alta (seeing mediocre) → alzare `baseline_min_snr` o `baseline_window_frames`.
- Card mostra "TOML" invece di "PHD2" → focale di guida non impostata nel profilo PHD2, o camera non connessa all'avvio
  (la lettura a guide_start dovrebbe poi sistemare).

---

## PROCEDURA REBUILD (obbligatoria post-modifica)

1. `python -m pytest tests/ -v` → tutti i test passano PRIMA del rebuild.
2. `python build_dist.py` (build completa; ora copia `Avvia.bat` + `Sblocca_Firewall_8080.bat`).
3. Copiare manualmente in `Pacchetto_Distribuzione/`: `config.toml` e `Sblocca_Firewall_8080.bat`
   (build_dist.py NON copia il config).
4. Verificare che in `Pacchetto_Distribuzione/` ci siano **solo** `Avvia.bat` (1 file) e `config.toml` (1 file),
   nessun residuo `config_*.toml` o `Avvia_*_*.bat`:
   ```powershell
   Get-ChildItem Pacchetto_Distribuzione\Avvia*.bat | Measure-Object | Select Count   # Atteso: 1
   Get-ChildItem Pacchetto_Distribuzione\config*.toml | Select Name                   # Atteso: solo config.toml
   ```
5. Aggiornare `LEGGIMI_PER_AVVIARE.txt` (flusso a file unico).
6. Ricreare ZIP `PHD2_Agent_Distribuzione.zip` con `[System.IO.Compression.ZipFile]::CreateFromDirectory(...)`.

---

## AGGIORNAMENTO DOCUMENTAZIONE

### `CONTESTO_PROGETTO.md`

Aggiornare la data in `## Stato attuale — aggiornato al ...` e aggiungere, prima di "Cosa NON è stato ancora fatto":

```markdown
### Auto-configurazione + config unico — IMPLEMENTATA (YYYY-MM-DD)
L'agente legge la pixel scale di guida da PHD2 (`get_pixel_scale`, fallback TOML) e deriva le soglie RMS da una
baseline misurata sul campo (config efficace in memoria, TOML mai riscritto). MinMove e aggressività restano
scale-independent. La configurazione è collassata in un solo `config.toml` + un solo `Avvia.bat`: valori unificati
(max_exposure 4000ms, snr_low 8.0, spike_min 0.25, hfd_min 4.0"); i 3 TOML per-setup e i 6 .bat sono stati eliminati.
La scelta del telescopio avviene selezionando il profilo in PHD2. Dettaglio in NOTE_CLAUDE.md §22.
```

In "Cosa NON è stato ancora fatto":
```
- Validazione LIVE dell'auto-configurazione: sessioni reali su almeno 2 profili PHD2 diversi (es. RC8 e Askar
  ridotto), verificando che pixel scale e soglie cambino da sole. Tarare poi rms_high_factor in base ai log.
```

### `NOTE_CLAUDE.md`

Verificare l'ultima sezione con `grep "^## [0-9]" NOTE_CLAUDE.md | tail -1` (atteso §21) e aggiungere in coda
`## 22. Auto-scala via RPC + soglie RMS adattive + config unico (YYYY-MM-DD)` con sottosezioni:
`### Motivazione`, `### Architettura`, `### Comportamento atteso`, `### File modificati` (inclusa l'eliminazione dei 3
TOML per-setup e dei 6 .bat, nuovo `Avvia.bat`, `build_dist.py` semplificato), `### Limiti dell'approccio` (cecità di
risoluzione e flessione differenziale su cercatore-guida; baseline misurata in seeing cattivo; scala == 1,00"/px = null),
`### Validazione raccomandata`.

### `README.md`

Aggiornare la sezione di avvio: un solo `Avvia.bat`, scelta del telescopio via profilo PHD2.

---

## CHECKLIST FINALE PRIMA DI COMMIT

- [ ] Pre-flight eseguito: letti `event_server.cpp`, `myframe.cpp` e i file Python in §0.
- [ ] `client.get_pixel_scale()` null-safe (Optional[float], nessuna eccezione su null/errore).
- [ ] `SetupConfig.pixel_scale_override` + property aggiornata (override > TOML).
- [ ] `AutoCalibrationConfig` + parsing retrocompatibile + campo in `AgentConfig`.
- [ ] `_apply_pixel_scale_from_phd2` chiamata a init, guide_start, resume/reconnect; log fonte.
- [ ] Calibratore baseline: solo frame NORMAL/SNR ok/no implosion; clamp; aggiorna `cfg.thresholds` E `analyzer`.
- [ ] Invalidazione baseline su cambio pixel scale.
- [ ] Nessuna scrittura ai file TOML a runtime.
- [ ] MinMove e range aggressività NON toccati.
- [ ] `config.toml` unico con valori unificati (max_exposure 4000, snr_low 8.0, spike_min 0.25, hfd_min 4.0,
      auto_calibration enabled true, exposure_dynamic enabled true, dry_run false).
- [ ] Eliminati `config_askar71f/tecnosky115/rc8.toml` e i 6 `Avvia_*.bat` (root + Pacchetto_Distribuzione).
- [ ] Creato `Avvia.bat` unico; `build_dist.py` aggiornato (config.toml + Avvia.bat + Sblocca_Firewall).
- [ ] `LEGGIMI_PER_AVVIARE.txt` riscritto per file unico.
- [ ] `tests/test_auto_calibration.py`: 9/9 passano; test esistenti reindirizzati a `config.toml`, nessuna regressione.
- [ ] `python build_dist.py` ok; in Pacchetto_Distribuzione un solo Avvia.bat e un solo config.toml; ZIP rigenerato.
- [ ] `CONTESTO_PROGETTO.md` + `NOTE_CLAUDE.md` §22 + `README.md` aggiornati.
- [ ] Nessuna modifica a backlash, esposizione dinamica (§19), escalation gate (§21), Baseline Guardian oltre al necessario.

---

## DOMANDE DA FARMI PRIMA DI PROCEDERE (se servono)

Se trovi: nome del campo SNR diverso da `snap.snr`; enum `SeeingCondition.NORMAL` con nome diverso; nessun hook
`GuidingResumed`/reconnect; punto del loop non chiaro dove inserire `_update_rms_baseline(snap)`; test esistenti che
dipendono dai TOML per-setup in modo non banale -> **fermati e chiedi**, non improvvisare.

Se tutto e' chiaro: procedi step-by-step, mostrami i diff prima di applicarli, poi test, rebuild e documentazione.

Grazie.
