# PROMPT PER CLAUDE CODE (Antigravity) — Refactor sezione [setup] e supporto Riduttore Focale
# Da copiare e incollare integralmente nella conversazione con Claude Code.
# Lavorare nella cartella: PHD2_Assist_PATCHED/

> **NOTA OPERATIVA**: questa è una **feature di refactor strutturale + operativa**.
> NON aggiunge logica di controllo di guida. Sposta la pixel scale di guida dalla
> sezione `[exposure_dynamic]` a una nuova sezione `[setup]` estesa che supporta
> due valori (nativo/ridotto) e un toggle `reducer_active`, attivabile via TOML
> o via flag CLI `--with-reducer` / `--no-reducer`. Questo permette ad Alessandro
> di passare al volo tra focale piena e focale ridotta usando `.bat` separati,
> senza editing manuale del TOML.
>
> La sessione precedente ha implementato l'esposizione dinamica RMS-based
> (sezione 19 di NOTE_CLAUDE.md). Quel lavoro va preservato — tu modifichi
> solo il punto di lettura della pixel scale (da `cfg.exposure_dynamic.guide_pixel_scale_arcsec`
> a `cfg.setup.guide_pixel_scale_arcsec`).

---

## 0. PRE-FLIGHT (rapido, niente sorgente PHD2 da consultare)

Questo refactor è interno al codice Python dell'agent. Non richiede di leggere
il sorgente C++ di PHD2 né la User Guide PDF. Ti basta:

1. Leggere `phd2_agent/config.py` — capire la struttura `AgentConfig`,
   `ExposureDynamicConfig` (sezione 19), e dove viene letto il campo `[setup]`
   esistente (oggi contiene solo `profile_name`).

2. Leggere `phd2_agent/controller.py` — trovare ogni occorrenza di
   `cfg.exposure_dynamic.guide_pixel_scale_arcsec` (`_evaluate_exposure_seeing`,
   `initialize`, eventuali altri punti). Ogni occorrenza dovrà essere sostituita
   con `cfg.setup.guide_pixel_scale_arcsec`.

3. Leggere `main.py` — capire come viene parsato `argparse` (probabilmente in
   testa al main, controlla `--config`, `--simulator`, `--dry-run`,
   `--monitor-only`). Aggiungerai due nuovi flag mutex.

4. Leggere uno qualsiasi dei `Avvia_*.bat` esistenti per capire il formato.

5. Verifica nei file di stato di sessione precedente:
   - `CONTESTO_PROGETTO.md` ha sezione "Esposizione dinamica RMS-based — IMPLEMENTATA"?
   - `NOTE_CLAUDE.md` ha sezione 19?
   Se sì, tu aggiungerai la **sezione 20**, non sovrascriverai la 19.

### Decisione architetturale già presa

La pixel scale di guida è una proprietà del **setup ottico** (telescopio + camera
di guida + eventuale riduttore), NON di una specifica feature. Per questo
spostiamo da `[exposure_dynamic]` a `[setup]`. Tutte le feature future che usano
la pixel scale (es. backlash diagnostic) leggeranno dallo stesso posto.

---

## 1. OBIETTIVO TECNICO

Tre obiettivi distinti:

1. **Refactor strutturale**: spostare `guide_pixel_scale_arcsec` da
   `[exposure_dynamic]` a una nuova sezione `[setup]` estesa con due valori
   (nativo + ridotto) e un toggle.

2. **Correzione valori pixel scale ridotti**: i valori nei commenti dei TOML
   attuali assumono riduttore 0.80x per tutti i setup. Il valore reale è:
   - Askar 71F: riduttore **0.75x** → 1.58 / 0.75 = **2.11"/px ridotto**
   - Tecnosky 115: riduttore **0.80x** → 1.03 / 0.80 = **1.29"/px ridotto** (corretto)
   - RC8: riduttore **0.75x** → 0.51 / 0.75 = **0.68"/px ridotto**

3. **Operatività rapida**: aggiungere flag CLI `--with-reducer` / `--no-reducer`
   che sovrascrive il valore `reducer_active` del TOML, e creare 3 `.bat`
   aggiuntivi per i setup ridotti. Così Alessandro fa doppio click su
   `Avvia_<setup>_Ridotto.bat` per usare il riduttore, senza editing TOML.

---

## 2. SPECIFICA FUNZIONALE

### 2A. Nuova dataclass `SetupConfig` in `phd2_agent/config.py`

Aggiungere accanto alle altre dataclass (es. dopo `PHD2LogConfig`):

```python
@dataclass
class SetupConfig:
    profile_name: str = ""
    guide_pixel_scale_arcsec_native:  float = 1.0
    guide_pixel_scale_arcsec_reduced: float = 1.0
    reducer_active: bool = False

    @property
    def guide_pixel_scale_arcsec(self) -> float:
        """Valore effettivo della pixel scale, in base allo stato reducer_active."""
        return (self.guide_pixel_scale_arcsec_reduced
                if self.reducer_active
                else self.guide_pixel_scale_arcsec_native)
```

Aggiornare `AgentConfig` per includere `setup: SetupConfig = field(default_factory=SetupConfig)`.

In `load_config()`, aggiungere il parsing della sezione `[setup]`:

```python
if "setup" in raw:
    s = raw["setup"]
    cfg.setup = SetupConfig(
        profile_name=str(s.get("profile_name", "")),
        guide_pixel_scale_arcsec_native=float(s.get("guide_pixel_scale_arcsec_native", 1.0)),
        guide_pixel_scale_arcsec_reduced=float(s.get("guide_pixel_scale_arcsec_reduced", 1.0)),
        reducer_active=bool(s.get("reducer_active", False)),
    )
```

**Importante**: rimuovere il campo `guide_pixel_scale_arcsec` da
`ExposureDynamicConfig` e dal relativo parsing. Quel valore ora vive solo
in `SetupConfig`. Se esiste codice che leggeva `cfg.exposure_dynamic.guide_pixel_scale_arcsec`,
va aggiornato a `cfg.setup.guide_pixel_scale_arcsec` (vedi 2C).

**Retrocompatibilità del parsing**: se un TOML legacy ha ancora
`guide_pixel_scale_arcsec` dentro `[exposure_dynamic]`, ignorarlo silenziosamente
(non rompere il caricamento). Loggare DEBUG: "campo legacy `guide_pixel_scale_arcsec`
in [exposure_dynamic] ignorato — usare [setup]".

**Aggiornamento test esistenti — OBBLIGATORIO**: il file
`tests/test_exposure_dynamic.py` (sezione 19, già esistente) crea oggetti
`ExposureDynamicConfig` con il parametro `guide_pixel_scale_arcsec=0.51`
nella funzione `_make_config()` (intorno alla riga 52-62). Dopo aver rimosso
quel campo da `ExposureDynamicConfig`, il test fallisce con
`TypeError: __init__() got an unexpected keyword argument 'guide_pixel_scale_arcsec'`.

Modifica richiesta in `tests/test_exposure_dynamic.py`:

1. Rimuovere la riga `guide_pixel_scale_arcsec=0.51,` dalla creazione di
   `ExposureDynamicConfig` in `_make_config()`.

2. Aggiungere subito sopra (o sotto) la creazione di `SetupConfig` per il
   profilo RC8 di test:
   ```python
   cfg.setup = SetupConfig(
       profile_name="rc8",
       guide_pixel_scale_arcsec_native=0.51,
       guide_pixel_scale_arcsec_reduced=0.68,
       reducer_active=False,
   )
   ```

3. Aggiungere `SetupConfig` agli import in cima al file:
   ```python
   from phd2_agent.config import (
       AgentConfig, AxisLimits, ControlConfig, EmergencyConfig,
       ExposureDynamicConfig, SetupConfig, Thresholds,
   )
   ```

Dopo queste modifiche i 5 test esistenti devono continuare a passare 5/5
senza modifiche logiche (la pixel scale 0.51 viene letta dalla nuova location
ma il valore effettivo è identico a prima).

### 2B. Modifica configurazioni TOML

#### `config.toml` (default)

Sostituire la sezione `[setup]` esistente (oggi contiene solo `profile_name`)
con la versione estesa. Rimuovere `guide_pixel_scale_arcsec` da `[exposure_dynamic]`.

```toml
[setup]
profile_name                     = "default"
guide_pixel_scale_arcsec_native  = 1.0
guide_pixel_scale_arcsec_reduced = 1.0
reducer_active                   = false

[exposure_dynamic]
# (rimosso guide_pixel_scale_arcsec — ora in [setup])
enabled                  = false
step_factor              = 1.5
max_steps_above_base     = 2
cooldown_s               = 90
spike_min                = 0.25
hfd_min_arcsec           = 4.0
peak_to_rms_ratio_min    = 3.0
nominal_for_seconds      = 60
```

#### `config_askar71f.toml`

```toml
[setup]
profile_name                     = "askar71f"
guide_pixel_scale_arcsec_native  = 1.58   # Askar 71F nativo
guide_pixel_scale_arcsec_reduced = 2.11   # con riduttore 0.75x (1.58/0.75)
reducer_active                   = false

[exposure_dynamic]
enabled                  = false
step_factor              = 1.5
max_steps_above_base     = 2
cooldown_s               = 90
spike_min                = 0.30
hfd_min_arcsec           = 4.5
peak_to_rms_ratio_min    = 3.0
nominal_for_seconds      = 60
```

Aggiornare anche il commento intestazione del file se ancora dice
`(1.97"/px ridotto)` o `(1.98"/px ridotto)` → corretto in `(2.11"/px ridotto, riduttore 0.75x)`.

#### `config_tecnosky115.toml`

```toml
[setup]
profile_name                     = "tecnosky115"
guide_pixel_scale_arcsec_native  = 1.03   # Tecnosky 115 nativo
guide_pixel_scale_arcsec_reduced = 1.29   # con riduttore 0.80x (1.03/0.80)
reducer_active                   = false

[exposure_dynamic]
enabled                  = false
step_factor              = 1.5
max_steps_above_base     = 2
cooldown_s               = 90
spike_min                = 0.25
hfd_min_arcsec           = 4.0
peak_to_rms_ratio_min    = 3.0
nominal_for_seconds      = 60
```

#### `config_rc8.toml` — IMPORTANTE: configurato per validazione LIVE

Alessandro deve vedere il comportamento dell'esposizione dinamica
**direttamente sul grafico della dashboard** (non solo nei log). Per questo
nel file `config_rc8.toml` deve essere già impostato:
- `[control] dry_run = false` (LIVE — comandi reali a PHD2)
- `[exposure_dynamic] enabled = true` (path B attivo)
- `[setup] reducer_active = false` (default focale piena, attivabile da bat)

```toml
[control]
dry_run = false       # LIVE per validazione sul grafico — non cambiare
interval_seconds = 10
window_frames = 30
cooldown_seconds = 30

[setup]
profile_name                     = "rc8"
guide_pixel_scale_arcsec_native  = 0.51   # RC8 nativo
guide_pixel_scale_arcsec_reduced = 0.68   # con riduttore 0.75x (0.51/0.75)
reducer_active                   = false

[exposure_dynamic]
enabled                  = true   # ATTIVA per validazione LIVE
step_factor              = 1.5
max_steps_above_base     = 2
cooldown_s               = 90
spike_min                = 0.20
hfd_min_arcsec           = 4.0
peak_to_rms_ratio_min    = 3.0
nominal_for_seconds      = 60
```

**Spiegazione razionale (da includere come commento sopra `dry_run`)**:

```toml
# CONFIGURAZIONE DI VALIDAZIONE LIVE
# Questo config è tarato per la prima sessione di test dell'esposizione
# dinamica RMS-based su RC8 + CEM70G. Alessandro vuole osservare il
# comportamento del loop di guida sulla dashboard al momento dei trigger,
# non solo dopo nei log. Quindi:
#   - dry_run = false → comandi reali a PHD2
#   - exposure_dynamic.enabled = true → path B attivo
# La sicurezza è data dall'escalation gate (path B non scatta finché
# aggressiveness/MinMove non hanno saturato i loro limiti) e dal
# max_steps_above_base = 2 (max ~2.25× base).
```

### 2C. Aggiornamento `phd2_agent/controller.py`

Trovare ogni occorrenza di `self.cfg.exposure_dynamic.guide_pixel_scale_arcsec`
e sostituirla con `self.cfg.setup.guide_pixel_scale_arcsec`.

Punto noto da cui partire: `_evaluate_exposure_seeing()` — la condizione
`snapshot.hfd_avg * ed.guide_pixel_scale_arcsec >= ed.hfd_min_arcsec`
diventa `snapshot.hfd_avg * self.cfg.setup.guide_pixel_scale_arcsec >= ed.hfd_min_arcsec`.

Eventuali log che mostrano la pixel scale (es. nel `reason` di una ControlAction)
devono leggere dallo stesso posto.

In `initialize()`, dopo aver letto `_valid_exposures`, aggiungere un log INFO
una volta sola che mostri la pixel scale effettiva e lo stato reducer:

```python
logger.info(
    "Setup: profile=%s, guide_pixel_scale=%.2f arcsec/px (reducer_active=%s, "
    "native=%.2f, reduced=%.2f)",
    self.cfg.setup.profile_name,
    self.cfg.setup.guide_pixel_scale_arcsec,
    self.cfg.setup.reducer_active,
    self.cfg.setup.guide_pixel_scale_arcsec_native,
    self.cfg.setup.guide_pixel_scale_arcsec_reduced,
)
```

### 2D. Aggiornamento `main.py` — flag CLI mutex

Dove viene definito `argparse` (probabilmente in cima al `main()`), aggiungere:

```python
reducer_group = parser.add_mutually_exclusive_group()
reducer_group.add_argument(
    "--with-reducer",
    action="store_true",
    help="Attiva il riduttore di focale (sovrascrive setup.reducer_active=true)",
)
reducer_group.add_argument(
    "--no-reducer",
    action="store_true",
    help="Disattiva il riduttore di focale (sovrascrive setup.reducer_active=false)",
)
```

Subito dopo `cfg = load_config(args.config)` (e dopo eventuali altri override
CLI come `--dry-run`), aggiungere:

```python
if args.with_reducer:
    cfg.setup.reducer_active = True
    logger.info("CLI override: --with-reducer → reducer_active=True")
elif args.no_reducer:
    cfg.setup.reducer_active = False
    logger.info("CLI override: --no-reducer → reducer_active=False")
# altrimenti: si usa il valore da TOML (nessun override)
```

### 2E. Tre nuovi `.bat` per setup ridotti

Creare in `Pacchetto_Distribuzione/`:

#### `Avvia_Askar71F_Ridotto.bat`
```batch
@echo off
cd /d "%~dp0"
echo === Askar 71F + Riduttore 0.75x ===
echo Pixel scale guida effettiva: 2.11 "/px
echo.
PHD2_Agent.exe --config config_askar71f.toml --with-reducer
pause
```

#### `Avvia_Tecnosky115_Ridotto.bat`
```batch
@echo off
cd /d "%~dp0"
echo === Tecnosky 115 + Riduttore 0.80x ===
echo Pixel scale guida effettiva: 1.29 "/px
echo.
PHD2_Agent.exe --config config_tecnosky115.toml --with-reducer
pause
```

#### `Avvia_RC8_Ridotto.bat`
```batch
@echo off
cd /d "%~dp0"
echo === RC8 + Riduttore 0.75x ===
echo Pixel scale guida effettiva: 0.68 "/px
echo MODALITÀ: LIVE (dry_run=false, exposure_dynamic.enabled=true)
echo.
PHD2_Agent.exe --config config_rc8.toml --with-reducer
pause
```

I 3 `.bat` esistenti (`Avvia_Askar71F.bat`, `Avvia_Tecnosky115.bat`, `Avvia_RC8.bat`)
restano invariati — usano la focale nativa (default del TOML, `reducer_active=false`).

Per coerenza, aggiornare il messaggio echo del solo `Avvia_RC8.bat` (focale piena)
per riflettere lo stato LIVE:

```batch
@echo off
cd /d "%~dp0"
echo === RC8 + Focale Piena ===
echo Pixel scale guida effettiva: 0.51 "/px
echo MODALITÀ: LIVE (dry_run=false, exposure_dynamic.enabled=true)
echo.
PHD2_Agent.exe --config config_rc8.toml
pause
```

Gli echo degli altri due `.bat` "nativi" (Askar, Tecnosky) restano com'erano —
quei setup mantengono `dry_run=true` o `false` come già configurato, e
`exposure_dynamic.enabled=false`.

---

## 3. MODALITÀ VALIDAZIONE LIVE (richiesta esplicita di Alessandro)

Alessandro ha richiesto esplicitamente che la validazione della feature
**esposizione dinamica RMS-based** avvenga in **modalità LIVE** (non DRY_RUN),
perché vuole osservare l'effetto sul grafico della dashboard al momento dei
trigger UP/DOWN, non solo a posteriori nei log `decisions_*.jsonl`.

Per questo:

- `config_rc8.toml` è configurato con `dry_run = false` e `enabled = true`
  già di default. **Tu non devi cambiare questi valori.** Sono intenzionali.
- I `.bat` `Avvia_RC8.bat` e `Avvia_RC8_Ridotto.bat` lanciano direttamente
  in LIVE.
- I log `decisions_*.jsonl` continuano a essere prodotti normalmente in
  LIVE (servono per il tuning successivo).

La sicurezza è garantita da tre meccanismi indipendenti:

1. **Escalation gate**: il path B (esposizione RMS-based) non scatta finché
   aggressiveness e MinMove di almeno un asse non hanno saturato i limiti
   per ≥ 1 cooldown completo.
2. **`max_steps_above_base = 2`**: massimo ~2.25× base con `step_factor = 1.5`,
   poi cap su `[emergency].max_exposure_ms = 6000`.
3. **Baseline Guardian v3**: ripristina esposizione base su Ctrl+C o crash.

Per gli **altri due setup** (Askar 71F, Tecnosky 115): conservare i valori
attuali di `dry_run` (probabilmente `true`) e `[exposure_dynamic].enabled = false`.
Alessandro non vuole testarli ora — la validazione primaria è solo su RC8.

---

## 4. TEST UNITARI

Aggiungere `tests/test_setup_config.py` con 3 casi:

```python
"""
test_setup_config.py — Test unitari per la sezione [setup] e il toggle
reducer_active (incluso override via CLI flag --with-reducer / --no-reducer).
"""
import unittest
from phd2_agent.config import SetupConfig

class TestSetupConfig(unittest.TestCase):

    def test_pixel_scale_native(self):
        """reducer_active=False → ritorna il valore native"""
        s = SetupConfig(
            profile_name="rc8",
            guide_pixel_scale_arcsec_native=0.51,
            guide_pixel_scale_arcsec_reduced=0.68,
            reducer_active=False,
        )
        self.assertAlmostEqual(s.guide_pixel_scale_arcsec, 0.51)

    def test_pixel_scale_reduced(self):
        """reducer_active=True → ritorna il valore reduced"""
        s = SetupConfig(
            profile_name="rc8",
            guide_pixel_scale_arcsec_native=0.51,
            guide_pixel_scale_arcsec_reduced=0.68,
            reducer_active=True,
        )
        self.assertAlmostEqual(s.guide_pixel_scale_arcsec, 0.68)

    def test_default_values_safe(self):
        """SetupConfig() di default non deve causare divisioni per zero"""
        s = SetupConfig()
        self.assertGreater(s.guide_pixel_scale_arcsec, 0.0)
        self.assertEqual(s.reducer_active, False)

if __name__ == "__main__":
    unittest.main()
```

Eseguire: `python -m pytest tests/test_setup_config.py -v`. Devono passare 3/3.

Eseguire anche i test esistenti per verificare zero regressioni:
`python -m pytest tests/ -v`. Devono passare anche i 5 test di
`test_exposure_dynamic.py` (sezione 19).

---

## 5. PROCEDURA REBUILD (obbligatoria)

1. `python build_dist.py`
2. Copiare in `Pacchetto_Distribuzione/`:
   - `config.toml`, `config_rc8.toml`, `config_tecnosky115.toml`, `config_askar71f.toml`
   - `Avvia_Askar71F.bat`, `Avvia_Tecnosky115.bat`, `Avvia_RC8.bat`
   - **Nuovi**: `Avvia_Askar71F_Ridotto.bat`, `Avvia_Tecnosky115_Ridotto.bat`, `Avvia_RC8_Ridotto.bat`
   - `Sblocca_Firewall_8080.bat`
3. Ripristinare `LEGGIMI_PER_AVVIARE.txt` (build_dist.py lo sovrascrive).
   Aggiornare il contenuto del LEGGIMI per spiegare i 6 `.bat` invece di 3:
   ```
   Avvia_Askar71F.bat            (490mm focale piena)
   Avvia_Askar71F_Ridotto.bat    (392mm con riduttore 0.75x)
   Avvia_Tecnosky115.bat         (800mm focale piena)
   Avvia_Tecnosky115_Ridotto.bat (640mm con riduttore 0.80x)
   Avvia_RC8.bat                 (1624mm focale piena, LIVE)
   Avvia_RC8_Ridotto.bat         (1218mm con riduttore 0.75x, LIVE)
   ```
4. Ricreare ZIP `PHD2_Agent_Distribuzione.zip` con `[System.IO.Compression.ZipFile]::CreateFromDirectory(...)`.

---

## 6. AGGIORNAMENTO DOCUMENTAZIONE

### `CONTESTO_PROGETTO.md`

Aggiornare la data della sezione `## Stato attuale`. Aggiungere un nuovo paragrafo
**dopo** la sezione "Esposizione dinamica RMS-based — IMPLEMENTATA":

```markdown
### Refactor [setup] e supporto Riduttore Focale — IMPLEMENTATO (YYYY-MM-DD)
Spostata `guide_pixel_scale_arcsec` da `[exposure_dynamic]` a una nuova sezione
`[setup]` estesa con campi `_native`, `_reduced` e flag `reducer_active`.
La pixel scale effettiva è esposta come property calcolata `cfg.setup.guide_pixel_scale_arcsec`,
letta da tutte le feature future (oggi dall'esposizione dinamica path B,
domani da eventuale backlash diagnostic).

Corretti i valori di pixel scale ridotta per i tre setup:
- Askar 71F: 1.58"/px nativo, 2.11"/px ridotto (riduttore 0.75x)
- Tecnosky 115: 1.03"/px nativo, 1.29"/px ridotto (riduttore 0.80x)
- RC8: 0.51"/px nativo, 0.68"/px ridotto (riduttore 0.75x)

Aggiunti flag CLI `--with-reducer` e `--no-reducer` in `main.py` come override
del valore TOML. Creati 3 nuovi `.bat` (`Avvia_<setup>_Ridotto.bat`) per
attivare la modalità riduttore con doppio click, senza editing del TOML.

`config_rc8.toml` configurato per validazione LIVE: `dry_run = false`,
`[exposure_dynamic].enabled = true`. Su RC8 il setup primario di test:
i `.bat` lanciano direttamente in modalità operativa per permettere
osservazione del grafico dashboard al momento dei trigger.

Vedere NOTE_CLAUDE.md sezione 20 per dettaglio completo.
```

In `## Cosa NON è stato ancora fatto`:
- Rimuovere o spostare la voce sulla validazione DRY_RUN (oggi è LIVE)
- Aggiornare a:
  ```
  - Validazione LIVE dell'esposizione dinamica RMS-based su RC8 + CEM70G:
    almeno 2 sessioni reali con osservazione del grafico dashboard al momento
    dei trigger UP/DOWN. Tarare poi spike_min, hfd_min_arcsec, cooldown_s
    in base alla frequenza dei trigger osservata nei decisions_*.jsonl.
  ```

### `NOTE_CLAUDE.md`

Aggiungere in coda **sezione 20** (dopo la 19 esistente sull'esposizione dinamica):

```markdown
---

## 20. Refactor [setup] e supporto Riduttore Focale (YYYY-MM-DD)

### Motivazione
La sezione 19 aveva messo `guide_pixel_scale_arcsec` dentro `[exposure_dynamic]`.
Discussione con Alessandro ha evidenziato due problemi:
1. La pixel scale di guida è una proprietà del **setup ottico**
   (telescopio + camera + riduttore), non di una specifica feature.
   Future feature (es. backlash diagnostic) avrebbero duplicato il campo.
2. Alessandro usa due configurazioni alternate per ciascun OTA: focale
   piena e focale ridotta (riduttore 0.80x per Tecnosky, 0.75x per Askar 71F
   e RC8). Editare manualmente il TOML ad ogni cambio è error-prone.

### Soluzione architetturale
Spostata `guide_pixel_scale_arcsec` in una nuova sezione `[setup]` estesa:

```toml
[setup]
profile_name                     = "rc8"
guide_pixel_scale_arcsec_native  = 0.51
guide_pixel_scale_arcsec_reduced = 0.68
reducer_active                   = false
```

`SetupConfig` espone una property calcolata `guide_pixel_scale_arcsec`
che ritorna `_native` o `_reduced` in base a `reducer_active`. Tutte le
feature leggono dalla property, sempre coerente.

### Operatività CLI
Aggiunti flag mutualmente esclusivi in `main.py`:
- `--with-reducer` → forza `reducer_active = true` (override TOML)
- `--no-reducer`   → forza `reducer_active = false` (override TOML)
- nessun flag → usa il valore del TOML

Creati 3 `.bat` aggiuntivi che lanciano lo stesso config con `--with-reducer`:
- `Avvia_Askar71F_Ridotto.bat`
- `Avvia_Tecnosky115_Ridotto.bat`
- `Avvia_RC8_Ridotto.bat`

I `.bat` originali (focale piena) restano invariati. Doppio click sul `.bat`
giusto = setup corretto, niente editing manuale.

### Valori pixel scale corretti
Errore preesistente: i commenti nei TOML originali assumevano riduttore 0.80x
per tutti i setup. Verità verificata:

| Setup | Riduttore | Native | Reduced reale |
|---|---|---|---|
| Askar 71F | 0.75x | 1.58"/px | 2.11"/px (era erroneamente 1.97 o 1.98) |
| Tecnosky 115 | 0.80x | 1.03"/px | 1.29"/px (corretto) |
| RC8 | 0.75x | 0.51"/px | 0.68"/px (era erroneamente 0.64) |

### Validazione LIVE su RC8
`config_rc8.toml` impostato con:
- `[control] dry_run = false`
- `[exposure_dynamic] enabled = true`

Motivazione: Alessandro vuole osservare il comportamento dell'esposizione
dinamica RMS-based **sul grafico della dashboard** al momento dei trigger,
non solo nei log a posteriori. La sicurezza è garantita da escalation gate
+ max_steps_above_base + Baseline Guardian v3.

Gli altri due setup (Askar 71F, Tecnosky 115) restano in DRY_RUN /
`exposure_dynamic.enabled=false` per ora. Validazione su quei setup
(se desiderata in futuro) richiederà flip manuale dei flag.

### File modificati
- `phd2_agent/config.py`: dataclass `SetupConfig` con property
  calcolata; rimosso campo `guide_pixel_scale_arcsec` da `ExposureDynamicConfig`
  (con retrocompatibilità nel parsing — campo legacy ignorato silenziosamente)
- `phd2_agent/controller.py`: ogni `cfg.exposure_dynamic.guide_pixel_scale_arcsec`
  → `cfg.setup.guide_pixel_scale_arcsec`; log INFO setup all'`initialize()`
- `main.py`: flag CLI `--with-reducer` / `--no-reducer` con override
- `config.toml`, `config_askar71f.toml`, `config_tecnosky115.toml`, `config_rc8.toml`:
  sezione `[setup]` estesa, rimozione `guide_pixel_scale_arcsec` da `[exposure_dynamic]`
- `Pacchetto_Distribuzione/` stessi config + 3 `.bat` ridotti nuovi
- `LEGGIMI_PER_AVVIARE.txt`: aggiornato per 6 .bat invece di 3
- `tests/test_setup_config.py`: 3 test (native, reduced, defaults)
```

### `README.md` (se presente)

Se nel README c'è una tabella dei setup, aggiungere riga "Riduttore"
con valori 0.75x / 0.80x / 0.75x. Altrimenti non toccare.

---

## 7. CHECKLIST FINALE PRIMA DI COMMIT

- [ ] `SetupConfig` dataclass creata con property calcolata `guide_pixel_scale_arcsec`
- [ ] `AgentConfig` ha `setup: SetupConfig` come field
- [ ] `load_config()` parsa la sezione `[setup]` con tutti e 4 i campi
- [ ] Campo `guide_pixel_scale_arcsec` rimosso da `ExposureDynamicConfig`
- [ ] Parsing `[exposure_dynamic]` ignora silenziosamente `guide_pixel_scale_arcsec` legacy (retrocompatibile)
- [ ] `controller.py`: ogni occorrenza `cfg.exposure_dynamic.guide_pixel_scale_arcsec` → `cfg.setup.guide_pixel_scale_arcsec`
- [ ] Log INFO setup in `initialize()`
- [ ] `main.py`: flag CLI mutex `--with-reducer` / `--no-reducer` con override
- [ ] Valori pixel scale ridotti **corretti** (2.11 / 1.29 / 0.68) nei TOML
- [ ] `config_rc8.toml`: `dry_run = false`, `[exposure_dynamic].enabled = true`, commento esplicativo
- [ ] Altri config: `dry_run` e `enabled` invariati rispetto a prima del refactor
- [ ] 3 nuovi `.bat` `Avvia_<setup>_Ridotto.bat` creati con echo informativo
- [ ] `Avvia_RC8.bat` (focale piena) aggiornato con echo "MODALITÀ: LIVE"
- [ ] `tests/test_setup_config.py`: 3/3 test passano
- [ ] `tests/test_exposure_dynamic.py`: 5/5 test passano (zero regressioni)
- [ ] `python build_dist.py` completato senza errori
- [ ] Tutti gli 8 file (4 TOML root + 4 Pacchetto_Distribuzione) aggiornati
- [ ] 6 `.bat` (3 nativi + 3 ridotti) presenti in `Pacchetto_Distribuzione/`
- [ ] `LEGGIMI_PER_AVVIARE.txt` aggiornato con tabella 6 .bat
- [ ] ZIP rigenerato
- [ ] `CONTESTO_PROGETTO.md` aggiornato (data + paragrafo refactor + voce "non fatto")
- [ ] `NOTE_CLAUDE.md` ha sezione 20 completa
- [ ] La sezione 19 (esposizione dinamica) non è stata toccata

---

## 8. DOMANDE DA FARMI PRIMA DI PROCEDERE (se servono)

Se durante l'implementazione trovi:
- Occorrenze di `guide_pixel_scale_arcsec` in altri file oltre `controller.py`
  (es. dashboard, logger, ecc.) — riportami dove e chiediamo se vanno aggiornate
- Conflitti con altri flag CLI esistenti in `main.py`
- Sezione `[setup]` già esistente con campi diversi da `profile_name` (potrebbe
  esserci un campo legacy da preservare)

→ **Fermati e chiedi**, non improvvisare.

Se invece tutto è chiaro: procedi step-by-step, mostrami i diff prima di
applicarli (preferisco vederli), poi esegui i test e il rebuild, infine
aggiorna la documentazione.

Grazie.
