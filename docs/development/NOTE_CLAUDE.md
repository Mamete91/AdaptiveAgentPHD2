# Note sessione Claude Code — PHD2 Adaptive Agent v1.1
# Data: 2026-04-28 / aggiornato 2026-04-29
# Autore note: Claude Code (Anthropic) — sessione interattiva con Alessandro

Questo file documenta tutto ciò che è stato fatto nella sessione di lavoro
con Claude Code, in modo che un agente AI esterno possa riprendere da qui
senza perdere contesto.

---

## 1. Punto di partenza

Il progetto era già stato preparato in una conversazione precedente su
claude.ai (chat web). Quella conversazione aveva prodotto il pacchetto
PHD2_Assist_PATCHED con tutte le patch v1.1 già applicate ai file Python.
Ciò che mancava era l'esecuzione dei passi di installazione e compilazione
sul PC Windows di Alessandro.

---

## 2. Tutto ciò che è stato fatto in questa sessione

### 2a. Installazione ambiente

- **Python 3.12.10** installato tramite `winget install Python.Python.3.12`
- **Dipendenze pip** installate con `pip install -r requirements.txt`:
  - fastapi 0.136.1
  - uvicorn 0.46.0
  - numpy 2.4.4
  - scipy 1.17.1
  - websockets 16.0, pydantic 2.13.3, starlette 1.0.0 e dipendenze varie
  - (tomli non installato: Python 3.12 ha tomllib in stdlib)
- **PyInstaller 6.20.0** installato con `pip install pyinstaller`

### 2b. Fix a build_dist.py (modifica minore, non alla logica)

`build_dist.py` usava argomenti pyinstaller inline che NON includevano
scipy tra gli hidden imports. Questo avrebbe causato un ModuleNotFoundError
a runtime nel .exe.

**Modifica applicata** (riga ~25 di build_dist.py):

PRIMA:
```python
run_cmd([
    "pyinstaller", "--noconfirm", "--onedir", "--name", "PHD2_Agent",
    "--hidden-import", "tomli",
    "--hidden-import", "uvicorn",
    "--hidden-import", "fastapi",
    "main.py"
])
```

DOPO:
```python
run_cmd(["pyinstaller", "--noconfirm", "PHD2_Agent.spec"])
```

Motivazione: PHD2_Agent.spec era già stato preparato con tutti gli hidden
imports corretti (scipy, scipy.ndimage, scipy.ndimage._filters, ecc.).
Usare il .spec è più robusto e coerente con la guida di compilazione.

### 2c. Build completata

Eseguito: `python build_dist.py`
Risultato:

```
Pacchetto_Distribuzione/
├── PHD2_Agent.exe              (11.5 MB + _internal/ ~100 MB dipendenze)
├── Diagnostica_Connessione.exe (48.4 MB, onefile)
├── config.toml                 (config default)
├── config_rc8.toml             (copiato manualmente)
├── config_tecnosky115.toml     (copiato manualmente)
├── config_askar71f.toml        (copiato manualmente)
├── dashboard/
├── phd2_log/
└── LEGGIMI_PER_AVVIARE.txt

PHD2_Agent_Distribuzione.zip    (100.9 MB) ← file finale da distribuire
```

### 2d. Test simulatore (Step 2 della guida)

Eseguiti 2 run sequenziali di `python main.py --simulator --dry-run`:

**Run 1 (25 secondi):**
- Nessun ModuleNotFoundError ✅
- Simulatore PHD2 partito su localhost:4400 ✅
- Dashboard avviata su localhost:8080 ✅
- Controller inizializzato, parametri letti (RA aggr=70, minmove=0.15) ✅
- Baseline salvata: `Baseline salvata in baseline.json (setup=default)` ✅
- Decisioni DRY_RUN emesse:
  `[TEST] RA Aggressiveness: 70.0 -> 72.0 — guida stabile, aumento graduale` ✅
- Kill forzato → baseline.json rimane su disco (orfana)

**Run 2 (12 secondi, verifica orphan recovery):**
- `Trovata baseline.json orfana — sessione precedente non chiusa correttamente` ✅
- `Ripristino baseline (origine=orphan_recovery, eta=0.0h, setup=default)` ✅
- `[DRY_RUN] Skipping actual baseline restore` (corretto: in dry-run non
  invia comandi a PHD2, ma la logica di detect+restore è confermata) ✅

---

## 3. Quirk noto — double initialize() (NON è un bug da correggere)

Nei log si vede `initialize()` chiamato due volte in rapida successione
all'avvio. Succede perché main.py chiama `controller.initialize()` sia
quando trova lo stato PHD2 già "Guiding" alla connessione, sia quando
riceve l'evento `StartGuiding` (che il simulatore invia subito).

La seconda call trova `baseline.json` della prima e la tratta da orfana.

- **In DRY_RUN**: completamente inoffensivo.
- **In LIVE**: manda due `set_algo_param` ridondanti con gli stessi valori
  (nessun cambio a PHD2). Nessun danno pratico.

Questo comportamento è **pre-esistente alla v1.1**, non introdotto dalle
patch. Non modificare senza discutere con Alessandro.

---

## 4. Cosa NON è ancora stato testato/fatto

### Da fare la prima sessione in campo (verifica manuale con Ctrl+C):
Avviare `PHD2_Agent.exe --config config_askar71f.toml`, aspettare qualche
minuto, premere Ctrl+C e verificare che nei log finali compaiano:
```
Shutdown controller - restore baseline...
Baseline file rimosso (shutdown pulito)
```
Queste righe confermano lo shutdown graceful del Baseline Guardian.

### Test kill brutale (una volta, in LIVE):
1. Avviare in LIVE (dopo aver validato in DRY_RUN)
2. Aspettare che il controller faccia almeno 1-2 modifiche di parametri
3. Uccidere il processo da Task Manager (Termina processo)
4. Riavviare — verificare nel log:
   `Trovata baseline.json orfana — sessione precedente non chiusa correttamente`
   `Ripristino baseline (...)`
   `Baseline ripristinata con successo`
5. La riga "Baseline ripristinata con successo" appare solo in LIVE (non DRY_RUN)

### Test Saturation Timer (una volta, accelerato):
1. Impostare temporaneamente `saturation_timeout_s = 30` nel config usato
2. Avviare in DRY_RUN
3. Aspettare 30 secondi con AI Star Finder attivo su stella satura
4. Verificare: `Stella satura tracciata da 30s ... forzo re-scan find_star standard`
5. Rimettere `saturation_timeout_s = 300`

### Sessioni DRY_RUN reali (prima di passare a LIVE):
- Sessione 1-2: Askar 71F (focale corta, più tollerante)
- Sessione 3-4: Tecnosky 115
- Sessione 5+: RC8 (lunga focale, più critico)
Analizzare `logs/decisions_*.jsonl` per verificare che le decisioni siano
ragionevoli prima di attivare LIVE.

### Taratura soglie dopo prime sessioni:
Dal file `logs/session_*.summary.json`:
- `rms_low  = 0.7 × mean_rms_total_arcsec`
- `rms_high = 1.5 × mean_rms_total_arcsec`

### Passaggio a LIVE (Askar 71F per primo):
1. `config_askar71f.toml`: `dry_run = false`
2. Abbassare i passi: `aggr_step_down = 2`, `aggr_step_up = 1` (poi tornare a 5/3)
3. Monitorare dashboard: mostra `[LIVE]` invece di `[TEST]`
4. Solo dopo Askar validato → Tecnosky → RC8

---

## 5. Come avviare il pacchetto compilato

```powershell
cd Pacchetto_Distribuzione

# Setup Askar 71F (consigliato per iniziare)
.\PHD2_Agent.exe --config config_askar71f.toml

# Setup Tecnosky 115
.\PHD2_Agent.exe --config config_tecnosky115.toml

# Setup RC8
.\PHD2_Agent.exe --config config_rc8.toml

# Solo monitoraggio (zero controllo, ultra-sicuro)
.\PHD2_Agent.exe --config config_askar71f.toml --monitor-only
```

Dashboard: http://localhost:8080

---

## 6. Regole di sicurezza (da rispettare sempre)

- `dry_run = true` in tutti i config finché non hai validato i log DRY_RUN
- NON modificare la logica del codice senza discutere con Alessandro
- NON toccare la backlash compensation di PHD2 (hardcoded fuori dai limiti)
- NON passare a LIVE su RC8 senza aver prima validato Askar 71F e Tecnosky
- NON distribuire una build senza aver passato il test simulatore

---

## 7. Struttura file modificati in questa sessione

```
build_dist.py            ← modificato: usa PHD2_Agent.spec invece di argomenti inline
phd2_agent/controller.py ← fix bug _AGGR_ALIASES (vedi sezione 8)
CONTESTO_PROGETTO.md     ← aggiornato con stato attuale al 2026-04-28
NOTE_CLAUDE.md           ← questo file
```

---

## 8. Bug fix da sorgente PHD2 — _AGGR_ALIASES (2026-04-29)

### Contesto

Alessandro ha aggiunto nella cartella del progetto `phd2-master/` contenente
il codice sorgente C++ ufficiale di PHD2 (OpenPHDGuiding). Questo ha permesso
di verificare i nomi esatti dei parametri esposti via JSON-RPC da ogni
algoritmo di guida, confrontandoli con gli alias usati nel controller Python.

### Nomi parametri ufficiali (da guide_algorithm_*.cpp)

| Algoritmo      | Parametri esposti via JSON-RPC                              |
|----------------|-------------------------------------------------------------|
| Hysteresis     | `aggression`, `hysteresis`, `minMove`                       |
| Lowpass2       | `aggressiveness`, `minMove`                                 |
| Resist Switch  | `aggression`, `fastSwitch`, `minMove`                       |
| Lowpass        | `slopeWeight`, `minMove`                                    |
| ZFilter        | `expFactor`, `minMove`                                      |
| Gaussian Proc. | `predictiveWeight`, `reactiveWeight`, `periodLength`, `minMove` |

### Bug trovato

`_AGGR_ALIASES` in `controller.py` era definito come `set` Python (non
ordinato). Per l'algoritmo **Hysteresis**, PHD2 restituisce sia `"hysteresis"`
che `"aggression"` come nomi parametro. Entrambi erano presenti nel set.
Poiché i set non hanno ordine garantito (dipende da PYTHONHASHSEED), il
controller poteva selezionare casualmente `"hysteresis"` (range 0.0–1.0)
come parametro da regolare al posto di `"aggression"` (range 0–100).
In LIVE mode questo avrebbe inviato valori completamente fuori scala a PHD2.

### Fix applicato (controller.py righe 94-113)

Convertiti `_AGGR_ALIASES` e `_MINMOVE_ALIASES` da `set` a `tuple` ordinata:

```python
# PRIMA (set, ordine casuale — BUG)
_AGGR_ALIASES = {
    "Aggressiveness", "aggressiveness",
    "Hysteresis",     "hysteresis",   # ← poteva matchare prima di "aggression"!
    "PPEC_Aggressiveness", "Aggression", "aggression",
}

# DOPO (tuple, priorità garantita — FIX)
_AGGR_ALIASES = (
    "aggression",           # Hysteresis, Resist Switch (da sorgente PHD2)
    "aggressiveness",       # Lowpass2 (da sorgente PHD2)
    "Aggressiveness",       # variante legacy
    "Aggression",           # variante legacy
    "PPEC_Aggressiveness",  # Predictive PEC
    # "hysteresis" RIMOSSO: è un parametro distinto (range 0-1), non aggressività
)

_MINMOVE_ALIASES = (
    "minMove",      # nome ufficiale in tutti gli algoritmi PHD2
    "MinMove",      # variante legacy
    "min_move", "Min Move", "Minimum Move",
)
```

### Rebuild eseguita

Dopo il fix è stato rieseguito `python build_dist.py`.
Il pacchetto `Pacchetto_Distribuzione/` e `PHD2_Agent_Distribuzione.zip`
sono stati aggiornati (timestamp 2026-04-29 00:37).

---

## 9. Procedura operativa prima notte in campo

Workflow validato per il Minix100 in osservatorio:

1. Copia `Pacchetto_Distribuzione/` sul Minix100
2. Avvia PHD2, carica profilo hardware
3. `Strumenti → Abilita Server` in PHD2 (OBBLIGATORIO)
4. Avvia la guida normalmente in PHD2
5. Apri PowerShell nella cartella e lancia:
   ```powershell
   .\PHD2_Agent.exe --config config_askar71f.toml
   ```
   (Askar 71F per la prima notte — scala più tollerante)
6. Apri browser su `http://localhost:8080`
7. Osserva dashboard: grafico RMS, stato controller, decisioni `[TEST]`
8. A fine sessione: `Ctrl+C` → verifica righe Baseline Guardian nei log finali

### Cosa vedere nella dashboard
- Badge **DRY_RUN** in alto = nessun comando inviato a PHD2
- Decisioni `[TEST]` = cosa l'agente FAREBBE (solo log, non eseguito)
- Stato: `NORMAL` / `DEGRADED` / `CRITICAL` / `RECOVERING`

### Analisi log il giorno dopo
In `Pacchetto_Distribuzione\logs\`:
- `session_*.summary.json` → leggi `mean_rms_total_arcsec`
- Usa quel valore per calibrare le soglie del config:
  - `rms_low  = 0.7 × mean_rms`
  - `rms_high = 1.5 × mean_rms`

### Passaggio a LIVE (non la prima notte)
Solo dopo 2-3 sessioni DRY_RUN con decisioni ragionevoli:
```toml
# config_askar71f.toml
dry_run = false   # cambia solo questa riga
```
Ordine: Askar 71F → Tecnosky 115 → RC8 (mai saltare).

---

## 10. Stato finale pacchetto al 2026-04-29

- `PHD2_Agent_Distribuzione.zip` (100.9 MB) — pronto per uso in campo
- Tutti i config hanno `dry_run = true`
- Bug `_AGGR_ALIASES` risolto, verificato su sorgente PHD2
- Test simulatore superato (orphan recovery confermato)
- Graceful shutdown (Ctrl+C) da verificare la prima notte in campo

---

## 11. Modifiche sessione 2026-04-30 (Claude Code)

### 11a. Sezione [phd2_log] nei config e in config.py

I tre file `config_rc8.toml`, `config_tecnosky115.toml`, `config_askar71f.toml`
non avevano la sezione `[phd2_log]` presente in `config.toml` default.
Aggiunta a tutti e tre (sia in `Pacchetto_Distribuzione/` che nella root del progetto):

```toml
[phd2_log]
log_dir     = ""        # cartella log PHD2 (vuoto = scoperta automatica)
output_dir  = "phd2_log"
auto_import = true
```

`phd2_agent/config.py` non parsava questa sezione (silently ignored).
Aggiunto `PHD2LogConfig` dataclass e relativo parsing in `load_config()`.

### 11b. Fix double initialize() — main.py

Il simulatore PHD2 invia sia `AppState:Guiding` che `StartGuiding` alla
connessione, causando due chiamate a `controller.initialize()` in rapida
successione. La seconda trovava la baseline della prima e la trattava da orfana.

Fix applicato:
- `controller.py`: aggiunto metodo `mark_uninitialized()`
- `main.py` handler `StartGuiding`: `if not controller.is_initialized(): controller.initialize()`
- `main.py` handler `GuidingStopped`: aggiunto `controller.mark_uninitialized()`

### 11c. Aggiornamenti documentazione

- `README.md`: corretto `rms_low 0.35 → 0.45`, `aggr_max 90 → 80`,
  oscillazione `RA → RA e DEC`, sezione avvio con tabella 3 setup + .bat
- `config.toml`: rimosso riferimento a "C9.25", sostituito con testo generico

### 11d. Avvio rapido con file .bat

Creati tre file .bat in `Pacchetto_Distribuzione/`:
- `Avvia_Askar71F.bat`
- `Avvia_Tecnosky115.bat`
- `Avvia_RC8.bat`

Ogni .bat usa `cd /d "%~dp0"` per funzionare da qualsiasi percorso di
installazione e lancia `PHD2_Agent.exe --config config_<setup>.toml`.

---

## 12. Dithering/Settling — implementazione (Gemini + verifica Claude, 2026-05-01)

### Problema

Tra uno scatto e l'altro il software di acquisizione (es. N.I.N.A.) invia un
comando di dithering a PHD2. PHD2 sposta la stella guida di alcuni pixel e
poi si rista­bilizza (settling). Durante questo periodo i `GuideStep` hanno
valori di errore elevati (movimento intenzionale, non seeing) che potrebbero
far scattare il controller in modo errato.

### Implementazione (main.py)

Flag `is_settling` locale a `_event_loop`. Copertura doppia:

| Evento PHD2 | Azione |
|---|---|
| `SettleBegin` | `is_settling = True` — blocca valutazioni |
| `SettleDone` | `is_settling = False`, `analyzer.reset()` |
| `AppState: Settling` | `is_settling = True` (percorso backup) |
| `AppState: Guiding` (se era settling) | `is_settling = False`, `analyzer.reset()` |

I `GuideStep` durante `is_settling` vengono scartati con `continue` prima
di entrare nell'analyzer. Il reset su `SettleDone` pulisce la finestra
statistica così il controller riparte con dati freschi post-dithering.
Dashboard aggiornata via broadcast `{"type": "settling", ...}`.

### Nota: StarLost durante settling

`StarLost` non è bloccato da `is_settling` (gap minore, non critico in DRY_RUN).
Se la stella viene persa durante il dithering (normale), il controller
reagisce comunque. Da valutare in futuro se necessario.

---

## 13. Bug critico scala aggression — trovato in LIVE (2026-05-01)

### Contesto

Alessandro ha attivato la modalità LIVE con Askar 71F (Hysteresis RA,
Resist Switch DEC). Il log mostrava:

```
[ERROR] Errore set_algo_param ra/aggression: RPC Error 1: could not set param
[TEST]  RA aggression: 0.700 -> 3.700
```

### Causa

PHD2 espone il parametro `aggression` (Hysteresis, Resist Switch) in
scala **0.0–1.0**, non 0–100. Il valore letto era `0.7` (= 70% nella GUI).
Il controller sommava `step_up=3` e tentava di inviare `4` → fuori range.
All'errore RPC, l'azione veniva retro-marcata `dry_run=True` → `[TEST]`.

Il parametro `aggressiveness` (Lowpass2) usa invece scala 0–100: nessun
problema per quell'algoritmo.

### Fix applicato (controller.py)

1. Costante `_AGGR_FRACTIONAL_PARAMS = frozenset({"aggression", "Aggression"})`
2. Funzione `_aggr_native_scale(param_name)` → `0.01` o `1.0`
3. `AxisState.aggr_native_scale: float = 1.0` — fattore di scala per asse
4. `_setup_axis()`: legge valore PHD2 nativo, lo divide per la scala,
   lo memorizza in scala config (0-100) per aritmetica uniforme con i limiti
5. `_apply()`: riconverte a scala nativa prima di inviare a PHD2
   - `aggression`: `round(new_value * 0.01, 4)` → PHD2 riceve es. `0.73`
   - `aggressiveness`: `int(round(new_value))` → PHD2 riceve es. `73`
6. `save_baseline()`: aggiunto `"version": 2` e `"aggr_native_scale"` nel JSON
7. `restore_baseline()`: invalida baseline v1 (scala incompatibile),
   usa scala salvata per il restore

### Scala parametri PHD2 verificata (sorgente C++)

| Algoritmo | aggr_param | Scala PHD2 |
|---|---|---|
| Hysteresis | `aggression` | 0.0 – 1.0 |
| Resist Switch | `aggression` | 0.0 – 1.0 |
| Lowpass2 | `aggressiveness` | 0 – 100 |
| Lowpass | `slopeWeight` | — |
| Gaussian Process | `predictiveWeight` / `reactiveWeight` | — |

### Log atteso dopo il fix

```
Asse ra: aggr_param=aggression (0.7 -> config 70.0) ...
[LIVE] RA aggression: 70.000 -> 73.000
✅ set_algo_param axis=ra name=aggression value=0.73
```

---

## 14. Stato finale pacchetto al 2026-05-01 (pre-sessione LIVE)

- `PHD2_Agent_Distribuzione.zip` (100.9 MB) — timestamp 01/05/2026 02:05
- Tutti i config hanno `dry_run = true` (da rimettere in false per LIVE)
- Bug scala `aggression` risolto e testato in campo
- Dithering/Settling implementato e verificato
- Double initialize() risolto
- `[phd2_log]` aggiunto a tutti i config, `PHD2LogConfig` in config.py
- README.md e config.toml aggiornati (rimosso C9.25, numeri corretti)

### Nota operativa: post-build
Ogni volta che si modifica un file `.py`, il pacchetto va ricompilato:
1. `python build_dist.py`
2. Copiare `config_*.toml`, `Avvia_*.bat`, `Sblocca_Firewall_8080.bat`
3. Ripristinare `LEGGIMI_PER_AVVIARE.txt` (build_dist.py lo sovrascrive)
4. Ricreare ZIP

---

## 15. Confronto PHD2 Guiding Assistant vs agente adattivo (2026-05-01)

### Prodotto

Creato `doc/CONFRONTO_GA_AGENT.md` (23 KB) tramite analisi del sorgente C++
PHD2 (`phd2-master/`) e confronto con la logica Python dell'agente.

### Formula SmartDefaultMinMove (verificata su sorgente)

```
SmartDefaultMinMove = max(0.1515 + 0.1548 / imageScale_arcsec_per_px, 0.15)
```

Dove `imageScale = pixel_size_µm / focal_length_mm * 206.265`.

### Pixel size corretti per i setup di Alessandro

| OAG | Sensore | Pixel µm |
|-----|---------|----------|
| Askar 71F | ASI120MM Mini (AR0130CS) | **3.75 µm** |
| RC8 + Tecnosky 115 | ASI220MM Mini (SC2210) | **4.0 µm** |

Nota: `config_askar71f.toml` usava 4.0 µm per errore → pixel scale corretta
da `1.68"/px` a `1.58"/px` (nativo) e da `2.10"` a `1.97"` (ridotto).

### Valori SmartDefault calcolati (con pixel size corretti)

| Setup | Focale | Scale OAG | SmartDefault |
|-------|--------|-----------|--------------|
| RC8 | 1624 mm | 0.508"/px | 0.457 px |
| Tecnosky 115 | 800 mm | 1.031"/px | 0.302 px |
| Askar 71F | 490 mm | 1.580"/px | 0.249 px |

Il documento include anche analisi dei parametri GA non accessibili via JSON-RPC
(backlash, polar alignment residuals, PE correction) e comparazione algoritmica
con le strategie dell'agente.

---

## 16. Prima sessione LIVE Askar 71F — diagnosi crash USB (2026-05-01)

### Risultati guida nella fase stabile

- RMS RA: 0.11–0.20" (ottimo per 490 mm, AM5)
- RMS DEC: 0.13–0.43"
- Il controller ha operato correttamente in LIVE con `aggr_native_scale` fix

### Evento critico alle 00:12:45

Crash USB del cavo ASI120MM Mini. Sintomi:

1. SDK ASI restituisce `EXP_FAILED giving up` in loop
2. PHD2 emette eventi `StarLost` continuativi
3. Controller chiama `find_star()` ogni ~10 s senza nessun backoff
4. Risultato: 130+ chiamate in ~6 minuti (da log PHD2)
5. I pochissimi frame corrotti prima del crash avevano RMS 17.86" RA / 12.17" DEC
   (fisicamente impossibili a 1.58"/px) → controller li elaborava normalmente

### Mitigazioni hardware e architetturali

- **Hardware**: acquistato cavo **Lindy Anthra Line USB-A/USB-C 0.5 m** per
  sostituire il cavo di origine della camera guida.
- **Architetturale**: PHD2 non espone via JSON-RPC endpoint per reset/reinit
  camera. Non è implementabile un recovery automatico via software. La gestione
  si limita a stop/restart guiding (già gestito da `mark_uninitialized` +
  `StartGuiding` handler).

---

## 17. FIX 1 — find_star backoff (2026-05-03)

### File modificato

`phd2_agent/controller.py`, metodo `_evaluate_star_lost` (ramo `else`, non-ai path)

### Costanti aggiunte (livello modulo)

```python
_FIND_STAR_SLOW_THRESHOLD = 5    # fallimenti → tier slow
_FIND_STAR_SUSP_THRESHOLD = 10   # fallimenti → sospeso
_FIND_STAR_SLOW_INTERVAL  = 30.0 # secondi tra tentativi slow
_FIND_STAR_SUSP_INTERVAL  = 60.0 # secondi tra log alert sospeso
```

### Stato aggiunto in `__init__` e `initialize()`

```python
self._find_star_failures: int = 0
self._find_star_last_attempt: float = 0.0
```

Resettati a 0/0.0 in `initialize()` (chiamato su `StartGuiding`).
`_find_star_failures` resettato a 0 anche al successo di `find_star()` in LIVE.

### Logica tier (solo LIVE; in DRY_RUN failures non incrementa)

| Tier | Condizione | Comportamento |
|------|-----------|---------------|
| Normal | failures < 5 | Tenta ogni `find_star_delay` s |
| Slow | 5 ≤ failures < 10 | Tenta ogni 30 s |
| Suspended | failures ≥ 10 | Nessuna chiamata; WARNING ogni 60 s |

Il WARNING in Suspended dice: `"find_star SUSPENDED dopo N fallimenti consecutivi — verificare connessione USB camera."`

### Nota: ramo ai_find non modificato

Il ramo `if self.ai_find_enabled` ha già gestione degli errori con fallback a
`find_star()` standard. Il backoff non è applicato lì (scenario meno critico,
il crash USB si manifesta principalmente nel path non-ai).

---

## 18. FIX 2 — RMS implosion detector (2026-05-03)

### File modificato

`phd2_agent/analyzer.py`, metodo `StatisticsAnalyzer._compute()`

### Costanti aggiunte (livello modulo)

```python
_RMS_IMPLOSION_FACTOR          = 8.0  # moltiplicatore soglia
_RMS_IMPLOSION_SUSPEND_SECONDS = 60   # secondi di sospensione
```

### Campi aggiunti

In `AnalysisSnapshot`:
```python
implosion_detected: bool = False   # frame garbage rilevato
implosion_suspended: bool = False  # decisioni sospese durante finestra post-implosion
```

In `StatisticsAnalyzer.__init__` (e `reset()`):
```python
self._rms_reference: Optional[float] = None
self._implosion_suspended_until: float = 0.0
```

### Logica EMA e rilevamento

Reference inizializzata quando la finestra è piena per la prima volta
(`n >= window_size`) e `snr_avg >= snr_low`.

**Aggiornamento EMA (α=0.1) solo su frame validi**:
- `rms_total < 8 × reference` (non garbage)
- `snr_avg >= snr_low` (SNR sufficiente)

Questo previene che frame patologici sub-soglia (es. 7× reference) spostino
il riferimento verso l'alto rendendo il trigger più difficile da scattare.
La scelta di non aggiornare EMA su frame garbage è quindi deliberata e
non solo una "sottigliezza da v2".

### Comportamento al rilevamento

1. `snap.implosion_detected = True`
2. Log `CRITICAL: RMS IMPLOSION: X.XX" >> 8.0× ref Y.YY" — decisioni sospese per 60s`
   (logato solo alla prima rilevazione, non ad ogni frame della finestra di sospensione)
3. `_implosion_suspended_until = time.monotonic() + 60`
4. Tutti i frame successivi entro 60 s: `snap.implosion_suspended = True`
5. Contatori `_consecutive_high`/`_consecutive_low` **non aggiornati** durante sospensione
   (evita stato CRITICAL spurio al ritorno alla normalità)
6. `snap.condition` forzata a `SeeingCondition.NOMINAL` con descrizione
   `"RMS implosion detector — analisi sospesa (RMS=X.XX\", ref=Y.YY\")"`

### Reset

`reset()` (chiamato su `SettleDone` e `StarFound`) azzera `_rms_reference = None`
e `_implosion_suspended_until = 0.0`. Questo è corretto: dopo un dithering/settling
si ricomincia a costruire il riferimento da zero con dati freschi.

---

## 19. Esposizione dinamica RMS-based (2026-05-09)

### Motivazione
Il path attuale `_evaluate_exposure()` reagisce solo a LOW_SNR. La discussione
con Alessandro ha identificato un secondo caso utile, fisicamente diverso:
seeing degradato a focale lunga (RC8, 0.51"/px), dove integrare via esposizione
riduce il rumore stocastico ad alta frequenza (RMS scende ~ √N). Il beneficio
è marginale a focale media (Tecnosky 115) e nullo a focale corta (Askar 71F,
1.97"/px), per questo la feature nasce disattiva e per-setup.

### Architettura
Macchina a stati `ExposureState` con stati mutuamente esclusivi:
- `NOMINAL` — esposizione = `base_exposure_ms`
- `BOOSTED_FOR_SNR` — path A (LOW_SNR, preesistente)
- `BOOSTED_FOR_SEEING` — path B (RMS-based, nuovo)

Il path A ha priorità su B: se LOW_SNR e DEGRADED_SEEING coesistono,
A prevale. B può attivarsi solo se lo stato è NOMINAL.

### Trigger UP (path B)
Tutte AND:
1. `exposure_dynamic.enabled` true per il setup
2. `condition == DEGRADED_SEEING` (e != OSCILLATING, != LOW_SNR)
3. `not implosion_suspended`
4. `consecutive_high >= consecutive_frames`
5. `spike_score >= spike_min`
6. `hfd_avg * guide_pixel_scale_arcsec >= hfd_min_arcsec`
7. peak/rms ratio (RA o DEC) >= `peak_to_rms_ratio_min`
8. `steps_above_base < max_steps_above_base`
9. **Escalation gate**: almeno un asse con `current_aggr ≈ aggr_min` AND
   `current_minmove ≈ minmove_max`, persistente da almeno 1 cooldown.
   Senza saturazione delle leve "cheap" (aggressiveness/MinMove) il path B
   non si attiva: gerarchia di escalation deliberata.
10. Cooldown dedicato esposizione >= `cooldown_s`

Step: `current * step_factor` snap-pato a `get_exposure_durations()`.
Dopo cambio confermato in LIVE: `analyzer.reset()` obbligatorio.

### Trigger DOWN (path B → NOMINAL)
Tutte AND:
1. Stato `BOOSTED_FOR_SEEING`
2. `condition == NOMINAL` da `nominal_for_seconds` continui
3. `consecutive_low >= 2 * consecutive_frames`
4. Cooldown >= `cooldown_s * 1.5`

Step: `current / step_factor` snap-pato, mai sotto `base_exposure_ms`.
Si scende di un livello per volta.

### Esclusioni di sicurezza
- **OSCILLATING**: esposizione lunga aumenta il lag → over-correzione peggiore.
  Mai allungare in questo regime.
- **LOW_SNR**: gestito dal path A; B non interviene per evitare doppia
  regolazione sulla stessa leva con cause diverse.

### Soglie configurabili per setup
| Setup | enabled default | guide_pixel_scale_arcsec | spike_min | hfd_min_arcsec |
|---|---|---|---|---|
| Askar 71F | false | 1.58 (nativo, 1.97 ridotto) | 0.30 | 4.5 |
| Tecnosky 115 | false | 1.03 (nativo, 1.29 ridotto) | 0.25 | 4.0 |
| RC8 | false | 0.51 (nativo, 0.64 ridotto) | 0.20 | 4.0 |

### Baseline Guardian
Bumpato a `version: 3`. Salva e ripristina anche `current_exposure_ms`,
`exposure_state`, `exposure_steps_above_base`. Restore di baseline v2 (legacy)
ignora i campi esposizione e riparte da NOMINAL.

### File modificati
- `phd2_agent/controller.py` — macchina a stati, `_evaluate_exposure_seeing`,
  refactor `_evaluate_exposure_snr`, baseline v3
- `phd2_agent/config.py` — dataclass `ExposureDynamicConfig`, parsing
- `main.py` — passa `analyzer` al controller per `analyzer.reset()` post-cambio
- `config.toml`, `config_askar71f.toml`, `config_tecnosky115.toml`,
  `config_rc8.toml` — sezione `[exposure_dynamic]`
- `Pacchetto_Distribuzione/config_*.toml` — copie aggiornate post-rebuild
- `tests/test_exposure_dynamic.py` — 5 test unitari

### Procedura di validazione (LIVE primario, scelta operativa)
1. Test simulatore: solo sanity-check non-regressione (decisioni esistenti
   continuano a funzionare, nessun crash, dashboard espone blocco `exposure`).
2. **Sessione LIVE RC8** con `[exposure_dynamic].enabled = true` e
   `dry_run = false` nel `config_rc8.toml`. Osservazione diretta sulla
   dashboard del comportamento RMS prima e dopo i trigger.
   Motivazione della scelta LIVE invece di DRY_RUN: il valore della feature
   sta nell'effetto sul loop di guida, non nell'emissione della decisione.
   In DRY_RUN si vedrebbe solo `[TEST]` nei log senza alcun impatto reale,
   il che non permette di valutare il beneficio (o danno) della modifica
   di esposizione.
3. Tuning iterativo dei parametri sulla base di:
   - frequenza dei trigger (eccessiva → alzare `spike_min` / `cooldown_s`)
   - assenza di trigger (in nottata turbolenta → abbassare le soglie)
   - effetto sul grafico RMS post-cambio (positivo / neutro / negativo)
4. La sicurezza in LIVE è garantita da:
   - `enabled` per-setup (parte OFF, attivazione manuale)
   - escalation gate (path B non scatta senza saturazione delle leve cheap)
   - `max_steps_above_base = 2` (max ~2.25× base con `step_factor = 1.5`)
   - cap a `max_exposure_ms` del config `[emergency]` esistente
   - Baseline Guardian v3 ripristina esposizione su Ctrl+C / kill brutale

### Note di design
- `analyzer.reset()` post-cambio è obbligatorio: l'RMS calcolato su finestra
  con esposizioni miste 2s/3s non è confrontabile (diverso peso del rumore
  ad alta frequenza).
- La feature non interagisce con aggressiveness/MinMove: agisce su una leva
  ortogonale (l'esposizione cambia il segnale in ingresso, l'aggressività
  cambia la risposta a quel segnale).
- Il `step_factor = 1.5` è meno aggressivo del `× 2` del path A, perché
  il seeing è un continuum (a differenza della perdita stella che è on/off).
- Pre-flight su sorgente PHD2 (event_server.cpp, myframe.cpp): `set_exposure`
  accettato durante Guiding senza controllo stato; l'algoritmo di guida
  (Hysteresis m_lastMove, ResistSwitch m_history) NON viene resettato da
  un semplice set_exposure — reset avviene solo su GuidingResumed(). La nota
  "transitorio" nelle reason delle ControlAction documenta questo comportamento.

---

## 20. Refactor [setup] e supporto Riduttore Focale (2026-05-09)

### Motivazione
La sezione 19 aveva messo `guide_pixel_scale_arcsec` dentro `[exposure_dynamic]`.
Analisi post-implementazione ha evidenziato due problemi:
1. La pixel scale di guida è una proprietà del **setup ottico**
   (telescopio + camera + riduttore), non di una specifica feature.
   Feature future (es. backlash diagnostic) avrebbero dovuto duplicare il campo.
2. Alessandro usa due configurazioni alternate per ciascun OTA: focale
   piena e focale ridotta. Editare manualmente il TOML ad ogni cambio è error-prone.

### Soluzione architetturale
Spostata `guide_pixel_scale_arcsec` in una nuova sezione `[setup]` estesa:

```toml
[setup]
profile_name                     = "rc8"
guide_pixel_scale_arcsec_native  = 0.51
guide_pixel_scale_arcsec_reduced = 0.68
reducer_active                   = false
```

`SetupConfig` in `config.py` espone una property calcolata:

```python
@property
def guide_pixel_scale_arcsec(self) -> float:
    return (self.guide_pixel_scale_arcsec_reduced
            if self.reducer_active
            else self.guide_pixel_scale_arcsec_native)
```

Tutte le feature leggono dalla property — sempre coerente indipendentemente
da quale file TOML è caricato e se è attivo il riduttore.

### Retrocompatibilità
Se un TOML legacy ha ancora `guide_pixel_scale_arcsec` dentro `[exposure_dynamic]`,
viene ignorato silenziosamente con log DEBUG:
`"Campo legacy guide_pixel_scale_arcsec in [exposure_dynamic] ignorato — usare [setup]"`.
Il caricamento non si rompe; la pixel scale viene letta da `[setup]` (o dal default 1.0).

### Operatività CLI
Aggiunti flag mutualmente esclusivi in `main.py`:
- `--with-reducer` → forza `reducer_active = True` (override TOML)
- `--no-reducer`   → forza `reducer_active = False` (override TOML)
- nessun flag → usa il valore del TOML (`reducer_active` in `[setup]`)

Override applicato **dopo** `load_config()`, quindi sovrascrive sempre il TOML.

### .bat operativi
Creati 3 `.bat` aggiuntivi che lanciano con `--with-reducer`:
- `Avvia_Askar71F_Ridotto.bat`   → 367mm, 2.11"/px
- `Avvia_Tecnosky115_Ridotto.bat` → 640mm, 1.29"/px
- `Avvia_RC8_Ridotto.bat`         → 1218mm, 0.68"/px (LIVE)

I `.bat` originali (focale piena) restano invariati. Totale: 6 `.bat` in distribuzione.

### Valori pixel scale corretti
Errore preesistente nei TOML: tutti i setup assumevano riduttore 0.80x.
Valori reali verificati:

| Setup | Riduttore | Native | Reduced corretto | Era (errato) |
|---|---|---|---|---|
| Askar 71F | 0.75x | 1.58"/px | 2.11"/px | 1.97"/px |
| Tecnosky 115 | 0.80x | 1.03"/px | 1.29"/px | (corretto) |
| RC8 | 0.75x | 0.51"/px | 0.68"/px | 0.64"/px |

### Configurazione LIVE su RC8
`config_rc8.toml` impostato con `dry_run = false` e `[exposure_dynamic].enabled = true`.
Motivazione: Alessandro vuole osservare l'effetto dell'esposizione dinamica
**sul grafico della dashboard** al momento dei trigger, non solo nei log a posteriori.
La sicurezza è garantita da escalation gate + `max_steps_above_base = 2` + Baseline Guardian v3.
Gli altri due setup (Askar 71F, Tecnosky 115) restano `enabled = false`.

### File modificati
- `phd2_agent/config.py`: `SetupConfig` esteso con property calcolata; campo
  `guide_pixel_scale_arcsec` rimosso da `ExposureDynamicConfig`; parsing
  `[setup]` aggiornato; parsing `[exposure_dynamic]` con retrocompatibilità
- `phd2_agent/controller.py`: `ed.guide_pixel_scale_arcsec` →
  `self.cfg.setup.guide_pixel_scale_arcsec`; log INFO setup in `initialize()`
- `main.py`: flag CLI mutex `--with-reducer` / `--no-reducer`
- `config.toml`, `config_askar71f.toml`, `config_tecnosky115.toml`, `config_rc8.toml`:
  sezione `[setup]` estesa; `guide_pixel_scale_arcsec` rimosso da `[exposure_dynamic]`
- `Pacchetto_Distribuzione/`: stessi 4 TOML + 3 `.bat` ridotti + `Avvia_RC8.bat` aggiornato
- `LEGGIMI_PER_AVVIARE.txt`: aggiornato con tabella 6 `.bat` (focale piena + ridotta)
- `tests/test_setup_config.py`: 3 test (native, reduced, defaults)
- `tests/test_exposure_dynamic.py`: aggiornato per nuova posizione pixel scale

---

## 21. Dashboard §21: Pannello Stato Esposizione & Escalation Gate (2026-05-12)

### Obiettivo
Rendere visibile lo stato dell'esposizione dinamica (§19) e dell'escalation gate
sulla dashboard, con marker in-chart per ogni cambio esposizione.

### Modifiche a controller.py — get_status()
Aggiunto blocco `escalation_gate` e arricchito blocco `exposure`:
```python
"exposure": {
    ...
    "cooldown_total_s": cfg.exposure_dynamic.cooldown_s,
    "cooldown_residuo_s": round(max(
        0.0,
        cfg.exposure_dynamic.cooldown_s - (time.monotonic() - last_exposure_action_time)
    ), 1),
},
"escalation_gate": {
    "enabled": cfg.exposure_dynamic.enabled,
    "ra":  self._axis_levers_saturated(self._ra,  self.cfg.ra),
    "dec": self._axis_levers_saturated(self._dec, self.cfg.dec),
},
```
`_axis_levers_saturated` già esisteva: restituisce True se aggr <= aggr_min+1
AND minmove >= minmove_max-step AND entrambi i cooldown trascorsi.

### Config TOML — tutti i setup ora LIVE
Aggiornati `config_askar71f.toml` e `config_tecnosky115.toml` (root +
Pacchetto_Distribuzione): `dry_run = false` + `[exposure_dynamic].enabled = true`.
Motivazione: la dashboard §21 è utile solo in LIVE; DRY_RUN su Askar e Tecnosky
non aveva più senso dopo la validazione positiva sul campo con RC8.

### .bat files — formato uniforme e nuovo
Tutti i 6 `.bat` (root + Pacchetto_Distribuzione) aggiornati con echo uniforme:
```
MODALITA: LIVE (dry_run=false)
exposure_dynamic.enabled: true (path B attivo)
```
`build_dist.py` aggiornato per copiare tutti e 6 (inclusi `_Ridotto`).

### Dashboard HTML/CSS/JS

**index.html**: inserita `<section class="mid-row-2">` tra `mid-row` e `log-section`
con `exposure-card` (stato, valori ms, cooldown bar) e `escalation-card`
(gate enabled badge, RA/DEC status badges, nota contestuale).

**style.css**: aggiunti:
- `.mid-row-2` (grid 2 colonne, responsive a 1 colonna sotto 1100px)
- `.exposure-card`, `.escalation-card` (stessa card pattern di `.controller-card`)
- `.exposure-state-badge` con varianti `.nominal` / `.boosted-snr` / `.boosted-seeing`
- `.cooldown-bar-wrap`, `.cooldown-bar`, `.cooldown-bar.hot`
- `.gate-enabled-badge`, `.gate-status-badge.saturated`, `.gate-status-badge.ok`

**app.js**:
1. Array parallelo `exposureMarkerMeta[]` al fianco delle label del grafico.
2. 4° dataset Chart.js (scatter triangoli, showLine=false), con `pointRadius`
   e `backgroundColor` scriptable che leggono da `exposureMarkerMeta[ctx.dataIndex]`.
   Marker giallo triangolo = UP, verde = DOWN. Non visibili quando null.
3. `addChartPoint(label, ra, dec, tot, expMarker=null)` aggiornato: push su
   datasets[3].data (null o 0.06) e su `exposureMarkerMeta`. Shift sincronizzato.
4. `updateGuideStep()`: prima di chiamare `addChartPoint`, cerca in `msg.actions`
   la prima con `axis==='exposure'`; se trovata costruisce il meta oggetto.
5. `updateExposureEscalation(ctrl)`: aggiorna tutti gli elementi del pannello §21
   (badge stato, ms, steps, cooldown bar, gate badges, nota).
6. `applyFullStatus()`: chiama `updateExposureEscalation(ctrl)` se `ctrl.exposure`
   o `ctrl.escalation_gate` presenti.
7. Clear chart handler: resetta `exposureMarkerMeta = []` insieme ai datasets.
8. Tooltip: `filter` salta dataset 3 quando nessun marker; callback mostra
   "Exp UP/DOWN: X ms → Y ms" per i punti con marker.

### Test
`tests/test_get_status.py` — 8 test che verificano:
- `exposure.cooldown_total_s` == 90.0
- `exposure.cooldown_residuo_s` == 0.0 (controller fresco)
- `cooldown_residuo_s <= cooldown_total_s`
- `escalation_gate` presente con chiavi `enabled`, `ra`, `dec`
- tutti e tre bool
- controller fresco → gate non saturato

### Risultato test
16 test totali, 0 fallimenti.

### LEGGIMI aggiornato
Nuovo formato con 6 .bat (focale piena + ridotta), nota che tutti sono LIVE.

### File modificati
- `phd2_agent/controller.py`: `get_status()` esteso
- `config_askar71f.toml`, `config_tecnosky115.toml`: dry_run=false, enabled=true
- `Pacchetto_Distribuzione/config_askar71f.toml`, `config_tecnosky115.toml`: idem
- `dashboard/index.html`: sezione mid-row-2 aggiunta
- `dashboard/style.css`: stili §21 aggiunti
- `dashboard/app.js`: 4° dataset, updateExposureEscalation, marker logica
- `Avvia_*.bat` (root × 6 + Pacchetto_Distribuzione × 6): formato uniforme LIVE
- `build_dist.py`: lista bat aggiornata (tutti e 6)
- `Pacchetto_Distribuzione/LEGGIMI_PER_AVVIARE.txt`: tabella 6 .bat aggiornata
- `tests/test_get_status.py`: nuovo file, 8 test
- `CONTESTO_PROGETTO.md`: data e sezione §21 aggiunte

## 22. Auto-scala via RPC + soglie RMS adattive + config unico (2026-05-27)

### Motivazione
Fino alla §21 la pixel scale di guida era hard-coded per setup in `[setup]`, le soglie RMS erano costanti tarate a
mano in `[thresholds]`, ed esistevano 3 TOML per-setup + 6 `.bat` (focale piena/ridotta). Ogni cambio telescopio
richiedeva di scegliere il file giusto e ritarare a mano. Obiettivo: agente auto-configurante e a config unico.

### Architettura
1. **Pixel scale efficace**: `client.get_pixel_scale()` reso null-safe (`Optional[float]`, gestisce `null` RPC ed
   eccezioni). `SetupConfig.pixel_scale_override` (campo runtime, NON parsato dal TOML); la property
   `guide_pixel_scale_arcsec` ritorna l'override se valorizzato, altrimenti reduced/native (TOML).
   `controller._apply_pixel_scale_from_phd2(context)` imposta l'override col valore PHD2 quando valido,
   altrimenti `None` → fallback TOML.
2. **Soglie RMS adattive**: `controller._update_rms_baseline(snap)` campiona `rms_total` solo in condizione stabile
   (`SeeingCondition.NOMINAL`, `snr_avg ≥ baseline_min_snr`, `not implosion_detected`); a finestra piena
   `_finalize_rms_baseline()` deriva `rms_high = clamp(rms_high_factor × mediana)` e `rms_low = rms_low_factor × mediana`,
   aggiornando SIA `cfg.thresholds` SIA gli attributi dell'analyzer (config efficace in memoria, **TOML mai riscritto**).
3. **Timing hook**: `_apply_pixel_scale_from_phd2("init")` è chiamato dentro `controller.initialize()`. Non esiste un
   evento PHD2 `GuidingResumed`: `initialize()` è già il punto di convergenza, invocato a init (state Guiding), su
   `StartGuiding`, su `AppState→Guiding` e dopo riconnessione (vedi `main.py`). Il caso `null` a freddo si auto-corregge
   appena la camera è connessa. La baseline RMS NON viene azzerata a ogni re-init: lo stato `_rms_baseline_*` vive solo
   in `__init__` e l'invalidazione (`_invalidate_rms_baseline`) scatta SOLO su cambio scala reale (`abs(prev-scale) > 1e-3`).
4. **Dashboard**: blocco `auto_calibration` in `get_status()` (pixel scale efficace + fonte phd2/toml, baseline_rms,
   progresso `n/window`, baseline_done, rms_high/low attivi); card "Auto-calibrazione" in dashboard (riusa `.exposure-card`).

### Comportamento atteso
Con `[auto_calibration].enabled = false` comportamento identico a prima (nessuna raccolta/modifica, soglie = TOML).
Con `enabled = true`: pixel scale auto da PHD2, soglie auto dopo i primi `baseline_window_frames` frame in NOMINAL.
MinMove e range aggressività NON toccati (già scale-independent). Backlash, esposizione dinamica (§19), escalation
gate (§21), Baseline Guardian e RMS implosion detector invariati.

### Config unico
Unico `config.toml` con costanti unificate (max_exposure 4000ms, snr_low 8.0, spike_min 0.25, hfd_min 4.0",
`[auto_calibration].enabled = true`, `[exposure_dynamic].enabled = true`, `dry_run = false`). Unico `Avvia.bat`.
La scelta del telescopio si fa selezionando il profilo in PHD2 (focale → pixel scale auto-rilevata). I flag
`--with-reducer`/`--no-reducer` restano per retrocompat (ininfluenti con auto-scala: comanda la focale del profilo).

### Limiti dell'approccio
- **Cecità di risoluzione**: `get_pixel_scale` riflette il profilo PHD2; se la focale nel profilo è errata, la scala
  è errata. Su cercatore-guida la flessione differenziale non è osservabile dalla sola pixel scale.
- **Baseline in seeing cattivo**: se il cielo parte turbolento la baseline non si completa (campiona solo NOMINAL):
  comportamento atteso, le soglie restano ai valori TOML finché non c'è un periodo stabile.
- **Scala == 1.00"/px**: PHD2 risponde `null` (indistinguibile da "scala sconosciuta") → fallback TOML.

### File modificati
- `phd2_agent/client.py`: `get_pixel_scale()` null-safe (Optional[float])
- `phd2_agent/config.py`: `SetupConfig.pixel_scale_override` + property; nuova `AutoCalibrationConfig`; campo in
  `AgentConfig`; parsing retrocompatibile in `load_config`
- `phd2_agent/controller.py`: stato baseline in `__init__`; `_apply_pixel_scale_from_phd2`, `_invalidate_rms_baseline`,
  `_update_rms_baseline`, `_finalize_rms_baseline`; chiamata in `initialize()` e in `evaluate()`; blocco
  `auto_calibration` in `get_status()`
- `main.py`: help `--with-reducer`/`--no-reducer` aggiornato (retrocompat)
- `config.toml`: riscritto come config unico
- ELIMINATI: `config_askar71f.toml`, `config_tecnosky115.toml`, `config_rc8.toml` e i 6 `Avvia_*.bat`
  (root + Pacchetto_Distribuzione)
- NUOVO: `Avvia.bat` (unico)
- `build_dist.py`: copia solo `config.toml`; `bat_files = ["Avvia.bat", "Sblocca_Firewall_8080.bat"]`;
  `LEGGIMI_PER_AVVIARE.txt` riscritto per flusso a file unico
- `dashboard/index.html`: card "Auto-calibrazione"; `dashboard/app.js`: `updateAutoCalibration()`
- `tests/test_auto_calibration.py`: nuovo file, 12 test; `tests/test_setup_config.py`: +1 test override

### Validazione raccomandata
Sessioni LIVE su almeno 2 profili PHD2 diversi (RC8 e Askar ridotto): verificare nella card che la pixel scale cambi
da sola con badge "PHD2", che la baseline si completi (n/60) in cielo calmo e che `rms_high`/`rms_low` derivati siano
plausibili. Cercare nei log `[autocal]`. Tarare `rms_high_factor` (1.5) se troppi/pochi DEGRADED.

## 23. Clamp proporzionale + gate rifiuto baseline (2026-05-28)

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
- Se `baseline > reject_threshold` → rifiuta, `_rms_baseline_rejected = True`, soglie invariate (il gate
  gira PRIMA del cap: una baseline troppo alta viene scartata, non clampata).
- Altrimenti: `rms_high = min(cap_efficace, rms_high_factor * baseline)`,
  `rms_low = max(rms_low_min_arcsec, rms_low_factor * baseline)`.
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
- `phd2_agent/config.py`: 4 nuovi campi in `AutoCalibrationConfig` (`rms_high_max_factor`, `rms_low_min_arcsec`,
  `baseline_reject_factor`, `baseline_reject_min_arcsec`) + 2 default modificati (`rms_high_min_arcsec` 0.50→0.70,
  `rms_high_max_arcsec` 2.50→3.00); parsing esteso.
- `phd2_agent/controller.py`: 3 nuovi flag stato (`_rms_baseline_rejected`, `_rms_high_cap_active`,
  `_rms_high_cap_value`) in `__init__` e resettati in `_invalidate_rms_baseline`; riscritto `_finalize_rms_baseline`;
  esteso `get_status()`.
- `config.toml`: sezione `[auto_calibration]` estesa con nuovi parametri commentati.
- `dashboard/index.html`, `dashboard/app.js`, `dashboard/style.css`: card estesa con riga "Cap rms_high" + badge
  CAP ATTIVO (ambra) + badge BASELINE RIFIUTATA (rosso).
- `tests/test_auto_calibration.py`: rimosso il vecchio `TestBaselineClamp` (baseline 5.0 ora cade nel rifiuto),
  aggiornato `_make_config` ai nuovi default, +8 nuovi test §23 (cap RC8/ceiling Askar/floor, rifiuto RC8/floor
  assoluto, accettazione borderline, floor rms_low, reset flag su invalidazione). Totale suite: 36 test verdi.

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

## 24. Taratura fine: cap a 1.00" + ranges aggr/MinMove armonizzati (2026-05-29)

### Motivazione
La §23 aveva fissato il tetto assoluto del cap auto-calibrazione a 3.00 arcsec come safety per scale
grossolane. L'analisi dei log reali su RC8/Tecnosky 115/Askar 71F mostra però che gli RMS tipici stanno
ben sotto 1", quindi 3.00" come tetto è eccessivo e non offre la protezione che dovrebbe nei casi limite
(es. cercatore-guida con focale 400mm in parallelo a imaging 1000mm, dove la pixel scale di guida 1,93"/px
porterebbe il cap proporzionale §23 a 3.86", troncato dal ceiling a 3.00" — comunque troppo permissivo
per stelle imaging puntiformi). Abbassare il tetto a 1,00" allinea l'Agente al benchmark fisico
universalmente riconosciuto di "guida pulita" e copre anche il caso cercatore.

Sui ranges: i precedenti `[limits.ra]` (40-80 aggr, 0.15-0.80 minmove) e `[limits.dec]` (35-75 aggr,
0.18-0.85 minmove) erano leggermente disomogenei tra i due assi. L'armonizzazione a 35-90 / 0.15-0.85
su entrambi dà più dinamica al controller (più reattivo in cieli ottimi, più tollerante in cieli scarsi)
e coerenza concettuale RA/DEC.

### Architettura
Zero modifiche logiche. Solo cambio di valore di default:
- `AutoCalibrationConfig.rms_high_max_arcsec`: 3.00 → 1.00 (default dataclass + fallback parser).
- `AxisLimits`: default armonizzati a 35-90 (aggr) e 0.15-0.85 (minmove); rimosso l'override
  `AgentConfig.dec = AxisLimits(aggr_max=85.0)` → ora `default_factory=AxisLimits` (RA/DEC identici).
- `config.toml`: `[auto_calibration].rms_high_max_arcsec = 1.00`, `[limits.ra]`/`[limits.dec]` armonizzati.

### Effetto sui setup
| Setup | pixel scale | cap §23 (era) | cap §24 (ora) |
|---|---|---|---|
| RC8 | 0,51 | 1,02" | 1,00" |
| Tecnosky 115 | 1,03 | 2,06" | 1,00" |
| Askar 71F | 1,58 | 3,00" (ceiling) | 1,00" |
| Cercatore 400mm + ASI120 (1,93) | 1,93 | 3,00" (ceiling) | 1,00" |

A scala finissima (es. 0,30"/px) il cap proporzionale (0,60") viene comunque alzato dal pavimento
`rms_high_min_arcsec = 0.70`: il tetto globale 1,00" non è vincolante perché la formula proporzionale
già taglia più stretto.

### File modificati
- `phd2_agent/config.py`: default `rms_high_max_arcsec` 3.00 → 1.00 (+ fallback in `load_config`);
  default `AxisLimits` ranges aggiornati; `AgentConfig.dec` armonizzato a `default_factory=AxisLimits`.
- `config.toml`: `[auto_calibration]` aggiornato; `[limits.ra]` e `[limits.dec]` armonizzati e identici.
- `tests/test_auto_calibration.py`: 3 test §23 aggiornati al nuovo cap (RC8 1.02→1.00; Askar ceiling
  3.00→1.00 con cap ora attivo; borderline 1.02→1.00), +2 nuovi test §24 (cap globale 1.00 su quattro
  scale incl. cercatore; pavimento proporzionale prevale a scala 0.30). Totale suite: 38 test verdi.

### Limiti dell'approccio
1. Il cap a 1,00" è ancora "globale assoluto", non personalizzato per la specifica ottica di ripresa.
   Per i guide-scope users esiste ancora un margine di imprecisione (es. cercatore 200mm + imaging 3000mm
   vorrebbe cap ancora più stretto). Soluzione futura: introdurre un campo opzionale
   `imaging_pixel_scale_arcsec` in `[setup]` che, quando valorizzato, sostituisce la pixel scale di guida
   nella formula del cap. Non implementato in §24.

### Validazione raccomandata
1. Sessione RC8 in seeing normale: cap NON attivo, badge non compare.
2. Sessione RC8 in seeing scarso/vento: cap attivo, badge "CAP ATTIVO" visibile.
3. Verifica sui log dei ranges effettivi che il controller può raggiungere (aggr 35-90, minmove 0.15-0.85).

## 25. Refresh ciclico baseline (tightest-wins) + rms_high_factor 1.3 (2026-05-30)

### Motivazione
Validazione sul campo della prima sessione §22-§24 (Askar 71F, baseline 0,571" misurata con cielo già velato):
le soglie derivate restavano "congelate" su una calibrazione di cielo mediocre per tutta la nottata. La feature
risolve introducendo un refresh periodico (default 30 min) della baseline, con regola "tightest-wins"
(applica solo se più stretta della corrente). L'Agente si adatta a un cielo che migliora ma non si lascia
trascinare da uno che peggiora.

Inoltre `rms_high_factor` abbassato da 1.5 a 1.3: il cuscinetto del 50% sopra la baseline produceva su RC8
(0,51"/px) soglie DEGRADED già fuori scala per il campionamento (0,82-0,90" su baseline tipica 0,55-0,60");
il 30% (= f=1.3) produce soglie 0,72-0,78" — protezione reale per le focali lunghe, zero effetti pratici sulle
corte (dove l'RMS reale tipico sta comunque sotto entrambe le soglie).

### Architettura
- Nuovi campi `AutoCalibrationConfig`: `refresh_enabled`, `refresh_interval_seconds`, `refresh_only_if_tighter`.
- Cambio default `rms_high_factor`: 1.5 → 1.3 (default dataclass + fallback parser + TOML).
- Nuovo stato `AdaptiveController`: `_baseline_finalize_time` (timestamp monotonic dell'ultima applicazione),
  `_baseline_refresh_in_progress`, `_last_refresh_action` ("applicato"/"rifiutato"/None), `_last_refresh_baseline`.
  Tutti azzerati in `_invalidate_rms_baseline`.
- Nuovo metodo `_maybe_start_refresh()` chiamato in `evaluate()` prima di `_update_rms_baseline`: se il timer
  è scaduto e la baseline è applicata, azzera samples e `_rms_baseline_done` per riaprire la raccolta.
  **Le soglie correnti restano attive** durante la ri-misura.
- `_finalize_rms_baseline()` ristrutturato: cattura `prev_baseline` PRIMA di sovrascrivere. Tre branch:
  (1) gate §23 prevale sempre; se in refresh, `_last_refresh_action="rifiutato"` e baseline corrente preservata;
  (2) tightest-wins: se in refresh e `new >= prev`, rifiuta e mantieni soglie correnti;
  (3) applica (primo finalize OR refresh accettato): aggiorna soglie + setta `_baseline_finalize_time = now`.
- `get_status()` esteso con 6 nuovi campi (`refresh_enabled`, `refresh_interval_seconds`, `refresh_in_progress`,
  `refresh_progress`, `refresh_seconds_to_next`, `last_refresh_action`, `last_refresh_baseline_arcsec`).
- Dashboard: nuova riga "Refresh" nella card Auto-calibrazione (countdown / "in corso N/W" / "spento")
  + badge "ULTIMO: APPLICATO" (verde) / "ULTIMO: RIFIUTATO" (neutro). Riusa palette `gate-status-badge` esistente.

### File modificati
- `phd2_agent/config.py`: 3 nuovi campi `AutoCalibrationConfig` + parsing + cambio default `rms_high_factor`.
- `phd2_agent/controller.py`: 4 nuovi stati `__init__` + reset in `_invalidate_rms_baseline` +
  `_maybe_start_refresh()` + `_finalize_rms_baseline()` ristrutturato + chiamata in `evaluate()` +
  `get_status()` esteso.
- `config.toml`: `rms_high_factor = 1.3` + 3 nuovi parametri refresh commentati.
- `dashboard/index.html`, `dashboard/app.js`: riga "Refresh" + badge esito (CSS riusa `.gate-status-badge.ok`).
- `tests/test_auto_calibration.py`: `_make_config` non specifica più `rms_high_factor` (usa nuovo default 1.3);
  4 asserzioni numeriche aggiornate (HappyPath 0.75→0.65, cap_floor 0.45→0.39, rms_low_floor 0.375→0.325,
  proportional_floor_§24 0.45→0.39); +8 nuovi test §25 (tightest-wins applica/rifiuta-peggiore/rifiuta-uguale;
  trigger disabilitato/abilitato; refresh con gate §23; due test stato `/status`). Totale: 46 test verdi.

### Limiti dell'approccio
1. Il refresh è "puramente temporale": ogni `refresh_interval_seconds` ri-misura. Non c'è euristica di
   "ri-misura subito se il cielo è cambiato drasticamente" (es. fine di cloud passing). Possibile evoluzione
   futura: trigger di refresh anche su cambio condizione sostenuto.
2. Se il timer scade durante un seeing molto degradato, il refresh raccoglierà campioni solo in frame NOMINAL
   (filtro §22), quindi può richiedere molto tempo per completarsi o non completarsi affatto se le condizioni
   non migliorano. Comportamento corretto, ma da tenere a mente.

### Validazione raccomandata
1. Sessione con cielo stabile (almeno 1h): verificare che il primo refresh dopo 30 min sia "rifiutato"
   (baseline simile o leggermente più alta per fluttuazioni naturali).
2. Sessione con cielo che migliora (es. velatura che si dirada): dovrebbe arrivare un "applicato" con
   baseline più stretta e soglie ristrette.
3. Sessione con cielo che peggiora: serie di "rifiutato", soglie iniziali mantenute.

---

## 26. Branding progetto + identità autore (rilascio pubblico v2.2) (2026-05-30)

### Motivazione
Dopo §25, il software è funzionalmente pronto per il primo rilascio pubblico
in un gruppo Telegram italiano di astrofotografia (~1000 utenti). Distribuire
uno ZIP anonimo perderebbe sia la paternità del lavoro sia il valore del
feedback strutturato. Serve un livello di branding consistente che attraversi
ogni touchpoint del software: banner console, dashboard, manuale, metadata
Windows, file ZIP. Single source of truth in un solo modulo Python così che
bumpare la versione in futuro richieda un solo edit.

### Architettura
- Nuovo modulo `phd2_agent/__about__.py`: costanti `__project_name__`,
  `__short_name__`, `__author__`, `__version__`, `__version_tuple__`,
  `__copyright__`, `__license__`, `__contact_telegram__` (NO
  `__contact_email__`: l'unico canale di contatto è il gruppo Telegram della
  community, hard-coded a `https://t.me/+eewRNpvElSs5OWY8`).
  Helper `banner_lines()` e `about_payload()`.
- `phd2_agent/__init__.py` ri-esporta le costanti principali (compatibilità con
  eventuali import esterni). Il vecchio `__version__ = "1.0.0"` è stato
  rimosso a favore dell'import da `__about__` (versione bumpata a 2.2).
- `main.py` logga `banner_lines()` come prime righe del log della sessione,
  sostituendo il mini-banner statico v1.1.0.
- `server.py` espone endpoint `/about` che ritorna `about_payload()`. Scelta
  esplicita di NON gonfiare `/status` (chiamato a ~1Hz) con costanti
  invarianti.
- Dashboard (`index.html`/`app.js`/`style.css`): byline sotto il logo + footer
  a piè pagina popolati da `/about` al `DOMContentLoaded`. Footer ha link
  Telegram cliccabile (`<a target="_blank" rel="noopener noreferrer">`).
  CSS riusa variabili esistenti `--text-muted`, `--border`, `--blue` (non
  `--accent` che non esisteva nello stylesheet).
- `version_info_template.py` (nuovo): genera `version_info.txt` PyInstaller
  da `__about__`. Richiamato da `build_dist.py` prima di PyInstaller.
- `PHD2_Agent.spec`: aggiunto parametro `version='version_info.txt'` nel
  blocco `EXE(...)`. Verificato che le stringhe (`Adaptive Agent for PHD2`,
  `Alessandro Curci`, copyright) finiscano effettivamente nelle resource
  UTF-16 del PE finale.
- `build_dist.py`: ZIP rinominato in `Adaptive_Agent_PHD2_v<version>.zip`;
  template `LEGGIMI_PER_AVVIARE.txt` aggiornato con copertina branded.
- `config.toml`, `Avvia.bat`: header brandizzato (commenti `(c)` ASCII per
  compatibilità shell legacy).
- `doc/Manuale_Utente_Agent.md`: copertina branded (markdown).
- `doc/Manuale_Utente_Agent .txt`: copertina branded (plain text, no
  asterischi). NB: rompe leggermente la byte-identity `.md`/`.txt` che
  c'era da §25, ma solo nelle prime ~10 righe della copertina (resto
  del documento ancora identico).
- `doc/build_manual_pdf.py` (nuovo nel repo): copia versionata dello script
  outputs/ (già adattato cross-platform in §25), con metadata PDF
  (title/author/subject/creator/keywords) letti da `__about__`. Path output
  default = `doc/Manuale_Utente_Agent.pdf` relativo al file stesso, override
  via `argv[1]`.

### Comportamento atteso
- Nessuna modifica logica all'Agente: tutte le feature §1-§25 inalterate.
- Banner Python presente nei log della sessione (7 righe).
- Endpoint `/about` ritorna JSON con tutti i campi, niente `contact_email`.
- Dashboard mostra byline + footer.
- Proprietà Windows dell'`.exe` mostrano `Adaptive Agent for PHD2`,
  `Alessandro Curci`, `2.2`, copyright.
- PDF manuale ha metadata branded (Title/Author/Subject/Creator).
- ZIP finale: `Adaptive_Agent_PHD2_v2.2.zip`.

### File modificati
- NUOVO: `phd2_agent/__about__.py`
- NUOVO: `version_info_template.py` (root)
- NUOVO: `doc/build_manual_pdf.py` (versionato; lo script outputs/ resta lì
  come copia storica)
- NUOVO: `tests/test_about.py` (13 test in 5 classi)
- `phd2_agent/__init__.py`: ri-esporto da `__about__`, rimossa versione 1.0.0
- `main.py`: import `banner_lines`, sostituito mini-banner statico
- `server.py`: import `about_payload`, endpoint `/about`
- `dashboard/index.html`: meta tag author, byline nel logo, footer
- `dashboard/app.js`: `loadBrandInfo()` su DOMContentLoaded
- `dashboard/style.css`: classi `.brand-byline`, `.brand-footer`,
  `.brand-contact` (usano `--text-muted`/`--border`/`--blue`)
- `PHD2_Agent.spec`: parametro `version='version_info.txt'` in `EXE(...)`
- `build_dist.py`: chiama `write_version_info()`, ZIP rinominato, LEGGIMI
  template branded
- `config.toml`: header commento brandizzato (commento, zero valori toccati)
- `Avvia.bat`: echo di banner branded
- `doc/Manuale_Utente_Agent.md`: copertina markdown
- `doc/Manuale_Utente_Agent .txt`: copertina plain text

### Test
- 59 test verdi (46 pre-§26 + 13 nuovi in `test_about.py`).
- Test anti-regressione email espliciti: `__contact_email__` non esiste;
  `contact_email` non è nel payload; `@` e `mail` assenti dal banner.

### Limiti dell'approccio
1. L'`.exe` PyInstaller mostra i metadata Windows solo dopo che
   `version_info_template.py` viene eseguito **prima** della build. Se per
   errore si lancia PyInstaller a mano senza passare da `build_dist.py`, i
   metadata possono restare vuoti.
2. Il footer della dashboard è statico per sessione (caricato a
   `DOMContentLoaded`). Se in futuro si bumpa la versione mentre la dashboard
   è aperta, l'utente deve ricaricare la pagina per vederla.
3. L'unico canale di feedback è il gruppo Telegram. Utenti che non hanno
   Telegram (caso raro nella nicchia astrofotografica italiana, ma esiste)
   non hanno un canale alternativo. Decisione consapevole per il primo
   rilascio: tutta la community converge in un solo posto, gestione
   centralizzata.
4. Il glifo `©` nel banner Python viene visualizzato come `?` sulla console
   Windows con code page legacy (cp1252) — è una limitazione del terminale,
   il file di log su disco mantiene il glifo UTF-8 corretto. Nei `.bat` e
   `.toml` si è scelto `(c)` ASCII per compatibilità totale.

### Validazione raccomandata
1. Build completa con `python build_dist.py` → ispezione proprietà `.exe`.
2. Avvio `Avvia.bat` → verifica banner console.
3. Apertura dashboard → verifica byline + footer + `/about` JSON.
4. Apertura PDF → verifica metadata (Adobe Reader o anteprima file manager).
5. Verifica nome ZIP finale = `Adaptive_Agent_PHD2_v2.2.zip`.

---

## 27. Plugin NINA opzionale per dashboard embedded — Adaptive Agent for PHD2 — Dashboard (2026-06-02)

### Motivazione
La dashboard web `http://localhost:8080` è già il canale primario di osservazione dello stato dell'Agente, accessibile
da qualsiasi browser (incluso tablet, secondo monitor, PC remoto sulla stessa rete). Tuttavia per chi usa NINA come
suite di acquisizione l'esperienza richiede una finestra browser separata da tenere aperta accanto a NINA. Decisione:
realizzare un plugin C# minimale per NINA che aggiunga a NINA un pannello dockable contenente la stessa dashboard,
caricata via WebView2 embedded. **Valore puramente UX**, zero logica nuova: la dashboard è quella di sempre, solo che
ora vive dentro NINA come scheda dockable.

### Vie considerate prima della scelta
1. **Pubblicazione su GitHub del progetto Python** — accantonata. Niente basi di ritorno economico, niente struttura di
   marketing, e la distribuzione via gruppo Telegram alla community italiana (~1000 utenti) basta come bacino di
   feedback qualificato. GitHub aprirà la porta a internazionalizzazione/contributors solo quando il progetto sarà
   rodato.
2. **Plugin NINA nativo con logica C# riscritta** — scartata. Riscrivere controller, analyzer, baseline, escalation gate,
   auto-calibrazione, refresh ciclico in C# significherebbe mesi di lavoro, doppia implementazione da mantenere allineata
   (debito tecnico permanente), e perdita totale della velocità di iterazione di Python. Tecnicamente sconsigliato anche
   nel lungo termine.
3. **Plugin NINA come WebView locale** — **scelta**. Nessuna logica da riscrivere, nessuna duplicazione, valore puramente
   UX. Costo: un paio di giorni di sviluppo C# minimale.

### Architettura del plugin (progetto separato, non parte del repo Python)
- Repository: `C:\Users\aless\Documents\N.I.N.A\AdaptiveAgentForPHD2.NinaPlugin\`
- Linguaggio: C# WPF, `TargetFramework = net8.0-windows10.0.17763.0` (Windows 10 RS5 minimum, richiesto da WebView2)
- SDK NINA: `NINA.Plugin 3.2.0.9001` (stable, compatibile con NINA 3.3)
- WebView2: `Microsoft.Web.WebView2 1.0.3650.58` (match esatto con la versione che NINA porta nella sua directory;
  `ExcludeAssets=runtime` per evitare duplicati)
- GUID univoco stabile: `6F2E9C19-4F66-4F69-B7D3-E21D5AD7458B` (MAI cambiare nei rilasci futuri — è l'identità del
  plugin per NINA, cambiare significa che NINA tratta la nuova versione come plugin diverso, con doppia voce e perdita
  settings).
- Base classi: `PluginBase` (export come `IPluginManifest`), `DockableVM(IProfileService)` (export come `IDockableVM`)
- Cartella di installazione runtime: `%LOCALAPPDATA%\NINA\Plugins\3.0.0\AdaptiveAgentForPHD2.NinaPlugin\` —
  importante: la cartella `3.0.0\` non è la versione applicazione di NINA, è la versione **API compatibility folder**
  che TUTTA la serie NINA 3.x usa (3.0, 3.1, 3.2, 3.3 leggono tutti i plugin da lì). Ogni plugin vive in una sua
  sotto-cartella per assembly name.

### Componenti del plugin
- `AdaptiveAgentForPHD2Plugin` — entry point `PluginBase`, manifest via `AssemblyMetadata` (Id, Name, Author, Homepage =
  link Telegram community, ChangelogURL, MinimumApplicationVersion = `3.3.0.0`)
- `AdaptiveAgentDashboardVM` — `DockableVM` con `Title = "Adaptive Agent for PHD2"`, `ContentId` e property
  `DashboardUrl = "http://localhost:8080"`. Costruttore `[ImportingConstructor]` riceve `IProfileService`.
- `AdaptiveAgentDashboardView` — UserControl WPF con WebView2, header (titolo + URL + pulsante Reload), pannello di
  fallback "Agente non raggiungibile" con pulsante Riprova (visibile quando `NavigationCompleted.IsSuccess == false`),
  footer copyright.
- `Resources/DataTemplates.xaml` con `[Export(typeof(ResourceDictionary))]` code-behind (convenzione NINA: il key del
  DataTemplate segue il pattern `FullNamespace.ClassName_Dockable`).
- `scripts/install-plugin.ps1` — copia automatica della DLL dalla build nella cartella plugin di NINA.

### Comportamento atteso
- All'avvio NINA carica il plugin e registra il pannello dockable. L'utente può attivarlo dal menu pannelli di NINA.
- Aprendo il pannello: il WebView2 si carica e naviga a `http://localhost:8080`. Se l'Agente Python è in esecuzione, la
  dashboard appare entro 2-3 secondi.
- Se l'Agente NON è in esecuzione (URL non raggiungibile): il pannello di fallback mostra "Agente non raggiungibile.
  Avvia `Avvia.bat` dal pacchetto Adaptive Agent for PHD2, attendi qualche secondo, poi premi Riprova." con pulsante
  Riprova che ri-tenta il caricamento.
- Sequenza di avvio consigliata: PHD2 → `Avvia.bat` → NINA. Se NINA era già aperto, basta il pulsante Riprova dopo
  l'avvio dell'Agente.
- Il plugin **non avvia** `PHD2_Agent.exe`, **non legge** alcun file dell'Agente, **non comunica** con PHD2 in alcun
  modo: i due lifecycle sono completamente separati.

### File modificati nel repo Python (solo documentazione)
- `Pacchetto_Distribuzione/LEGGIMI_PER_AVVIARE.txt` — passo 5 esteso con "DUE MODI" (browser web o plugin NINA);
  nota sequenza di avvio se si usa anche il plugin.
- `README.md` — riga "Plugin NINA opzionale" nella tabella feature; sotto-sezione dedicata in "Avvio rapido".
- `doc/Manuale_Utente_Agent.md` — nuova sezione "Bonus: usare la dashboard dentro NINA (plugin opzionale)" dopo
  la sezione Web Dashboard.
- `doc/Manuale_Utente_Agent .txt` — gemello allineato.
- `doc/build_manual_pdf.py` — sezione equivalente nel PDF (header viola ACCENT2, callout importante sul fatto che il
  plugin è opzionale, lista sequenza di avvio, callout suggerimento WebView2 runtime).
- `doc/Manuale_Utente_Agent.pdf` — rigenerato, 11 pagine, 110 KB.
- `CONTESTO_PROGETTO.md` — data aggiornata, paragrafo §27 aggiunto, voce in "Cosa NON è stato ancora fatto" per la
  validazione del plugin in NINA reale.
- Nessuna modifica al codice Python dell'Agente: `controller.py`, `analyzer.py`, `client.py`, `config.py`, `server.py`,
  `main.py` e i test sono **invariati**.

### Validazione raccomandata (manuale)
1. Riavviare NINA 3.3, andare in Settings → Plugins, verificare che "Adaptive Agent for PHD2 — Dashboard" appaia
   nella lista con stato OK e versione 1.0.0.0.
2. Aprire il menu dockable di NINA, attivare il pannello "Adaptive Agent for PHD2", trascinarlo in posizione.
3. Lanciare `Avvia.bat` → la dashboard deve caricare nel pannello entro pochi secondi.
4. Chiudere l'Agente (Ctrl+C nella console del .bat) → premere Reload sul pannello → il pannello di fallback deve
   apparire con il messaggio e il pulsante Riprova.
5. Rilanciare `Avvia.bat`, premere Riprova → la dashboard torna visibile.

### Limiti dell'approccio
1. URL fisso a `http://localhost:8080`. Se in futuro la porta della dashboard viene resa configurabile nel `config.toml`
   dell'Agente, il plugin non si aggiorna automaticamente. Evoluzione possibile v1.1: settings page del plugin.
2. WebView2 runtime non installato su Windows 10 datati → schermo bianco senza fallback (il fallback scatta solo dopo
   un fallimento di navigazione, non se il controllo WebView2 non riesce neanche a inizializzare). Documentato nel
   manuale: nota su come scaricare il runtime da Microsoft.
3. Nessun health-check proattivo dell'Agente: il fallback scatta solo al primo tentativo di navigazione. Va bene per
   v1.0, evoluzione possibile v1.1: GET periodico su `/about` per mostrare badge "Agente online v2.2".
4. Versione plugin slegata dalla versione Agente: la 1.0.0.0 del plugin è progettata per girare con Agente v2.2 ma non
   c'è enforcement. Pratica accettabile finché lo schema dashboard non cambia in modo breaking.

### Stato finale
Plugin compilato `Release/x64` con 0 errori, 0 warning. DLL installata nel path corretto. README + LICENSE creati nel
repo del plugin. Pronto per la validazione sul campo, e successivamente per la distribuzione opzionale sul gruppo
Telegram della community (probabilmente come ZIP separato dal pacchetto Agente, con istruzioni di installazione
incluse).

## 28. Plugin NINA v1.1 — Launch Agent + badge stato (2026-06-03)

### Motivazione
Chiusura dei limiti #1 e #3 di §27, emersi come evoluzioni naturali: in v1.0 l'URL della dashboard era hard-coded e non
c'era alcun health-check proattivo (il fallback scattava solo dopo un fallimento di navigazione). v1.1 aggiunge due
rifiniture UX leggere che condividono lo stesso piccolo poller: (1) un **badge di stato** sopra il WebView che mostra
"Agente online vX.Y" (verde) o "Agente offline" (grigio), e (2) un pulsante **"Avvia Adaptive Agent"** che lancia
`Avvia.bat` con un click, senza che l'utente debba aprire Esplora Risorse. Resta **valore puramente UX**: nessuna pausa
automatica della sequenza NINA, nessun `ISequenceMediator`, nessuna logica su `/status`, nessuna interferenza col
Sequencer. La logica adattiva continua a vivere interamente nel pacchetto Python.

### Architettura del plugin (progetto separato, repo invariato per path/GUID)
- Repository: `C:\Users\aless\Documents\N.I.N.A\AdaptiveAgentForPHD2.NinaPlugin\` (stesso di §27)
- GUID `6F2E9C19-4F66-4F69-B7D3-E21D5AD7458B` **invariato**; versione plugin `1.0.0.0 → 1.1.0.0` (AssemblyVersion +
  AssemblyFileVersion; `PluginBase.Version` legge `AssemblyFileVersion`).
- **Composition root statico `AgentServices.cs`** invece di MEF `[ImportingConstructor]` nel DockableVM. Decisione
  architetturale chiave: per non rischiare di rompere il caricamento del pannello dockable di v1.0, la firma del
  costruttore di `AdaptiveAgentDashboardVM` resta **identica** (solo `IProfileService`). I tre servizi condivisi
  (`PluginSettings`, `AgentHealthChecker`, `AgentLauncher`) vivono in un singleton `AgentServices.Instance` (Lazy) letto
  sia dal plugin (lifecycle del poller in `Initialize`/`Teardown`) sia dal VM (sottoscrizione a `StatusChanged`). Il
  pragmatismo "non rompere ciò che funziona" ha priorità sulla purezza del pattern DI.
- **Pre-flight con `ilspycmd`** (decompilazione di NINA reale in `C:\Program Files\N.I.N.A...`) per estrarre i nomi
  veri delle API NINA invece di indovinarli:
  - Logger: `NINA.Core.Utility.Logger.Info/Warning/Error(string)`
  - Toast: `NINA.Core.Utility.Notification.Notification.ShowInformation/ShowWarning/ShowError(string)`
  - INPC base: `NINA.Core.Utility.BaseINPC : CommunityToolkit.Mvvm.ComponentModel.ObservableObject`,
    `RaisePropertyChanged()`
  - Command: `CommunityToolkit.Mvvm.Input.AsyncRelayCommand` (NINA ships 8.4.0.1; AssemblyVersion 8.4.0.0 identico →
    bind a runtime OK; `PackageReference` con `ExcludeAssets=runtime`)
  - **Chiave pagina opzioni**: `NINA.ViewModel.Plugins.PluginOptionsDataTemplateSelector` risolve un `DataTemplate` con
    chiave `IPluginManifest.Name + "_Options"`, e `PluginBase.Name` deriva da `AssemblyTitle`. Quindi la chiave è
    `"Adaptive Agent for PHD2 — Dashboard_Options"` con **EM DASH U+2014**, verificata **byte-per-byte nel BAML
    compilato** (prefisso lunghezza 0x2D = 45 byte UTF-8, sequenza E2 80 94). Il DataContext del template è l'istanza
    reale del plugin (i plugin installati sono `IDictionary<IPluginManifest,bool>`, chiave = plugin) → bind a
    `{Binding Settings}`.
  - Settings persistence: nel SDK `NINA.Plugin 3.2.0.9001` **non esiste** `IPluginOptionsAccessor` → serializzazione
    JSON manuale.

### Componenti aggiunti
- `Settings/PluginSettings.cs` — modello `BaseINPC` con tre property: `AgentBatPath` (default vuoto),
  `HealthCheckIntervalSeconds` (default 15, clamp 5–120), `DashboardUrl` (default `http://localhost:8080`). Persistenza
  JSON automatica su ogni set in `%LOCALAPPDATA%\NINA\Plugins\AdaptiveAgentForPHD2.NinaPlugin\settings.json` (fuori dalla
  cartella versionata `3.0.0\`, così sopravvive ai reinstalli). Evento `IntervalChanged` per riarmare il timer del poller.
- `Settings/PluginSettingsView.xaml(.cs)` — pagina opzioni sobria (tema NINA via stili impliciti), pulsante "Sfoglia..."
  che apre `Microsoft.Win32.OpenFileDialog` filtrato `*.bat`.
- `Health/AgentHealthChecker.cs` — poller condiviso: `HttpClient` timeout 3s, `System.Threading.Timer` ogni
  `HealthCheckIntervalSeconds`, `GET <DashboardUrl>/about`. 2xx con JSON valido → Online + `version`; refused/timeout/5xx/
  JSON malformato → Offline (mai eccezioni propagate). Espone `AgentHealth(bool IsOnline, string? Version)`, property
  `Current` ed evento `StatusChanged` invocato **solo sulle transizioni** (record equality); `Logger.Info` **solo** su
  online↔offline, mai a ogni tick.
- `Launch/AgentLauncher.cs` — `LaunchAsync(batPath)` con validazioni (vuoto → NotConfigured, inesistente → FileNotFound),
  `Process.Start` con `UseShellExecute=true` (serve per il .bat) e **`WindowStyle.Minimized`** (la console parte
  minimizzata ma resta chiudibile manualmente dall'utente). `LaunchResult` con `Level` (Info/Warning/Error) per scegliere
  il tipo di toast. Non attende che l'Agente sia up: la conferma arriva dal poller entro l'intervallo.
- `AgentServices.cs` — composition root statico (vedi Architettura).
- `Dashboard/AdaptiveAgentDashboardVM.cs` esteso — badge (`StatusBadgeText`/`StatusBadgeBackground` verde/grigio
  frozen+thread-safe), pulsante (`LaunchButtonText`/`Enabled`/`Tooltip`), `AsyncRelayCommand` con toast per ogni esito;
  update UI marshalato su `Application.Current.Dispatcher`. `DashboardUrl` ora letto dalle settings.
- `Dashboard/AdaptiveAgentDashboardView.xaml` esteso — nuova riga in cima (badge a sinistra + pulsante a destra) **sopra**
  l'header e il WebView v1.0 invariati.

### Comportamento atteso
- Badge offline (grigio) all'apertura del pannello con Agente non in esecuzione.
- Pulsante abilitato solo quando l'Agente è **offline** *e* `AgentBatPath` è configurato; testo sostitutivo "Configura
  percorso Avvia.bat nelle settings" quando il path è vuoto; **disabilitato quando l'Agente è online** (tooltip "Agente
  già in esecuzione", no-op per non lanciarlo due volte).
- Click su "Avvia Adaptive Agent" → la console del `.bat` si apre minimizzata; entro l'intervallo di polling il badge
  transita a verde "Agente online vX.Y" e il pulsante si disabilita. Chiudendo la console (Ctrl+C) il badge torna grigio
  entro un intervallo.
- Il path deve puntare al `Avvia.bat` del pacchetto Python, **non** al DLL del plugin (un `.dll` non è shell-eseguibile:
  Windows risponde "Nessuna applicazione associata", catturato e mostrato come toast d'errore).

### File modificati nel repo Python (solo documentazione + distribuzione)
- `Pacchetto_Distribuzione/LEGGIMI_PER_AVVIARE.txt` — blocco "NOVITA' v1.1 (Launch Agent + badge stato)" in coda alla
  sezione "(*) COME INSTALLARE IL PLUGIN NINA".
- `doc/Manuale_Utente_Agent.md` / `doc/Manuale_Utente_Agent .txt` / `doc/build_manual_pdf.py` — sotto-paragrafo
  "Novità v1.1: pulsante Avvia e badge stato" nella sezione Bonus NINA; PDF rigenerato.
- Nuova cartella `AdaptiveAgentForPHD2.NinaPlugin/` (DLL v1.1.0.0) e ZIP `Adaptive_Agent_PHD2_v2.2.zip` per la
  distribuzione community.
- Nessuna modifica al codice Python dell'Agente: invariato.

### Validazione (sul campo, superata)
NINA carica v1.1.0.0; badge grigio "Agente offline" all'apertura; pagina opzioni accessibile da Options → Plugins con
"Sfoglia" che apre l'OpenFileDialog `.bat`; dopo aver impostato il path, "Avvia Adaptive Agent" lancia la console
minimizzata e dopo l'intervallo il badge passa verde con la versione e il pulsante si disabilita. Build `Release/x64`
0 errori / 0 warning.

### Limiti
1. Solo localhost: poller e WebView puntano all'host configurato (default `localhost:8080`), pensato per Agente sulla
   stessa macchina di NINA.
2. Nessuna auto-pause della sequenza NINA né reazione a `/status`: è una scelta deliberata (eventuale auto-pause
   rivalutabile in futuro solo se emergerà dai feedback).
3. ~550 righe C# nette nuove (sopra la stima iniziale ~200), dovute a verbosità INPC e commenti, non a scope creep:
   ogni riga mappa su un requisito. Scelta confermata di non rifattorizzare codice funzionante e leggibile.

### Stato finale
Plugin v1.1.0.0 compilato 0/0, installato, validato sul campo. Documentazione (NOTE §28, README plugin, LEGGIMI,
manuale 3 formati) aggiornata. Cartella plugin + ZIP `Adaptive_Agent_PHD2_v2.2.zip` pronti per la distribuzione opzionale
sul gruppo Telegram come aggiornamento.

## 29. Plugin NINA v1.2 — Safety Monitor virtuale + auto-reload WebView (2026-06-03)

Sezione unica che copre la linea v1.2 completa: `1.2.0.0` (Safety Monitor), `1.2.1.0` (auto-reload WebView su
transizione online), `1.2.2.0` (fix reload su cambio schermata). Tutto nel repo plugin separato
`C:\Users\aless\Documents\N.I.N.A\AdaptiveAgentForPHD2.NinaPlugin\`; nel repo Python solo documentazione + distribuzione.

### Motivazione
Estendere il **modello safety nativo di NINA** con un driver virtuale che riflette lo stato della guida dell'Agente.
Filosofia "separation of concerns": il plugin **osserva e segnala** (flag `IsSafe`), **NINA decide e agisce** in base
alle policy configurate dall'utente (Options → Safety, oppure Advanced Sequencer `Trigger On Unsafe` / `Wait until safe`).
Idiomatica nel modello equipment di NINA, **zero invasività su `ISequenceMediator`**: il plugin non mette mai in pausa
la sequenza di testa propria, si limita ad aggiornare il flag che NINA già sa interpretare.

### Architettura del Safety Monitor (v1.2.0.0)
- **Pattern MEF reale (scoperto via pre-flight `ilspycmd` PRIMA di scrivere codice)**: NINA per l'equipment custom dei
  plugin **non** importa `[Export(typeof(ISafetyMonitor))]`. Il `PluginLoader` fa `[ImportMany(typeof(IEquipmentProvider))]`
  (classe `NINA.Plugin.PartsImport`); il `PluginEquipmentProviderManager` riflette l'argomento generico di
  `IEquipmentProvider<T>` e instrada il provider al `IEquipmentProviders<T>` giusto via `AddProvider`; infine il
  `SafetyMonitorChooserVM.GetEquipment()` (in `NINA.WPF.Base`) chiama `provider.GetEquipment()` e popola la tendina.
  → Il contratto corretto è **`[Export(typeof(IEquipmentProvider))]` su `AdaptiveAgentSafetyMonitorProvider :
  IEquipmentProvider<ISafetyMonitor>`** con `string Name` + `IList<ISafetyMonitor> GetEquipment()`, **non**
  l'export diretto di `ISafetyMonitor`. Questa correzione è la scoperta-chiave del pre-flight (il prompt iniziale
  assumeva l'export diretto, che NINA non avrebbe mai visto).
- **Driver `AdaptiveAgentSafetyMonitor : BaseINPC, ISafetyMonitor`** (stesse convenzioni del `SafetyMonitorSimulator`
  di NINA): `Category = "N.I.N.A."`, `DisplayName = "Adaptive Agent for PHD2 — Guide Safety"`, GUID stabile
  `10A715AD-903C-499E-9CC7-CA8E66A49B7C` **distinto** dal GUID plugin `6F2E9C19-4F66-4F69-B7D3-E21D5AD7458B`.
  (Il GUID suggerito nel prompt era malformato — 9 cifre esadecimali nel primo gruppo — intercettato e rigenerato valido.)
  `ISafetyMonitor : IDevice` richiede Connect/Disconnect/SetupDialog + Id/Name/DisplayName/Category/Connected/Description/
  DriverInfo/DriverVersion/SupportedActions + Action/SendCommand*.
- **Decision engine `SafetyDecisionEngine` — una sola condizione di unsafe**: `guiding_state == "STAR_LOST"` consolidato
  per `StarLostConsolidationSeconds` (default 300 = 5 minuti → 20 tick a 15s). **Esclusi esplicitamente**:
  `escalation_gate.ra && escalation_gate.dec` (è l'apertura del path B esposizione §19, NON un'emergenza),
  `saturation.active` (azione di recovery dell'AI Star Finder, NON un fallimento), RMS oltre soglia (soglia dinamica:
  quando viene superata l'Agente sta già reagendo). Stati neutrali (`INACTIVE`/`DEGRADED`/`CRITICAL`/`RECOVERING`/altro)
  non triggerano nulla e resettano il contatore STAR_LOST.
- **Asimmetria temporale intenzionale**: 5 minuti per dichiarare unsafe (alta evidenza: l'AI Star Finder dovrebbe
  recuperare entro quel tempo se è recuperabile); ~45s (3 poll `NORMAL` consecutivi) per tornare safe (reattività al
  recupero, per non perdere finestre di acquisizione).
- **Connected / auto-disconnect**: il driver si auto-disconnette (`Connected = false`) quando l'Agente smette di
  rispondere a `/about`. NINA legge `IsSafe`/`Connected` via **polling** (`SafetyMonitorVM` usa un `DeviceUpdateTimer`
  a `DevicePollingInterval`, verificato nel pre-flight — **non** via `PropertyChanged`), quindi basta impostare
  `Connected=false` per propagare la disconnessione; NINA tratta la perdita di comunicazione come "safety scollegato"
  e applica la policy utente (più onesto che servire stale data).
- **Settings**: una sola property nuova `StarLostConsolidationSeconds` (default 300, range 30–1800), persistita nello
  stesso `settings.json` della v1.1 (utenti che aggiornano da v1.1: chiave assente → default 300 al primo run).
- **Polling esteso**: `AgentHealthChecker` (v1.1) ora legge anche `GET /status` quando il safety è connesso
  (`StatusPollingEnabled`), estraendo **solo** `controller.guiding_state` via `JsonDocument` (niente DTO pesante);
  evento `StatusUpdated(AgentStatusSnapshot)` a ogni tick (il decision engine conta tick consecutivi). Quando il driver
  è disconnesso torna a leggere solo `/about` (efficienza: niente payload più pesante se non serve).

### Auto-reload WebView (patch v1.2.1.0)
Risolve un retaggio di design v1.0: il pannello di fallback "Agente non raggiungibile" restava visibile finché l'utente
non premeva manualmente "Riprova", anche se il poller v1.1 sapeva già che l'Agente era tornato online (i due meccanismi
— poller del badge e WebView — non si parlavano). Fix: il code-behind del View si sottoscrive a `StatusChanged` e, sulla
transizione **offline → online**, chiama `NavigateToDashboard()` marshalato sul UI thread (`Dispatcher.Invoke`).
Sottoscrizione su `Loaded` (con `-=`/`+=` difensivo), disiscrizione su `Unloaded` (no leak). Pulsante "Riprova" manuale
**invariato** come fallback per casi limite. ~22 righe nel code-behind. Nota: `StatusChanged` è un `Action<AgentHealth>`
(non un `EventHandler`), quindi handler a **singolo parametro** `OnAgentHealthChanged(AgentHealth health)`.

### Fix cambio schermata (patch v1.2.2.0)
La v1.2.1 copriva "Agente torna online durante la sessione", ma non "View ricaricato da NINA dopo cambio schermata".
Quando NINA scarica/ricarica un pannello dockable (cambio tab o layout), il `Loaded` del View provoca un nuovo `Navigate`
del WebView2; se il primo `NavigationCompleted` arriva con `IsSuccess=false` (timing sfortunato con risorse sub-page) il
fallback si attiva. Ma il poller dice già online (stato condiviso nel composition root) → **nessuna transizione** →
l'handler v1.2.1 non scatta → fallback resta. Fix: nel `Loaded`, dopo la sottoscrizione, check immediato dello stato
corrente del poller (`AgentServices.Instance.HealthChecker.Current.IsOnline`); se online, schedula `NavigateToDashboard()`
ritardato di 500ms (`await Task.Delay(500)` + `Dispatcher.BeginInvoke` con `DispatcherPriority.Background`, per dar tempo
al primo Navigate di completare prima di correggerlo). Aggiunto guard difensivo `if (!IsLoaded) return;` nell'handler
(evita operazioni su un View fuori dalla visual tree). ~12 righe nette. Il `Dispatcher.BeginInvoke` restituisce una
`DispatcherOperation` awaitable → in metodo `async` genera CS4014: risolto con discard esplicito `_ = Dispatcher.BeginInvoke(...)`
per mantenere il build a 0 warning.

### File modificati nel repo plugin (NON nel repo Python)
- `src/.../Safety/AdaptiveAgentSafetyMonitorProvider.cs` (nuovo — entry MEF `[Export(typeof(IEquipmentProvider))]`)
- `src/.../Safety/AdaptiveAgentSafetyMonitor.cs` (nuovo — driver `ISafetyMonitor`)
- `src/.../Safety/SafetyDecisionEngine.cs` (nuovo — logica STAR_LOST consolidato / resume NORMAL×3)
- `src/.../Health/AgentHealthChecker.cs` (esteso: `StatusPollingEnabled`, `StatusUpdated`, probe `/status` mirato via `JsonDocument`, one-shot probes per `Connect`)
- `src/.../Settings/PluginSettings.cs` + `PluginSettingsView.xaml` (1 property nuova `StarLostConsolidationSeconds`)
- `src/.../AgentServices.cs` (`Lazy<SafetyDecisionEngine>`, `Lazy<AdaptiveAgentSafetyMonitor>` — composition root singleton)
- `src/.../Dashboard/AdaptiveAgentDashboardView.xaml.cs` (auto-reload v1.2.1 + fix cambio schermata v1.2.2)
- `Properties/AssemblyInfo.cs` + `.csproj`: versione → **1.2.2.0**, GUID plugin **INVARIATO**

### File modificati nel repo Python (solo documentazione + distribuzione)
- `Pacchetto_Distribuzione/LEGGIMI_PER_AVVIARE.txt` (+ template embedded in `build_dist.py`): blocco "NOVITA' v1.2
  (Safety Monitor virtuale opzionale)" in coda alla sezione "(*) COME INSTALLARE IL PLUGIN NINA".
- `doc/Manuale_Utente_Agent.md` / `.txt` / `build_manual_pdf.py`: sotto-paragrafo "Novità v1.2: Safety Monitor virtuale"
  nella sezione "Bonus: usare la dashboard dentro NINA"; PDF rigenerato.
- Nessuna modifica al codice Python dell'Agente: invariato.

### Validazione (sul campo, superata)
- Simulator NINA + Agente simulator con `StarLostConsolidationSeconds=30` per test rapido: safe→unsafe dopo ~30s di
  STAR_LOST consolidato, ritorno safe dopo ~45s di NORMAL ✓
- Auto-reload sulla transizione offline→online del poller ✓
- Pannello stabile su cambio schermata NINA dopo fix v1.2.2 ✓
- Pulsante "Riprova" manuale continua a funzionare ✓
- Pulsante "Avvia Adaptive Agent" + badge stato v1.1 invariati; WebView v1.0 invariato ✓
- Build `Release/x64` 0 errori / 0 warning su tutte e tre le patch.

### Limiti
1. **Una sola condizione unsafe** (STAR_LOST consolidato). Condizioni multi-criterio più sofisticate potrebbero emergere
   dai feedback Telegram → eventuale v1.3.
2. Il fix v1.2.2 ricarica il WebView 500ms dopo il `Loaded`; in casi rari di apertura/chiusura rapidissimi del pannello
   può esserci un breve flash visivo. Accettabile per v1.2.
3. Le **reazioni concrete** a un unsafe (pausa sequenza, parking, warm-up camera, ecc.) NON sono nel plugin: si
   configurano in NINA tramite Options → Safety (policy globale) o Advanced Sequencer (`Trigger On Unsafe`,
   `Wait until safe`). È una scelta di design, non una mancanza.

### Stato finale
Plugin v1.2.2.0 stabile, installato in `%LOCALAPPDATA%\NINA\Plugins\3.0.0\AdaptiveAgentForPHD2.NinaPlugin\`, validato sul
campo. Documentazione (NOTE §29, LEGGIMI, manuale 3 formati) aggiornata. Cartella plugin + ZIP `Adaptive_Agent_PHD2_v2.2.zip`
rigenerati (DLL v1.2.2.0). Naming pacchetto invariato (`v2.2`): l'Agente Python è invariato, il versionamento del plugin è
interno. Pronto per la distribuzione opzionale sul gruppo Telegram insieme all'Agente Python v2.2.

### Patch v1.2.3.0 (compatibilità NINA 3.2 stable) — 2026-06-04

**Problema.** Dopo la distribuzione pubblica, un astrofilo del gruppo Telegram con **NINA 3.2 stable** ha riportato
l'errore *"Failed to load plugin Adaptive Agent for PHD2 — Dashboard version 1.2.2.0"*. Sui setup con NINA 3.3 nightly
(quello di Alessandro) il plugin si caricava regolarmente.

**Causa (identificata dal pre-flight).** La v1.2.2.0 era stata compilata contro `Microsoft.Web.WebView2 1.0.3650.58`,
versione shipped **solo da NINA 3.3 nightly**. WebView2 usa versioning stretto (l'`AssemblyVersion` coincide con la versione
completa): l'assembly del plugin richiedeva quindi a runtime `Microsoft.Web.WebView2.Core, Version=1.0.3650.58`, ma NINA 3.2
stable nella propria directory fornisce solo la `1.0.3296.44` → il bind falliva → *"Failed to load plugin"*. Il pre-flight,
eseguito leggendo direttamente le DLL della NINA 3.2.0.9001 installata, ha mostrato che **le altre due dipendenze erano già
corrette**: `NINA.Plugin 3.2.0.9001` è proprio la versione di 3.2 stable (non, come ipotizzato inizialmente, una 3.3 nightly)
e `CommunityToolkit.Mvvm 8.4.0` (AssemblyVersion 8.4.0.0) coincide con quella shipped da 3.2 stable. Quindi **l'unico
colpevole era WebView2**.

**Fix.** Downgrade della sola dipendenza WebView2 nel `.csproj`: `1.0.3650.58` → **`1.0.3296.44`** (versione shipped da NINA
3.2 stable). `NINA.Plugin` e `CommunityToolkit.Mvvm` lasciati invariati. `ExcludeAssets=runtime` mantenuto su tutte e tre
(NINA fornisce le DLL a runtime, non le duplichiamo — verificato che la cartella plugin installata contiene solo
`AdaptiveAgentForPHD2.NinaPlugin.dll`). **Nessuna modifica al codice C# del plugin**: pura ricompilazione mirata. Bump versione
`1.2.2.0` → `1.2.3.0` in `.csproj` e `AssemblyInfo.cs`. GUID plugin e GUID Safety Monitor invariati; `MinimumApplicationVersion`
resta `3.0.0.0`. Build `Release/x64` 0 errori / 0 warning; l'assembly risultante referenzia ora `WebView2 1.0.3296.44`.

**Risultato.** Una sola build copre entrambi i target: gira su NINA 3.2 stable e, grazie alla forward compatibility, anche su
NINA 3.3 nightly. **Validazione cross-version eseguita due volte da Alessandro**: disinstallata 3.3 nightly → installata 3.2
stable → plugin v1.2.3.0 caricato e funzionante (versione visibile in Options → Plugins, pannello dockable + badge + pulsante
Avvia + Safety Monitor tutti OK) → reinstallata 3.3 nightly → riconfermato senza regressioni. Procedura ripetuta due volte.
Cartella distribuzione plugin aggiornata e ZIP `Adaptive_Agent_PHD2_v2.2.zip` rigenerato (1382 entry, DLL plugin v1.2.3.0,
50176 byte). Naming pacchetto invariato (`v2.2`): l'Agente Python è invariato, è solo il plugin a essere bumpato.

---

## 30. Satisfaction gate sulla mediana baseline — Agente v2.3 (2026-06-06)

### Motivazione
Osservazione sul campo di Alessandro: nel ramo "guida ottima" (CASO 3 di `_evaluate_axis`) il controller spingeva
Aggressività UP e MinMove DOWN in modo **monotòno** a ogni cooldown finché `rms < rms_low`, con unica condizione
d'arresto lo sbattere contro i bound estremi (`aggr_max=90`, `minmove_min=0.15`, §24). Risultato: anche quando l'RMS
era già sceso al livello della mediana baseline misurata (cioè la guida era di fatto al target), il controller
continuava a "indurire" le leve verso la reattività massima. Leve troppo reattive in un cielo già buono producono
**guida nervosa** che insegue il rumore atmosferico anziché stabilizzarsi → l'RMS torna lentamente a salire senza che
il controller se ne accorga (finché resta sotto `rms_low` continua a spingere nella stessa direzione).

### Soluzione adottata
Satisfaction gate **stateless** sulla mediana baseline. Alternativa scartata: hill-climb regret-aware con memoria del
best (`prompts_storici/PROMPT_SETTLE_LEVE_MEDIANA_BASELINE.md`) — troppo complesso per il caso reale, richiedeva stato
persistente e reset su ogni cambio regime/esposizione/baseline. Il gate stateless cattura lo stesso intent ("non
spingere oltre se sei già al target") con una pura condizione di tick.

### Architettura
- Gate valutato all'inizio del CASO 3, **prima** delle azioni legacy su Aggr/MinMove. Se
  `enabled and _rms_baseline_value is not None and not _rms_baseline_rejected` e `rms <= mediana × target_factor`
  → `return actions` immediato (nessuna azione su quel tick). Altrimenti il CASO 3 procede invariato (codice v2.2).
- **Stateless**: nessun campo nuovo in `AxisState`, nessun reset su eventi. Lo "stato del gate" è solo la condizione
  `rms <= target` rivalutata a ogni tick. Se l'RMS risale, il gate rilascia automaticamente le leve.
- **Asimmetria intenzionale**: il gate vive solo nel CASO 3 (ramo `elif rms < rms_low`). CASO 1 (degradato,
  `rms > rms_high`) e CASO 2 (oscillazione) sono in `elif` separati e non vengono mai raggiunti quando il gate
  scatta. Quando il seeing peggiora, le leve continuano ad ammorbidirsi fino all'eventuale escalation gate §19.
- Unità omogenee: `_rms_baseline_value` è la mediana di `rms_total` in arcsec (§22/§25); il gate la confronta con
  l'`rms` per-asse (anch'esso arcsec) passato a `_evaluate_axis`.

### Comportamento
- `enabled=false` → `baseline_target_available=False` → CASO 3 legacy, identico a v2.2.
- baseline non finalizzata (`_rms_baseline_value is None`, warm-up) → gate non scatta, CASO 3 legacy.
- baseline rifiutata (`_rms_baseline_rejected=True`, §23) → mediana non rappresentativa, gate non scatta, CASO 3 legacy.
- Logging a livello DEBUG (`[opt] {asse}: gate attivo ...`) per non sporcare `decisions_*.jsonl` quando il gate è
  attivo per molti tick consecutivi in cielo buono.
- `get_status` espone il blocco globale `lever_optimization` (`enabled`, `target_factor`, `target_median_arcsec`).
  Il sotto-blocco per-asse `active_now` NON è stato implementato: manca una property `last_rms` per-asse nel
  controller (la dashboard confronta a vista RMS corrente vs `target_median_arcsec`).

### Parametri (CONFERMATI da Alessandro)
`enabled=true` di default (deroga consapevole alla convenzione "feature OFF": v2.3 è un miglioramento visibile che i
beta tester devono vedere subito sui valori RMS). `target_factor=1.0` (ferma se RMS <= mediana). Bounds leve INVARIATI
(35-90, 0.15-0.85). Niente memoria del best, niente reset, niente hill-climb.

### File modificati
- `phd2_agent/__about__.py`: bump `__version__` 2.2 → 2.3, `__version_tuple__` (2,3,0,0). Propaga automaticamente a
  banner d'avvio, endpoint `/about`, metadata `.exe` (version_info_template), metadata PDF manuale.
- `phd2_agent/config.py`: nuova `LeverOptimizationConfig` (enabled=True, target_factor=1.0), campo in `AgentConfig`,
  parsing TOML retrocompatibile.
- `phd2_agent/controller.py`: gate all'inizio del CASO 3 di `_evaluate_axis` (~30 righe) + blocco `lever_optimization`
  in `get_status`.
- `config.toml`: header v2.3 + nuova sezione `[lever_optimization]`.
- `build_dist.py`: blocco "NOVITA' v2.3" nel template LEGGIMI; commento stale v2.2 generalizzato.
- `doc/Manuale_Utente_Agent.md` / `.txt`: copertina v2.3 + sotto-paragrafo accessibile in "Cosa fa in automatico".
- `tests/test_lever_optimization_gate.py`: nuovo file, 8 test (gate attivo/inattivo, enabled=false, baseline
  None/rifiutata, CASO 1 invariato, retrocompat TOML). Suite totale: 67 test verdi.

### Limiti / Note
- Il gate dipende dalla baseline finalizzata: in warm-up e su baseline rifiutata (§23) il comportamento è quello
  legacy v2.2 (corretto: senza un target rappresentativo non avrebbe senso fermarsi).
- Gate stateless = zero complessità di reset su cambio regime/esposizione/baseline.
- Plugin NINA INVARIATO (DLL resta v1.2.3.0): è solo l'Agente Python a passare a v2.3.

### Validazione raccomandata
1. Sessione reale con baseline finalizzata: quando l'RMS scende sotto la mediana, osservare sulla dashboard che le
   leve smettono di muoversi (nessuna azione Aggr UP / MinMove DOWN in `decisions_*.jsonl`).
2. Se il cielo peggiora (RMS sopra mediana), le leve riprendono il movimento.
3. Tuning: gate sempre attivo → abbassare `target_factor` (0.9); troppe oscillazioni in cielo buono → alzare (1.1).

---

## 31. Seeing Diagnostic Engine (jitter + lag-1) — modalità JITTER e GUARDIAN — Agente v2.4 (2026-06-08)

### Motivazione
La v2.3 decide sul solo RMS: sa *quanto* è degradata la guida, non *perché*. Il motore aggiunge due metriche
ricavate dai dati GuideStep già ingeriti (nessuna RPC nuova, nessun FITS): **jitter** RMS frame-to-frame
(velocità del movimento residuo) e **autocorrelazione lag-1** di RA/DEC (struttura: <<0 = il segno si ribalta
ogni frame → oscillazione di loop; >0 = deriva correlata). Combinate con RMS, **HFD** (allargamento stella) e
trend danno una diagnosi *causale* del regime: SEEING (turbolenza: HFD alto + jitter alto), OVERCORRECTION
(loop che oscilla: lag-1 fortemente negativo, HFD nella norma), DRIFT (deriva direzionale: trend alto,
jitter/HFD normali), NOMINAL. Il jitter da solo è ambiguo (residuo di loop chiuso): si decide SEMPRE sulla
diagnosi combinata. Scartate le ipotesi "shadow" (osservazione senza azione — coincide col motore spento) e
"ab_alternate" (troppa complessità per la validazione sul campo): due usi netti, `jitter` (ricerca) e
`guardian` (distribuibile).

### Architettura (file modificati)
- `phd2_agent/analyzer.py`: `_compute()` calcola `jitter_rms`/`jitter_n` e `lag1_ra`/`lag1_dec`; nuova funzione
  pura `_lag1_autocorr`; 7 campi default in `AnalysisSnapshot` (retrocompatibili). `_classify` (incl.
  OSCILLATING/trend) NON modificato: lag-1 è il segnale del motore, separato.
- `phd2_agent/diagnostic_engine.py` (NUOVO): `SeeingDiagnosticEngine` con reference EMA `_jitter_ref`/`_hfd_ref`,
  `classify()`→`DiagnosisResult` (stato, confidence provvisoria non calibrata, `LeverProposal` di direzione,
  `label` IT, `evidence` ✓/◦, booleani grezzi), `review()`→`GuardianVerdict` (CONFIRM/ATTENUATE/BLOCK),
  `micro_proposal()`, `get_state()`. NON accede mai a `self.client`.
- `phd2_agent/controller.py`: `_make_diagnostic_engine`/`_init_diagnostic_engine`; `_engine_owns_levers`
  (jitter) / `_guardian_active`; classify in `evaluate()`; sospensione CASO 1/2/3 in `_evaluate_axis` (solo
  jitter); `_apply_with_guardian` ai punti `_apply` dei CASO (review + `current_*` solo se applicato);
  `_evaluate_engine_actions` (jitter), `_guardian_micro_correction`; outcome pre/post
  (`_open_outcome`/`_track_outcome`/`_finalize_outcome`); `set_diagnostic_mode`/`_apply_mode_transition`/
  `_restore_levers_to_baseline`; `diagnostic_summary_context`; blocco in `get_status`.
- `phd2_agent/config.py`: `DiagnosticEngineConfig` + parsing (validazione `mode`, fallback "guardian").
- `phd2_agent/logger.py`: 11 colonne CSV §31 (incl. `jitter_ref`/`hfd_ref`/`rms_high_active`/`rms_low_active`
  per lo sweep offline delle soglie), `experimental_<session_id>.jsonl` (`schema_version`,
  `metrics_at_decision` grezzi+ref, `thresholds_active`, `v23_proposed`, `outcome` pre/post/post_max/delta),
  summary con blocco `context` + `state_counts`/`guardian_counts`.
- `server.py`: `POST /config/diagnostic_mode` ("off"/"jitter"/"guardian"). `main.py`: wiring
  `controller.session_logger`↔`session_logger.bind_controller`; `engine.reset()` ai reset analyzer.
- `dashboard/`: card "Seeing Diagnostic Engine" (HERO diagnosi colorata + evidenze → azione/esito → dettaglio
  tecnico collassabile → switcher OFF/GUARDIAN/JITTER). `__about__.py`: 2.3 → 2.4.

### Comportamento
- **`enabled=false` (default di fabbrica)**: il motore NON è istanziato → comportamento identico alla v2.3
  (verificato: `_apply_with_guardian` in non-guardian è `_apply` + riallineo `current_*`, bit-identico ai
  rami CASO della v2.3; suite test verde).
- **`jitter`**: il motore è unica autorità su Aggr/MinMove. I rami CASO 1/2/3 di `_evaluate_axis` ritornano
  `[]`. Decide *quando*; il *quanto* resta `[limits]`/cooldown v2.3. DRIFT/UNCERTAIN → nessuna azione; NOMINAL
  ottimizza solo sopra mediana baseline (§30). Logging azione→esito in `experimental_*.jsonl`.
- **`guardian`**: la v2.3 pilota. Il motore (a) rivede le mosse leva v2.3: CASO1 in DRIFT → BLOCK, CASO3 aggr↑
  in OVERCORRECTION → BLOCK, CASO1 MinMove↑ in OVERCORRECTION → ATTENUATE, altrimenti CONFIRM; fail-safe (in
  dubbio CONFIRM). (b) Fa micro-correzioni proprie ad ampiezza ridotta (`guardian_action_factor`) SOLO dove la
  v2.3 è ferma nel tick e la diagnosi è confidente SEEING/OVERCORRECTION. Mai mentre la v2.3 agisce; DRIFT
  escluso.
- L'esposizione resta SEMPRE gestita dalla v2.3 (§19): il motore non la tocca mai, né backlash/star-lost.

### Limiti / Note
- Il jitter è un residuo di loop chiuso: ambiguo da solo, sempre combinato con HFD (seeing vs over-correzione)
  e lag-1 (oscillazione vs deriva). Soglie/confidence sono **provvisorie, non calibrate** (`confidence_calibrated=False`):
  la dashboard lo segnala. La calibrazione è demandata alla v2.5 (dataset `experimental_*.jsonl` già nel formato).
- Dipendenza dall'esposizione mitigata azzerando le reference EMA a ogni cambio esposizione (8 punti
  `analyzer.reset()` ↔ `engine.reset()` paired) e su dither/StartGuiding.
- `analyzer._classify` (OSCILLATING/trend) NON toccato: due classificatori distinti convivono (v2.5
  riconcilierà).
- Guardian è un assistente *attivo* gentile (micro-correzioni nei buchi), non solo una rete passiva di review.

### Validazione
- `jitter` (Alessandro): analizzare le finestre outcome (pre/post in `experimental_*.jsonl`) negli episodi
  DRIFT/OVERCORRECTION — NON l'RMS medio aggregato.
- `guardian` (flotta): nei log `axis="guardian"` verificare BLOCK/ATTENUATE sensati (motivi DRIFT/OVERCORRECTION),
  le micro-correzioni nei buchi, il fail-safe nei dubbi. Tarare `jitter_high_factor`/`hfd_high_factor`
  (SEEING spuri), `lag1_oscillation_thresh` (OVERCORRECTION non rilevata), `trend_drift_min` (DRIFT frequente),
  `guardian_min_confidence`/`guardian_action_factor`.
- v2.5: eventuale guardian default flotta (`enabled=true`); baseline jitter per-esposizione; auto-valutazione
  soglie dal dataset; riconciliazione con OSCILLATING/§30.

### Test
`tests/test_diagnostic_engine.py` (37 test: jitter/lag-1, classify SEEING/OVERCORRECTION/DRIFT/NOMINAL gate/
INSUFFICIENT, review BLOCK/ATTENUATE/fail-safe, micro, cold-start, bounds, CASO sospesi in jitter,
set_diagnostic_mode, last_outcome/reset). `tests/test_get_status.py` aggiornato (blocco a motore spento).
Suite totale: 105 test verdi.

## 32. Recupero MinMove nella banda morta (asimmetria leve §4) — Agente v2.5 (2026-06-12)

### Motivazione
Sintomo storico (v2.2/2.3/2.4, osservato da Alessandro sul campo): MinMove si **congela al floor 0,15 e non
risale** anche quando dovrebbe ammorbidire (vento). Causa radice confermata sul codice: la catena CASO della
v2.3 ha **trigger asimmetrici con un'ampia banda morta**. MinMove **scende** quando `rms < rms_low` (CASO 3,
frequente su cielo buono) ma **risale solo** quando `rms > rms_high` (CASO 1, raro). Tra `rms_low` e `rms_high`
— la **banda morta** — nessun ramo scatta e la leva resta dov'è (al floor). Quantificato sui log notte 2026-06-11
(Askar 1,579″/px, GUARDIAN, `session_20260611_003714`): **745/1253 frame (59%) in banda morta**, asimmetria di
opportunità ~35:1 (663 `consec_low≥5` vs 19 `consec_high≥5`). NON è un bug del §31: precede l'HFD. Riferimento:
`DESIGN_RATIONALE_LEVER_RESPONSIVENESS.md`.

### Cosa fa (fix minimo, puro-RMS, solo MinMove)
Aggiunge alla catena CASO un **ramo di recupero** (ultimo `elif` di `_evaluate_axis`, attivo a motore **OFF** e
in **GUARDIAN**; in **JITTER** la catena è sospesa → fuori scope). È il **complemento speculare del satisfaction
gate §30**, sulla stessa àncora (mediana baseline): §30 = "se `rms ≤ mediana` non spingere verso la reattività";
recupero = "se `rms > mediana` persistente nella banda morta, alza MinMove di un gradino verso la morbidezza".
- **Trigger:** `rms_total > mediana × minmove_recovery_factor` per `consecutive_frames` tick (contatore globale
  `_recovery_consec`, aggiornato una volta per tick in `_update_recovery_state`).
- **Azione:** `new_mm = min(minmove_max, old_mm + minmove_step)` — un gradino, OLTRE il valore iniziale, fino a
  `minmove_max`. Floor `minmove_min=0.15` **invariato** (limite inferiore, mai toccato).
- **Isteresi anti-pompaggio:** su solo se `rms > mediana`, giù (CASO 3) solo se `rms < rms_low` → tra i due la
  leva resta ferma; recupero (su) e CASO 3 (giù) non si alternano.
- **Anti-windup (puro-RMS):** dopo `recovery_no_progress_k` recuperi senza un calo dell'RMS (> `_RECOVERY_PROGRESS_EPS`
  = 0,01″ rispetto all'anchor del run) ci si **ferma**: quell'RMS è atmosferico, non lever-fixable → niente windup
  verso `minmove_max`. Se l'RMS cala, si ri-ancora e si prosegue. Gestito in `_finalize_recovery_windup` (una volta
  per tick, dopo i due assi; l'RMS di feedback è `rms_total`).
- **Cooldown:** `minmove_cooldown` (1,5× base), come il MinMove-up del CASO 1.

### Decisione di scope: solo MinMove (non Aggression coordinata)
Scelta **(a) solo MinMove**, non (b) MinMove+Aggression coordinata. Motivi: (1) il kill-switch è **default-on** →
arriva all'intera flotta (OFF+GUARDIAN) → blast-radius minimo obbligatorio; (2) il `DESIGN_RATIONALE_LEVER_RESPONSIVENESS.md`
§5bis stesso definisce il fix minimo come "parte sicura, puro-RMS, solo MinMove", e il loop a due leve jitter-aware
come **design completo fuori scope** (accoppiato al §32 HFD); (3) coordinare due leve verso soft introduce rischio
di doppio-conteggio/over-softening. L'Aggression ha lo stesso schema di asimmetria (resta alta in banda morta:
scende solo su CASO 1/2) + passo asimmetrico `aggr_step_down=5/aggr_step_up=2`: la sua correzione è rimandata al
loop a due leve. `aggr_step_down/up` **non toccati**.

### File modificati
- `phd2_agent/config.py`: `LeverOptimizationConfig` + 3 chiavi (`minmove_recovery_enabled=true`,
  `minmove_recovery_factor=1.0`, `recovery_no_progress_k=3`) + parsing retrocompatibile (sezione/chiavi assenti → default).
- `phd2_agent/controller.py`: costante `_RECOVERY_PROGRESS_EPS`; stato recupero in `__init__`; helper
  `_recovery_threshold`/`_update_recovery_state`/`_finalize_recovery_windup`; ramo RECOVERY in `_evaluate_axis`
  (caso `"RECOVERY"` → in guardian `review()` lo CONFERMA, §31 NON toccato); due call per-tick in `evaluate()`.
- `tests/test_minmove_recovery.py` (NUOVO, 13 test). `replay_minmove_recovery.py` (NUOVO, replay offline).
- `phd2_agent/__about__.py`: 2.4 → **2.5**.

### Comportamento / retrocompatibilità
- **`minmove_recovery_enabled=false`** → ramo saltato, comportamento **identico bit-per-bit** alla v2.4.
- Default-on giustificato (richiesta di Alessandro): correzione di un comportamento base osservato sul campo
  (non feature sperimentale come l'HFD sampling-aware), confermata da codice+log, migliora simultaneamente OFF e
  GUARDIAN e tutte le versioni future. Kill-switch sempre presente nel TOML per rollback immediato.
- **Vincolo di rilascio:** il default-on entra in campo solo dopo replay (fatto) + validazione beta.

### Validazione
- **Replay obbligatorio** su `session_20260611_003714` (GUARDIAN, mediana 0,7806″, soglia=mediana×1.0):
  **745 frame in banda morta (59%, coincide con l'analisi del rationale)**, 269 frame eleggibili,
  **14 risalite MinMove col fix vs 0 oggi** (oggi MinMove risale solo nei 24 frame con `rms>rms_high`); 1 stop
  anti-windup; MinMove 0,15 → 0,85. Comando: `python replay_minmove_recovery.py <session.csv>`.
- **Suite:** 118 test verdi (105 preesistenti + 13 nuovi).
- **Campo (Alessandro):** avviare in guardian, osservare in dashboard/log che MinMove **risale** quando l'RMS sale
  nella banda morta e non resta incollato a 0,15.

### Limiti / note
- Solo MinMove: l'Aggression resta col suo schema asimmetrico (rimandata al loop a due leve jitter-aware, §32 HFD).
- In JITTER il recupero non agisce (catena CASO sospesa): per beneficiarne usare **GUARDIAN** (modalità distribuibile).
- L'anti-windup è puro-RMS (ferma quando il softening non riduce l'RMS); lo stop "a priori per regime" richiede il
  segnale jitter (§32 HFD), ed è fuori scope.

## 33. La baseline deve formarsi SEMPRE (prerequisito di P1) — Agente v2.5 (2026-06-13)

### Accertamento
Notti di seeing brutto con RC8 (montagna, CEM70): l'RMS è genuinamente alto e la **baseline auto-calibrata non si
forma** → il controllore resta **senza riferimento** → satisfaction-gate (§30), RECOVERY (§32) e tutta la logica P1
sono **inerti** proprio quando servirebbero. Meccanismo esatto (verificato sul codice + log): NON è il gate di
rifiuto §23 (è secondario, non viene nemmeno raggiunto), ma il **filtro di campionamento**: la baseline accumulava
campioni **solo da frame `condition==NOMINAL`** (servono 60), e a guida degradata 60 frame NOMINAL non esistono.
Conferma notte serena `session_20260613_004934` (RC8 0,508″/px, 3258 frame, SNR ottimo): solo **16 frame NOMINAL** →
finestra mai riempita → `baseline_rms_median = null`. Riferimento: `PRINCIPIO_CONVERGENZA_PRESTAZIONE.md` (P1).

### Cosa fa (fix sul campionamento, non sul rifiuto)
- **Percorso NOMINAL invariato** (notti buone: nessuna regressione, bit-identico).
- **FALLBACK §33** (`controller._update_rms_baseline`): mantiene una finestra rolling di **tutti i frame SNR-validi**
  (no implosion) e un contatore. Se i 60 campioni NOMINAL non si accumulano entro `baseline_fallback_frames` (180)
  frame SNR-validi, finalizza dalla finestra "tutti i frame" con stimatore **mediana del miglior X%**
  (`baseline_best_fraction`=0.33) — la "miglior prestazione raggiungibile nelle condizioni correnti" (P1), NON la
  mediana di tutto (che sovrastimerebbe).
- **CAP su rms_high INVARIATO** (`rms_high_max_arcsec=1,00″`): con baseline alta, `rms_high=min(1,3×baseline; 1,00)=1,00″`
  → l'Agente interviene comunque sopra 1,00″.
- **Anti-inversione bande** (`_finalize_rms_baseline`): `rms_low ≤ rms_high × rms_low_high_ratio_max` (0,85). Senza
  questo, una baseline alta dà `rms_low=0,75×baseline > rms_high` cappato → bande invertite (logica rotta). Sana anche
  un **bug latente preesistente** (baseline ~1,33–1,52″ su RC8 produceva già rms_low>rms_high).
- **Rifiuto di fallback ridisegnato**: non più su valore assoluto basso (una notte brutta reale ha baseline alta ma
  legittima), ma su **instabilità** (CoV della best-fraction > `baseline_fallback_max_cov`=0,50 = transitorio/spazzatura)
  o tetto **"guida fondamentalmente rotta"** (`baseline_fallback_reject_arcsec`=4,0″). Il gate §23 e il refresh
  tightest-wins (§25) restano per il percorso NOMINAL.

### File modificati
- `phd2_agent/config.py`: `AutoCalibrationConfig` + 6 chiavi (`baseline_always_form=true` kill-switch,
  `baseline_fallback_frames=180`, `baseline_best_fraction=0.33`, `rms_low_high_ratio_max=0.85`,
  `baseline_fallback_max_cov=0.50`, `baseline_fallback_reject_arcsec=4.0`) + parsing retrocompatibile. Valori PROVVISORI.
- `phd2_agent/controller.py`: import `deque`; stato §33 in `__init__` (finestra all-frames + frames_seen); reset in
  `_invalidate_rms_baseline` e `_maybe_start_refresh`; `_update_rms_baseline` (campionamento + trigger fallback);
  `_finalize_rms_baseline(fallback=...)` (stimatore best-fraction, rifiuto instabilità/tetto, cap anti-inversione).
- `tests/test_baseline_formation.py` (NUOVO, 12 test). `replay_baseline_formation.py` (NUOVO).

### Comportamento / retrocompatibilità
- **`baseline_always_form=false`** → identico bit-per-bit alla v2.4/§32 (solo NOMINAL, nessun fallback, nessun cap
  anti-inversione, gate rifiuto §23 classico). Default **true** (correzione di un comportamento base, prerequisito P1).
- **NIENTE rebuild** in questo step (richiesta di Alessandro): il fix si folderà nel prossimo build v2.5. **Lo ZIP
  v2.5 già prodotto col §32 è quindi STALE** (non contiene §33): il prossimo build includerà §32+§33. Nessun bump
  versione (resta 2.5, non ancora deployata).

### Validazione
- **Replay** su `session_20260613_004934` (serena, baseline oggi=None): **16 frame NOMINAL** (coincide con
  l'accertamento), OGGI baseline=None → COL FIX **baseline 1,452″ via FALLBACK**, `rms_high=1,000″` (CAP invariato),
  `rms_low=0,850″` (ANTI-INVERSIONE, < rms_high). Comando: `python replay_baseline_formation.py <session.csv>`.
- **Suite:** 130 test verdi (118 + 12 nuovi).

### Limite onesto (dall'accertamento)
Il fix rende l'Agente **non-inerte** (gli dà un riferimento), ma **NON fa guidare bene l'RC8** su queste notti
(~2″ RMS con ~27% oscillazione anche a cielo sereno): è in gran parte **taratura montatura/guida** (aggressività, PA,
bilanciamento, PEC) a monte dell'Agente — verificare col Guiding Assistant di PHD2 in parallelo.

## 34. Cadenza loop / baseline reale / pulizia logging INSUFFICIENT — Agente v2.5 (2026-06-15)

### Accertamento (verdetto: CONFERMATO sul codice)
Sintomi sui log RC8 v2.5 (`session_20260615_000212`, 2149 frame): 78% dei frame loggano `exposure_ms=0` pur con
SNR/HFD ottimi e sono ~100% `diag_state=INSUFFICIENT_DATA`; la baseline si forma a ~frame 900 (~25-37 min) invece dei
~180 attesi. **Causa confermata** (`main.py` `_event_loop`): per ogni GuideStep si fa `ingest_guide_step` →
(gated) `evaluate` → **sempre** `log_snapshot`. Ma `evaluate()` gira solo quando `now - last_eval >= interval_seconds`
(10s, ~1 frame su 5, main.py L280-287). Dentro `evaluate()`: `exposure_ms` (controller L780/866), `diag_state` (L782/868)
e l'accumulo baseline `_update_rms_baseline` (L816/902) → quindi le righe FUORI-TICK escono coi **default dello
snapshot** (`exposure_ms=0`, `diag_state="INSUFFICIENT_DATA"` da analyzer.py L99-100), e il contatore `_baseline_frames_seen`
(§33) avanza per TICK, non per frame → `baseline_fallback_frames=180` ≈ 180 tick × 10s ≈ 30 min. Replay: l'81%
INSUFFICIENT crolla a **15% sui soli frame valutati**.

### Cosa fa (fix isolato a cadenza/accumulo/logging — NON tocca la logica diagnostica/leve)
- Nuovo `controller.ingest_frame(snapshot)` chiamato in `main.py` per **OGNI** guide-frame (quando `analyzer.is_ready`),
  distinto da `evaluate()` che resta gated sul tick. `ingest_frame` (kill-switch `[control] per_frame_baseline`):
  (1) accumula la baseline sui guide-frame REALI (`_maybe_start_refresh` + `_update_rms_baseline`) → fallback §33 in
  ~8 min invece di ~37; (2) popola `exposure_ms` (reale) e `diag_state`/`confidence` (ULTIMO esito valido) sulle righe
  fuori-tick, niente più placeholder.
- `evaluate()`: l'accumulo baseline è ora gated `if not per_frame_baseline` (in per-frame avviene in ingest_frame);
  marca `snapshot.evaluated = True` (il tick vero).
- Nuova colonna CSV **`evaluated`** (logger) + `schema_version` 1→2: la % INSUFFICIENT reale = INSUFFICIENT su
  `evaluated==True`. `classify()` e la logica leve NON toccate (restano per-tick, con cooldown).

### File modificati
`config.py` (`ControlConfig.per_frame_baseline=true` + parsing) · `analyzer.py` (`AnalysisSnapshot.evaluated`) ·
`controller.py` (`ingest_frame`; baseline gated in `evaluate`; `evaluated=True`; summary `schema_version`=2) ·
`logger.py` (colonna `evaluated`, `schema_version`=2) · `main.py` (chiama `ingest_frame` per-frame) ·
`config.toml` (`per_frame_baseline = true`). Test: `tests/test_per_frame_baseline.py` (6). Replay:
`replay_cadence_artifact.py`.

### Comportamento / validazione
- Kill-switch `per_frame_baseline` **default true** (shipped ON). A **false**: comportamento storico per-tick
  (baseline in `evaluate`, righe fuori-tick placeholder) — utile per A/B. `evaluated` è additivo in entrambi i casi.
- Replay `session_20260615_000212`: 1675/2149 righe fuori-tick (78%); INSUFFICIENT 81% (tutte) → **15% (valutati)**;
  baseline ~36,7 min (per-tick) → **~8,1 min (per-frame)** (frame ~2,7s, ~4,5 frame/tick). Suite: 145 test verdi.

## 35. Riselezione stella all'aumento esposizione (Path B) — Agente v2.5 (2026-06-15)

### Accertamento (verificato sul codice)
Quando Path B (`_evaluate_exposure_seeing`) alza l'esposizione (leve sature + DEGRADED_SEEING), NON c'è riselezione
stella: solo `set_exposure` + reset analyzer/motore. La saturazione è gestita SOLO dal timer reattivo da 300s
(`_evaluate_saturation_timer`), armato unicamente dall'AI Star Finder su StarLost (controller L1921), **non agganciato
a Path B**. Effetto: una stella ben esposta a 1s che **satura a 2s** (picco flat-top → centroide in bias) degrada la
guida per ~5 minuti prima del re-scan — proprio mentre Path B voleva migliorarla.

### Cosa fa (isolato al path esposizione + riselezione)
- Dopo che Path B ha alzato l'esposizione (UP applicato, non dry_run) si arma un check ritardato: `_pathb_restar_pending`
  + `_pathb_restar_due = now + pathb_restar_settle_frames × (nuovo_tempo/1000)` (settle perché il nuovo tempo sia attivo).
  Il ritorno a esposizione più bassa (DOWN) annulla il pending.
- Nuovo `_evaluate_pathb_restar` (chiamato in `evaluate` dopo `_evaluate_exposure`): a settle scaduto, su immagine
  FRESCA (`save_image` + `find_best_star`), **se e solo se** la stella corrente è satura (`is_saturated`), riseleziona
  la migliore stella **NON satura** via `find_best_star(prefer_unsaturated=True)` + `set_lock_position`. Se non esiste
  alternativa non satura → arma la rete del timer 300s. **Condizionale** (mai a ogni cambio esposizione),
  **anti-flapping** via `pathb_restar_cooldown_s`, solo in guida valida (no STAR_LOST/INACTIVE).
- `star_finder.find_best_star(prefer_unsaturated=True)` (NUOVO param): scarta i blob con `peak >= SATURATION_THRESHOLD_ADU`
  e ritorna la migliore NON satura (None se non ce ne sono). Riusa la logica `is_saturated` esistente.

### File modificati
`star_finder.py` (param `prefer_unsaturated`) · `controller.py` (stato `_pathb_restar_*`; pending set/clear nei rami
Path B UP/DOWN; `_evaluate_pathb_restar`; chiamata in `evaluate`) · `config.py` (`ExposureDynamicConfig`:
`restar_on_pathb_saturation=true`, `pathb_restar_settle_frames=2`, `pathb_restar_cooldown_s=120` + parsing) ·
`config.toml` (chiavi shipped ON). Test: `tests/test_pathb_restar.py` (9, incl. FITS reale per `prefer_unsaturated`).

### Comportamento
- Kill-switch `restar_on_pathb_saturation` **default true** (shipped ON). A **false**: comportamento identico
  all'attuale (solo timer 300s). NON tocca §31/§32/§33/leve/backlash. Il timer 300s resta come rete per gli altri casi.
- L'anti-flapping (cooldown + riselezione solo su UP-saturazione, mai su DOWN) evita l'oscillazione su/giù della
  lock position. Suite: 145 test verdi.

## 36. FIX unità: RMS misurato in PIXEL ma trattato come ARCSEC — Agente v2.5 (2026-06-15)

### Bug confermato sul codice (PHD2 + Agente)
PHD2 espone `RADistanceRaw/DECDistanceRaw = mountOffset.X/Y` in **PIXEL** (`event_server.cpp:2883-2884`); tiene le
RMS in px e converte in arcsec **solo per il display** (`statswindow.cpp:168` `arcsecs(px, sampling)=px*sampling`;
`graph.cpp:293` arcsec opt-in). L'Agente legge quei pixel (`analyzer.py:140-141`) in campi commentati "arcsec" e
**non** li converte (Analyzer senza pixel-scale) → `rms_ra/dec/total`, peak, jitter, trend risultano in **px**. Ma le
soglie sono in **arcsec** e moltiplicano per `scale`: reject `max(1.50, 3.0×scale)` (controller L554), cap
`clamp(2.0×scale, 0.70, 1.00)` (L611). → **misura(px) confrontata con soglie(arcsec)**: miscalibrazione di un fattore
pixel-scale, in direzioni opposte per setup (RC8 0.51 sovrastima ×~2, Askar 1.58 / Mirko 1.76 sottostimano).

### Pre-flight (confermato): nessuna conversione compensativa
Le uniche moltiplicazioni per `scale` sono concetti DIVERSI, da NON toccare: mapping aggressività (L363 `/scale`,
L783/794 `×scale`), costruzione soglie (L554/611), e la conversione HFD dedicata di Path B (L1778
`hfd_avg×scale ≥ hfd_min_arcsec`). Nessun `×scale` sul percorso distanza/RMS. `ingest_star_lost` non legge distanze;
`server.py` passa `rms_*` senza scala (niente doppia conversione a valle). Unico lettore dei raw: `ingest_guide_step`.

### Cosa fa (isolato alla conversione della MISURA)
- `analyzer.ingest_guide_step(event, pixel_scale=1.0)`: converte `ra_raw/dec_raw` **× pixel-scale viva** al punto
  d'ingresso (UNA volta). Tutto il derivato (rms, peak, jitter, trend) eredita arcsec → combacia con le soglie già in
  arcsec, **nessuna ritaratura**. Default 1.0 = identità (retrocompat test).
- `main.py`: passa la scala VIVA (`controller.cfg.setup.guide_pixel_scale_arcsec`, override PHD2→reduced/native),
  gated dal kill-switch `[analyzer] convert_distance_to_arcsec` (a OFF passa 1.0 = px grezzi).
- HFD lasciato in px (ha la sua conversione in L1778). Soglie/cap/reject/floor e scaling aggressività NON toccati.
- Commenti "arcsec" dell'Analyzer ora **veri**. `schema_version` 2→**3** (i log post-fix hanno la misura in arcsec:
  i replay distinguono pre/post).

### File modificati
`config.py` (`AnalyzerConfig.convert_distance_to_arcsec=true` + AgentConfig + parsing `[analyzer]`) · `analyzer.py`
(`ingest_guide_step(pixel_scale)`, conversione + commenti) · `main.py` (passa scala viva, gated) · `logger.py` +
`controller.py` (`schema_version`=3) · `config.toml` (`[analyzer] convert_distance_to_arcsec = true`). Test:
`tests/test_units_conversion.py` (9). Replay: `replay_units_arcsec.py`.

### Impatto per-setup (dichiarato: sposta i numeri)
`arcsec = px × scale`. **RC8 (0.51)**: l'RMS visualizzato scende da ~2 a **~1,0"** (guida in realtà buona); finiscono
i **rifiuti baseline spuri**. **Askar (1.58) / Mirko (1.76)**: gli RMS **salgono** (px < arcsec) → diagnosi più
severa ma corretta. Le soglie nel TOML restano numericamente identiche (sono già arcsec).

### Validazione
- Kill-switch `convert_distance_to_arcsec` **default/shipped true** (un fix di correttezza non gira col bug). A
  **false** = misura px (comportamento buggato) per A/B.
- Replay `session_20260615_000212` (RC8, scale 0.508): RMS mediano loggato **1.786 px → 0.907" reale**; gate rifiuto
  1.524" → baseline **PRIMA rifiutata (1.79 px), DOPO accettata (0.91")**. Suite: **154 test verdi** (145 + 9).
- **P1**: misura e soglie ora nella stessa unità → prerequisito di baseline/cap/RECOVERY/diagnosi. Da verificare in
  campo che la dashboard RC8 mostri ~1" non ~2".

## 37. HFD declassato a SOLO INFORMATIVO: fuori dal gate SEEING — Agente v2.5 (2026-06-16)

### Problema (verificato sul campo, tutti i setup / tutte le notti)
La diagnosi **SEEING** richiedeva un gate AND `rms_total > rms_high AND jitter_high AND hfd_high`
(`diagnostic_engine.py` §31). Ma sulla **camera di guida** l'HFD resta piatto (`hfd_avg/hfd_ref ≈ 1.0`) a
ogni scala/SNR: `hfd_high` non scatta MAI → il termine AND **azzerava SEEING** anche con guida realmente
turbolenta. Conferma 2026-06-16 RC8: `SEEING=0` con guida ottima a 0.83". L'HFD sulla guida è **cieco al
seeing**; il segnale di seeing vero arriverà in futuro dalla camera di **ripresa** (roadmap NINA).

### Cosa fa (isolato a `diagnostic_engine.py` + config)
- **SEEING ridefinito sulla sola firma DINAMICA**: `rms_total > rms_high AND jitter_high AND not oscillation`.
  Il `not oscillation` lo tiene **specifico** (distinto da OVERCORRECTION, che è `oscillation`); da DRIFT è già
  distinto perché `drift` esclude `jitter_high` per costruzione. Confidence SEEING ora su 2 segnali (RMS+jitter)
  → 76 (≥ `act_min_confidence`/`guardian_min_confidence` 60: le azioni jitter/micro-guardian restano possibili).
- **HFD rimosso da OGNI decisione**: tolto `and hfd_high` da SEEING e `and not hfd_high` da OVERCORRECTION/DRIFT.
  `hfd_high` resta **calcolato** e i campi `hfd`/`hfd_ref` restano nelle `metrics` (CSV + card dashboard intatti):
  HFD ora è **solo lettura/telemetria**. Evidence aggiornata ("◦ HFD informativo (non-gating)").
- **Guardian invariato** (review-only): il motore continua a CONFIRM/ATTENUATE/BLOCK e fa micro-correzioni solo
  a v2.3 ferma. Riabilitare SEEING senza HFD non lo fa "pilotare": test dedicato verifica che con v2.3 attiva
  (CASO1) non parte alcuna micro extra.

### Kill-switch (shipped sul comportamento nuovo — born operative)
`[diagnostic_engine] hfd_gates_seeing` (`config.py` default `False`, `config.toml` = `false`). **false (shipped)**
= HFD informativo, SEEING su jitter+RMS. **true** = gate §31 legacy (SEEING richiede anche `hfd_high`,
OVER/DRIFT richiedono `not hfd_high`) per confronto A/B. Retrocompatibilità verificata in test.

### File modificati
`phd2_agent/diagnostic_engine.py` (classify: gate ramificato su `hfd_gates`; `_build_evidence`; docstring) ·
`phd2_agent/config.py` (`DiagnosticEngineConfig.hfd_gates_seeing=False` + parsing `[diagnostic_engine]`) ·
`config.toml` (`hfd_gates_seeing = false` + commento) · `tests/test_diagnostic_engine.py` (+7: SEEING con HFD
piatto, specificità RMS, oscillazione→OVER, HFD ancora loggato, regressione gate legacy, guardian review-only).

### Scelta di design
Questa è la via **semplice** scelta da Alessandro (declassamento netto dell'HFD) al posto del weighting
sampling-aware proposto in `DESIGN_RATIONALE_HFD_SAMPLING_AWARE.md` / `PROPOSTA_§32_HFD_SAMPLING_AWARE.md`:
non si pretende dall'HFD un'informazione che lo strumento (camera di guida) non può dare.

### Validazione
- Suite **161 test verdi** (154 + 7). Il replay sul log RC8 `session_20260615_211617` (conteggio di quante volte
  SEEING scatterebbe ora, verificando che siano eventi reali di alta turbolenza e non rumore) è **da eseguire su
  Minix100**: il CSV non è nel repo (i `logs/` sono in `.gitignore`).
- **P1**: una leva/segnale non informativo non deve condizionare le decisioni. Declassare l'HFD libera la diagnosi
  SEEING dai segnali dinamici reali (jitter+RMS), senza pretendere un dato che lo strumento non può fornire.

## 38. jitter_ref/hfd_ref che si formano SEMPRE (motore finalmente operativo) — Agente v2.5 (2026-06-16)

### Problema (scoperta riprodotta sui log reali, fratello del §33 un livello più sotto)
Dopo §34 (freeze=logging) e §37 (HFD fuori dal gate) il motore continuava a **non diagnosticare SEEING**. Causa: le
reference EMA (`_jitter_ref`/`_hfd_ref`) si formavano **solo** nel ramo stretto `rms_total <= rms_low AND
condition == NOMINAL` (`diagnostic_engine.py` §31), e `refs_ready` (gate di `jitter_high`, quindi di SEEING)
richiedeva entrambe non-None. Su notti turbolente quel ramo capita di rado e, peggio, `reset()` azzera le ref a ogni
cambio esposizione/dither/StartGuiding → tra un reset e l'altro la ref spesso non si forma mai. È lo **stesso schema
del bug baseline §33**: la reference campiona solo una condizione rara.

### Verdetto Fase 1 (riprodotto): CONFERMATA
Replay su RC8 `session_20260615_211617` (866 frame `evaluated`): `jitter_ref>0` solo **11,8%** (mediana 0);
`rms<=rms_low_active` **2,2%**; `condition==NOMINAL` 56,7%; `rms>rms_high_active` 33%; `hfd_high` 0%; **SEEING = 0**
in assoluto (552 UNCERTAIN, 113 DRIFT). Il jitter è **sempre > 0** (min 0,53): la ref a 0 dipende solo dal ramo
stretto + i reset, non dalla mancanza di dati. Con una `jitter_ref` robusta (p20 del jitter di sessione) **~9% dei
frame sarebbero SEEING-eligibili** — oggi 0 diagnosticati. Citazioni: `diagnostic_engine.py:157-159` (refs_ready),
`:203-205` (formazione stretta), `:218-219` (jitter_high gated da refs_ready).

### Cosa fa (isolato a `diagnostic_engine.py` + config)
- **Reference via BEST-FRACTION su finestra mobile** (approccio A, specchio §33): finestre `deque(maxlen=refs_window_frames)`
  di `jitter_rms`/`hfd_avg` alimentate a OGNI frame valido (`_update_refs_window`, chiamato in `classify` dopo il gate
  INSUFFICIENT e prima del ramo NOMINAL). Dopo `refs_warmup_frames` campioni, `jitter_ref`/`hfd_ref` = mediana del
  best-fraction (i valori più BASSI = guida più calma). Si forma **sempre e presto**, anche senza frame `rms<=rms_low`.
- **`refs_ready` dipende SOLO da `jitter_ref`** (post-§37 l'HFD è informativo: gating la prontezza su `hfd_ref` era un
  residuo). `hfd_ref` resta calcolato/loggato (card dashboard intatta). Aggiunta guardia `_hfd_ref is not None` nel
  calcolo di `hfd_high` (ora refs_ready può essere vero con hfd_ref None → evitato TypeError).
- **NOMINAL e satisfaction-gate INVARIATI**: la formazione reference è isolata; l'EMA-in-NOMINAL §31 resta solo in
  modalità legacy. Condizioni SEEING/OVERCORRECTION/DRIFT (§37) non toccate.

### Kill-switch + parametri (shipped sul nuovo comportamento — born operative)
`[diagnostic_engine] refs_always_form` (`config.py` default `True`, `config.toml` `true`). **true** = best-fraction
sempre-forma; **false** = formazione EMA-in-NOMINAL §31 (refs_ready su entrambe le ref) per A/B. Parametri attivi:
`refs_window_frames=120`, `refs_best_fraction=0.25`, `refs_warmup_frames=15`. NB: il warmup governa solo il **ritardo
iniziale** dopo ogni reset; la qualità del best-fraction viene dalla finestra che cresce fino a `refs_window_frames`.
15 è scelto per robustezza ai reset frequenti (dither/exposure) restando breve.

### File modificati
`phd2_agent/diagnostic_engine.py` (finestre + `_update_refs_window`/`_best_fraction_stat`; `refs_ready`; guardia
`hfd_high`; `reset()` pulisce le finestre; docstring) · `phd2_agent/config.py` (4 chiavi `refs_*` + parsing) ·
`config.toml` (chiavi attive) · `tests/test_diagnostic_engine.py` (helper `_build_refs`/`_warm_refs` warmup-aware;
`test_refs_form_after_warmup` aggiornato; +7 test §38: riproduzione, warmup, indipendenza da hfd_ref, payoff SEEING,
regressione legacy, NOMINAL invariato).

### Validazione
- Suite **168 test verdi** (161 + 7). Verdetto Fase 1 CONFERMATA con numeri riprodotti (sopra).
- **Replay reale** `211617` col motore §38: `refs_ready` da **11,8% → 95,4%** (solo reset da cambio esposizione,
  derivabili dal CSV) e **52 SEEING** (prima 0). Il CSV non contiene gli eventi dither/StartGuiding che nel run reale
  chiamano `reset()`, quindi è una stima ottimistica; resettando periodicamente per mimare il dither, alla cadenza che
  riproduce l'11,8% legacy (~ogni 100 frame) §38 tiene **~60-83%** (warmup 30→15) vs **~11%** del legacy: **5-7×**.
- **P1**: un motore che deve riconoscere il seeing ha bisogno di un *riferimento di calma* che si formi davvero. §38 è
  il fratello del §33: "il riferimento si forma sempre, dalla migliore prestazione disponibile nelle condizioni
  correnti". Da validare in campo (dashboard SEEING ora non più sempre a 0 in notti turbolente).

## 39. Il riferimento di calma SOPRAVVIVE al dither + logging cause di reset — Agente v2.5 (2026-06-16)

### Problema (passo 2/2 del motore operativo, dopo §38)
Il §38 fa riformare in fretta `jitter_ref`/`hfd_ref`, ma la causa profonda restava: `diagnostic_engine.reset()`
azzerava i riferimenti **e** le finestre §38 a OGNI dither/settle, e il dithering avviene ogni pochi minuti → il
motore passava la vita a ricostruire un riferimento che gli veniva continuamente cancellato. Un dither **non cambia
l'atmosfera** (sposta la stella): azzerare lì il "jitter di calma" è sbagliato — stessa lezione del §36
sull'invalidazione della baseline solo a vero cambio di regime.

### Verdetto Fase 1 (confermato): CONFERMATA
7 call-site di `diagnostic_engine.reset()` classificati: `main.py:338` StartGuiding (**guiding_restart**→azzera),
`main.py:371` fine dither (**dither**→preserva), `main.py:400` SettleDone (**settle**→preserva), `controller.py:1646`
transizione modalità (**mode_transition**→preserva), `controller.py:1727/1748/1819/1862` Path B (**exposure_change**→
azzera). Churn dimostrato: il reset azzerava refs+finestre; ai dati §38, reset ~ogni 25 frame → refs_ready 0%.

### Cosa fa (isolato a call-site reset + reset(cause) + logger)
- **2A — disciplina di reset.** `reset(cause)` (`diagnostic_engine.py`): azzera SEMPRE solo `_last`; azzera i
  RIFERIMENTI (+ finestre §38) **solo** se la causa cambia il regime del jitter. `_PRESERVE_CAUSES =
  {dither, settle, mode_transition}` → preservano; `exposure_change/pixel_scale_change/target_change/guiding_restart/
  manual` → azzerano. Ogni call-site mappato alla causa corretta. **`analyzer.reset()` NON toccato** (la finestra RMS
  deve resettarsi al dither: le posizioni saltano); il best-fraction §38 è robusto al transiente post-dither (ancorato
  ai frame calmi già in finestra) — verificato in test (`test_no_poisoning_after_dither`).
- **2B — logging cause di reset.** Nuova colonna CSV **`reset_cause`** (vuota senza reset, valorizzata col motivo sul
  primo frame dopo il reset, via `consume_reset_cause()` read-and-clear nel logger). **`schema_version` 3→4**. Rende
  fedeli i replay futuri (oggi i reset da dither NON erano nei log: ecco perché §38 non era pienamente validabile).

### Kill-switch (shipped sul nuovo comportamento)
`[diagnostic_engine] preserve_refs_on_dither` (`config.py` default `True`, `config.toml` `true`). **true** = preserva
su dither/settle/mode_transition; **false** = azzera sempre (comportamento §31) per A/B. Retrocompatibilità verificata
(`test_legacy_mode_wipes_on_dither`).

### File modificati
`phd2_agent/diagnostic_engine.py` (`_PRESERVE_CAUSES`; `reset(cause)`; `consume_reset_cause()`; `_pending_reset_cause`)
· `main.py` (3 call-site → cause) · `phd2_agent/controller.py` (5 call-site → cause) · `phd2_agent/config.py`
(`preserve_refs_on_dither=True` + parsing) · `config.toml` (chiave attiva) · `phd2_agent/logger.py` (colonna
`reset_cause`, `consume_reset_cause`, `schema_version`=4) · `tests/test_diagnostic_engine.py` (+7 test §39).

### Validazione
- Suite **175 test verdi** (168 + 7). Demo sintetica churn (warmup=15): con §39 `refs_ready` resta **97,7% a
  qualunque cadenza di dither**; legacy (azzera) crolla — 44% a dither ogni 25 frame, 0% a ogni 10.
- **Limite onesto del replay**: il log RC8 `session_20260615_211617` è **pre-§39 e NON contiene `reset_cause`**, quindi
  NON può validare appieno il §39 (i reset reali da dither non sono nei log). La validazione piena arriva dal
  **prossimo run di campo** con `reset_cause` loggato; sul vecchio log si vede solo il churn legacy come baseline.
- **P1 / coerenza §36**: un riferimento si invalida solo quando cambia davvero il regime che descrive. §38 forma in
  fretta, §39 evita di dover riformare di continuo: insieme rendono il motore davvero operativo (passo 2/2).

## 40. La baseline si forma anche a SNR basso (chiude il buco low-SNR) — Agente v2.6 (2026-06-17)

### Problema (validato in LIVE da Alessandro)
Il gate `_update_rms_baseline` (`controller.py`) aveva `if not snr_ok: return` con `snr_ok = snap.snr_avg >=
baseline_min_snr` (=**10**): bloccava SIA il percorso NOMINAL SIA il fallback §33. Su una notte a SNR basso la
baseline non si formava per NESSUNA via. Campo 71F `session_20260617_221428`: SNR mediano **9,2**, 100% frame < 10 →
baseline mai formata → `rms_high_active` inchiodato a 1,20. Validato in LIVE: forzando PHD2 a guidare su stella a
SNR 10 la baseline si è formata subito.

### Cosa fa (isolato al gate baseline + config)
- **`baseline_min_snr` 10 → 6.0** = pavimento "Minimum star SNR for AutoFind" di default di PHD2 (ogni utente lo ha →
  la baseline si forma per tutti). Resta ≤ `snr_low` (8): decoupling voluto — 6 = soglia RILEVAMENTO stella, 8 =
  soglia CONTROLLO esposizione.
- **Fallback §33 non più congelabile dalla soglia SNR.** Il gate non early-returna più su SNR basso: scarta solo
  `implosion`. Il percorso NOMINAL resta gated da `baseline_min_snr` (notti buone invariate); il FALLBACK accumula i
  frame sopra un **floor anti-garbage** `baseline_fallback_min_snr=3.0` (= reject rilevamento stella di PHD2) e forma
  dal best-fraction → su una notte genuinamente fioca la baseline si forma comunque dai frame meno peggio. La soglia
  alta PREFERISCE i frame migliori (NOMINAL), non BLOCCA tutto.
- **NOMINAL/cap/anti-inversione/reject §33 intatti** (cap rms_high 1,00", `rms_low ≤ rms_high×0.85`, reject su
  instabilità/tetto). Esclusione implosion mantenuta.

### Kill-switch (shipped sul nuovo comportamento)
`[auto_calibration] baseline_fallback_ignores_snr_gate` (`config.py` default `True`, `config.toml` `true`) +
`baseline_fallback_min_snr=3.0`. **true** = fallback usa il floor (si forma a SNR basso); **false** = gate stretto §33
(fallback gated da `baseline_min_snr`) per A/B. `baseline_min_snr` shipped a 6.0.

### File modificati
`phd2_agent/controller.py` (`_update_rms_baseline`: gate disaccoppiato) · `phd2_agent/config.py`
(`baseline_min_snr=6.0`, `baseline_fallback_ignores_snr_gate=True`, `baseline_fallback_min_snr=3.0` + parsing) ·
`config.toml` (chiavi attive) · `tests/test_baseline_formation.py` (`TestSnrGate` riscritto + `TestLowSnrBaselineV40`).

### Validazione
- Suite **180 test verdi** (175 + 5). Replay `session_20260617_221428` (71F, SNR mediano 9,2): PRE-§40 baseline
  **None**, `rms_high_active` 1,20 (inchiodato); §40 baseline **0,58"**, `rms_high_active` **0,752"** (si stacca),
  `rms_low_active` 0,434". (Il prompt stimava ~0,68"; il misurato è 0,58".)
- **P1**: terza volta che "il riferimento deve formarsi sempre" (baseline §33, jitter_ref §38, baseline a SNR basso
  §40). Con la v2.6 il principio è chiuso: nessun riferimento di prestazione può essere bloccato — né da assenza di
  frame NOMINAL, né da reset frequenti, né da una stella debole.

---

# RELEASE v2.6 (2026-06-17) — motore diagnostico operativo + RMS in arcsec + baseline robusta

Prima versione ufficiale sopra la 2.5 (commit §36 `13d2848`). Il motore di diagnosi del seeing passa da **dormiente a
operativo**, parte attivo in GUARDIAN e misura nella giusta unità. Milestone §37→§40:
- **§37** HFD declassato a informativo (fuori dal gate SEEING; SEEING su jitter+RMS).
- **§38** `jitter_ref`/`hfd_ref` sempre-forma (best-fraction su finestra mobile); `refs_ready` scollegato da hfd_ref.
- **§39** i riferimenti sopravvivono a dither/settle; logging `reset_cause`; schema CSV 3→4.
- **§40** baseline anche a SNR basso (`baseline_min_snr` 10→6 = floor AutoFind PHD2; fallback non-congelabile).
- (su base **§36**, già in v2.5: RMS px→arcsec.)
Tutte le feature **default-ON** nel `config.toml` (born operative). Validato sul campo (71F @490 2026-06-17:
jitter_ref 12%→87%, motore che diagnostica, baseline che si forma). Bump versione 2.5→2.6 in `__about__.py`
(single source: ZIP, version_info, agent_version, banner).

---

## 41. Step 0 telemetria NINA (lato Agente): canale in ingresso `POST /nina/telemetry` — Agente v2.6 (2026-06-18)

### Contesto (roadmap telemetria NINA, gate di N1–N8)
Step 0 della `ROADMAP_TELEMETRIA_NINA.md` (rif. `REVISIONE_ARCHITETTURALE_v2.6.md` §7/§9). Oggi il flusso
plugin→Agente è di **sola lettura** (`GET /about` + `GET /status`): non esisteva un canale in INGRESSO per ricevere le
metriche per-posa di NINA (HFR, conteggio stelle, SNR/fondo, eccentricità). Questo apre quel canale. **Infrastruttura,
non modello**: non migliora l'RMS e non deve — apre l'occhio ortogonale (la forma reale delle stelle nella posa) che
servirà a disambiguare la causa del degrado (RMS↑+HFR↑ = seeing vs RMS↑+HFR piatto = meccanica) e a validare il motore
§31. L'intelligenza che ci scorre dentro (N2 context-gating, N1 trasparenza, N6 safety, N7 tag, N8 confidence) è nei
prompt successivi, ciascuno col proprio gate.

### Cosa fa (isolato a server/store/config/main; motore/leve/baseline INTOCCATI)
- **`POST /nina/telemetry`** (`server.py`) — endpoint **difensivo**. Modello pydantic `NinaTelemetryPayload`
  (`schema_version` obbligatorio `ge=1`; tutto il resto opzionale, range-sanity `ge=0` su hfr/star_count/adu/…). Payload
  valido → `200 {"accepted":true,"schema_version":N}` + aggiorna lo store; malformato/fuori-range → **422** gestito da
  FastAPI **prima** dell'handler (store intatto); nessuna eccezione può raggiungere il loop di guida (endpoint sul thread
  uvicorn, non chiama mai controller/motore/leve). Campi mancanti tollerati (mai un 500).
- **`NinaTelemetryStore`** (`phd2_agent/nina_telemetry.py`, nuovo) — store **opzionale e thread-safe** (`threading.Lock`):
  ultimo payload (`last`), timestamp d'arrivo (monotonic), breve `deque` di storico (`history_frames`), property
  `is_fresh`/`last_age_s`/`count`, `status_block()`. **Layer-1 puro**: nessuna logica derivata (niente TransparencyIndex/
  indici Layer-2/confidence). Modulo senza dipendenze dal resto del progetto né da FastAPI/pydantic.
- **Blocco `nina` top-level in `/status`** (`server.py`, NON dentro `controller`: è telemetria esterna):
  `{enabled, connected (=is_fresh), schema_version, last_age_s, metrics}`. Graceful: store assente/disabilitato o nessun
  POST → `connected:false, metrics:{}, last_age_s:null` (la dashboard mostra "NINA non connesso" senza errori).
- **Wiring**: setter dedicato **`server.set_nina_store(store)`** (opzione meno invasiva: la firma di `set_global_state`
  resta **bit-identica** — retrocompat totale). Store creato in `main.py` (sempre; registrato sul server solo con
  dashboard attiva). Sezione config `[nina_telemetry]` (`config.py` `NinaTelemetryConfig` + parsing).

### Kill-switch / config (`[nina_telemetry]`, born-operative)
`enabled=true` (ATTIVO ma **inerte** finché nessuno POSTa) · `staleness_seconds=180.0` (oltre → `connected=false`,
metriche conservate) · `history_frames=60` · `log_arrivals=false`. **enabled=false** = kill-switch: endpoint risponde
`200 {"accepted":false,"reason":"disabled"}`, non memorizza, `/status.nina.enabled=false`. Sezione assente → default
born-operative (enabled=true).

### Contratto JSON versionato (`schema_version=1`, per il lato plugin)
`{schema_version, source, ts_unix, image:{hfr, hfr_std, star_count, eccentricity, mean_adu, median_adu, stdev_adu,
exposure_s, filter}, context:{activity, target}}`. `schema_version` obbligatorio; campi mancanti tollerati su **entrambi**
i lati (§9 della revisione); l'Agente non assume la presenza di `context` (arriva con N2). Le firme esatte di
`ImageSavedEventArgs`/`StarDetectionAnalysis` vanno verificate contro l'SDK della NINA installata quando si farà il lato
plugin (dove vive l'eccentricità cambia tra minor version).

### Lato plugin — RIMANDATO al ripristino del PC principale (plugin congelato)
L'iscrizione a `IImageSaveMediator.ImageSaved` + inoltro POST (+ eventuale FITS keyword/sidecar per N7) **non** è in questo
prompt: il plugin è congelato fino al ripristino del PC. Il plugin ha già `HttpClient` e il poller (`AgentHealthChecker`):
l'aggiunta sarà un secondo client POST, non una riscrittura. Il contratto JSON sopra permette di sviluppare i due lati in
parallelo.

### File modificati
`phd2_agent/nina_telemetry.py` (**nuovo**, `NinaTelemetryStore`) · `server.py` (modelli pydantic + `set_nina_store` +
`POST /nina/telemetry` + blocco `nina` in `/status`) · `phd2_agent/config.py` (`NinaTelemetryConfig` + parsing) ·
`main.py` (creazione store + registrazione) · `config.toml` (`[nina_telemetry]`) · `tests/test_nina_telemetry.py` (**nuovo**).

### Validazione (soglia bassa: infrastruttura, non modello)
Suite **203 test verdi** (180 pre-§41 + 23 nuovi). Test 1–8 del prompt coperti: POST valido→200/store riflesso;
campi mancanti→accettato/null; malformato/fuori-range→422 senza eccezioni e store invariato; kill-switch→accepted:false;
staleness→connected:false con metriche conservate; graceful assente→`/status` identico al pre-§41 a meno del solo blocco
`nina`; **isolamento**: il POST non altera `/status.controller` e un GuideStep degradato dà le **stesse** decisioni con e
senza telemetria (lo store non è letto dal motore/leve); thread-safety con writer/reader concorrenti. Niente bump
versione (release in un prompt git dedicato). Senza POST l'Agente è **bit-identico** a oggi.

---

## 42. Step 0 telemetria NINA (lato PLUGIN): inoltro metriche per-posa → Agente — Plugin v1.3 (2026-06-18)

### Contesto (seconda metà dello Step 0)
Il §41 ha aperto il canale in INGRESSO sull'Agente (`POST /nina/telemetry`, store, blocco `nina` in `/status`, contratto
`schema_version=1`), ma restava **inerte**: nessuno POSTava. Il §42 fa la **sorgente** nel **repo plugin separato**
(`AdaptiveAgentForPHD2.NinaPlugin/`, GitHub `Mamete91/AdaptiveAgentPHD2-NinaPlugin` — NON il repo Agente). Congelamento
plugin **rimosso** (Alessandro, 2026-06-18): il sorgente su questo PC è identico a quello del PC in riparazione → si
sviluppa/builda/valida **qui**. Unico prerequisito di toolchain risolto: installato il **.NET 8 SDK** (8.0.422, via
`winget`; prima c'era solo il runtime → vedi memoria `nina-plugin-build-env`, ora superata).

### Cosa fa (isolato al repo plugin; Agente toccato per 1 sola riga, vedi sotto)
- **`Telemetry/AgentTelemetryForwarder.cs`** (nuovo) — si iscrive a `IImageSaveMediator.ImageSaved`; a ogni light salvata
  mappa le metriche sul contratto §41 (solo `image{}`) e fa `POST <DashboardUrl>/nina/telemetry`. Imita
  `AgentHealthChecker`: `HttpClient` riusato (no socket exhaustion), timeout 3 s, `ConfigureAwait(false)`, **swallow
  totale**. Handler **non-throwing** e veloce: estrae i campi e lancia `_ = PostAsync(...)` **fire-and-forget** (non awaita
  → non rallenta/blocca il salvataggio posa). Null-check su `StarDetectionAnalysis` + skip se nessuna stella → niente
  payload spazzatura. `AddIfNumber` scarta NaN/Infinity/negativi (no eccezioni di serializzazione, no 422).
- **`Plugin/AdaptiveAgentForPHD2Plugin.cs`** — `[ImportingConstructor]` ora importa via MEF `IImageSaveMediator`, crea il
  forwarder (con `AgentServices.Instance.Settings`) e lo possiede: `Subscribe()` in `Initialize`, `Dispose()` in
  `Teardown` (simmetrico, idempotente). Posseduto dal plugin e NON da `AgentServices` (composition root statico, senza MEF
  → non può ottenere il mediator).
- **`Settings/PluginSettings.cs` + `PluginSettingsView.xaml`** — toggle `ForwardTelemetryToAgent` (default **true**,
  born-operative; kill-switch: forwarder iscritto ma non POSTa). DTO con `bool?` → chiave assente all'upgrade da <v1.3
  ⇒ `null` ⇒ default true (un `bool` non-nullable avrebbe deserializzato `false`, disabilitando di nascosto). Riusa
  `DashboardUrl` esistente (URL non duplicato).
- **Versione** `1.2.3.0 → 1.3.0.0` (`.csproj` + `AssemblyInfo`); LongDescription aggiornata. **GUID e dipendenze
  NINA/WebView2/MVVM invariati** (`ExcludeAssets=runtime` mantenuto — lezione WebView2).

### Mapping eventargs → contratto §41 e la LEZIONE verify-before-implement
| `image.*` | proprietà NINA 3.2.0.9001 | esito |
|---|---|---|
| `hfr` | `StarDetectionAnalysis.HFR` (px) | ✓ mappato |
| `hfr_std` | `StarDetectionAnalysis.HFRStDev` (px) | ✓ |
| `star_count` | `StarDetectionAnalysis.DetectedStars` | ✓ |
| `mean_adu`/`median_adu`/`stdev_adu` | `Statistics.Mean`/`Median`/`StDev` | ✓ (nomi confermati su GitHub) |
| `exposure_s` | `Duration` (s) | ✓ |
| `filter` | `Filter` | ✓ |
| `fwhm` (arcsec), `eccentricity` | `StarDetectionAnalysis.FWHM`/`.Eccentricity` | ❌ **NON esistono in 3.2.0.9001** |

La tabella del prompt veniva dal ramo `develop` (NINA 3.3-in-arrivo). Il **compilatore** contro l'SDK installato
(3.2.0.9001) ha dato `CS1061` su `FWHM` ed `Eccentricity`: aggiunti a `IStarDetectionAnalysis` **dopo** la 3.2 →
**omessi** (regola "campo assente nell'SDK → non inventarlo"). Il campo `fwhm` resta nel contratto §41 (vedi sotto),
forward-ready: appena la NINA installata li espone, basta riaggiungere 2 righe nel forwarder. Confermato anche che
`StarDetectionAnalysis` può essere null → skip POST.

### Unica modifica lato Agente (FASE 0.B): campo `fwhm`
`NinaImageMetrics` (`server.py`) non aveva `fwhm`: pydantic v2 **scarta i campi sconosciuti**, quindi una FWHM-arcsec
inviata sarebbe stata persa. Aggiunto `fwhm: Optional[float] = Field(default=None, ge=0)` accanto a `hfr`. Additivo e
retrocompatibile (resta `null` finché il plugin non lo invia). I 3 "buchi §41" della vecchia nota (sezione `[nina_telemetry]`,
parsing `config.py`, NOTE §41) erano **già chiusi** dal §41 (verificato: `config.toml:222`, `config.py:529`, `NOTE:2249`),
non rifatti.

### Graceful / regole rispettate
Agente offline → POST fallisce → swallow (log `Debug`), NINA prosegue la sequenza, nessun popup/eccezione. Toggle off →
nessun POST. Nessuna `context{}` (è N2). NON toccati: shell WebView/dashboard, `AgentHealthChecker`, Safety Monitor /
`SafetyDecisionEngine` (N6), dipendenze NINA/WebView2.

### Validazione
- **Build plugin**: baseline as-is 0/0; con §42 **0 errori / 0 warning** (Release, x64) contro NINA 3.2.0.9001 — il
  `CS8622` su `sender` risolto con `object?`.
- **Contratto §41↔§42** (automatico, in-process via TestClient): il payload esatto del forwarder (3.2: no fwhm/ecc.) →
  `200 accepted:true`, `/status.nina.connected=true` con `hfr/star_count/mean_adu/stdev_adu` corretti, `fwhm`/`eccentricity`
  → `null`. Suite Agente **203 verdi** (regressione dopo l'aggiunta `fwhm`).
- **NINA-in-the-loop** (manuali, sul campo): Agente vivo→`connected:true` su posa reale; Agente spento→posa salvata senza
  errori; toggle off→nessun POST. Da spuntare alla prossima sessione NINA.
- Niente commit/push (prompt git dedicato). DLL installabile con `scripts\install-plugin.ps1`.

---

## 43. Rifiniture v2.6: freschezza telemetria ADATTIVA + cap aggressività 100 — Agente v2.6 (2026-06-19)

### Contesto
Validazione di campo (Minixz100/NINA 3.3, 71F, 2026-06-18): telemetria NINA reale su `/status.nina`, `jitter_ref`
dinamico, GUARDIAN che fa la prima micro su SEEING reale. Due rifiniture emerse dai dati.

### §43a — Finestra di freschezza telemetria ADATTIVA alla posa
**Problema (dato reale):** `/status.nina.connected:false` con `last_age_s:197.9` mentre tutto funzionava. Le pose sono
**300s** ma `staleness_seconds=180`: la telemetria arriva una volta per posa → per ~120s di ogni ciclo il blocco andava
"stantio" (falso "disconnesso").
**Fix** (`phd2_agent/nina_telemetry.py` + config): finestra **adattiva**
`effective_window = max(staleness_seconds, staleness_exposure_factor × image.exposure_s)` applicata sia a `is_fresh`
sia a `status_block()`. **Graceful**: senza `exposure_s` → solo `staleness_seconds` (pavimento). Nuova chiave
`[nina_telemetry] staleness_exposure_factor = 1.5` (attiva; 0 disattiva l'adattività) + parsing. `/status.nina` espone
`effective_staleness_s` per trasparenza.

### §43b — Cap aggressività 90 → 100
`config.toml [limits.ra]` e `[limits.dec]`: `aggr_max` 90 → **100** (entrambi gli assi). È solo un **tetto** (CASO3 /
satisfaction-gate §30 / OVERCORRECTION governano il valore reale; clamp `min(limits.aggr_max, …)` a
[controller.py:1144](phd2_agent/controller.py:1144)/[:1390](phd2_agent/controller.py:1390) usa il nuovo tetto).
**`minmove_max` NON toccato** (resta 0.85): MinMove è una distanza px/arcsec, non una %; 100 disattiverebbe la guida.

### File / test
`phd2_agent/nina_telemetry.py` (`_effective_window` + adattività) · `phd2_agent/config.py`
(`NinaTelemetryConfig.staleness_exposure_factor` + parsing) · `main.py` (pass-through) · `config.toml`
(`staleness_exposure_factor=1.5`, `aggr_max=100` RA/DEC). Test: `TestAdaptiveFreshness` (window 450 con exposure 300;
pavimento 180 senza exposure; factor 0) + parse factor + `TestAggrMaxShippedConfig`. Suite **213 verdi**.

---

## 44. Baseline a rinnovo CONTINUO e BIDIREZIONALE (CAP §24 mantenuto) — Agente v2.6 (2026-06-19)

### Evidenza dai log (sessione `223204`) — il driver NON era il cap
L'ammorbidimento leve osservato (RA aggr 70→68, MinMove 0.2→0.22) è avvenuto con **cap NON attivo**
(`rms_high`=0.704, baseline 0.541, `rms_high_cap_active:false`). Causa reale: con seeing in peggioramento la **baseline
non è potuta salire** (regola "tightest-wins" del §25 + formazione una-tantum) → `rms_high` inchiodato a 0.704 → RMS
legittimi per quel seeing letti come SEEING → softening spurio. **Quindi:** l'ipotesi iniziale di rimuovere il cap è
stata SCARTATA (nei dati il cap non mordeva); la fix che conta è la **baseline che traccia la scala reale della notte**.

### Cosa fa (decisione Alessandro+Cowork 2026-06-19)
- **C1 — rinnovo continuo:** dopo la formazione iniziale (§33/§40 invariata), la baseline si aggiorna **a ogni frame**
  su **finestra mobile** (deque `_rms_rolling`, ampiezza `baseline_window_frames`) con lo stimatore **best-fraction**
  (liscio: mediana su finestra, non per-frame; guardia anti-churn 0.01″). Sostituisce l'attesa `refresh_interval_seconds`
  (1800s) del §25: `_maybe_start_refresh` è no-op in questa modalità.
- **C2 — bidirezionale:** rimosso il vincolo "tightest-wins": la baseline aggiornata **sostituisce** la corrente sia se
  più stretta sia se **più larga** → traccia il peggioramento (un RMS alto-ma-stabile per la notte resta NOMINAL, niente
  SEEING spurio). Kill-switch `[auto_calibration] baseline_track_bidirectional` (default **true**; `false` ripristina il
  legacy §25 tightest-wins per A/B).
- **C3 — CAP §24 MANTENUTO:** `rms_high = min(rms_high_factor × baseline, cap)` **invariato**. La derivazione soglie
  (cap + floor + anti-inversione §33) è stata estratta nel punto UNICO `_apply_derived_thresholds`, usato sia dal finalize
  sia dal tracker continuo (una sola sorgente di verità, nessuna divergenza). Interazione voluta: la baseline segue le
  condizioni **fino al tetto del cap** (~1,00″ sul 71F); sopra, il cap resta backstop assoluto.

### Backstop mantenuti (NON toccati)
Gate di **rifiuto baseline §23** (anche nel tracker continuo: baseline > `max(1.50, 3×pixel_scale)` → nessun update,
soglie correnti mantenute), **anti-inversione** `rms_low ≤ rms_high×0.85`, formazione §33/§40, esclusione implosion.
`/status.auto_calibration.track_bidirectional` per trasparenza.

### File / test / validazione
`phd2_agent/controller.py` (`_rms_rolling`; `_apply_derived_thresholds` estratto; `_continuous_track_baseline`;
`_update_rms_baseline` ristrutturato; `_maybe_start_refresh` gated; `/status`) · `phd2_agent/config.py`
(`baseline_track_bidirectional=True` + parsing) · `config.toml`. Test `TestBaselineContinuousBidirectional`
(peggioramento→baseline sale sotto cap; miglioramento→stringe; cap ancora efficace a baseline alta; gate §23 backstop;
kill-switch off→legacy) + 2 test §25 legacy aggiornati a `baseline_track_bidirectional=false`. Suite **213 verdi**.
**Smoke (71F, scale 1.579):** formazione baseline 0.541→`rms_high` 0.703 (= valore inchiodato di 223204); con seeing in
peggioramento baseline **sale** a 0.850 → `rms_high` **1.000** con `cap_active:true` (il cap fa da tetto); con
miglioramento baseline scende a 0.350 → `rms_high` 0.455. Niente commit/push (prompt git dedicato).

---

## 45. N1 — Transparency Index (Layer-2, ortogonale a PHD2) — Agente v2.6 (2026-06-19)

### Contesto
Primo indice Layer-2 sopra la telemetria §41/§42: un segnale di **trasparenza** del cielo dal conteggio stelle + fondo
della camera di RIPRESA (centinaia di stelle), che PHD2 — vedendo solo la stella di guida — non può dare. È il segnale
che alimenta N8 (§46). Metodologia live: born-operative, visibile in dashboard, kill-switch.

### Cosa fa (`phd2_agent/nina_indices.py`, nuovo — Layer-2 PURO, NON tocca lo store §41/§42)
`TransparencyTracker.ingest(payload)` per-posa; `status_block()` per /status; `confidence_input()` per N8.
- **Riferimento SEMPRE RELATIVO al campo+filtro corrente, MAI soglie assolute** (un campo povero ma stabile NON è una
  nube): rolling-high (mediana del best-fraction più ALTO) su finestra mobile per-filtro = "cielo più limpido recente".
  Conseguenza: livello basso ma **stabile** → ratio ~1 → CLEAR; calo % **rapido** (velature) → il riferimento "ricorda"
  il limpido recente → ratio basso → HAZE/CLOUD. **Privilegia il trend/derivata**, non l'assoluto.
- `TI = clamp((star_count/base_stars) × (base_bkg/bkg), 0..1)` — **NIENTE HFR** (domini separati: HFR = fuoco/seeing).
  Fondo cielo secondario. Stato **CLEAR/HAZE/CLOUD** con **isteresi**. `confirmed_subs` = pose consecutive col calo oltre
  la dead-band (trend, anti singolo frame anomalo) → usato da N8.
- **Cambio filtro** → finestra propria (riferimento si ri-forma). **Target** non ancora nel payload (arriva con N2): v1
  per-filtro + adattiva (onesto; robusta con N2). Graceful: niente star_count → no-op; nessun dato → indice None.

### Visibilità / config / log
`/status.nina.transparency` = `{enabled, available, index, state, deficit_pct, confirmed_subs, base_stars, star_count,
bkg, filter}`. Dashboard: card **"Trasparenza (NINA)"** (icona+stato CLEAR/HAZE/CLOUD, indice, stelle corrente/base,
filtro), nascosta se non disponibile. CSV: colonne `transparency_index`, `transparency_state` (schema 4→**5**). Config
`[nina_indices]` (`enabled=true`, `baseline_window_subs=12`, `base_best_fraction=0.5`, `clear_above=0.8`,
`cloud_below=0.5`, `hysteresis=0.05`, `deadband_deficit=0.10`) + parsing. Kill-switch `enabled=false`.

### Test (`tests/test_nina_indices.py`)
campo povero stabile → CLEAR (anti soglia-assoluta); calo % rapido → HAZE; calo forte sostenuto → CLOUD; confirmed_subs
sale e si azzera; singola posa anomala non persiste; cambio filtro → finestra propria → CLEAR; graceful/kill-switch.

---

## 46. N8 — Confidence fusion: la trasparenza modula la diagnosi SEEING — Agente v2.6 (2026-06-19)

### Contesto / gancio
Primo CONSUMATORE della telemetria NINA. Il motore §31 aveva `confidence_calibrated` **hard-coded False e inutilizzato**:
è il gancio per N8. NINA **non comanda le leve**: **modula** la fiducia del motore nel SEEING con una **penalità
proporzionale al calo % di trasparenza** (N1). Metodologia live: operativo, visibile, reversibile, GUARDIAN-piccolo,
fail-safe.

### Cosa fa (`diagnostic_engine.py`)
- `transparency_provider` iniettato nel motore (dal controller: `_nina_confidence_input`, che gatea la **freschezza**
  sullo store §43 — single-source — e ritorna None se feature off / telemetria assente o stantia → graceful PHD2-only).
- Modulazione **SOLO sulla diagnosi SEEING** (la trasparenza confonde solo il seeing; OVERCORRECTION/DRIFT/meccanica
  **mai** toccati). `confidence_finale = confidence_phd2 − penalità(deficit)`.
- **Penalità proporzionale** (`_nina_modulation`): dead-band sul rumore (`nina_deadband=0.10`) → ramp lineare fino a
  `nina_max_penalty=40` a `nina_full_deficit=0.45`; scatta **solo** se confermata su ≥ `nina_persist_subs=2` pose
  (anti singolo frame anomalo). Monotòna, tarabile. NINA **non aumenta MAI** confidence/aggressività (penalità sottratta,
  clamp ≥0). `confidence_calibrated=True` quando NINA fresca (anche con penalità 0).
- **Cosa tocca:** SOLO `confidence`, che è una **soglia** (`≥ guardian_min_confidence`) → effetto **binario al gate**
  (agisci/astieniti), **NON** scala l'ampiezza (governata da `guardian_action_factor`, intatto). Impatto leve in v1 =
  "a volte una micro-correzione in meno". Direzione sicura: solo astenersi dall'ammorbidire sul SEEING.

### Visibilità (cuore della validazione live), numeri RELATIVI
- **Evidence** con modulazione esplicita: `◦ trasparenza in calo (−18% vs riferimento campo) → confidence 76→58`.
- **Dashboard** (card motore): badge confidence **decomposto** `58% (PHD2 76 − NINA 18)`.
- **Grafico guida:** marcatore (rombo viola) quando NINA ha modulato (WS `nina_mod`, telemetria read-only).
- CSV: `nina_penalty` (+ `transparency_index/state`); decomposizione in `metrics`.

### Config / test
`[diagnostic_engine]` `confidence_use_nina=true` (born-operative) + `nina_deadband/full_deficit/max_penalty/persist_subs`
+ parsing; `false` = confidence PHD2-only (pre-§46). Test (`tests/test_nina_confidence.py`): penalità proporzionale
lieve(dead-band→0)/moderata/forte monotòna; seeing+velo lieve → resta sopra il gate (agisce); crollo → sotto il gate
(si astiene); OVERCORRECTION/DRIFT non modulati; persistenza (singola posa no, ≥2 sì); graceful/kill-switch; fail-safe
(mai aumenta). Suite **232 verdi** (213 + 19). Niente commit/push (prompt git dedicato).

---

## 47. Esperimento OUTCOME-FIRST: ramo oscillazioni disattivo (reversibile) + attribuzione — Agente v2.6 (2026-06-21)

### Direzione (Alessandro)
Il motore deve reagire al **risultato misurabile** della guida, non pre-classificare le cause. Con RMS reale + §44
baseline bidirezionale + Guardian + outcome + NINA/confidence, una vera oscillazione patologica **si manifesta comunque
come peggioramento di RMS/outcome** → non serve un ramo dedicato. *"Non mi interessa se la stella oscilla; mi interessa
se la guida peggiora."* **Esperimento REVERSIBILE**: si DISATTIVA (kill-switch), non si cancella; si rimuove solo dopo
3–4 sessioni di conferma. **Nota onesta dai log:** la OVERCORRECTION (lag-1) ha inciso ~1%; il driver dominante della
spirale è stato il **SEEING-softening + §32**, NON l'oscillazione → disattivare il solo ramo potrebbe non bastare: è
proprio ciò che l'esperimento deve rivelare (per questo §B strumenta l'attribuzione).

### §A — Ramo oscillazioni gateato (kill-switch `oscillation_branch_enabled`, default **false**)
- **Motore** (`diagnostic_engine.py`): nel ramo OVERCORRECTION lo stato resta **informativo** ma `proposal=None`
  (default) → nessuna micro/azione jitter da oscillazione; `micro_proposal()` ritorna None per OVERCORRECTION. `true` =
  legacy (`proposal=aggr-1`).
- **Controller** v2.3 **CASO2** ("Oscillazione=trend → ↓aggr") gateato dallo stesso flag → un trend non riduce più
  l'aggressività spacciandosi per oscillazione (la condizione cade nel ramo successivo/banda morta).
- Codice **dormiente** dietro il flag, reversibile. SEEING-softening (CASO1), §32 recovery, Guardian, §44 **invariati**.

### §B — Strumentazione di attribuzione (chi guida la spirale ora)
- `ControlAction.softening_source` (`SEEING`/`minmove_recovery_§32`/`guardian_micro`/`oscillation`/`optimization`/`other`)
  + `minmove_arcsec` (MinMove efficace = px×pixel-scale) su **ogni** azione → in `to_dict`/history/WS/jsonl.
- **Shadow would-have-fired** (motore): `osc_would_fire` (+ `osc_would_fire_degraded` quando rms>rms_high) = quante volte
  il ramo AVREBBE agito da disattivo → quantifica cosa è stato tolto e se in quei frame l'RMS peggiorava davvero.
- `/status`: blocco `oscillation_experiment` `{branch_enabled, softening_sources(breakdown sessione), osc_would_fire,
  osc_would_fire_degraded}` + i campi nel blocco `diagnostic_engine`. **Dashboard:** badge "ramo oscillazioni
  DISATTIVO (sperimentale)" + breakdown sorgenti softening + contatore would-fire.

### Config / test / validazione
`[diagnostic_engine] oscillation_branch_enabled=false` (born-operative, esperimento) + parsing. Test
(`tests/test_oscillation_experiment.py`, 7): default off → OVERCORRECTION proposal None + would_fire conta + CASO2 nessuna
azione; reversibile on → legacy; SEEING-softening e §32 **restano** e taggati (`softening_source`+`minmove_arcsec`).
2 test legacy OVERCORRECTION + 1 micro aggiornati a `oscillation_branch_enabled=true` (ramo ora opt-in). Suite **239
verdi** (232 + 7). Smoke: CASO1 → 2 azioni `softening_source=SEEING`, MinMove `minmove_arcsec=0.45`. NON in questo prompt:
cap MinMove + discriminatore oscillazione (parcheggiati). Niente commit/push.

---

## 48. N1 finalizzato come UNICO riconoscitore trasparenza + contratto `fresh` per i consumatori — Agente v2.6 (2026-06-21)

### Architettura a livelli (confermata)
**N1 è l'unico modulo che riconosce la trasparenza** (Layer-2, `nina_indices.py`, §45). **N6 (safety, §49) e N8
(confidence, §46) sono semplici consumatori** dello STESSO stato di N1: N8 usa l'`index` continuo (penalità
proporzionale), N6 usa lo `state` discreto CLEAR/HAZE/CLOUD. **Nessun'altra parte ricalcola le nubi.** N1 espone
**sia** l'indice continuo **sia** lo stato discreto; l'isteresi di sicurezza vive nel consumatore (N6), non in N1.

### Cosa cambia in §48 (N1 già in §45, qui si finalizza il contratto)
- **`/status.nina.transparency.fresh`** (nuovo, `server.py`): freschezza **single-source** dallo store §43
  (`is_fresh`, adattiva alla posa). È il campo che N6 usa come **FAIL-SAFE**: senza telemetria fresca la condizione nubi
  è neutra. Aggiunto anche `background` (alias di `bkg`) al blocco per il contratto consumatori.
- Il resto di N1 (baseline per-filtro relativa rolling-high, TransparencyIndex continuo stelle+fondo NO-HFR con enfasi
  trend, persistenza `confirmed_subs`, stato CLEAR/HAZE/CLOUD con isteresi, card dashboard, colonne CSV, kill-switch
  `[nina_indices]`, graceful) è invariato dal §45. Nota onesta: baseline per-**target** piena arriva con N2 (oggi
  per-filtro + adattiva al regime).
- Test: `TestTransparencyFreshContract` (fresh=true dopo POST recente; fresh=false su staleness → fail-safe N6;
  fresh=false senza tracker). Suite **242 verdi**.

---

## 49. N6 — Safety su nubi: il Safety Monitor ferma la ripresa sulle nubi (plugin v1.4) — 2026-06-21

### Motivazione di campo (2026-06-21)
Nuvole copiose → il modulo SEEING ha letto il degrado-da-nubi come seeing e il **Safety Monitor NON ha fermato la
ripresa** (oggi va UNSAFE solo su `STAR_LOST` di guida, 5 min). Il conteggio stelle dei light NINA crollava tra le pose
= firma delle nubi, segnale **già** in arrivo (§42) ma non consumato. N6 è il consumatore-sicurezza sopra N1.

### Cosa fa (repo plugin, cross-processo: legge il `/status` che già interroga)
- **`AgentHealthChecker.ProbeStatusAsync`** ora estrae anche `nina.transparency` (`state`, `fresh`, `index`) dallo
  stesso `/status` (JSON puro → **version-agnostic**, gira su NINA 3.2 e 3.3). `AgentStatusSnapshot` esteso con
  `TransparencyState`/`TransparencyFresh`/`TransparencyIndex` (tolleranti: assenti → null/false).
- **`SafetyDecisionEngine`** — condizione CLOUD **ACCANTO** a STAR_LOST (due latch indipendenti, OR):
  - **UNSAFE** se `state==CLOUD` per **`CloudUnsafePolls`** poll consecutivi (isteresi lenta; default 8).
  - **SAFE** se `state∈{CLEAR,HAZE}` per **`ClearSafePolls`** poll (recovery più rapido; default 4). HAZE breve NON
    manda unsafe.
  - **FAIL-SAFE (critico):** feature off o `fresh==false`/transparency assente → condizione nubi **neutra** (contatori
    azzerati, latch congelato: non forza UNSAFE né SAFE). Resta STAR_LOST come backstop. Si agisce sulle nubi **solo** su
    segnale CLOUD **positivo e fresco**.
  - `LastCause` (StarLost/Cloud) → notifica/log distinguono la causa. Confine invariato: il monitor segnala UNSAFE/SAFE,
    **NINA** decide pausa/park.
- **Settings** (`PluginSettings` + view): toggle `CloudSafetyEnabled` (default ON, kill-switch) + `CloudUnsafePolls`/
  `ClearSafePolls` (DTO nullable → upgrade-safe). **Version bump plugin 1.3.0.0 → 1.4.0.0** (csproj + AssemblyInfo +
  DriverInfo/Version). GUID plugin e Safety Monitor invariati; dipendenze NINA/WebView2 invariate.

### Validazione
Build plugin Release **0 errori / 0 warning** contro SDK NINA 3.2.0.9001. Algoritmo del `SafetyDecisionEngine`
validato con simulazione deterministica (mirror del C#) sui 7 scenari: CLOUD persistente→UNSAFE(causa Cloud); HAZE
breve→no; recovery CLEAR→SAFE; STAR_LOST invariato; fail-safe `fresh=false`→nessun unsafe spurio; kill-switch off→solo
STAR_LOST; freeze (cloud-unsafe + telemetria stantia → resta unsafe, non forza safe). Test NINA-in-the-loop = manuali
(sul campo). **Nota utente (README):** in NINA la sequenza deve avere **"Wait Until Safe" DENTRO il loop** di ripresa
per protezione continua. Niente commit/push.

---

## 50. Fondamenta motore (A): INIT ai valori standard PHD2 — stato iniziale noto — Agente v2.6 (2026-06-22)

### Perché (P1)
Un controllore adattivo deve partire da uno **stato noto**: così ogni adattamento è attribuibile al motore, non alla
configurazione ereditata dall'utente, e i **log dei beta tester diventano confrontabili**. Principio architetturale
(non sperimentazione), trasversale a Outcome-First/Guardian/NINA.

### Cosa fa (`controller.py`, in `initialize()` dopo calibrazione, prima della baseline)
Ciclo: `Connessione → Calibrazione → Inizio guida → INIT standard → Formazione baseline → Agent attivo`.
- Punto d'inserzione: subito **dopo `save_baseline()`** (che salva i valori leva utente per il restore) e **prima** della
  formazione baseline. Su reconnect il Baseline Guardian ha già ripristinato i valori utente (orphan restore) prima di
  questo punto → nulla si perde.
- **Valori standard** (via `_apply`, che converte con `aggr_native_scale`): **RA (Hysteresis)** aggr **70** (→0.70
  native), MinMove **0.20**; **DEC (Resist Switch)** aggr **100** (→1.00 native), MinMove **0.20**.
- **Algoritmo-aware (fail-safe):** applica SOLO se l'asse usa la scala frazionaria `aggression` (native 0.01 =
  Hysteresis/Resist Switch). Se l'asse usa un algoritmo a scala diversa (es. Lowpass2 `aggressiveness` 0-100) → **WARNING
  + skip** di quell'asse (mai valori a scala sbagliata).
- **Ripristino:** allo shutdown pulito il Baseline Guardian ripristina i valori utente; su kill brutale l'orphan-recovery
  li recupera. Rispetta `dry_run`. Sorgente azione `softening_source=init_standard`.
- Kill-switch `[control] init_to_phd2_standard=true` (false = eredita come oggi).

---

## 51. Fondamenta motore (B): cap MinMove ADATTIVO (baseline §44 filtrata) — Agente v2.6 (2026-06-22)

### Perché
Il MinMove può salire per assorbire il seeing, ma **mai oltre ciò che il setup può davvero raggiungere** (altrimenti
ignora errori ancora correggibili → esce dalla regione ottimale). Riferimento **deciso**: NON la baseline iniziale
(fotografa solo l'avvio), NON il valore istantaneo (rincorre il seeing), **SÌ la baseline §44 FILTRATA nel tempo**
(EMA su ~decine di minuti): capacità reale media della notte, segue lentamente l'evoluzione.

### Cosa fa (`controller.py`)
- **EMA temporale** della baseline §44 (`_update_minmove_baseline_filter`, una volta per tick in `evaluate`), costante di
  tempo `baseline_filter_tau_minutes` (~18 min). Fallback: EMA non pronta / baseline rifiutata → **nessun cap** (legacy).
- **Formula:** `cap_arcsec = min( k × baseline_filtrata , imaging_ceiling_arcsec )`, `cap_px = cap_arcsec / pixel_scale`.
  - **`k` UNIVERSALE < 1** (default **0.8**): è un **rapporto** (dead-band ÷ RMS raggiungibile) → scale-indipendente per
    costruzione → uguale per tutti i setup. k<1 tiene il dead-band una frazione dell'RMS (niente feedback cap↔baseline).
  - **`imaging_ceiling_arcsec`** (default 2.0, **per-setup**, stub di N5): requisito di imaging. **La dipendenza dalla
    scala di RIPRESA entra QUI, non in k.** In futuro derivato da scala imaging + durata posa (N5 completo).
- **Applicato in salita** su **entrambi gli assi** a **tutti** i punti che alzano MinMove: CASO1 seeing-softening, §32
  recovery, micro/jitter (`_apply_proposal`). Upper-bound `min(new_mm, cap_px)`; floor `minmove_min` resta la barriera
  inferiore. La discesa (CASO3) non è toccata.
- **/status.minmove_cap:** MinMove efficace arcsec per asse, `cap_arcsec`/`cap_px`, `winning` (guiding vs imaging),
  `baseline_filtered_arcsec`. Kill-switch `[limits] minmove_cap_adaptive_enabled=true`.

### Config / test / validazione
Config: `[control] init_to_phd2_standard` (§50) + `[limits]` scalari `minmove_cap_adaptive_enabled` /
`minmove_cap_baseline_factor`(k) / `minmove_imaging_ceiling_arcsec` / `baseline_filter_tau_minutes` (§51). Test
(`tests/test_engine_foundations.py`, 12): INIT applica 70/0.20 (RA) e 100/0.20 (DEC), skip+warning su algoritmo
non-standard, kill-switch eredita; cap guiding-term vince (0.5→0.4"→0.8px), imaging-ceiling vince, clamp in salita, floor
vince su cap minuscolo, fallback (disabilitato/EMA None), EMA seed+track lento, usa il filtrato non l'istantaneo, CASO1
rispetta il cap. Suite **254 verdi** (242 + 12). NON toccati: backlash, esposizione, §31, telemetria §41/§42, baseline
§44 (LETTA filtrata, non modificata), cap rms_high §24. Niente commit/push.

---

## 52. Dashboard: card "Adaptive MinMove" (§51) aggiunta + card "Oscillation" rimossa (Outcome-First) — 2026-06-22

Frontend (`dashboard/`) + un solo flag backend. Principio di progetto dashboard: **mostra solo informazioni operative
utili durante una sessione**; le logiche sperimentali restano nel backend/`/status` e nei log, non affollano la vista.

- **§0-bis (backend, `controller.py`):** nuovo flag **`/status.minmove_cap.clamping_active`** — true SOLO quando il
  controllore ha richiesto un MinMove-up **maggiore del cap** e il cap l'ha tagliato (registrato in `_cap_minmove_up`
  quando `cap_px < new_mm`), con persistenza anti-flicker (`_MINMOVE_CLAMP_PERSIST_S=90s`). ACTIVE ≠ "MinMove==cap".
  Nessun cambio alla logica di clamp (già presente). Test in `test_engine_foundations.py` (255 verdi).
- **Card "Adaptive MinMove"** (`index.html` + `updateMinMoveCap` in `app.js`, accanto ad Auto-calibrazione): badge
  **ACTIVE (arancione) / IDLE (verde)** guidato da `clamping_active` (con tooltip), **cap** arcsec(+px), **baseline
  filtrata** §44, badge **GUIDING/IMAGING** (termine vincente, con tooltip), **MinMove efficace RA/DEC** in arcsec, k +
  soffitto imaging. Graceful: `minmove_cap` assente / kill-switch off → "NON ATTIVO" (grigio), nessun errore JS.
  Verificato live via preview (ACTIVE→arancione, GUIDING→blu, IDLE→verde, graceful→"NON ATTIVO", 0 errori console).
- **Card "Oscillation" rimossa** dalla vista principale (elemento `diag-osc-experiment` + `updateOscExperiment` + call).
  Il **backend `/status.oscillation_experiment` NON è toccato** (resta per log/analisi; leggibile dal JSON grezzo).
  `diagnostic_engine` e le altre card intatte; nessun riferimento pendente. Coerente con Outcome-First (ramo oscillazioni
  disattivo di default §47 → la sua card mostrava logica superata).
- **Cache:** dopo l'update, hard-refresh (Ctrl+Shift+R); il pannello NINA WebView2 può restare su versione cached.
  Niente commit/push.

---

## 53. Recupero SIMMETRICO guidato dall'esito: banda morta bidirezionale (aggr + MinMove) — Agente v2.6 (2026-07-02)

### Causa (evidenza `session_20260702_215202`)
Prova con seeing degradato simulato + recupero + crash camera. **Degradazione:** motore corretto (leve ammorbidite,
aggr al pavimento 35/35). **Recupero:** RMS torna a ~0,75" (poco sopra baseline, niente più SEEING) **ma le leve restano
aperte** e l'aggressività **non risale mai** in sessione continua (DEC = 10 GIÙ / 0 SU nell'intera notte). Solo il
crash→INIT §50 ha riportato lo standard → **il problema è la logica di RECUPERO, non i valori.**
**Asimmetria del control-law (letta nel codice):** (a) il §32 "recupero banda morta" **alzava** il MinMove (un secondo
*softening*, non un recupero); le micro-discese viste erano il cap §51 che tagliava; (b) l'aggr risaliva **solo nel
CASO3** (`rms<rms_low`, guida già ottima) → nella banda morta **nessun percorso alzava l'aggr** → ratchet unidirezionale
verso il morbido.

### Fix (§53): banda morta BIDIREZIONALE guidata dall'esito, àncora = standard §50
`controller.py`, ultimo `elif` di `_evaluate_axis` → dispatch sul VERSO deciso in `_update_recovery_state`:
- **STIFFEN** (`_recovery_stiffen_axis`): se le leve sono più MORBIDE dello standard §50 (`_levers_softened`) **e** la
  guida è STABILE (`_recovery_is_stable`: RMS non in salita + non-SEEING + N1 non-CLOUD advisory), irrigidisce verso lo
  standard — **aggr SU** (esteso all'aggressività, oggi senza recupero; solo assi a scala frazionaria; mai OLTRE il
  nominale §50) + **MinMove GIÙ** (mai SOTTO il nominale §50). Un gradino per cooldown (`_apply_with_guardian`,
  caso="RECOVERY" → guardian CONFIRM, §31 intatto).
- **Outcome gate** (`_finalize_recovery_windup`, ramo stiffen): su `recovery_outcome_window_frames`, se l'RMS regge
  (≤ anchor×`recovery_outcome_tolerance_factor`) → KEEP + ri-ancora + prossimo gradino; se peggiora → **STOP**
  (`_recovery_stiffen_blocked`), tiene le leve e passa a soften (era seeing vero).
- **SOFTEN** (`_recovery_soften_axis`): il §32 legacy (alza MinMove) diventa **FALLBACK evidence-based** — scatta solo se
  non-softened (niente da recuperare) o dopo lo STOP dell'irrigidimento. Sparisce il ratchet.
- **Anti-flapping:** verso deciso globalmente una volta per tick; un solo verso per asse/tick; `_recovery_stiffen_blocked`
  non si sblocca finché l'RMS non rientra (reset del run). **Satisfaction §30:** rms ≤ soglia → nessuna azione (guida
  buona = lasciare stare). **Cap §51** resta il tetto in salita; aggr ≤ nominale §50, MinMove ≥ nominale §50.

### Visibilità / config / test
`/status.recovery` = `{enabled, state (RECOVERING/HOLDING/IDLE), direction, anchor_rms, consec, blocked, stiffen_blocked}`
+ log dettagliati (verso, old→new, anchor, verdetto KEEP/STOP). Config `[lever_optimization]`: `symmetric_recovery_enabled`
(true, born-operative, kill-switch), `recovery_stiffen_aggression` (true), `recovery_outcome_window_frames` (6),
`recovery_outcome_tolerance_factor` (1.05) + parsing. Test `tests/test_recovery_symmetric.py` (9): stiffen su
softened+stable, **aggr recupera** (regressione dell'asimmetria), outcome STOP/KEEP, fallback dopo STOP, bounds §50 (aggr
≤ nominale, MinMove ≥ nominale), satisfaction §30 → no-op, kill-switch = §32 legacy, anti-flapping. I test legacy §32
(`test_minmove_recovery.py`) opt-in a `symmetric_recovery_enabled=false`. Suite **264 verdi** (255 + 9). Smoke (aggr al
floor + RMS 0,75" stabile): aggr **risale** (RECOVERING, non più inchiodato) — la fix del bug di campo. NON toccati:
backlash, §31/§44/§50/§51/N1/N6/N8. Niente commit/push (validazione di campo prima).

---

## 54. Deprecazione modalità JITTER: rimossa dal toggle dashboard + guard-rail backend — Agente v2.6 (2026-07-02)

### Motivazione
La modalità **JITTER** (motore §31 UNICA autorità sulle leve → catena CASO 1/2/3 **sospesa**) **scavalca** tutto il
controllore outcome-first validato (§44 baseline bidirezionale, §50 INIT, §51 cap, **§53 recupero simmetrico**, §32,
satisfaction §30) ed è **mai validata sul campo**. Era attivabile **a un clic** dal toggle dashboard (OFF/GUARDIAN/JITTER)
→ rischio che io o un beta-tester ci finisse per sbaglio. **GUARDIAN** è la modalità ufficiale; **OFF** resta A/B legittimo.
Il **motore §31** e **GUARDIAN** restano invariati: si deprecano solo la **modalità** jitter (engine-owns-levers) e la sua
esposizione UI. Codice jitter **non cancellato**: dormiente, raggiungibile solo con flag esplicito.

### §1 — Frontend (`dashboard/`)
Switcher ridotto a **`['off','guardian']`** (render + handler in `app.js`); bottone `diag-btn-jitter` rimosso da
`index.html` (commentato); `confirm()` jitter rimosso (resta quello GUARDIAN). **Badge graceful**: se un config legacy
riporta ancora `mode="jitter"`, il badge mostra **"JITTER (deprecato)"** senza ricreare il bottone né rompere nulla
(CSS `mode-jitter` innocuo). Verificato live via preview: nessun bottone jitter, OFF+GUARDIAN presenti, badge legacy
corretto, 0 errori console.

### §2 — Backend guard-rail (difesa in profondità)
Nuovo flag `DiagnosticEngineConfig.allow_experimental_jitter` (default **false**). Due punti di intercetto:
- **`controller.set_diagnostic_mode("jitter")`**: se il flag è off → coercizione a **GUARDIAN** con WARNING prominente;
  l'endpoint ritorna la modalità **EFFETTIVA** (guardian) così la UI riflette la realtà. Il gate è a monte di
  `allow_dashboard_mode_switch`; `_engine_owns_levers()`/CASO/§53 **non toccati**.
- **`config.load_config`**: `mode="jitter"` + flag assente/false → fallback GUARDIAN + WARNING (nessun crash).
Con `allow_experimental_jitter=true` la jitter è **onorata** (percorso deliberato per una futura validazione live) e il
ramo jitter resta **funzionante e invariato**, solo gated.

### Config / test
`[diagnostic_engine] allow_experimental_jitter=false` nel `config.toml` (commento: sblocca jitter deprecata; scavalca
§44/§50/§51/§53). Test `tests/test_jitter_deprecation.py` (6): jitter→guardian con flag off (+WARNING, ritorno effettivo);
jitter onorata con flag on (`_engine_owns_levers()` True); off/guardian invariati; config legacy jitter→guardian; config
con flag→jitter; default guardian. Test esistente `test_activation_gated` aggiornato (usa `allow_experimental_jitter=true`
per esercitare il gate allow_dashboard con jitter). Suite **270 verdi** (264 + 6). Coerente col principio dashboard
(§51/§52): la vista mostra solo logica operativa e validata. Niente commit/push.

## 55. FIX di sicurezza N6: stantio→UNSAFE, persistenza CLOUD sull'indice, agent-lost≠safe + osservabilità — Plugin v1.5.0.0 + Agente (2026-07-10)

**Contesto.** Validazione live 2026-07-09/10 (Borno, RC8): N1 ha seguito il cielo perfettamente (indice fino a 0.08,
stelle >150→5) ma il Safety Monitor è rimasto SAFE per ~17 min di nube piena e non ha mai fermato la sequenza. Dai log
NINA (v3.3.0.1048): zero UNSAFE-nube in tutta la notte (3 UNSAFE, tutte STAR_LOST), 3 episodi "Agente offline →
monitor disconnesso → **Safe**", 2 eccezioni cross-thread nel health-checker. Tre bug concatenati, tutti con lo stesso
difetto di direzione: **quando N6 smette di vedere bene, si dichiarava al sicuro invece di fermarsi.**

**Root cause (verificate sul codice al pre-flight):**
- **Bug A** (`SafetyDecisionEngine.cs`): `isClearish = CLEAR||HAZE` azzerava lo streak nubi → col flicker
  CLOUD↔HAZE di N1 gli 8 poll consecutivi erano irraggiungibili.
- **Bug B**: blocco CLOUD gated da `TransparencyFresh`; il ramo `else` azzerava gli streak → telemetria stantia =
  sicurezza-nubi silenziosamente SPENTA (più nubi → meno pose → più stantio → meno sicurezza: fail-dangerous).
- **Bug C** (`AdaptiveAgentSafetyMonitor`): agente irraggiungibile → `Disconnect()` → `IsSafe=true` (+ mai riconnesso;
  timeout HTTP 3s → bastava un tick lento). Alle 03:17 il flip a Safe è avvenuto con un WaitUntilSafe attivo.
- **Bug C-bis**: eccezione cross-thread di un subscriber in `OnTick` → catch unico → `Evaluate` SALTATO per quel tick.

**Fix (plugin v1.5.0.0, tutta la decisione nel `SafetyDecisionEngine`, unit-testabile via `ISafetySettings`):**
- **§2 indice leaky** (`UseIndexCloudLogic=true`, kill-switch→legacy): degrado +1/poll se `index<0.5` (=cloud_below N1),
  −2/poll se `index≥0.8` (=clear_above N1; rate=CloudUnsafePolls/ClearSafePolls), zona HAZE **neutra** (non azzera).
  UNSAFE a degrado≥8 (2 min), SAFE a 0. Fallback su stato discreto se indice assente (HAZE comunque neutra).
- **§1 stale→UNSAFE** (`StaleUnsafeEnabled=true`, `StaleUnsafePolls=8`): fresh=false (già = oltre finestra adattiva §43,
  quindi il gap normale tra sub NON scatta) + sessione attiva + ultimo contesto degradato (index<0.5 o stato≠CLEAR) →
  UNSAFE causa `StaleTelemetry`. Lo stantio NON azzera più il degrado accumulato.
- **§5 agent-lost≠safe** (`AgentLostUnsafeEnabled=true`, `AgentLostUnsafePolls=4`): eliminato l'auto-Disconnect; il
  monitor resta connesso, il checker passa `AgentReachable=false` a ogni tick → a sessione attiva UNSAFE causa
  `AgentLost` (~1 min). A guida INACTIVE: neutro (fine sessione = normale). `Disconnect()` esplicito non imposta più
  IsSafe=true. Latch preservati durante l'irraggiungibilità; il rientro NON è gratis (degrado saturato → servono
  ClearSafePolls di evidenza CLEAR; senza trasparenza: guida NORMAL per ResumeTicks).
- **Bug C-bis**: `OnTick` con try/catch per-stadio (un subscriber che lancia non salta più Evaluate, loggato Warning);
  `Notification.Show*` marshallate sul dispatcher (`ShowToast`). Timeout HTTP 3s→5s (robustezza, NON il fix).
- **§3 osservabilità**: `Logger.Debug` per tick (`N6 tick: reachable/guiding/transp/idx/fresh/age | degr/stale/lost |
  latch → SAFE/UNSAFE`), `Logger.Info` su ogni transizione con causa; agente espone `age_s`+`window_s` in
  `/status.nina.transparency` (server.py, dallo store §43); card dashboard: "Telemetria FRESH·42s / STANTIA·età>finestra".

**Settings nuove** (persisted DTO nullable, born-operative): `UseIndexCloudLogic`, `CloudIndexAccumulateBelow=0.5`,
`CloudIndexDrainAbove=0.8`, `StaleUnsafeEnabled`, `StaleUnsafePolls=8`, `AgentLostUnsafeEnabled`, `AgentLostUnsafePolls=4`.
UI settings completamente in inglese (chiusura item pendente) + righe nuove; badge/fallback/launcher EN.

**Test**: NUOVO progetto `tests/AdaptiveAgentForPHD2.NinaPlugin.Tests` (MSTest, primo del repo plugin): **12 verdi** —
gli 8 casi del prompt (flicker→UNSAFE; stale+degradato→UNSAFE; contesto CLEAR stantio→nessun falso allarme; 0.08
sostenuto→UNSAFE in 8 poll; recupero con isteresi; kill-switch=legacy bit-identico incl. Bug A riprodotto;
agent-lost→UNSAFE e mai SAFE; INACTIVE+offline→neutro) + latch preservato, rientro con evidenza, regressioni STAR_LOST
e payload invalido. Agente: suite **270 verdi** (contratto `age_s`/`window_s` in test_nina_telemetry). Build plugin
Release **0 warning / 0 errori**. Pacchetto agente ricompilato. **Validazione live alla prossima notte con nubi**
(o simulando stantio) osservando card Telemetria + log N6. Niente commit/push (gate).

## 56. Fix re-init "self-orphan" + leve preservate tra ripartenze + log su file — Agente v2.7 (2026-07-12)

**Motivazione (prova sul campo).** Log del 2026-07-12: il WARNING `Trovata baseline.json orfana — sessione precedente
non chiusa correttamente` delle 02:42:05 coincide AL SECONDO con "Guiding Begins at 02:42:05" nel PHD2 GuideLog; la
guida è ripartita ~9 volte tra 02:20 e 03:52 → ~9 falsi orphan. Causa (verificata al pre-flight): `initialize()` è
ri-eseguita a OGNI ripartenza guida (`GuidingStopped → mark_uninitialized()`, poi StartGuiding/AppState→Guiding) ed
eseguiva SEMPRE l'init pieno: (1) `_check_orphan_baseline()` trovava la baseline scritta da NOI al primo init (mai
cancellata fino allo shutdown) → falso "orfana" + `restore_baseline` ai valori UTENTE; (2) subito dopo §50
`_init_to_phd2_standard()` → valori STANDARD. Doppio reset: la convergenza costruita nella corsa precedente veniva
scartata a ogni autofocus/cambio filtro/ricentraggio.

**Architettura del fix (`controller.py`).** Nuovo flag di PROCESSO `_process_initialized` (accanto a `_initialized`
di sessione), settato una sola volta al primo `initialize()` riuscito e MAI resettato da `mark_uninitialized()`.
In `initialize()`: `full = first_init or cfg.control.full_reinit_on_restart` — orphan-check, `save_baseline()` e §50
girano solo se `full`; sui ri-init di sessione resta il ri-aggancio leggero (esposizioni, `probe_algo_params`/
`_setup_axis` — che RI-LEGGE le leve reali da PHD2, quindi l'agente resta veritiero —, pixel scale, diagnostic engine)
con `INFO "Ri-aggancio guida (ripartenza sessione) — leve preservate: …"` (niente WARNING). `reinitialize()` (API senza
chiamanti, "dopo cambio profilo utente") ora resetta anche `_process_initialized` = re-bootstrap completo esplicito.
La recovery VERA resta garantita: un nuovo processo nasce con flag False → orphan-check al primo init, guard esistenti
intatti (setup_id uguale, età<24h, versione≥2). Niente token di processo nel baseline.json (deciso al Gate): col gating
il self-orphan è strutturalmente impossibile; il token avrebbe richiesto baseline v4 + migrazioni per un percorso morto.

**Kill-switch**: `[control] full_reinit_on_restart = false` (default = nuovo comportamento; `true` = legacy identico,
init pieno a ogni ripartenza). Parsing TOML retrocompatibile (chiave assente → false).

**§B — log su file** (`main.py setup_logging()`): `RotatingFileHandler` su `logs/agent.log` (5 MB × 5, UTF-8, fallback
console-only se non scrivibile) — i crash notturni (es. hang 02:48 / offline 03:59 del 2026-07-12) ora lasciano
traceback. Header di versione: il banner (versione agente) finisce nel file; nuovo branch evento `Version` di PHD2 in
main.py → `INFO "PHD2 vX.Y.Z (subver, MsgVersion)"` alla connessione. Versioni plugin/NINA NON conoscibili lato agente
(la telemetria §41 ha `source="nina-plugin"` senza versione): estenderle = micro-feature separata, non fatta qui.

**Comportamento atteso.** Ripartenze guida nella stessa sessione: nessun WARNING "orfana", leve ai valori convergenti
(visibile in dashboard/decisions_*.jsonl). Shutdown pulito: baseline rimossa, riavvio senza orphan. Crash (kill del
processo): al riavvio orphan-recovery vera UNA volta. `logs/agent.log` popolato.

**File modificati**: `phd2_agent/controller.py` (flag + gating + reinitialize), `phd2_agent/config.py` +
`config.toml` (kill-switch), `main.py` (RotatingFileHandler + evento Version). **Test**: nuovo
`tests/test_reinit_orphan.py` (8): orphan reale al primo init (restore+§50); ri-init leggero (niente orphan/save/§50,
leve preservate = stato reale PHD2, no WARNING); crash→nuovo processo (recovery vera); kill-switch legacy; guard
setup/età; reinitialize=full; smoke `logs/agent.log`. Suite **278 verdi** (270+8), zero regressioni (nessun test
esistente chiamava davvero initialize/save/restore — verificato al pre-flight). Pacchetto ricompilato.

**Limiti / validazione raccomandata.** Su riavvio di PHD2 a metà sessione (profilo ricaricato) il ri-init leggero
adotta i valori del profilo utente senza ri-applicare §50 (comportamento pre-§50: sicuro; eventuale re-bootstrap
esplicito disponibile via `reinitialize()`). Validazione campo: (1) ripartenze guida senza WARNING e leve stabili;
(2) shutdown pulito senza orphan al riavvio; (3) kill da task manager → orphan-recovery una sola volta; (4) agent.log
popolato. Niente commit/push senza gate.

## 57. Recovery AUTO-STARTING da UNSAFE-nubi: S1 sonda-timeout (template builtin) + S2 hint SNR-guida — Agente v2.7 + Plugin v1.6.0.0 (2026-07-13)

**Motivazione (deadlock provato, notte 12/7).** §55 ferma correttamente su nubi, ma il ritorno a SAFE richiede dati
freschi da N1, che si aggiorna SOLO sui light salvati — e il `Wait Until Safe` di NINA non scatta pose (verificato sul
sorgente: puro poll 5s). Prova: indice congelato a 0.115 per 28 min (00:41→01:09) mentre la SNR guida oscillava 30↔63
(il cielo variava, nessuno lo misurava). Mancava il "come ripartire".

**Ricognizione builtin-first (decisiva, ha cambiato l'architettura).** (1) Il "Trigger On Unsafe" visto da Alessandro
è CORE NINA 3.3 (Before/After Waiting For Safety; assente dall'SDK 3.2). (2) `LoopWhileUnsafe` esiste GIÀ nel core
(anche SDK 3.2): condizione inversa di "Loop while safe", e il ConditionWatchdog taglia il container ANCHE a metà di un
Wait → un loop sonda che esce da solo, all'istante, al ritorno del SAFE. ⇒ **S1 è esprimibile al 100% builtin**:
l'`ISequenceItem WaitForSafeWithProbe` prevista dal prompt è stata ELIMINATA (gate intermedio approvato).

**Architettura (distribuita, N1/N6/forwarder INTATTI — diff vuoto):**
- **S1 (fail-safe, zero codice)** — template di sequenza: `Trigger On Unsafe → Before = Container[Loop While Unsafe]:
  Wait 12min → Take Exposure (LIGHT, stessa esposizione del sub, filtro già in posizione, NON guidata — in nube fitta
  la stella guida sparisce: 13/7 guida mai ripartita dalle 03:20)`. Sonda salvata → forwarder (già senza filtro tipo
  immagine) → N1 fresco → drain §55 → SAFE → il watchdog esce dal loop → la sequenza riprende.
  Doc completo: `TEMPLATE_SEQUENZA_RECOVERY_S1.md` (ordine, container, parametri, motivazioni, limitazioni).
- **S2 (acceleratore, autorità ZERO)** — agente: nuovo `phd2_agent/recovery_hint.py` (`RecoveryHintTracker`, fratello
  di N1): integra la SNR guida per-frame (fluisce durante l'attesa) con accumulatore leaky SIMMETRICO al CLOUD di N6
  (+1 se snr ≥ max(floor, frac×snr_ref), −drain altrimenti; latch a sustained, rilascio a 0), gated su ultimo stato N1
  CLOUD/HAZE (a CLEAR è inerte e cattura snr_ref in EMA). Espone `/status.recovery_hint` (active/snr/ref/accumulatore/
  reason/probes) + card dashboard "Recovery (§57)". `observe_probe()` (hook 1-riga in server.py accanto all'ingest):
  registra ogni sonda con attribuzione by-construction (hint attivo ⇒ `hint_S2`, altrimenti `timeout_S1`) + esito
  (index/state post) — paletto 8. NESSUN percorso verso N6/IsSafe (test strutturale).
- **Plugin v1.6.0.0** — micro-istruzione `WaitForRecoveryHint` ("Wait for recovery hint (Adaptive Agent)"):
  puro GATE TEMPORALE dentro il loop (al posto del Wait fisso): ritorna a `hint.active OR timeout`, MAI prima di
  `min_interval` (floor assoluto, anche per il timeout — paletto 3), logica pura in `RecoveryProbeGate` (testabile).
  Non legge/imposta safety (l'uscita a SAFE è del LoopWhileUnsafe via CancellationToken), non cattura immagini
  (niente IImagingMediator — test strutturale), agente offline ⇒ puro S1. Config: `[recovery_probe]` (timeout 12min,
  min_interval 5min, match_sub) + `[recovery_hint]` (frac 0.8, floor 25, sustained 20 frame ≈60s, cap 20, drain 2 —
  PROVVISORI; nota: i "poll" sono guide-frame ~3s, non i poll 15s del plugin: 8 frame sarebbero ~24s, troppo nervosi).

**Paletti (8/8):** S1 autonomo (hint spento ⇒ Wait fisso) · sonda match-sub non guidata · min-interval floor ·
osservabilità totale (log agente+NINA+card) · soglie provvisorie in TOML · accumulatore/isteresi (no flag nudo) ·
3 kill-switch a strati (template rimovibile / `recovery_hint.enabled` / istruzione sostituibile col Wait) · telemetria
per-sonda completa. **Test**: agente `test_recovery_hint.py` (12: picco singolo no, isteresi, gating CLEAR/ignoto,
soglia relativa+floor, strutturale no-safety, kill-switch, attribuzione S1/S2, light normale non registrato) — suite
**290 verdi**; plugin `RecoveryProbeGateTests` (6: S1 standalone, floor con hint, floor sul timeout, hint mai
soppressivo, reason S1/S2, no-imaging strutturale) — **18 verdi** totali. Build plugin **0 warning**.

**Limiti/validazione.** Sonde = light veri nella cartella target (se il cielo era tornato sono sub buoni). Template
richiede NINA 3.3 (variante 3.2 documentata: blocchi alternati Loop While Safe/Unsafe). Prova a banco col pannello
Gemini (chiudi→UNSAFE→sonde S1→riapri→hint→sonda S2→SAFE, cronometrare l'anticipo). Taratura `[recovery_hint]` dai
record di 2-3 notti. §58 (park su unsafe prolungato) mappato: stesso trigger, `Before = [LoopWhileUnsafe: Wait X →
Park]` (il watchdog salta il Park se il safe torna presto) — prompt separato. Niente commit/push (gate).

### §57-bis — Revisione post-GUI: RecoveryProbe autocontenuta + hint a tempo reale (2026-07-13)

**Trigger della revisione (prova pratica di Alessandro sulla GUI, NINA 3.3.0.1048):** i container del Trigger On
Unsafe ACCETTANO le istruzioni del plugin ma RIFIUTANO le istruzioni di categoria Camera (Take Exposure & co.) → il
template v1 (gate `WaitForRecoveryHint` + TakeExposure esterno) non era montabile. Verifica sorgente: il trigger usa
`SequentialContainer` senza restrizioni nel proprio codice → il filtro è nel layer GUI/drop (coerente: la nostra
istruzione ha categoria propria). Gate §57-bis approvato con due decisioni:

1. **Sonda DENTRO l'istruzione** (proposta di Alessandro, paletto v1 ritirato con motivazione): il divieto di
   `IImagingMediator` nasceva contro le catture AUTONOME (monitor/timer); un'ISequenceItem che cattura nel proprio
   `Execute()` è il sequencer stesso che fa imaging — identico al TakeExposure core. `WaitForRecoveryHint` →
   **`RecoveryProbe`** ("Recovery probe (Adaptive Agent)"): gate invariato (S1 timeout / S2 hint / floor min-interval,
   logica pura in `RecoveryProbeGate`) POI cattura interna: `CaptureSequence` LIGHT che **replica il light interrotto**
   — esposizione/gain/offset/binning da **`LastLightMemory`** (nuovo subscriber `LastLightTracker` su ImageSaved, il
   forwarder §42 resta INVARIATO), filtro = ruota già in posizione (zero comandi), fallback exposure configurabile solo
   se nessun light visto in sessione. Flusso canonico: CaptureImage → ToImageData → PrepareImage(detectStars) →
   `IImageSaveMediator.Enqueue` → ImageSaved → forwarder → N1. IValidatable (warning se camera non connessa).
   Cancellazione: il watchdog del Loop While Unsafe taglia anche a metà posa (SAFE può arrivare solo da una sonda
   precedente → abort corretto). Paletto riformulato: "l'imaging avviene solo dentro istruzioni eseguite dal sequencer".
2. **Criterio a TEMPO REALE per l'hint** (riflessione di Alessandro sul criterio campioni-vs-tempo): l'accumulatore S2
   contava guide-frame, ma il frame-rate varia col setup (0.5–4 s) → stesso valore, comportamenti diversi. Ora
   l'accumulatore è **in secondi** (`acc += dt` sui frame buoni, `acc −= drain_factor×dt` sui cattivi, dt clampato a
   5 s contro i buchi: stella persa non accredita tempo fantasma), latch a `sustained_seconds=60`, rilascio a 0.
   Config: `sustained_seconds`/`drain_factor` sostituiscono `sustained_polls`/`accumulator_cap`/`drain_rate`.
   NB: la paura "8 sonde × 300 s = 40 min" NON si applica al rientro: dopo UNA sonda serena l'indice resta fresco per
   max(180, 1.5×exp) e il drain N6 va a poll fissi 15 s → SAFE in ~1 min. N6 §55 e N1 restano invariati (per mandato).

**Test/build**: agente **291 verdi** (nuovo caso gap-clamp; test hint riscritti con clock iniettato); plugin **19
verdi** (test strutturale aggiornato: niente cattura AUTONOMA — no timer; LastLightTracker senza imaging mediator —
+ test LastLightMemory); build **0 warning**. Template riscritto (rev. §57-bis) con la limitazione GUI documentata.

## 58. Auto-gestione del ciclo di vita dell'Agente dal Plugin: avvio automatico + spegnimento graceful — Plugin v1.7.0.0 + Agente (2026-07-13)

**Motivazione.** Coerenza con l'ecosistema NINA (installa → configura una volta → automatico) + eliminazione alla
radice degli hard-kill: molti utenti chiudono l'Agente brutalmente → uscita sporca → baseline orfana (§56) + PHD2
lasciato con le leve sintonizzate. Se start e stop li gestisce il plugin, il comportamento scorretto sparisce
(il §56 resta il backstop per crash di NINA/plugin/OS).

**Meccanismo /shutdown — perché HTTP e non segnali.** Su Windows i segnali POSIX verso un python wrappato da
`Avvia.bat` sono inaffidabili (console group del cmd). Nuovo `POST /shutdown` sull'Agente (server.py): risponde
`200 {"shutting_down": true}` PRIMA di innescare (callback con ~0.3 s di ritardo su thread separato, così la risposta
viene consegnata), idempotente (seconda chiamata → `already_requested`), 503 se il callback non è registrato.
Il callback (registrato da main.py accanto ai signal handler) setta lo STESSO `_stop_event` dei segnali → il main
loop esce → percorso di shutdown già esistente (riconnessione a PHD2 se serve → `controller.shutdown()` → restore
baseline → uscita). Zero logica nuova di spegnimento: si riusa quella validata.

**Architettura plugin (v1.7.0.0).**
- `Lifecycle/LifecycleGate` (decisioni PURE, stile RecoveryProbeGate): ShouldAutoLaunch (opt-in + path + probe
  "già in esecuzione") e ShouldRequestShutdown (politica A/B).
- `Lifecycle/AgentLifecycleCoordinator`: Initialize → auto-avvio FIRE-AND-FORGET (Task.Run: NINA mai bloccata,
  eccezioni confinate, toast marshallata su fallimento — lezione §55); Teardown (chiamato da ApplicationVM.Closing,
  verificato sul sorgente NINA) → spegnimento a DUE STADI: `POST /shutdown` + poll di conferma su /about (1 s) fino a
  ShutdownTimeoutSeconds, poi fallback `Process.Kill(entireProcessTree: true)` sull'handle.
- **Gotcha albero di processi**: lanciando `Avvia.bat` l'handle è cmd.exe e il python è un FIGLIO → il fallback
  DEVE uccidere l'albero, mai il solo handle (agenti orfani vivi altrimenti). `AgentLauncher.LastStartedProcess`
  ora conservato.
- **Proprietà (paletto 1)**: `OwnsAgent` = auto-avvio §58 O avvio dal pulsante manuale (stesso AgentLauncher
  condiviso) — il pulsante È il plugin. Un agente avviato fuori dal plugin non è mai owned (politica A).
- **Caso "raggiungibile-ma-piantato"** (02:48 del 12/7): uvicorn su thread daemon risponde a /about anche col main
  loop bloccato → il pulsante grigio resta corretto (un secondo processo = conflitto di porta); l'evento di /shutdown
  non verrebbe consumato → è proprio il fallback kill-albero a risolvere il piantato (poi §56 al riavvio).
- Settings (§58, upgrade-safe): `AutoLaunchEnabled=false` (opt-in — trasparenza per il Registry, nessuna sorpresa
  per chi aggiorna; si spunta una volta accanto al path), `ManageExternalAgent=false` (politica B opt-in),
  `ShutdownTimeoutSeconds=15` (clamp 5–60; il restore può passare da una riconnessione a PHD2).
- Pulsante dashboard: già corretto (grigio quando raggiungibile) — nessuna modifica alla VM.

**Limiti (espliciti).**
1. **Politica B su agente esterno PIANTATO = garanzia più debole**: senza handle di processo non c'è fallback
   kill-albero → se l'esterno non consuma /shutdown resta vivo; ripulisce il §56 al riavvio successivo. (La politica
   A col pulsante/auto-avvio ha sempre l'handle → garanzia piena.)
2. Crash di NINA/OS: Teardown non gira → agente resta vivo → §56 al riavvio (by design).
3. `POST /shutdown` è servito solo con dashboard attiva (`--no-dashboard` → 503; il plugin degrada al fallback).

**Test.** Agente: `test_shutdown_endpoint.py` (4: 503 senza callback; 200 prima dell'innesco; idempotente con
callback UNA volta; eccezione nel callback ingoiata) — suite **295 verdi**. Plugin: `LifecycleGateTests` (7: skip se
raggiungibile; run se opt-in+path+non raggiungibile; skip senza path; opt-in OFF = comportamento attuale; politica A
solo owned; politica B adotta esterno; owned fermato anche se irraggiungibile → fallback) — **26 verdi** totali,
build **0 warning**. Invarianti: N1/N6/forwarder/§55/§56/§57 diff vuoto (Safety Monitor toccato SOLO per le stringhe
di versione 1.7.0.0). Validazione campo: avvio NINA con opt-in ON → agente parte da solo; chiusura NINA → restore
baseline + nessun processo orfano; avvio manuale poi NINA → nessun doppio avvio; path errato → NINA parte, toast.

### §58-bis — Agente in BACKGROUND: via la finestra DOS (2026-07-13)

**Motivazione (beta tester, conclusione naturale del §58):** la console del processo Python era diventata la prima
causa di assistenza — gli utenti non capiscono cosa sia, la chiudono per errore (= kill dell'agente, plugin "morto"
senza spiegazione), nessun plugin del Registry apre una finestra DOS permanente. Col plugin proprietario del ciclo di
vita, la console non ha più alcuna funzione che il log su file (§56) e la dashboard non coprano già.

**Scelta tecnica: fix alla radice — exe WINDOWED** (`PHD2_Agent.spec: console=False`, PE subsystem GUI): la console
sparisce per OGNI percorso di lancio (auto-avvio plugin, pulsante, doppio-click), non solo per quello del plugin.
Adattamenti: `setup_logging` aggiunge lo StreamHandler solo se `sys.stderr` esiste (nella build windowed è None; il
file `logs/agent.log` è il canale primario); `uvicorn.run(log_config=None)` (niente handler propri su stderr, i
record propagano ai handler di root). Da sorgente (`python main.py`) la console resta come sempre.

**Il "terminale" diventa un viewer richiudibile senza rischi** (la cura del problema n.2): `Mostra_Log.bat`
(PowerShell `Get-Content -Wait` su agent.log — chiuderlo non tocca l'agente). `Avvia.bat` riscritto: `start`
detached, la finestra lampeggia e sparisce. Nuovo `Arresta.bat`: stop pulito manuale via `curl POST /shutdown`
(ripristino baseline) — l'utente non ha più NESSUN motivo di uccidere un processo. `build_dist` pacchettizza i
3 bat + LEGGIMI aggiornato.

**Plugin (launcher §58 rifinito):** lancio DIRETTO di `PHD2_Agent.exe` se esiste accanto al .bat configurato →
l'handle è il PROCESSO AGENTE VERO (proprietà §58 perfetta, il fallback kill non dipende dal wrapper); fallback
`cmd /c` NASCOSTO del .bat per i setup custom (sorgente/venv). `CreateNoWindow` ovunque.

**Test/verifiche:** suite agente **296 verdi** (nuovo: setup_logging con stderr=None → niente StreamHandler, file
handler presente); build plugin **0 warning**; verifica PE subsystem==GUI sul pacchetto rigenerato. Limite: in
background un crash PRIMA del setup del logging non lascia traccia visibile (finestra inesistente) — mitigato dal
fatto che setup_logging è la prima cosa che main() fa.

### §58-ter — Description del Safety Monitor = mini-manuale (2026-07-14)

Dal campo: la Description spiegava COSA fa il monitor ma non COME si monta la sequenza — e lo screenshot di
validazione di Alessandro mostrava proprio l'errore che ne deriva: Recovery probe messa DIRETTAMENTE nel Before,
senza il container `Loop While Unsafe` → UNA sola sonda per episodio unsafe, poi attesa muta (il deadlock §57
rientrerebbe se la prima sonda non basta). Interventi (zero comportamento): (1) `Description` del driver riscritta
in due parti — funzionamento (le 4 condizioni UNSAFE + principio "perdita di osservabilità = rischio") e SETUP
della sequenza (albero poi semplificato dal §57-ter: la sola Recovery probe nel Before) e il divieto di istruzioni
Camera nel container; (2) stessa mini-guida nella pagina Options del plugin (dove l'utente configura). Valutazione GUI:
`ISafetyMonitor.Description` è una `string` del contratto SDK → NINA la rende come TESTO (niente immagini; \n e
caratteri unicode di albero supportati); la superficie nostra dove un'immagine è possibile è la pagina Options /
README (screenshot in arrivo col resto). Build 0 warning, 26 test verdi.

### §57-ter — Il ciclo diventa INTERNO alla Recovery probe (2026-07-15)

**Seconda evidenza sperimentale della GUI (screenshot di Alessandro, 14/7):** i container del Trigger On Unsafe
rifiutano anche le CONDIZIONI/container di ciclo — `Loop While Unsafe` esiste nella libreria ("Condizione di Ciclo")
ma il drag&drop nel Before viene rifiutato, esattamente come per le istruzioni Camera (§57-bis). Il design a loop
esterno era quindi non montabile: senza loop, UNA sola sonda per episodio unsafe e poi attesa muta (deadlock di
ritorno se la prima sonda non basta).

**Soluzione A adottata (proposta di Alessandro, condivisa):** il ciclo è INTERNO all'istruzione. `RecoveryProbe` ora
è l'intero recovery: `while (monitor UNSAFE): attesa gate (S1/S2, floor min-interval) → sonda → ripeti`, con lo stato
del monitor riletto ogni 5 s (esce da sola anche a metà attesa, come faceva il watchdog del loop esterno) e uscita per
cancellazione (sequenza annullata/chiusura NINA). Setup utente ridotto al minimo assoluto: `Trigger On Unsafe →
Before → Recovery probe` — nessun container, nessuna condizione. Scartata la Soluzione B (nostro container-loop
custom): duplicava un pezzo core con lo stesso rischio di rifiuto GUI e più superficie di manutenzione.

**Confine di safety — precisazione del paletto:** l'istruzione ora LEGGE lo stato del Safety Monitor
(`ISafetyMonitorMediator.GetInfo()`, presente nell'SDK 3.2 — è lo stesso identico meccanismo del `Wait Until Safe`
core) ma SOLO per sapere quando fermarsi: consumo, non giudizio. Il paletto resta: mai IMPOSTARE la safety, mai
influenzarla — SAFE arriva esclusivamente da sonda → N1 → drain §55 → N6. `Validate()` ora segnala anche il Safety
Monitor non connesso (senza, il loop non saprebbe quando finire). Telemetria: log per-sonda numerate
("probe #N") + esito del loop ("SAFE — recovery loop ends (N probe(s) attempted)").

**Hardening (verifica pre-commit di Alessandro):** la sola `TakeProbeAsync` è in try/catch dentro il loop — un guasto
di cattura (camera/USB/driver/ruota) NON termina più il ciclo (prima: istruzione FAILED → Before completato → attesa
muta con monitor UNSAFE = deadlock di ritorno nello scenario peggiore). Su eccezione: Warning nel log + toast
marshallata (SOLO al primo fallimento, poi solo log — niente spam ogni gate) + retry al gate successivo; il loop resta
reattivo a SAFE e alla cancellazione (OperationCanceledException rilanciata, mai ingoiata). Confermati al contempo:
Waiting For Safety del trigger è un'istruzione core (WaitUntilSafe, poll 5 s) che NON può contenere nulla — vuoto by
construction; SAFE a metà posa completa la posa (light utilizzabile) ed esce subito dopo; ~1 min di isteresi drain §55
tra sonda serena e SAFE.

**Doc allineata** (Description del driver, mini-guida Options, template rev. §57-ter con la 2ª limitazione GUI
documentata, CONTESTO). Build **0 warning**, **26 test verdi** (gate/LifecycleGate invariati — la logica di gate
per-iterazione non è cambiata). Resta v1.7.0.0 (mai rilasciata).

## 59. Chiusura di NINA istantanea: delega dello shutdown dopo il 200 + watchdog di auto-terminazione — Agente + Plugin v1.7.0.0 (2026-07-15)

**Osservazione dal campo (v1.7 in prova):** alla chiusura di NINA il plugin attendeva la scomparsa dell'agente
(poll /about fino a 15 s) → NINA restava aperta per secondi. FASE 0: l'attesa NON serviva al percorso felice (l'agente
sano completa da solo dopo il 200) — serviva SOLO al caso piantato: uvicorn (thread daemon) risponde 200 anche col
main loop bloccato, quindi il 200 provava la ricezione, non la presa in carico; solo l'attesa+timeout distingueva
"accettato ma non muore" e faceva scattare il kill-albero. Fire-and-forget puro = regressione sul piantato.

**Soluzione: rendere il 200 un CONTRATTO.** La garanzia si sposta DENTRO l'agente — `POST /shutdown` ora arma anche un
**watchdog daemon di auto-terminazione** (`SHUTDOWN_SELFKILL_GRACE_S = 25 s`, server.py): se lo shutdown graceful non
completa (main loop piantato: l'evento non verrebbe mai consumato), `os._exit(1)` con log flushato — il §56 ripulisce
al riavvio. Nel percorso felice il timer daemon muore col processo senza mai scattare. Il 200 ora significa
"TERMINERÒ comunque: con grazia se posso, forzatamente altrimenti" → il plugin può legittimamente delegare:
`StopAgentIfOwnedAsync` esce subito dopo il 200 (niente più `WaitUntilGoneAsync`, rimossa; `ShutdownTimeoutSeconds`
rimossa da settings/DTO/XAML — v1.7 mai rilasciata, nessuna migrazione). NINA si chiude all'istante. In più: uscita
immediata senza alcun probe HTTP quando né owned né ManageExternalAgent (Teardown ~0 ms per chi non usa la gestione).

**Il watchdog MIGLIORA i casi che il timeout lato plugin non copriva:** agente piantato a metà notte con Arresta.bat
(prima: restava piantato) e agente ESTERNO piantato in policy B (prima: nessun handle, nessun rimedio) ora si
auto-risolvono. Il fallback kill-albero resta per "HTTP morto ma processo owned vivo" (POST fallito). Invarianti §58
intatti: policy A/B invariate, restore baseline invariato, nessuna perdita del graceful.

**Limite documentato:** dopo la chiusura di NINA l'agente può sopravviverle di qualche secondo (3-8 s felice, 25 s
worst) mentre completa il restore — un riavvio IMMEDIATO di NINA può trovare l'agente morente: l'auto-launch lo vede
vivo e non rilancia; al successivo probe/pulsante si rilancia (caso raro, accettato). Test: agente **297 verdi**
(nuovo: watchdog scatta a grazia scaduta con graceful in stallo, `_force_exit` spiato, grazia accorciata); plugin
**26 verdi**, build **0 warning**; pacchetto rigenerato (subsystem GUI riconfermato). Niente commit/push (gate).

## 60. Internationalization & UX del plugin: lingua selezionabile via Resource (.resx) — Plugin v1.7.0.0 (2026-07-16)

**Obiettivo (milestone di sola UX, motore intoccato):** il plugin visualizzabile in una lingua scelta dall'utente
(Follow N.I.N.A. / English / Italiano) SENZA toccare la lingua di N.I.N.A., con tutte le stringhe UI nelle Resource
.NET invece che hard-coded.

**Architettura.** Deviazione deliberata dai satellite assemblies: entrambe le lingue vivono come **resx neutri
EMBEDDED nella DLL principale** (`Localization/Strings_en.resx` + `Strings_it.resx`, underscore per non innescare i
satellite) — motivo: il plugin si distribuisce come SINGOLA DLL (install-plugin.ps1 oggi, ARCHIVE domani) e una
cartella `it\` dimenticata = italiano silenziosamente rotto. `Loc` (BaseINPC, singleton) sceglie il ResourceManager e
espone l'**indexer bindabile** in puro pattern NINA: `{Binding [Chiave], Source={x:Static loc:Loc.Instance}}` +
`RaisePropertyChanged("Item[]")` al cambio → **la UI si aggiorna LIVE, senza riavvio**. Fallback a cascata:
IT→EN→chiave (mai stringhe vuote). Nuova lingua domani = 1 resx + 1 voce nel combo, zero codice.

**Copertura (70 chiavi ×2):** pagina impostazioni completa (con nuovo selettore "Plugin language" in testa),
pannello dashboard (badge/pulsante/tooltip/fallback), toast (lifecycle, Safety Monitor, Recovery probe), esiti del
launcher, etichette della riga Recovery probe nel sequencer, Description del Safety Monitor. Setting persistita:
`PluginLanguage` ("" = Follow N.I.N.A. via CurrentUICulture, "en", "it"), upgrade-safe.

**Limiti documentati (SDK):** gli `ExportMetadata` dell'istruzione sequencer (nome/descrizione nella sidebar) sono
costanti compile-time → restano in inglese (standard per i plugin); il `Name` del device Safety Monitor resta in
inglese di proposito (riconoscibilità in profili/support); i **LOG restano SEMPRE in inglese** (sono per il
supporto/Discord, non per l'utente — decisione esplicita).

**Test:** plugin **31 verdi** (+5 `LocTests`: EN/IT risolte dalle resource embedded; **completezza EN↔IT simmetrica**
— una chiave dimenticata in una lingua fa fallire la build dei test; fallback alla chiave; Follow-N.I.N.A. segue
CurrentUICulture; i placeholder {0} sopravvivono alla traduzione). Build **0 warning**. Invarianti: zero file di
logica toccati (engine/gate/forwarder/health/memory) — solo presentazione. Resta v1.7.0.0 (mai rilasciata).

### §60 — chiusura certificata (2026-07-17)

**Audit di completezza (richiesto da Alessandro prima del commit).** Sweep globale con script dedicato su 3 XAML +
21 .cs (attributi WPF visibili, testo inline, literal C# multi-parola fuori dalle righe Logger, superfici
Notification/ApplicationStatus/FileDialog), con classificazione machine-checkable di ogni residuo contro una
whitelist motivata. Inventario: **73 stringhe localizzabili pre-migrazione, 67 migrate al primo giro, 6 residue**
trovate dall'audit — di cui **2 ancora in ITALIANO** (Title+Filter dell'OpenFileDialog in
`PluginSettingsView.xaml.cs`, code-behind sfuggito alla migrazione batch) e 4 in EN (2 messaggi `Validate()` della
Recovery probe → triangolo giallo del sequencer; 2 `ApplicationStatus` → barra di stato). L'audit ha scovato anche
2 contenuti STANTII: footer dashboard fermo a "v1.5" e LongDescription del Plugin Manager che citava ancora la
defunta "Wait for recovery hint (v1.6)".

**Fix applicati:** file-picker e Validate() migrati (**74 chiavi ×2**, simmetria garantita dal test);
`ApplicationStatus` lasciati **EN-by-design** (decisione condivisa: le reason arrivano preformattate da
`RecoveryProbeGate` — file di logica che §60 si vieta di toccare — e localizzare solo la cornice darebbe testo
misto; sono telemetria transiente coerente con la sidebar EN); footer ora **derivato dall'assembly**
(`FooterText` nel VM: mai più stantio); LongDescription riscritta sulla Recovery probe autocontenuta §57-ter +
menzione della UI bilingue; `Debug.WriteLine` residuo tradotto in EN. Verdetto finale audit: **0 residui non
classificati** (77 literal restanti, tutti deliberati e motivati: manifest/ExportMetadata compile-time,
identità/brand, endonimi, albero-sequenza, log multilinea, reason di gate, canale Debug).

**Lifecycle ON di default (ultima rifinitura §60, richiesta esplicita).** `DefaultAutoLaunchEnabled` e
`DefaultManageExternalAgent` ribaltati a **true**: col ciclo di vita maturo (§56 orphan recovery, §58 graceful,
§59 watchdog) l'opt-in di §58 non proteggeva più nulla e faceva sembrare il plugin inerte alla prima
installazione ("installa e funziona", non "installa e configura"). Motore NON toccato: è solo il default di due
setting; entrambe restano disattivabili (kill-switch) e l'help `Settings_ManageExt_Help` riscritto in ENTRAMBE le
lingue spiega il nuovo default + il caso standalone (chi vuole che l'Agente sopravviva a NINA la spegne).
Auto-launch resta inerte senza path configurato (LifecycleGate). **Upgrade-safety (DTO nullable):** chiave assente
(ogni utente reale: v1.7 mai rilasciata) → ON; un `false` salvato esplicitamente resta false — ⚠ i settings.json
delle macchine di test interne hanno il false esplicito di §58: per provare il nuovo default serve toggle manuale
o file rimosso. Verifica: 3 test nuovi (`PluginSettingsDefaultsTests`, il costruttore fresco È l'installazione
nuova perché `Load()` senza file lo restituisce identico). Suite plugin: **34 verdi** (26+5 Loc+3 defaults), build
`--no-incremental` 0/0.

### §60 — tooltip localizzati sui parametri numerici del Safety Monitor (2026-07-17)

Rifinitura UX approvata dopo analisi (nessun motore toccato): **6 tooltip** (`Settings_Tip_*`, 80 chiavi totali ×2)
su Degradato→unsafe, Sereno→safe, Accumula/Scarica indice, Stantia→unsafe, Agente perso→unsafe — su etichetta E
casella di ogni campo. Principio: il tooltip insegna il **modello mentale corretto del parametro** nel punto di
decisione, non ripete l'help. Tre regole applicate: (1) niente "poll consecutivi" — l'accumulatore §55 è leaky
(il sereno scarica, l'HAZE è neutro), e il tooltip lo dice; (2) i due watchdog citano i **gate di attivazione**
(stantia: sicurezza nubi attiva + sessione attiva + ultimo cielo noto degradato; agente perso: sessione attiva)
per evitare interpretazioni errate sul campo; (3) ogni testo chiude con l'**effetto pratico** ("più alto = più
tollerante alle velature brevi") + unità (1 poll = intervallo di controllo, default 15 s; indice 0–1 allineato
alle soglie N1 0.5/0.8). Implementazione WPF: contenuto tooltip = `TextBlock` con `TextWrapping` e `MaxWidth=360`
espliciti — NIENTE style implicito locale su `ToolTip`, che scavalcherebbe (non estenderebbe) il tema di NINA.
Test: +1 in LocTests (`TooltipKeys_ResolveNonEmptyAndTranslated`: esistenza, lunghezza minima, EN≠IT) oltre alla
simmetria generale che copre le nuove chiavi da sola. Suite **35 verdi**, build 0/0, audit ri-certificato
(**80/80 chiavi, 0 dead, 0 residui non classificati**).

Analisi architetturale contestuale (STAR_LOST vs sicurezza nubi, su domanda di Alessandro): canali
**complementari, non ridondanti** — sensori diversi (camera di guida in tempo reale vs statistica di campo della
camera principale a cadenza per-sub), tempi diversi (fronte rapido → STAR_LOST prima; degrado lento → trasparenza
prima o da sola), scenari esclusivi in entrambe le direzioni (velatura con stella guida brillante → solo nubi;
raffica/cavo/rugiada a cielo sereno → solo STAR_LOST). Quattro latch indipendenti in OR con causa diagnostica;
stale/agent-lost sono watchdog dell'osservazione, non terzi rilevatori. Il consolidamento lungo di STAR_LOST è
voluto: lascia al GUARDIAN dell'agente il tempo di recuperare (il monitor è ultima istanza). **Semplificazione
futura candidata:** rimozione della logica CLOUD legacy (`UseIndexCloudLogic` + `EvaluateCloudLegacy` + 2
setting) quando la logica a indice sarà validata sul campo — NON la fusione dei canali; cross-informing valutato
e sconsigliato (accoppiamento).

## 61. Proprietà architetturale VERIFICATA: il Sequence Engine di NINA è l'unica autorità sul ciclo di vita della sequenza (2026-07-17)

**Domanda di Alessandro (post v1.7.0.0):** se un criterio di fine sequenza (ora impostata, alba, altitudine,
n° pose, stop) matura MENTRE la Recovery probe è nel suo ciclo, la probe viene cancellata? E un ritorno del SAFE
a sequenza conclusa può riavviare qualcosa? Verifica di sola lettura su ENTRAMBI i lati, sorgenti alla mano.

**Lato NINA (sorgente `isbeorn/nina`, ramo develop = linea 3.3):** (1) `SequenceContainer.Execute` crea
`localCTS = CreateLinkedTokenSource(token)` e la strategia gira con `localCTS.Token`; (2) `SequentialStrategy`
esegue i trigger — ANCHE quelli ereditati dai container padri, via risalita ricorsiva `RunTriggers(container.Parent,…)`
— **con lo stesso token della strategia**, cioè dentro la catena di cancellazione del container in esecuzione;
(3) le condizioni a tempo/astronomiche usano `ConditionWatchdog` (TimeCondition: 1 s) che allo scadere, a container
RUNNING, chiama **`Parent.Interrupt()`** (log NINA: "Time limit exceeded - Interrupting current Instruction Set");
(4) `Interrupt()` = `localCTS.Cancel()` → la cancellazione raggiunge tutto ciò che gira sotto, trigger inclusi;
(5) `TriggerOnUnsafe.Execute` esegue BeforeWaitForSafe (la nostra probe) → WaitUntilSafe → AfterWaitForSafe col
token ricevuto (l'unico CTS interno, la guardia dell'AfterWaitForSafe, resta linked al padre).

**Lato plugin (fatti provati a grep/lettura):** (a) `RecoveryProbe.Execute` onora il token a OGNI attesa
(ThrowIfCancellationRequested in testa a entrambi i loop, `Task.Delay(…, token)`, token in tutta la catena di
cattura CaptureImage→ToImageData→PrepareImage→Enqueue) e l'hardening §57-ter **rilancia** OperationCanceledException
(catturiamo solo i guasti di cattura non-cancellazione); (b) **zero fire-and-forget**: Execute è interamente
awaited dal motore — finché la probe gira, la sequenza è PER COSTRUZIONE ancora viva; non esiste lo stato
"sequenza finita ma probe in esecuzione"; (c) **il plugin non referenzia alcuna API di controllo sequenza**
(nessun ISequenceMediator in tutto src/ — è dichiarato come regola nel header del monitor); il Safety Monitor è
un device ISafetyMonitor passivo: espone flag che NINA legge in polling, non comanda mai.

**Risposte:** (1) SÌ — tre classi di terminatori: stop/chiusura NINA → token radice → probe cancellata subito;
criteri watchdog (ora/sole/luna/altitudine) → `Parent.Interrupt()` entro ~1 s → cancellazione lungo la catena
linked → probe cancellata **anche a metà posa-sonda**; criteri a conteggio → non maturano durante la probe (si
valutano ai confini degli item): al ritorno SAFE la condizione viene rivalutata e la sequenza chiude senza altri
light. (2) NO — a sequenza conclusa i trigger sono smontati (teardown della strategia) e il SAFE che torna cambia
solo il flag del device: nessuno lo consuma, e il plugin non ha comunque alcuna API per riavviare. (3) SÌ, per
costruzione: il flusso è a senso unico (NINA legge noi; noi non comandiamo NINA). Il Safety Monitor protegge una
sequenza attiva; non è mai un secondo orchestratore.

**Esito:** conforme — NESSUNA modifica necessaria. Documentato come proprietà architetturale in: README plugin
("Design guarantee"), TEMPLATE recovery (FAQ fine-sequenza), CONTESTO. Verifica a banco suggerita (2 min): Ripeti
fino a un'ora vicina + pannello coperto → nel log NINA compare "Time limit exceeded - Interrupting…" e la probe
si ferma. Rifinitura opzionale futura (non richiesta): log esplicito di uscita-per-cancellazione nella probe per
rendere la proprietà osservabile anche nel NOSTRO log.

## 62. REGOLA PERMANENTE di processo: il rebuild del distribuibile fa parte della Definition of Done (2026-07-17)

Stabilita da Alessandro dopo la v2.8: il commit era corretto ma nella cartella c'era ancora solo
`Adaptive_Agent_PHD2_v2.7.zip` — repo aggiornato, software installabile stantio. Da oggi, **ogni modifica
approvata al codice si considera conclusa SOLO dopo il rebuild del componente toccato**, anche quando commit/push
non sono richiesti (sono attività distinte: il repo è la storia, il pacchetto è il software reale).

Workflow standard: 1) implementazione → 2) build 0 errori/0 avvisi → 3) test/validazione → 4) **REBUILD**
(Agente: `build_dist.py` → `Pacchetto_Distribuzione/` + `Adaptive_Agent_PHD2_v<versione>.zip`, versione
single-source da `__about__.py`; Plugin: build Release + `install-plugin.ps1` + verifica hash DLL installata ==
DLL buildata) → 5) commit/push quando richiesti → 6) report con conferma esplicita della corrispondenza
sorgente ↔ artefatto ↔ versione dichiarata. Gotcha noti: agente in esecuzione = lock su
`Pacchetto_Distribuzione/logs/agent.log`; NINA aperto = lock sulla DLL; `pyinstaller` va invocato col
`.venv/Scripts` nel PATH (build_dist lo chiama nudo via subprocess).

## 63. Primo bug di campo della v2.8: NameError nel wiring §57 abbatteva il loop — fix v2.8.1 + ciclo motore osservabile (2026-07-19)

**Forense (notte 2026-07-19, prima validazione reale del blocco §57).** `recovery_hint_tracker` era una variabile
locale di `main()` referenziata dentro `_event_loop()` (che non la riceveva): NameError al primo frame "ready"
di ogni finestra → l'eccezione risaliva all'handler esterno il cui `finally` DISCONNETTEVA da PHD2 → ciclo
connect → ~9 frame warmup → decimo frame → crash → reconnect, **178 volte in 65 minuti** (100 buchi >10 s nel
CSV, 87 reset `guiding_restart`). Conseguenze provate dai dati: hint S2 mai alimentato (→ "hint inactive" tutta
la notte), `controller.evaluate` MAI eseguito (`evaluated=False` × 837, decisions vuoti, GUARDIAN inerte),
baseline RMS affamata (~1 campione/ciclo → 23/60 dopo 40 min: l'ipotesi velature è smentita — SNR mediana 50.9,
100% dei frame sopra soglia 6). Il §56 ha retto (leve preservate a ogni ri-aggancio). Perché 297 test verdi non
l'hanno visto: nessun test eseguiva il CORPO reale di `_event_loop`.

**Timeline N1 dal CSV** (le colonne transparency_*): CLOUD idx 0.16 dalle 01:34, **sonda-1 alle 01:48 con idx
1.00 CLEAR** (la probe FUNZIONA e aggiorna N1), 13 minuti ancora UNSAFE, sonda-2 alle 02:01 (idx 0.92 = lo
screenshot), stop 02:04. **Resta aperto il caso N6-non-torna-SAFE** (con CLEAR/1.00/fresh il drain matematico è
~4 poll): il gate `fresh` governa sia accumulo sia scarico e l'UNSAFE è scattato → il parsing funziona → il
guasto sta a valle del /status (polling plugin → engine → device → NINA). Da analizzare SEPARATAMENTE con i log
NINA dopo una sessione con la v2.8.1 (decisione di Alessandro: un problema alla volta, mai inseguirne due).

**Fix §63 (v2.8.1):** (1) `recovery_hint_tracker` è un PARAMETRO di `_event_loop`; (2) try/except difensivo —
un osservatore passivo non deve MAI poter abbattere il loop di guida (primo errore loggato, poi silenzio);
(3) `tests/test_event_loop_wiring.py`: 3 test che eseguono il VERO `_event_loop` (percorso completo del frame,
osservatore che esplode senza uccidere il loop, tracker assente) + 1 sul blocco engine — il buco "verdi ma rotto
in campo" è chiuso per sempre. Versioning: introdotto il livello patch (major.minor.patch per gli hotfix,
test_about aggiornato). **301 test verdi.** ZIP v2.8 difettoso RIMOSSO; `Adaptive_Agent_PHD2_v2.8.1.zip`
rigenerato (regola §62: exe 2.8.1, subsystem GUI).

**Ciclo motore osservabile (richiesta di Alessandro per la validazione).** Verificato sul codice che la catena
Analyzer→Diagnostic→Controller entra in funzione appena `analyzer.is_ready` (finestra ~10 frame) — `evaluate`
gira ogni EVAL_INTERVAL INDIPENDENTEMENTE dal completamento della baseline (la baseline governa le soglie, non
la valutazione; con baseline in corso valgono le soglie provvisorie §33/§40) — quella notte sembrava fermo
perché evaluate non veniva MAI raggiunto. Per renderlo visibile: `controller.eval_count`/`last_eval_ts` (§63,
incrementati accanto a `snapshot.evaluated=True`) + blocco `engine` in `get_status()` (eval_count, last_eval_ts,
actions_total, last_action) + riga "**Ciclo motore**" nella card diagnostica della dashboard con TRE stati:
ambra "In raccolta dati — nessuna valutazione ancora" (eval_count=0), verde "ATTIVO — valuta e non interviene
(N valutazioni · ultima hh:mm:ss)", blu "ATTIVO — ultimo intervento hh:mm:ss: RA aggression 70→65". Un motore
sano ma quieto ora si DISTINGUE da un motore fermo.

## 64. Cadenza della Recovery probe: da parametro a GRANDEZZA DERIVATA (plugin, 2026-07-19)

**Origine.** Dall'analisi §63-bis è emerso che il timeout della sonda non è una preferenza ma una
**conseguenza della fisica del sistema**: la sonda esiste per tenere vivo l'occhio di N1, quindi il ciclo
(attesa + posa) deve chiudersi DENTRO la finestra di freschezza adattiva §43. Se è più lungo, tra due sonde la
telemetria diventa stantia: N6 perde l'evidenza viva, il latch STALE può scattare e al ritorno dei dati
**risatura l'accumulatore nubi**, allungando proprio il recupero che la sonda doveva accelerare. Alessandro
aveva già scelto empiricamente 3 min al posto di 12: i conti dicono che aveva ragione (con posa 60 s, 12 min
lasciano ~10 min di stantio per ciclo, 3 min ne lasciano 60 s — sotto i 120 s che fanno latchare).

**Criterio.** `timeout = clamp(finestra_§43 − posa_sonda, 1 min, 15 min)`, in `RecoveryProbeGate.AdaptiveTimeout`
(funzione PURA, come tutta la logica testabile del progetto). Due scelte di progetto:
- la finestra si **legge dall'agente** (`/status.nina.transparency.window_s`, esposta in §55) invece di
  duplicare la formula: se l'utente ritara `[nina_telemetry]`, la cadenza lo segue da sola;
- la posa è quella che la sonda **replica davvero** (`LastLightMemory` → altrimenti fallback), quindi la
  cadenza si adatta al sub del momento (60 s → attesa 2 min; 300 s → attesa 2.5 min; 600 s → attesa 5 min).
Fallback graceful: agente offline/N1 spento → stessa formula §43 con i default noti (180 s / 1.5×). Ricalcolata
a OGNI poll del gate: un cambio filtro/target la aggiorna senza riavviare nulla.

**Parametro manuale: NON eliminato, retrocesso.** `AutoTimeout` (default **true**) è il comportamento; il campo
minuti resta come escape hatch, **editabile solo a Auto spento** (`ManualTimeoutEnabled`). Motivo: la dottrina
del progetto è "kill-switch ovunque" e la logica adattiva è ancora in validazione sul campo — se a mezzanotte
si comportasse male, l'utente deve poter tornare a un numero fisso senza reinstallare. Nell'uso normale la UI è
comunque **più semplice di prima** (il numero è spento e ignorabile).

**Verificata l'indipendenza dal tema aperto `controller.guiding_state` ↔ Diagnostic Engine** (richiesta
esplicita prima di implementare): latch diversi (STAR_LOST vs CLOUD), codebase diverse (agente vs plugin), e
durante un unsafe da STAR_LOST le sonde **non influenzano** il rientro (che avviene via `ResumeTicks`, 45 s di
guida NORMAL). L'unica superficie di contatto — il gate STALE — riceve telemetria *più fresca*, quindi la
modifica può solo ridurre il rischio su quel percorso.

**Test:** +5 (`AdaptiveTimeoutTests`), tra cui l'invariante di progetto verificato su tutta la gamma di pose
realistiche (10→600 s): `attesa + posa ≤ finestra`, sempre. Suite plugin **40 verdi**, build 0 warning, audit
localizzazione ri-certificato (82/82 chiavi, 0 residui non classificati), DLL reinstallata con hash-match.
**Da validare sul cielo prima del commit** (metodo permanente: implementazione → rebuild → cielo → commit).

### §64-bis — riga dell'istruzione nel sequencer: etichetta + tooltip (2026-07-19)

**Difetto §64 corretto:** il tema di NINA stila `CheckBox` come interruttore ON/OFF e **NON rende il
`Content`** — la casella "Cadenza automatica" appariva quindi come un toggle muto. Convenzione da rispettare
d'ora in poi (è la stessa della pagina Opzioni): **ogni etichetta è un `TextBlock` separato**, mai il Content
di un CheckBox.

**Tooltip localizzati sui parametri della sonda** (3 chiavi ×2, su etichetta E campo — 85 chiavi totali):
timeout = cadenza fail-safe usata solo a cadenza-auto spenta; min-interval = floor assoluto che vale anche per
l'hint ed è la leva sul numero di pose-sonda salvate; fallback = usata SOLO se nessun LIGHT è stato ancora
salvato in sessione (altrimenti si replica il sub, obbligatorio per N1 che non normalizza per posa).

**Icone cestino/disattiva assenti sulla riga — diagnosi:** i comandi ESISTONO già (`DetachCommand`,
`DisableEnableCommand` sono su `SequenceItem`): è solo rendering. I container Before/After di un trigger
renderizzano i figli con una `TreeView` le cui risorse mappano `DataType="{x:Type seqItem:SequenceItem}"` →
`SequenceBlockView` (la cornice con i pulsanti). In WPF il template implicito si risolve prima sul **tipo
esatto**: il template per `RecoveryProbe` (come quello di QUALSIASI istruzione con editor inline) scavalca
quello del tipo base e la riga esce nuda. Se confermato, è comportamento di NINA per tutte le istruzioni dentro
un trigger, non nostro → segnalazione a monte, nessuna patch fragile nel plugin. **Test empirico lasciato ad
Alessandro:** trascinare un'istruzione core nello stesso Before e vedere se ha le icone.

**Limite §60 rivedibile (decisione aperta):** `SequenceItem.Name` ha setter pubblico con `RaisePropertyChanged`
→ il nome dell'istruzione *nella sequenza* si potrebbe localizzare a runtime. Effetto collaterale: la voce in
**libreria** resta EN (lì è `ExportMetadata`, compile-time) → nomi misti. Non implementato di iniziativa.

Build 0/0, test 40 verdi, audit 85/85 con 0 residui non classificati, DLL reinstallata (hash-match). Non
committato: attende la validazione sul cielo insieme al §64.

### §64-ter — cornice della riga: era un NOSTRO difetto di convenzione, non un limite NINA (2026-07-19)

Il test empirico di Alessandro (istruzioni native dentro lo stesso Before: cestino e menu PRESENTI) ha smentito
la mia prima ipotesi "template implicito che scavalca la TreeView". La verità, dal template nativo di
`WaitForTime`: **la convenzione NINA è che la RADICE del DataTemplate di un'istruzione sia il wrapper
`view:SequenceBlockView`** (namespace `NINA.View.Sequencer`, assembly NINA.Sequencer — referenziabile dai
plugin), con l'editor dentro `SequenceItemContent`. È il wrapper a disegnare la cornice standard: icona, nome,
cestino (`DetachCommand`), abilita/disabilita, menu, riga retry/error. Il nostro template §57 aveva come radice
uno StackPanel nudo → riga senza cornice. Fix: wrappato (XAML-only, zero codice, zero stringhe nuove — la
cornice arriva da NINA già localizzata nella SUA lingua). Lezione per futuri template di istruzioni:
**SequenceBlockView come root, sempre.** Build 0/0, 40 test, DLL reinstallata hash-match. Da verificare
visivamente al prossimo avvio NINA; non committato (viaggia col §64).

### §64-quater — formula v2: il tetto non è un'uguaglianza (2026-07-19, autorizzata da Alessandro)

La domanda di Alessandro sulla funzione di costo ha scoperto il difetto della v1: ottimizzavo il numero di sonde
soggetto al vincolo di freschezza, sedendomi SUL tetto della finestra — ma il tetto è un vincolo, non un
obiettivo: sui sub lunghi allungava la latenza di rientro senza alcun beneficio (600 s: attesa 5 min contro i
3 min validati sul cielo, che stavano GIÀ dentro la finestra da 900 s). Funzione di costo corretta
(lessicografica): 1) MAI stantia (correttezza — la ri-saturazione STALE distrugge il drain parziale);
2) latenza cappata al target validato (3 min); 3) minimo numero di sonde soggetto a 1-2.

**v2: `timeout = clamp(min(finestra §43 − posa, 180 s), 60 s, 900 s)`** (`TargetSeconds=180` in
RecoveryProbeGate; ceiling ora rete inerte). Esempi: 60 s → 2 min (vincola la finestra — qui il fisso 3 min
VIOLAVA la freschezza: ciclo 4 min > 180 s); 300 s → 2.5 min; 600 s → 3 min (vincola il target — v1 dava 5).
La v2 domina sia la v1 sia il fisso validato: mai stantia E mai più lenta del valore da campo. Il razionale
teorico fine dei 3 min è rimandato a più esperienza sul campo (decisione di Alessandro). Test: +1
(`LongSubs_CappedAtFieldValidatedTarget`) e clamp-test aggiornato → 41; tooltip EN/IT aggiornati col cap.
Commit+push autorizzati esplicitamente ("miglioramento architetturale supportato dall'analisi; eventuali
criticità dal cielo → commit correttivo").

## 65. Il rientro da STAR_LOST guardava la QUALITÀ della guida invece della sua OPERATIVITÀ (2026-07-20)

**Sintomo (Alessandro, sul campo):** "fa fatica a recuperare il cielo sereno" — con dashboard che mostrava
CIELO LIMPIDO, indice N1 0.95, telemetria FRESH, e i parametri del percorso nubi già resi più aggressivi
(ClearSafePolls 2, soglie indice 0.5/0.5) senza alcun beneficio.

**Diagnosi (replay dei tick reali della notte 19/7).** Il ritardo non era sul percorso NUBI ma sul latch
**STAR_LOST**, che si sbloccava solo con `guiding_state == "NORMAL"` per `ResumeTicks`. Ma NORMAL, in
`controller._update_guiding_state`, richiede `rms < rms_low` = **75% della baseline**; nella banda neutra
(`rms_low`→`rms_high`) lo stato **non viene aggiornato affatto**, e la guida normale vive proprio lì (baseline
mediana 0.689"). Misure: solo **4 tick su 112 (3.6%)** hanno raggiunto NORMAL, tutti nell'ultimo minuto; il SAFE
delle 03:27:16 è arrivato **18 minuti dopo** l'UNSAFE, con il cielo limpido per tutto il tempo e il rientro
innescato da un tuffo casuale dell'RMS a 0.609". Non uno stallo assoluto: un'attesa **stocastica e scorrelata
dal cielo**. Spiega anche il "disallineamento guiding_state ↔ Diagnostic Engine" rimasto aperto in §63.

**Fix §65 (solo plugin, motore adattivo INTOCCATO).** Il criterio di uscita diventa il **complemento esatto**
di quello d'ingresso: si entra in UNSAFE perché la stella è persa, si esce quando la stella è di nuovo
tracciata. `isGuidingOperational = GuidingState ∉ {STAR_LOST, INACTIVE, null}`. Due argomenti a supporto della
scelta degli stati: (1) **coerenza logica** — DEGRADED e CRITICAL non generano UNSAFE da soli, quindi non devono
poterlo mantenere (uno stato che non basta a far scattare la protezione non può prolungarla); (2) **insieme
canonico dell'agente** — `controller.py` usa già `(STAR_LOST, INACTIVE)` come "PHD2 NON in guida valida" per il
gate della riselezione Path B: riusato quello invece di inventarne uno. `null` escluso per fail-safe (payload
incompleto non è evidenza di stella tracciata). Isteresi `ResumeTicks` invariata: cambia QUALI stati contano,
non per quanto.

**Nota su CRITICAL (valutata, non accantonata):** guida attiva ma RMS > 1.5×rms_high è pessima per l'imaging —
però quello è un giudizio di QUALITÀ, competenza del motore adattivo (che in CRITICAL sta già ammorbidendo le
leve), non della safety; e il percorso NUBI resta a proteggere il caso "cielo davvero inutilizzabile". Escluderlo
avrebbe reintrodotto una versione attenuata dello stesso stallo.

**Nessun kill-switch aggiunto** (deviazione consapevole dalla dottrina): i kill-switch di §55 proteggevano nuove
*escalation* verso UNSAFE (rischio falsi allarmi); qui si corregge un rientro che si è dimostrato difettoso, e
un interruttore per ripristinare il difetto avrebbe valore nullo. L'insieme degli stati è comunque una
condizione unica e nominata, banale da restringere. Disponibile ad aggiungerlo se Alessandro lo preferisce.

**Test: 45 verdi** (+4: il caso di campo con DEGRADED; tutti gli stati tracciati; INACTIVE/null NON sbloccano;
isteresi e azzeramento streak su ricaduta). La regressione originale su NORMAL continua a passare. Build 0/0,
DLL reinstallata (hash-match). **NON committato: attende validazione sul cielo** (decisione di Alessandro).

## 66. Il riferimento di N1 si auto-erodeva: cricchetto anti "rana bollita" (2026-07-20, agente v2.8.2)

**Conferma sul cielo (Alessandro, in diretta).** L'ipotesi formulata in §65 si è materializzata: durante un
degrado progressivo il riferimento scendeva insieme al cielo, rendendo il confronto sempre meno significativo.
Da ipotesi a comportamento reale da correggere.

**Causa.** `base_stars` era il rolling-high puro della finestra: **seguiva il cielo anche VERSO IL BASSO**.
Numeratore e denominatore scendevano insieme → indice ~1.00 → CLEAR, mentre il cielo si dimezzava. Misurato al
banco (36 pose da 5 min, −2%/posa, cielo al 48%): **§45 dava indice 0.842 = CLEAR** (rana bollita conclamata).

**Strategie valutate.** (a) *Massimo di sessione*: scartato — al cambio di campo/target o con il calo legittimo
per airmass produce una soglia **irraggiungibile** e uno stallo permanente. (b) *Pavimento relativo al massimo*:
stessa patologia, solo ritardata (un calo legittimo oltre la soglia del pavimento resta bloccato). (c) *Doppio
riferimento operativo*: due metri di paragone concorrenti = due superfici decisionali, complessità senza
guadagno. (d) **CRICCHETTO ASIMMETRICO — scelta.** L'asimmetria è fisica, non arbitraria: *le nubi non creano
stelle*, quindi un miglioramento è sempre evidenza legittima (adozione immediata), mentre un peggioramento è
ambiguo (nube? airmass? campo nuovo?) e va trattato con prudenza.

**Le tre regole** (`TransparencyTracker._ratchet`, vale per stelle e per fondo cielo):
1. **Miglioramento → adottato subito.**
2. **Stato già degradato (HAZE/CLOUD) → riferimento CONGELATO**: durante un evento il cielo non può riscrivere
   la propria normalità (stessa disciplina di `snr_ref` in §57). Con **tetto** `ref_freeze_max_min=90` min,
   tarato sulla durata reale degli eventi osservati (19→100 min).
3. **Peggioramento a cielo sereno → RILASCIO LENTO**, emivita `ref_release_half_life_min=25` min misurata in
   **tempo reale** (§57-bis: mai in campioni — indipendente dalla durata dei sub).

**Difetto del mio primo design, trovato dal banco PRIMA del rilascio:** senza il tetto alla regola 2, un livello
stabilmente più basso (cambio campo) congelava il riferimento **per sempre** → stallo permanente. Il tetto lo
elimina: recupero misurato ~130 min nel caso peggiore.

**Compromesso dichiarato e scelto consapevolmente** (tabella al banco, emivite 15/25/45/90 min): con emivita 25
si rileva −2%/posa (0.563 → HAZE) e NON si rileva −1%/posa (0.857 → CLEAR). Quest'ultimo è **voluto**: un calo
del 30% in 3 ore è indistinguibile dall'airmass di un target che scende, e segnalarlo produrrebbe falsi CLOUD
non risolvibili. Il tetto di congelamento privilegia la **sicurezza sulla disponibilità** (§55): meglio fino a
~2 h di riferimento conservativo dopo un cambio campo che l'erosione durante una nube di 100 minuti — e HAZE
(0.5–0.8) è comunque **neutro** per N6, quindi solo un campo nuovo sotto il 50% mette in pausa.

**Osservabilità (metodologia del progetto: prima si vede, poi si automatizza).** `/status.nina.transparency`
espone ora `base_stars_session_best` (high-water per filtro) e `ref_drift_pct`; la card mostra
"170/181 · best 188" con tooltip sulla deriva. Il massimo di sessione è **diagnostico puro**: non entra in
nessuna decisione, proprio perché come attuatore sarebbe pericoloso.

**Kill-switch** `[nina_indices] ref_ratchet_enabled=false` → comportamento §45 identico. **Test: 310 verdi**
(+9 `test_transparency_ratchet.py`, tra cui la **controprova** che col kill-switch la rana bolle di nuovo, il
test sul tetto anti-stallo e l'indipendenza dalla durata dei sub). ZIP **v2.8.2** rigenerato (regola §62), 2.8.1
rimosso. NON committato: attende validazione sul cielo.

## 67. Il contesto lo conosce già NINA: baseline per (target, filtro) + airmass (2026-07-20, agente v2.8.3)

**Osservazione architetturale di Alessandro**, condivisa: il §66 doveva *dedurre* il cambio campo dal
comportamento del conteggio stelle, quando NINA quel fatto **lo sa già**. Meglio riconoscerlo che inferirlo.

**Verifica prima di progettare** — il segnale c'è, ed è più ricco del previsto: `ImageSavedEventArgs.MetaData`
(che il forwarder ha già in mano a ogni posa) espone `Target.Name`, `Target.Coordinates` e
`Telescope.Altitude/Azimuth/`**`Airmass`** (NINA la calcola già). E il contratto §41 **aveva già lo slot**:
`NinaContext.target` esisteva per il futuro N2 e il plugin non lo popolava. Tutti i campi `Optional` → aggiunta
compatibile in ENTRAMBE le direzioni (agente vecchio+plugin nuovo = ignorato; agente nuovo+plugin vecchio =
None → fallback §66).

**Scelta di design: chiave, non reset.** Alessandro proponeva "cambio target → reinizializza la baseline". Ho
implementato invece **baseline indicizzata per (target, filtro)**, che è più pulita: nessun ordinamento/race da
gestire (il target arriva INSIEME a ogni posa, l'associazione è intrinseca), tornare su un target già visto ne
**ripristina gratis** la baseline, nessuna macchina a stati di reset da sbagliare, ed è la stessa estensione già
usata per il filtro. Un target nuovo parte con indice ~1.00 = CLEAR invece che con un falso CLOUD da smaltire.

**Conseguenze sul §66:** il tetto di congelamento (90 min) **retrocede a fallback** per l'eccezione (target
assente, riprese manuali, degrado reale su target singolo) invece di essere il discriminatore principale.

**Il best di sessione promosso da diagnostico a PAVIMENTO (regola 4).** Con la chiave per target il massimo di
sessione non è più pericoloso — un campo nuovo ha una chiave nuova, quindi un high-water nuovo — e diventa
quindi utilizzabile come vincolo: `ref >= ref_session_floor_frac × best(target, filtro)`, default **0.70**.
Chiude il buco residuo del rilascio a tempo, che essendo illimitato nel tempo poteva comunque erodere il
riferimento all'infinito. Margine sicuro: l'estinzione per airmass alle altezze d'uso reale vale pochi punti
percentuali (70°→45° ≈ 5%), molto meno del 30% di margine. Sotto il pavimento la degradazione resta VISIBILE
per sempre (a 50% del best → indice 0.71 = HAZE; a 35% → 0.5 = CLOUD).

**Airmass: SOLO telemetria** (decisione esplicita di Alessandro). Viaggia nel payload, si logga, si mostra in
dashboard accanto a filtro e target — nessuna decisione la consuma. Un test lo **blinda**: due sessioni identiche
con airmass 1.0 e 2.5 devono dare lo stesso indice. Dopo qualche notte di dati reali si valuterà se usarla.

**Test: 318 verdi** (+8 §67: cambio target senza falso allarme; ritorno al target precedente che ripristina la
baseline; nube sullo stesso target ancora rilevata; retrocompatibilità senza target; airmass inerte; pavimento
che tiene, che è per-target, e che è disattivabile). Plugin 45 verdi, build 0/0, DLL reinstallata (hash-match).
ZIP **v2.8.3** (regola §62), 2.8.2 rimosso. NON committato: validazione sul cielo di §65+§66+§67 insieme.

## 68. Osservabilità del canale di guida: l'ultimo canale scoperto — agente v2.9.0 + latch GUIDE_UNOBSERVABLE

**Guasto di campo (26/7, forense).** Camera di guida in stato patologico (sospetta congestione USB: setup
all-ZWO, USB Limit 70, "Failed to set ASI Control Value" nei log NINA). Sequenza reale ricostruita dai tick:
23:06:22 StarLost → `guiding_state=STAR_LOST` per **5 secondi** → arrivano ancora GuideStep pessimi (rms 1.6")
che riscrivono lo stato su **CRITICAL** → 23:06:43 **silenzio totale**. Lo stato resta congelato su un valore
OPERATIVO e `/status` continua a servirlo come attuale. Tutti e quattro i latch muti: STAR_LOST mai consolidato
(300 s richiesti, e con polling a 15 s c'era **2/3 di probabilità che N6 non vedesse nemmeno** quella finestra da
5 s — aliasing di campionamento), CLOUD con cielo CLEAR 0.919, STALE gated su "ultimo cielo degradato",
AGENT_LOST con agente vivo. Senza l'intervento manuale di Alessandro il monitor sarebbe rimasto **SAFE tutta la
notte**. Il guasto è dovuto al solo difetto strutturale: l'`OSError` delle 23:13 era una chiusura manuale.

**Principio.** Il consolidamento richiedeva **evidenza continuata del guasto**, ma questo guasto **distrugge il
canale dell'evidenza**. La domanda giusta non è "la stella è persa?" ma **"posso ancora fidarmi del canale di
guida?"** — che è §55 ("perdere l'osservazione affidabile è di per sé una condizione di rischio") finalmente
esteso all'ULTIMO canale rimasto scoperto: NINA aveva STALE, l'agente aveva AGENT_LOST, PHD2 non aveva nulla.
Confine §65 intatto: si misura l'OSSERVABILITÀ (binaria, oggettiva), non la QUALITÀ (continua, del motore).

**Scoperta sul protocollo PHD2** (letto `event_server.cpp` vendorizzato, non a memoria): stavamo buttando via
telemetria preziosa. `LoopingExposures` (camera che espone senza guidare — MAI gestito prima: il canale poteva
essere vivo e sembrarci muto); `ErrorCode` per-frame con `Star::FindResult` (**SATURATED / MASSCHANGE** =
esattamente la firma del frame corrotto da USB); `Alert.Type` **strutturato** (info|question|warning|error → via
lo string-matching fragile); `StarMass` già parsato e mai consumato.

**Agente (`guide_health.py`, misura e basta).** DUE orologi distinti: `frame_age_s` (ultimo frame QUALSIASI =
osservabilità vera) e `guide_age_s` (ultimo GuideStep = da quanto non si guida). `guiding_expected` derivato
dagli **annunci espliciti** di PHD2 (StartGuiding/GuidingStopped/Paused/Resumed/AppState) — è l'asimmetria che
rende sicuro il gate: **le pause legittime PHD2 le annuncia, sui guasti tace**. Volutamente indipendente da
`_lastKnownGuidingActive` del plugin: ripararlo avrebbe **disarmato STALE e AGENT_LOST** durante flip/autofocus
(regressione individuata prima di scrivere codice — "sessione attiva" ≠ "guida in corso"). Più: conteggio
ErrorCode per codice, severità Alert, dispersione robusta di StarMass (MAD/mediana: distingue il guasto
ELETTRICO — salti erratici — dalla velatura — calo graduale). Disciplina §63: osservatore passivo in try/except,
non può abbattere il loop. Kill-switch `[guide_health] enabled`.

**Plugin (latch GUIDE_UNOBSERVABLE, decide).** Quinto latch INDIPENDENTE (non fuso in un punteggio: i pesi non
sarebbero validabili e si perderebbe `LastCause`, cioè l'azione operativa distinta "vai a controllare camera/USB").
Accumulatore **leaky** come §55 — non streak consecutivo, che è precisamente il difetto del Bug A rimasto sul
canale guida. S1 fail-safe deterministico: silenzio > `GuideSilenceSeconds` (90 s) con guida attesa → accumula;
frame che tornano → drena; cap `GuideUnobservablePolls` (3 ≈ 45 s). S2 corroborazione (Alert severo o ≥3
ErrorCode recenti) **dimezza la soglia** ma non decide mai da sola — stesso paletto del §57. Retrocompat totale:
agente <v2.9 non espone il blocco → latch inerte. Kill-switch in opzioni + toast/tooltip localizzati.

**Latenza sul caso reale**: Alert a 6 s dall'ultimo frame → con corroborazione UNSAFE a ~90 s; senza, ~135 s.
Contro "mai".

**Test: 330 agente** (+12 `test_guide_health.py`) **e 52 plugin** (+6, incluso il caso 26/7 riprodotto:
stato congelato su CRITICAL + cielo CLEAR + agente vivo → UNSAFE solo per il silenzio). Build 0/0, audit
localizzazione 93/93 con 0 residui, ZIP **v2.9.0** e DLL reinstallata (hash-match). Punto 5 fatto: gli StarLost
finiscono ora anche nel CSV di sessione (nella forense del 26/7 mancava proprio quella riga). NON committato:
attende validazione sul cielo insieme a §65/§66/§67.

## 69. Il pedaggio IPv6 su `localhost` e il rumore del log — agente v2.9.1 (2026-07-30)

**Sintomo (Alessandro):** chiusura di NINA lenta, finestra congelata "parecchi secondi", due volte kill manuale.

**Forense sui log NINA** (ricostruzione al millisecondo, due chiusure reali). Prima ho **scagionato** due
sospetti miei: (a) i device si disconnettono in **238 ms** — l'ipotesi "USB/ZWO lento" cade; (b) il `Teardown`
del plugin è `async` con `ConfigureAwait(false)` e non esiste un solo `.Wait()/.Result` in tutto il plugin —
niente deadlock. Poi il dato: fra `Disconnected Safety Monitor` e il `200` del POST passavano **2807 ms**, di cui
**2031 ms per il solo POST /shutdown** verso localhost. L'agente rispondeva all'istante (2-3 s per l'intero
graceful, watchdog §59 mai scattato in 10 chiusure).

**Causa:** il plugin chiamava `http://localhost:8080`; su Windows `localhost` risolve **prima a `::1` (IPv6)`**
mentre uvicorn fa bind su `0.0.0.0` (**solo IPv4**) → ogni chiamata pagava il fallback.

**Prova sperimentale** (Alessandro, endpoint → `127.0.0.1`, due sessioni): POST `/shutdown` **2031 ms → 5 ms**
(fattore ~400); contributo totale del plugin **2807 → 239 ms**; sequenza visibile di chiusura **3043 → 402 ms**.
Non variabilità: sparizione di un ritardo sistematico.

**Fix.** `DefaultDashboardUrl` = `http://127.0.0.1:8080` + **migrazione one-shot** al Load: chi ha in
`settings.json` esattamente il vecchio default passa a 127.0.0.1 (non era una scelta, era un default difettoso);
un URL scelto a mano viene rispettato. Allineati anche i testi utente (help, fallback dashboard) e la
LongDescription. **Il bind dell'agente NON cambia** (`cfg.dashboard.host = 0.0.0.0`): la dashboard resta
raggiungibile da tutta la LAN via IP della macchina — sono due cose indipendenti (chi ascolta ≠ chi telefona).

**Rumore del log (stessa milestone).** Misurato: **85% del log** della notte 29/7 (8314 righe su 9716) era il
retry di connessione a PHD2 — 3 righe ogni 12 s per ore, con PHD2 chiuso e l'agente vivo insieme a NINA. Con la
rotazione a 5 MB quel rumore **espelle la storia utile**. Nuovo `phd2_agent/reconnect_log.py`
(`ReconnectLogPolicy`, logica pura + clock iniettabile, stile §57): primi N tentativi per esteso → **una** riga
di soppressione → **battito** ogni 10 min → **sintesi** al ritorno ("PHD2 raggiungibile dopo N tentativi in X
min"); un messaggio d'errore DIVERSO riporta subito in verboso. Il battito non è un vezzo: **il silenzio non è
mai una prova** — senza, un lettore futuro non distingue "agente vivo che ritenta" da "agente morto", ed è
l'ambiguità che è costata tempo in §63 e §68. Effetto misurato dal test: **un'ora di retry passa da ~700 righe a
≤11**. Parametri in `[logging]`, battito disattivabile (0).

**Test: 337 agente** (+7 `test_reconnect_log.py`, incluso il caso reale "un'ora di retry") **e 52 plugin**;
build 0/0, audit localizzazione 93/93 con 0 residui; ZIP **v2.9.1** e DLL reinstallata (hash-match).

**Terza modifica, autorizzata dopo il report — agente v2.9.2.** Anche `[phd2] host` pagava il pedaggio: nei log
una connessione RIFIUTATA a PHD2 impiegava **2 secondi** (un ECONNREFUSED su loopback IPv4 è istantaneo), e la
stessa latenza ricadeva sulla "riconnessione per restore baseline" allo shutdown. **Verifica di compatibilità
sul sorgente PHD2 vendorizzato** (`event_server.cpp:2619`): il server eventi crea un `wxIPV4address`, quindi
ascolta **SOLO su IPv4** — il tentativo IPv6 di `localhost` non può riuscire *per costruzione*, è latenza pura.
Prova più forte di quella del plugin, dove l'IPv4-only di uvicorn era dedotto dal bind. Fix: default
`127.0.0.1` in `PHD2Config`/`config.toml`/`PHD2Client` + **normalizzazione al load** del solo valore
`"localhost"` (case-insensitive, con log). Invariante protetto da test: si normalizza l'INTENTO (loopback), mai
la SCELTA — IP, hostname di rete e `::1` passano inalterati, e il **bind della dashboard resta `0.0.0.0`**
(altra cosa: è ciò che la rende raggiungibile da LAN). +6 test → **343 verdi**, ZIP **v2.9.2**.

**Aperti, con evidenza, NON risolti qui:**
1. **Thread-affinity WPF**: `AgentHealthChecker: a StatusChanged subscriber threw (The calling thread cannot
   access this object...)` — il VM del pannello aggiorna badge/pulsante dal thread del timer senza marshalling
   (View e SafetyMonitor invece marshallano). Catturata, safety prosegue, ma il badge non si aggiorna. Race.
3. **WebView2 mai disposto** nel pannello dashboard: difetto reale (risorse), ma **scagionato** dai ~3 s
   misurati — sta tutto DOPO l'ultima riga di log di NINA, zona cieca.
4. Le chiusure con **kill manuale** si sono piantate durante la disconnessione della **montatura**, prima ancora
   che il nostro Teardown venisse raggiunto: fuori dal nostro perimetro.

## 70. La sonda che si confrontava con se stessa: ereditarietà del contesto — agente v2.9.3 (2026-08-04)

**Prima uscita reale del recupero post-§67 (notte 3-4/8) e prima regressione del §67, trovata dal campo.**
Prova documentale nei nomi file di NINA (token `$$TARGETNAME$$`): le light di sequenza sono `LIGHT_H_Abell 61_…`,
le immagini della Recovery Probe sono `LIGHT_H__…` — **doppio underscore, target vuoto**. La RecoveryProbe vive
dentro Trigger On Unsafe, alla radice della sequenza, FUORI dal contenitore target: NINA risolve
`MetaData.Target` risalendo la catena dei contenitori e per la sonda non trova nulla. Strutturale: OGNI immagine
di sonda nasce senza target.

**Catena del guasto** (tre log incrociati: agent.log + CSV + log NINA): UNSAFE 23:35 (STAR_LOST, corretto) →
sonda #1 senza target → forwarder omette `context` (riga 150) → chiave §67 `("","H")` MAI vista → bootstrap
`refs[key]=candidate` → **7/7 = indice 1.00 per costruzione** → N1 CLOUD→CLEAR (23:43:05) → il falso CLEAR drena
l'accumulatore nubi → **falso SAFE 23:48 sotto nubi fitte**. Sonda #2 (32 stelle): cricchetto regola 1 sulla
chiave orfana (32>7) → 32/32=1.00. La prima light vera (00:08, CON target) è rientrata sulla chiave giusta:
130/263 = 0.49 VELATURE → UNSAFE#2 corretto. Nota: il "32/32 dopo il SAFE" che sembrava una posa era la CODA
della sonda #2 (loop chiuso a SAFE già dichiarato); la STANTIA 847s era il flip al meridiano (23:53-56). Anche il
recupero finale "giusto" (284/284, 356/356 su O) passava dallo stesso percorso rotto: `("","O")` era un'ALTRA
chiave vergine — esito corretto solo perché il cielo era davvero tornato. Con la chiave pre-§67 (solo filtro) la
sonda avrebbe detto 7/264=0.03 CLOUD: **il §67 ha spezzato in silenzio il contratto su cui la sonda si regge**
("replica il sub interrotto — obbligatorio per l'indice di trasparenza", §57-bis). I test §67 validavano le
light; il percorso sonda-contro-baseline non era mai stato esercitato (integration test rimandato; 27/7 senza
UNSAFE).

**Fix (§70, nina_indices.ingest, dentro il lock):** un'immagine che NON dichiara un target non apre una chiave
propria — **eredita il contesto di sessione corrente** (`_session_target` = ultimo target dichiarato da una
light). Robusto per costruzione: durante l'UNSAFE la sequenza è interrotta → il contesto non può cambiare; al
cambio target reale le nuove light dichiarano e il contesto si aggiorna; senza alcun target mai dichiarato →
chiave ("", filtro) = pre-§67 (retrocompatibile, validato mesi). L'ereditarietà riguarda il TARGET, il filtro
resta quello del payload (la sonda espone col vetro montato: il 3/8 ciclo 2 era O — corretto così). Il fix cura
TUTTI i produttori di immagini orfane, non solo la sonda. Limiti onesti, documentati: (a) riavvio agente durante
UNSAFE → contesto perso → prima sonda post-riavvio bootstrappa — proprietà pre-esistente delle baseline
in-memoria, non di questo fix; (b) UNSAFE nel varco slew→prima-light di un target nuovo → sonda ereditа il
target precedente — identico al comportamento pre-§67, mai stato un problema sul campo.

**Cambio di comportamento ATTESO da segnalare:** col fix, un evento nubi che scavalca il meridiano tiene UNSAFE
finché il cielo non torna davvero → il flip avviene DOPO, alla ripresa (il 3/8 il flip delle 23:53 è "andato in
orario" solo grazie al falso SAFE). La protezione a cavallo del meridiano è di NINA (19/7: flip bloccato in
unsafe, "Stopping tracking instead") — dominio suo, comportamento corretto nostro.

**Test:** `tests/test_target_inheritance.py` — replay fedele del 3/8 come regressione permanente (sonda 7 stelle
→ DEVE dire 0.03 CLOUD; 32 → 0.12 CLOUD; light 130 → 0.49 come sul campo; recupero reale 284 → CLEAR) + regole
di contesto (nessun-target-mai = pre-§67; cambio target aggiorna; filtri separati nel target ereditato).
**349 verdi.** ZIP **v2.9.3**. Plugin NON toccato. NO commit (validazione cielo prima).

### 70-bis. Flip al meridiano sotto UNSAFE prolungato — comportamento NINA verificato (log 19/7 + sorgente)

Domanda di Alessandro dopo il §70 (che rende possibile un UNSAFE *onesto* a cavallo del meridiano). Risposta
verificata su DUE fonti: il log NINA del 19/7 (lo scenario è GIÀ successo sul suo setup: UNSAFE 02:15→03:01,
deadline flip 02:38) e `MeridianFlipTrigger.cs` (develop).

**Catena:** (1) il trigger del flip VIENE valutato anche a sequenza parcheggiata (§61: RunTriggers risale ai
parent — provato dal log: valutazioni alle 02:38 con park dalle 02:15). (2) Deadline oltrepassata con monitor
unsafe → NON flippa: `Safety Monitor connected and reports unsafe conditions. Flip should happen but it is
unsafe. Stopping tracking instead.` → `telescopeMediator.SetTrackingEnabled(false)` — montatura congelata
appena oltre il meridiano, pier protetto. (3) Da quel momento il trigger SI AUTO-ESCLUDE: `Telescope is not
tracking. Skip flip evaluation` (ShouldTrigger → false se non traccia). (4) **NESSUN percorso di codice riavvia
il tracking** — verificato sul sorgente: zero occorrenze di ripresa. (5) Esiste una finestra di "delayed flip"
(~11-12 h post-meridiano) che recupererebbe il flip tardivo (è il percorso visto il 3/8 alle 23:53) — ma è
raggiungibile SOLO con tracking attivo: dopo lo stop di sicurezza è lettera morta.

**Conseguenza sistemica (deadlock, BY DESIGN di NINA):** tracking fermo → stella di guida deriva a velocità
siderale → StarLost continuo → latch STAR_LOST armato → mai SAFE; e le sonde stesse, su montatura ferma,
producono campo strisciato → star detection collassa → N1 resta CLOUD anche sotto cielo PERFETTO. Il sistema
non può uscirne da solo: **nubi che attraversano il meridiano in unsafe = notte finita su quel target**, chiusa
con grazia solo dalle condizioni di fine sequenza (§61: alba/ora — il loop di recovery viene cancellato, park/
warm finali eseguiti). Fail-safe stretto: nulla si rompe, la montatura è protetta.

**Recupero operatore = UN click:** riattivare il tracking siderale dal pannello montatura di NINA. Alla
valutazione successiva il trigger vede il pier sbagliato → "Flip should happen now" → flip tardivo completo
(slew, recenter, stella guida, ripresa autoguida) da solo. Il 3/8 il flip "in orario" delle 23:53 fu un
sottoprodotto del falso SAFE — coincidenza, non feature.

**Roadmap (non implementato, da discutere):** §72 candidato — toast del plugin quando il flip viene mancato per
unsafe ("al ritorno del sereno riattivare il tracking"): il plugin ha accesso ai mediator NINA, costo piccolo,
valore operativo alto. Cintura extra lato hardware: verificare il comportamento al meridiano impostato nel
firmware CEM70G (limite proprio della montatura, indipendente da NINA).

## 71. Il gate della sonda sul "canale pronto" — agente v2.10.0 + plugin v1.9.0.0 (2026-08-04)

**Origine:** riflessione di Alessandro dopo la notte 3-4/8 — la sonda #1 partì alle 23:38, nel minuto PEGGIORE
del canale guida (0/21 frame con stella), quando il suo esito era scontato. Il canale guida è il sensore
GRATUITO e continuo (3 s); la sonda quello COSTOSO e discreto (300 s): il gratuito deve decidere QUANDO il
costoso vale la pena. È il duale dell'hint S2 (stesso strumento fisico, polarità opposte): S2 accelera, §71
dirada.

**Forma: consenso AND di condizioni binarie SOSTENUTE — mai uno score pesato** (anti-§68: i pesi non si
validano sul cielo e un punteggio non spiega COSA manca). Asticella DELIBERATAMENTE sopra il criterio di PHD2
(che si dichiara "guiding" all'istante dell'aggancio): il riaggancio-lampo del 3/8 alle 23:40 (41% di frame
utili, ripersa subito) resta respinto; le 23:47 (86% sostenuto) aprono. Condizioni (`_channel_ready`,
guide_health.py): frame che fluiscono (≤10 s), frazione tracciata ≥70% su 90 s con base statistica minima (10
campioni — mai "pronto per assenza di prove"), ≤2 ErrorCode recenti, nessun Alert severo. Ogni condizione ha la
sua reason loggabile; `/status.guide_health.channel_ready` + reasons + tracked_fraction. Nuovo `on_star_lost()`
(lo StarLost È un frame — canale vivo, stella no; prima finiva in on_guide_step).

**Lato plugin: DEFERRER, mai veto.** `RecoveryProbeGate.Evaluate(..., channelReady)`: a canale dichiarato NON
pronto la S1 slitta, MAI oltre `AutoCeilingSeconds` (900 s, la costante §64) — sotto canale morto le sonde al
tetto sono pura diagnosi (i latch guida §65/§68 impediscono comunque il resume). Invarianti blindati nei test:
**S2 prioritario assoluto** (hint ⇒ gate aperto), **fail-open** su null (agente vecchio/irraggiungibile/
kill-switch ⇒ comportamento pre-§71), min-interval sovrano. Kill-switch `ProbeChannelGateEnabled` (default ON).
Replay 3/8 nei test agente (progressione 0%→41%→86%) e 26/7 (canale muto: mai pronto, tetto unica via).

## 72. MERIDIAN_PROTECTION: la finestra che evita il deadlock del flip — plugin v1.9.0.0 (2026-08-04)

**Problema (§70-bis, verificato su log 19/7 + sorgente):** flip deadline in unsafe → NINA non flippa, ferma il
tracking, e NULLA lo riavvia → stella in deriva (STAR_LOST perenne) + sonde strisciate (N1 CLOUD anche a cielo
perfetto) → il monitor perde TUTTI gli occhi insieme → mai più SAFE → notte finita. **Idea di Alessandro**,
principio: il nostro monitor DEVE osservare per decidere (§55); una protezione che acceca l'osservatore è essa
stessa un guasto di sicurezza. Il flip è una necessità GEOMETRICA della sessione, non un giudizio sul cielo →
MERIDIAN_PROTECTION = **autoprotezione del monitor**, non deroga.

**Vincolo che decide la forma: IsSafe è UN bit, broadcast.** Lo stato può esistere internamente, ma verso NINA
si proietta solo come finestra LIMITATA di Safe riportato. "Solo il flip" non lo impone il canale (impossibile):
lo impongono TIMING (apertura a lead min dalla deadline → il flip parte per primo per costruzione, "no more
remaining time") e REVOCA (pier cambiato → chiusa → l'unsafe onesto ri-parcheggia entro un ciclo; al più un
inizio di posa interrotto). **Verifica pregiudiziale sul sorgente NINA (MeridianFlipVM):** il flip riattiva il
tracking PRIMA dello slew e su OGNI percorso d'errore ("Re-enable Tracking after meridian flip error"); recenter
"best effort, so always return true" → sotto nubi il flip si completa meccanicamente. Seconda pregiudiziale
(altri consumatori di IsSafe): censimento dell'operatore — **nessuno, solo NINA**.

**Implementazione:** `MeridianProtectionEngine` (macchina a stati PURA: Idle→Open→Idle/Lockout, clock
iniettabile) + coordinator nel monitor. `_internalSafe` = stato ONESTO dei latch (MAI toccati);
`IsSafe = _internalSafe || windowOpen`. Apertura: unsafe interno + montatura connessa + pier west + deadline
(meridiano + MaxMinutesAfterMeridian del profilo, HA da LST−RA) entro lead (default 4 min). Chiusure: pier
cambiato (flip fatto, toast); TIMEOUT 20 min senza flip → **LOCKOUT** (niente riaperture = mai oscillazioni
safe/unsafe cicliche; toast col rimedio manuale); safe reale/mount perso/kill-switch. **Ex-post:** se il
tracking è GIÀ fermo (finestra nata tardi, o deadlock pre-esistente) lo riattiva UNA volta per finestra dentro
la finestra — il flip tardivo scatta alla valutazione successiva del trigger (finestra delayed ~11-12 h del
sorgente). Fail-inert totale: mount assente/pier ignoto/eccezione → finestra chiusa, tick N6 mai abbattuto.
Riga diagnostica: `meridian[OPEN|idle] internal=… reported=…`.

**Born-operative (decisione di Alessandro, agli atti):** nel perimetro attuale l'unico consumatore di IsSafe è
NINA e il rischio reale è il deadlock, non l'autorizzazione impropria di altri dispositivi. **Da rivalutare se
compariranno tetti/cupole/osservatori che consumano IsSafe** (annotato anche nell'help delle impostazioni).
Lead configurabile 1-10 min; kill-switch `MeridianProtectionEnabled`.

**Nuove dipendenze plugin:** `ITelescopeMediator` + `IProfileService` via MEF nel costruttore →
`AgentServices.AttachNinaServices` (nullable: senza aggancio la protezione è inerte).

**Test: 354 agente e 63 plugin** (+7 §72: aperture condizionate, chiusura su pier change, tetto+lockout senza
riaperture, ex-post una-volta-sola, fail-inert; +4 §71 gate). Build 0/0, audit 103/103 con 0 residui, ZIP
**v2.10.0** + DLL **1.9.0.0** installata (hash-match). NO commit: validazione sul cielo prima — con §70 la
prossima nuvolata a cavallo del meridiano è il banco di prova naturale di tutto il blocco §70-§72.

## 73. Lo stato del Safety Monitor nella dashboard — agente v2.11.0 + plugin v1.10.0.0 (2026-08-04)

**Richiesta di Alessandro:** dopo §71/§72 il monitor "non è più una funzione interna: è un protagonista della
sessione". Sostituire il toggle MODALITÀ TEST (spazio prezioso, utilità operativa ormai nulla) con un indicatore
di stato del Safety Monitor, uno solo alla volta, con tooltip esplicativi.

**Vincolo architetturale trovato subito (determina la forma).** La decisione di sicurezza vive nel PLUGIN
(latch, causa, finestra §72); la dashboard la serve l'AGENTE, che di tutto questo non sa nulla. Serviva quindi
un flusso NUOVO plugin → agente. Non un polling inverso (l'agente non deve interrogare NINA: dipendenza
capovolta, e il monitor potrebbe non esistere): il plugin **pubblica** a ogni tick su `POST /nina/safety`,
l'agente conserva e riespone su `/status.safety`. Direzione sola: nessuna risposta dell'agente influenza il
monitor.

**Nessuno stato inventato.** Alessandro aveva proposto anche RECOVERY_OBSERVATION / RECOVERY_PENDING: non
esistono nel `SafetyDecisionEngine` e fabbricarli avrebbe creato una mappa UI→realtà falsa. Gli stati VERI sono
tre — SAFE, UNSAFE, MERIDIAN_PROTECTION — e per l'UNSAFE è la CAUSA a fare lo stato visibile, perché la causa è
l'azione operativa distinta ("guarda la camera di guida" ≠ "aspetta che passi la nuvola"): STAR_LOST, NUBI,
TELEMETRIA STANTIA, AGENTE PERSO, GUIDE_UNOBSERVABLE (⚫ suo, come chiesto). L'intenzione dietro
RECOVERY_* è però reale e utile, e vive nella **riga di dettaglio**, composta dalla dashboard con dati che
l'agente ha già: "sonda differita — stella instabile (41% tracciata)" (§71), "canale guida pronto — in attesa
della sonda". Così si vede il PERCHÉ della decisione senza inventare stati.

**Invariante difeso (§55 esteso alla presentazione): l'assenza di notizie non è mai "sicuro".** Lo store ha
freschezza (60 s = 4 tick persi): plugin muto, NINA chiusa o monitor scollegato → **UNKNOWN ⚪**, mai un verde
residuo lasciato sullo schermo. Un UNSAFE stantio non decade in SAFE (test dedicato). `Disconnect()` pubblica
esplicitamente `connected=false`. Stato non riconosciuto (versione futura) → rifiutato, non indovinato: lo
stato precedente resta.

**§72 reso visibile:** dentro la finestra il RIPORTATO diverge dall'INTERNO — il chip dice MERIDIAN PROTECTION
🔵 e il tooltip aggiunge "Valutazione interna: ancora UNSAFE". È esattamente il caso in cui l'osservatore deve
capire perché la sequenza si muove sotto un cielo cattivo.

**Correzione architetturale in corsa (trovata dall'audit §60):** la prima versione faceva mandare al plugin una
stringa di dettaglio in italiano — ma il plugin è localizzato EN/IT e la dashboard ha una lingua sua: due
sistemi di localizzazione sullo stesso testo. Ora **il plugin invia FATTI (stato, causa), la dashboard mette le
PAROLE**. Audit di nuovo a 0 residui.

**Bug intercettato prima del campo:** rimuovendo il toggle restava `el('dry-run-switch').checked = isDryRun` in
`applyFullStatus` → `TypeError` a OGNI refresh → dashboard congelata. Trovato con una verifica di residui, non
dai test (la dashboard non ne ha). Da valutare: smoke test headless della dashboard.

**Sul toggle rimosso:** si è tolto l'INTERRUTTORE, non la funzione. `dry_run` resta impostabile da
`config.toml` [control] e da CLI `--dry-run`, e la modalità resta VISIBILE nel `mode-badge` sotto. Il colore del
chip è sempre ridondante col testo: mai affidare a un colore da solo un'informazione di sicurezza.

**Test: 363 agente** (+9 `test_safety_state.py`, incluso "un UNSAFE stantio non diventa mai SAFE") **e 63
plugin**; build 0/0, audit 103/103 con 0 residui; ZIP **v2.11.0**, DLL **1.10.0.0** installata (hash-match).
NO commit: validazione sul cielo con l'intero blocco §70-§73.

### 73-bis. Il badge del canale guida, e una mia disonestà corretta — agente v2.11.1

**Da una revisione esterna (GPT, relayed da Alessandro)** che chiedeva di rappresentare il gate §71 come
INFORMAZIONE ACCESSORIA e non come nuovo stato del monitor — "il §71 non modifica il Safety Monitor, modifica
il comportamento della Recovery Probe". Osservazione corretta e già rispettata nella struttura (§73 non ha mai
creato uno stato per il gate). Ma rileggendo la riga di dettaglio con quella lente, **commetteva in piccolo
proprio il peccato che avevo criticato**: diceva *"sonda differita"* e *"in attesa della sonda"* — affermazioni
sulla Recovery Probe che l'Agente NON PUÒ conoscere. L'Agente misura il canale; non sa se una sonda sia in
corso, né se una RecoveryProbe esista affatto nella sequenza dell'utente. Con una sequenza priva di sonda la
dashboard avrebbe dichiarato differita una posa inesistente.

**Corretto:** la riga dichiara ora solo il FATTO MISURATO (*"stella instabile (41% tracciata)"*, *"canale guida
stabile"*), e la conseguenza sulla sonda vive nel tooltip **al condizionale** ("le pose-sonda di recupero, SE
attive, restano differite... mai oltre 15 minuti"). Aggiunto il badge accessorio richiesto — `CANALE NON PRONTO`
(arancio) / `CANALE PRONTO` (giallo) — deliberatamente piccolo e subordinato al chip: la grafica non deve
suggerire che il gate sia uno stato del monitor. Visibile solo con UNSAFE + §68 abilitato + segnale presente
(assente ⇒ nascosto, mai un badge che finge di sapere).

**Nuovo controllo automatico:** lo script di verifica ora estrae ogni `el('id')` da app.js e ne verifica la
presenza in index.html. È il bug del §73 (`dry-run-switch` orfano ⇒ TypeError a ogni refresh) trasformato in
controllo ripetibile — la dashboard resta senza test propri, ma questa classe di errore ora non passa più.

**Due imprecisioni della revisione, per gli atti** (non cambiano le conclusioni): (a) `GUIDE_UNOBSERVABLE` è
una CAUSA di UNSAFE, non uno stato con una causa dentro; (b) non esiste un "UNSAFE HAZE" — HAZE è la zona
NEUTRA dell'accumulatore §55, quella che deliberatamente NON fa scattare nulla: la causa è CLOUD. (c) Il
"domani aggiungi una lingua senza toccare il plugin" vale come principio, ma la dashboard oggi è
monolingua italiana hard-coded: la separazione è pronta, la capacità multilingua della dashboard no.

**363 test verdi**, ZIP **v2.11.1**. Plugin invariato (1.10.0.0). NO commit.

## 74. Pannelli dinamici: lo spazio in proporzione all'attività — agente v2.12.0 (2026-08-04)

**Principio (Alessandro):** *"l'informazione più importante non è tutto ciò che esiste, ma ciò che sta
succedendo adesso"*. Osservazione nata dal campo: il Controller INACTIVE occupa un terzo dello schermo per ore
mostrando Aggressività e MinMove — valori leggibili in PHD2 e privi di valore operativo finché il motore non
interviene. La dashboard smette di essere una pagina di telemetria e diventa un cruscotto.

**Due categorie.** SEMPRE VISIBILI = stato generale che l'operatore deve poter consultare in qualsiasi momento
(Safety Monitor §73, Trasparenza, Recovery, grafico guida, stato Agente, e il ciclo motore §63 — è la spia di
"il motore è vivo", non un dettaglio interno). DINAMICI = attività interna del motore: Controller, Esposizione
Dinamica, Escalation Gate, Adaptive MinMove.

**Tre regole, scelte per non nascondere mai ciò che conta:**
1. **Attività → apre SEMPRE**, anche se l'operatore l'aveva chiuso a mano: un intervento del motore deve
   attirare l'occhio, è tutto lo scopo della modifica.
2. **Quiete → richiude dopo 120 s, MA MAI un pannello aperto dall'operatore** (pin 📌): una scelta esplicita non
   viene mai contraddetta dall'automatismo.
3. **Da chiuso la barra porta comunque lo STATO** (chip): l'informazione essenziale non sparisce, si comprime.
Il Log Decisioni resta la memoria persistente: richiudere non perde nulla di forense.

**Segnali di attività, tutti verificati sui campi reali di `controller.get_status()`** (nessuno inventato):
Controller = `engine.actions_total` che cresce (EVENTO, non stato: è l'intervento vero); Esposizione = stato
≠ NOMINAL, o `steps_above_base` > 0, o cooldown in corso; Escalation Gate = `ra || dec` saturato (gate APERTO,
path B può agire); Adaptive MinMove = **`clamping_active`**, non `cap_active`. Quest'ultimo è l'affinamento
importante: il controller espone due flag distinti — `cap_active` = il cap ESISTE (baseline pronta),
`clamping_active` = il cap ha davvero TAGLIATO una richiesta (§0-bis). "Spazio in proporzione all'attività"
significa il secondo: un cap pronto che non taglia nulla non sta lavorando. Chip a tre valori:
NON ATTIVO / PRONTO / STA LIMITANDO.

**Implementazione a rischio minimo: nessuna modifica strutturale all'HTML.** Il wrapping (header cliccabile +
`div.panel-body` richiudibile) avviene a runtime in `setupDynamicPanels()`: tutti gli id restano dove sono e
ogni funzione di aggiornamento esistente continua a trovare i propri elementi invariata. Il chip di stato si
aggiunge SOLO se l'header non ha già un badge suo (Adaptive MinMove ce l'ha) — niente informazione duplicata.
Un `try/catch` per pannello: uno che sbaglia non rompe il refresh degli altri.

**Verifiche:** oltre alla suite (363 verdi, invariata: la dashboard non ha test propri), **smoke test HTTP
reale** — server avviato, `/` 20.5 kB, `/status` con tutti i blocchi, `app.js` servito con le nuove funzioni — e
**test end-to-end del canale §73**: POST UNSAFE/CLOUD → riflesso corretto; MERIDIAN_PROTECTION con
`internal_safe=false`; stato ignoto → `accepted:false` e stato precedente intatto; `connected:false` → UNKNOWN.
Più il controllo automatico degli id orfani (§73-bis). ZIP **v2.12.0**, plugin invariato (1.10.0.0). NO commit.

**Prossimo incremento concordato (non fatto):** tooltip a due livelli — primo livello sintetico (cos'è, perché
conta, **origine del dato**: PHD2 / NINA / Safety Monitor / Agente), secondo livello "Approfondisci" solo per
gli elementi complessi. Solo hover, niente gestione touch (uso reale = browser su PC). Prerequisito già
identificato: esporre su `/status` le soglie citate, perché un tooltip non deve mai scrivere in prosa un numero
configurabile. Da fare DOPO la validazione sul cielo, quando i valori diagnostici si saranno visti muovere.

## 75. Fine ciclo dell'AI Finder: un interruttore che peggiorava il sistema — agente v2.13.0 (2026-08-04)

**Domanda di Alessandro, applicando la regola del §74** ("un elemento esiste perché rappresenta qualcosa che il
sistema fa realmente"): che ruolo ha oggi il toggle "AI Finder (Forzato)"? Promuoverlo a sottosistema vivo o
chiuderne il ciclo?

**Indagine sul codice** (con una mia correzione in corsa: avevo concluso troppo in fretta che scipy non fosse
nel distribuibile — c'era, il mio `head -3` aveva troncato l'elenco prima della "s"). Fatti:
- il toggle NON era una statuina: era agganciato al motore, ma **in un solo punto** — `_evaluate_star_lost()`,
  il ramo di recupero dopo la perdita stella;
- funzionava davvero (star_finder.py + scipy negli hidden import dello .spec);
- **spento di default** e con **zero test** su 363;
- **scavalcava il backoff §17** — i tre tier nati dopo l'incidente reale delle 130+ chiamate a `find_star` in
  6 minuti su camera crashata via USB. Le NOTE §17 lo dicevano candidamente: *"Il backoff non è applicato lì
  (scenario meno critico)"*. Dopo il **26/7** quella valutazione non regge più: acceso su una camera in crisi
  l'agente avrebbe fatto save_image + analisi scipy ogni 10 s **senza freno**, caricando proprio il bus che
  stava soffocando;
- il suo unico valore differenziale — rilevare la **saturazione** — è oggi coperto per via NATIVA dal §68
  (`ErrorCode = STAR_SATURATED` da PHD2, ogni 3 s, senza salvare un FITS, senza scipy, senza rischio).

**Decisione (Alessandro, condivisa):** rimuovere il toggle, NON il modulo. Motivazione architetturale che
condivido e metto agli atti: **la selezione della stella di guida è competenza di PHD2** — conosce camera,
profilo, calibrazione, maschere. Il progetto ha vinto ogni volta che ha rispettato i confini (PHD2 guida, NINA
possiede la sequenza, noi misuriamo e decidiamo la sicurezza) e ha sofferto quando li ha sfumati. L'Agente
misura, interpreta e decide; non duplica algoritmi nativi meglio informati.

**Rimosso:** `ai_find_enabled` dal controller, l'intero ramo in `_evaluate_star_lost` (ora il **backoff è
l'unico percorso** — guadagno netto di sicurezza), l'endpoint `POST /config/ai_find`, il campo su `/status`, il
toggle e il listener in dashboard, le voci del manuale (markdown + builder PDF). La riga di troubleshooting è
stata **riscritta su ciò che il sistema fa davvero oggi**: backoff → SUSPENDED → *"è un problema USB/camera"* +
il pannello GUIDE UNOBSERVABLE del §73.

**RESTA `star_finder.py`**, rinominato nella sua intestazione per quello che è: strumento del **Path B**, che lo
usa per riselezionare una stella NON satura al cambio esposizione — compito diverso, che PHD2 da solo non copre.
Sottosistema vivo. (Nota: scipy pesa 69 MB su 179 del pacchetto, ma non è eliminabile proprio perché il Path B
lo usa: rimuovere il toggle non fa risparmiare spazio, e non era quello l'obiettivo.)

**Test: 368** (+5 `test_star_lost_recovery.py`) che blindano l'invariante conquistato — *ogni tentativo di
riselezione passa dal backoff* — contro reintroduzioni future: il toggle non deve tornare né come attributo né
su `/status`; conteggio fallimenti, rallentamento, sospensione, reset al successo. **Verifica live sul server
reale**: `/config/ai_find` → **404**, `ai_find_enabled` assente da `/status`, `ai-find-switch` assente sia dalla
pagina servita sia da `app.js`. ZIP **v2.13.0**, plugin invariato (1.10.0.0). NO commit.

### 73-ter. Il battito mancante: due metà del §73 che assumevano cose opposte — v2.13.1 + plugin 1.10.1.0

**Segnalazione di Alessandro (4/8, dashboard aperta in attesa del buio):** all'avvio il monitor mostra SAFE,
dopo 2-3 minuti passa da solo a `MONITOR — in attesa del Safety Monitor`, senza aver scollegato nulla. Domanda:
è il timeout di freschezza previsto, o il plugin ha smesso di pubblicare? E la sua ipotesi: "magari torna SAFE
alla prima esposizione".

**Non era normale, e non si sarebbe sistemato da solo: difetto mio nel §73.** Le due metà si contraddicevano.

| Componente | Assunzione implicita |
|---|---|
| `SafetyStatePublisher` (plugin) | deduplicava — POST **solo al cambio di stato** ⇒ *"l'agente conserva l'ultimo valore"* |
| `SafetyStateStore` (agente) | freschezza 60 s ⇒ *"il plugin ripubblica periodicamente"* |

A stato stabile **nessuno dei due parlava più**: primo POST SAFE, poi silenzio, e dopo 60 s la dashboard
dichiarava UNKNOWN col monitor perfettamente vivo. Sarebbe rimasta così tutta la notte.

**Chi correggere.** La freschezza è GIUSTA — è l'invariante §55 applicato alla presentazione ("nessuna notizia
non è mai sicuro") e va difesa. A sbagliare era il publisher: **chi ha una scadenza deve ricevere un battito**.
Ora pubblica a OGNI tick; costo reale un POST su loopback da ~5 ms (misurato nel §69), a cadenza 15 s.

**Secondo difetto latente, trovato nello stesso ragionamento e corretto insieme:** `HealthCheckIntervalSeconds`
è configurabile **da 5 a 120 s**. Anche col battito, una soglia FISSA a 60 s sarebbe scaduta *sempre* con
cadenza 120 s — a monitor vivo. Il plugin ora **dichiara la propria cadenza** (`poll_interval_s` nel payload) e
l'agente ne **deriva** la finestra: `max(45 s, 3 × cadenza)` — tre battiti persi. È lo stesso principio del §43,
dove la finestra di freschezza si deriva dalla durata della posa invece di essere indovinata. Verificato dal
vivo: cadenza 15 s → finestra 45 s; cadenza 120 s → finestra 360 s. `/status.safety` espone ora anche
`staleness_window_s` e `poll_interval_s`, così un eventuale UNKNOWN a torto si spiega da sé.

**Test: 372** (+4) — SAFE stabile per 30 minuti simulati resta SAFE; finestra derivata dalla cadenza dichiarata;
pavimento a cadenza rapida; e soprattutto **l'invariante non indebolito**: il plugin che TACE davvero resta
UNKNOWN. Plugin 63 verdi, build 0/0. ZIP **v2.13.1**, DLL **1.10.1.0** installata (hash-match). NO commit.

**Lezione trasversale:** ogni canale con una scadenza ha bisogno di un battito, e chi ha la scadenza non deve
indovinare la cadenza altrui — deve fargliela dichiarare. Vale già per §43 (telemetria NINA) e §68 (frame di
guida); il §73 era l'unico che l'aveva dimenticato.

## 76. Il sensore veloce accanto a quello lento — agente v2.14.0 + plugin v1.11.0.0 (2026-08-05)

**Osservazione di Alessandro dopo la notte 4/8**, la prima ad attraversare tutte le fasi (limpido → degrado →
UNSAFE → sonda → recupero → SAFE): il Recovery Hint e la Recovery Probe lavorano su **scale temporali
incompatibili** — canale guida ogni ~3 s, posa di verifica ogni 300 s — e il monitor ascolta quasi solo il lento.

**Prima cosa: la risposta fattuale alla sua domanda** ("il Hint smette di calcolare durante la sonda?"). NO.
`update(snr)` gira a ogni GuideStep senza alcuna nozione di sonda in corso: durante i 300 s di posa il Hint è
vivo e produce evidenza. Si spegne invece nell'istante in cui **N1 dice CLEAR** (è gated su stato degradato) —
nei log del 4/8: sonda osservata 23:27:09, `hint inerte` 23:27:12, **tre secondi dopo**. L'infrastruttura
c'era già; mancava un consumatore.

**Il ritardo misurato, scomposto** (recupero del 4/8): canale guida vede la risalita 23:20 → hint ACTIVE 23:22
(60 s di sostegno) → **posa-sonda 300 s** → N1 CLEAR 23:27 → drain → SAFE ~23:28. **~8 minuti**, di cui **5 sono
l'esposizione stessa**: irriducibile, e non aggredibile dando peso al Hint.

**Decisione architetturale — le due direzioni NON sono simmetriche.**
• *Verso SAFE*: **no**. Il sensore veloce è UNA stella; N1 ne conta centinaia sul campo. Uno squarcio sopra la
  stella di guida non dice che il campo è utilizzabile — è la modalità di guasto del 3/8 (falso CLEAR → falso
  SAFE) da cui è nato il §70. Il giudice resta la posa-sonda. Richiesta declinata, con l'accordo di Alessandro.
  Nota: "il Hint influenza la valutazione della Probe" non ha un posto dove atterrare — la sonda non valuta
  nulla, è un'esposizione; a valutarla è N1.
• *Verso UNSAFE*: **sì, ed è un buco misurato**. Il 4/8 la SNR è crollata da ~70 a ~22 fra le 23:07 e le 23:11;
  N1 ha riconosciuto le nubi alle **23:14** (era fermo all'ultima posa buona) e il monitor è passato UNSAFE alle
  **23:16**. Otto minuti di posa integralmente sotto le nubi. E **nessun latch poteva scattare**: la stella non
  era *persa* (SNR 22, ancora tracciata), quindi STAR_LOST non si è armato. Non esisteva un percorso rapido per
  il *degrado*, solo per la *perdita*.

**Perché è sicuro in quella direzione**: (a) costi — dichiarare unsafe presto costa una pausa, tardi costa pose
rovinate; (b) fisica — una stella può testimoniare che il cielo è brutto (le nubi sono grandi: se coprono lei
coprono il campo), non che è tornato buono.

**Implementazione.** Agente: seconda polarità nel `RecoveryHintTracker` (stessa classe perché **condivide
`snr_ref`** — due copie dell'EMA divergerebbero e il riferimento È il metro di entrambe), gated sul complemento
esatto del hint (attiva a N1 CLEAR, rientra appena N1 riconosce). Asimmetrie deliberate: soglia 50% contro
l'80% del recupero, sostegno 90 s contro 60 s. Fail-inert senza riferimento credibile. Plugin: `SkyDegrading`
nello snapshot; nel percorso CLOUD **forza l'accumulo e blocca il drain**, mai il contrario; il gate di
freschezza è stato allentato perché **la SNR di guida arriva da PHD2, non da NINA** (test dedicato). Kill-switch
`SkyDegradingAccumulateEnabled`, fail-inert su Agenti <v2.14.

### 76-bis. La rana bollita, di nuovo — questa volta nel riferimento SNR

**Trovata scrivendo il replay della notte**: il test falliva con soglia `13.2` invece di `35`. Causa: `snr_ref`
era un'EMA **simmetrica**, aggiornata a ogni frame CLEAR — quindi durante il crollo il riferimento **colava giù
insieme al cielo** (70 → 26 in 4 minuti) e la soglia relativa con lui. Il degrado diventava **invisibile al
proprio stesso metro**. È esattamente il difetto del §66, identico, in un altro componente: lì il riferimento
era il conteggio stelle di N1, qui la SNR di guida.

Cura, la stessa: **cricchetto**. Il miglioramento si adotta subito ("le nubi non creano segnale"); verso il
basso si scende con **emivita lunga in tempo reale** (25 min, stessa costante del §66, regola 3). Con l'EMA
simmetrica il riferimento perdeva il 62% in 4 minuti; ora meno del 6%. Un primo tentativo — congelare durante
l'accumulo — **non bastava**, ed è documentato nel codice: il congelamento partiva troppo tardi, perché la
soglia scendeva più in fretta di quanto il segnale riuscisse a raggiungerla.

**Il difetto colpiva ANCHE l'hint di recupero (§57), nel verso opposto**: un riferimento eroso rende il
recupero troppo facile da dichiarare, quindi anticipa sonde su cielo ancora cattivo. Questa correzione risana
entrambe le polarità — ed è un bug fix indipendente dal §76.

## 77. "Condizioni del Cielo": far vedere il monitor mentre pensa — dashboard

Richiesta di Alessandro, esplicitamente **senza toccare la logica**: il riquadro "Condizioni" diventa
"Condizioni del Cielo" e ospita una riga che racconta cosa sta facendo il monitor, unendo le due voci — il
sensore veloce e quello lento. Sei situazioni, una sola alla volta, con la precedenza al fatto più urgente:
peggioramento in corso ☁️ / cielo coperto ☁️ / recupero visto dalla guida ma non ancora confermato 🌤️ / sonda
in corso 🔍 / recupero confermato ✅ / cielo limpido ☀️. I testi dicono sempre *chi* ha visto *cosa* — es. *"Il
canale di guida vede un miglioramento (SNR 52 su 70 di riferimento). Attendo la conferma della posa di verifica:
una stella sola non basta a dire che il campo è tornato buono."* Nessuna decisione, nessuno stato inventato: si
raccontano solo dati già presenti su `/status`.

**Test: 383 agente** (+11 `test_sky_degradation.py`: replay del 4/8, nessun falso positivo su transitori,
fail-inert senza riferimento, cricchetto, e i confini con §57/§55) **e 68 plugin** (+5: accumula a indice ancora
CLEAR, **mai drena**, kill-switch, funziona senza telemetria di trasparenza, fail-inert su agenti vecchi).
Build 0/0, audit 105/105 con 0 residui. Verifica live: `/status.recovery_hint` espone il blocco degrado, la
pagina servita contiene il pannello. ZIP **v2.14.0**, DLL **1.11.0.0** installata (hash-match). NO commit.

### 77-bis. Il racconto in due righe, e il "Recovery Manager" come modello mentale — v2.14.1

**Da una revisione esterna (GPT, relayed da Alessandro).** Due osservazioni, una già soddisfatta e una giusta.

**Già soddisfatta:** "Code parla di Hint / Probe / N1, l'utente no". Vero come principio, ma le stringhe
spedite nel §77 non contengono nessun nome interno — dicevano già *"il canale di guida vede un
miglioramento"*, *"verifico il campo di ripresa"*, *"recupero confermato dalla posa di verifica"*. Un
controllo automatico lo verifica adesso: zero occorrenze di hint/probe/N1/latch nelle stringhe visibili.

**Giusta, e recepita:** le mie frasi erano TROPPO LUNGHE. Gli esempi della revisione avevano una struttura
migliore — **cosa vedo / cosa sto facendo**, due righe brevi. Alle due di notte conta. Ora:

    ☁️  Il cielo sta peggiorando rapidamente.
        Sto accumulando evidenze senza aspettare la prossima posa.

    🌤️  Vedo un recupero stabile del cielo.
        Attendo la conferma dalla posa di verifica.

    🔍  Cielo coperto.
        Verifico periodicamente il campo di ripresa.

    ✅  Recupero confermato.
        Completo le verifiche, poi la sequenza riprende.

Prima riga in evidenza, seconda in sottotono; **i numeri (SNR, secondi, riferimento) sono migrati nel
tooltip** — chi vuole il dettaglio lo trova, chi passa davanti allo schermo legge due righe. Voce in prima
persona: il racconto è del recupero nel suo insieme, non di un componente.

**Sul "Recovery Manager" proposto dalla revisione** (Hint → Recovery Manager → accumulo/sonda → N1 → monitor):
come **modello mentale è corretto e utile**, e lo adotto nel linguaggio della documentazione e nella voce
della dashboard — che è appunto la voce del recupero, non di un sottosistema. Ma **non creo il componente**:
oggi il recupero è deliberatamente distribuito (il tracker misura nell'agente, il gate e il loop vivono nel
sequencer di NINA, i latch nel monitor) e accorparlo in un oggetto significherebbe spostare codice fra due
processi senza alcun beneficio funzionale, con rischio reale. È la stessa disciplina del §73 applicata
all'architettura: non si inventa una struttura che non esiste solo perché il diagramma è più bello.

**383 test verdi** (invariati: il pannello è presentazione), controllo id orfani + controllo nomi interni,
ZIP **v2.14.1**. Plugin invariato (1.11.0.0). NO commit.

---

## 95. La Base dell'esposizione si dichiara, non si eredita — agente v2.17.0 (2026-08-18)

**La domanda.** «Perche' la sessione del 17-18 agosto e' partita con Base 4000 ms? Non ricostruire la
teoria: dimmi dai log la sequenza reale degli eventi e quale variabile determina ciascun valore.»

**La sequenza, riga per riga.**

    16/08 03:04  la stella di guida collassa. SNR 6.1 < snr_low 8.0 -> Path A alza 2000 -> 4000 ms.
                 Un salto solo: la formula era `base * 2`, e con tetto 4000 il primo gradino
                 era anche l'ultimo.
    16/08 03:0x  la sessione si interrompe di colpo. Quattro tentativi di ripristino trovano
                 PHD2 gia' chiuso. I 4000 ms restano scritti nel profilo.
    17/08 22:51  nuova sessione. La baseline orfana viene trovata ma scartata: "vecchia di 48.2
                 ore - skip restore". Poi `controller.py:368` fa `base = client.get_exposure()`
                 e adotta i 4000 ms residui come riferimento della notte.
    17-18/08     quattro ore, ZERO interventi sull'esposizione. Non per prudenza: con base 4000
                 e tetto 4000 il controller non poteva salire (era al tetto) ne' scendere
                 (il pavimento della discesa E' la base). Paralizzato in entrambe le direzioni.

**Il difetto non e' "4 secondi".** E' che nessuno aveva scelto 4 secondi, e che una volta li' il
controller non aveva piu' gradi di liberta'. Il boiling frog per la sesta volta: un riferimento che
assorbe uno stato di emergenza e lo promuove a normalita' (dopo il riferimento N1 §66, snr_ref §76-bis,
jitter_ref, baseline RMS).

**Cio' che NON e' stato deciso.** Il confronto 4 s contro 2/2.5 s **resta aperto**. Il test manuale del
17-18 non isola nulla: venti minuti, condizioni in caduta, e nel confronto precedente i 2982 frame a
4000 ms erano quasi tutti a inizio notte (N1 1.00, airmass 1.00) contro 356 frame a 2500 ms tutti a fine
notte (N1 0.76-0.82, airmass 1.31-1.34). Non c'e' una sola regola in questo intervento che penalizzi le
pose lunghe: 4000 ms resta pienamente raggiungibile, in due gradini invece che con un salto.

**Tre vettori di ereditarieta', tutti chiusi.**

1. `initialize()` leggeva PHD2 a ogni re-init — e la notte del 17 i re-init sono stati 11. Ora la Base
   e' `target_exposure_ms` (2000, dichiarato in config) e a `full=True` PHD2 viene **riportato** li'.
   Al ri-aggancio la Base **non si rinegozia**: prende atto del gradino corrente e basta.
2. `restore_baseline()` riscriveva la base salvata su file — che il 16/8 valeva 4000 proprio perche'
   ereditata. Con un target dichiarato, comanda il target.
3. `target_exposure_ms = 0` (o riga assente) mantiene **esattamente** il comportamento storico, per chi
   non vuole che l'Agente tocchi l'esposizione.

**Path A sale e scende a gradini**, come Path B faceva gia'. E qui i test hanno trovato un difetto che il
ragionamento a mente non vedeva: `cur * 1.5` in salita e `cur / 1.5` in discesa **non percorrono la stessa
strada**, perche' in mezzo c'e' lo snap ai valori validi di PHD2. Da base 2000 la salita atterra su 3000
(esatto), ma la discesa da 4000 da' 2666, che snappa su 2500 — un ciclo su-e-giu' non tornava al punto di
partenza. Correzione: `_exposure_ladder()` costruisce la scala **una volta sola** dalla base al tetto, e
salita e discesa si muovono di un gradino su quella stessa scala. 2000 -> 3000 -> 4000 e ritorno.
`snr_step_cooldown_s = 45` fra un gradino e l'altro: piu' corto dei 90 s di Path B perche' con la SNR che
crolla la stella si perde in fretta, ma non zero perche' il cambio di posa azzera analyzer e motore
diagnostico e il gradino dopo va deciso su dati nuovi.

**La diagnostica che sarebbe bastata.** `/status` espone ora `target_ms` (il riferimento dichiarato) e
`phd2_ms` (cosa fa la camera **davvero**), e la dashboard mostra "PHD2 reale" in arancio quando diverge
dal valore interno. La notte del 17 l'Agente ragionava su una base che nessuno aveva scelto e dalla
dashboard non c'era modo di accorgersene: una riga sarebbe bastata a chiudere la domanda in dieci secondi.

**Perche' 2 s come partenza.** A 2 s il periodo della vite (348 s sulla CEM70) e' campionato 174 volte —
abbondante. Il margine di SNR resta ampio anche nella notte peggiore (6.1 era il **collasso**, non la
norma). E a 1624 mm la posa piu' lunga media il seeing invece di inseguirlo. 1 s resta configurabile ma
non e' la partenza predefinita.

**Deliberatamente NON toccato:** la normalizzazione del jitter grezzo. La correlazione +0.35 fra jitter
grezzo e FWHM nella notte con jet stream a 32 m/s e' un risultato interessante e va **studiato prima** di
cambiare il metro — stessa disciplina del §94: prima si misura in ombra, poi si decide.

**412 test verdi** (+16: eredita' da PHD2, dal file di baseline, ri-aggancio, snap del target, tetto,
comando rifiutato, scala in salita e in discesa, cooldown, stato incoerente, scenario completo della
notte 17-18). ZIP **v2.17.0**. Plugin invariato (1.11.0.0).

---

## 96. La gerarchia visiva: prima il dato, poi l'interpretazione — agente v2.17.0 (2026-08-20)

**Richiesta di Alessandro**, con uno screenshot della v2.6 come riferimento: entrando in dashboard l'ordine di
lettura deve essere *"Come sta guidando? -> Quali sono le condizioni? -> Qual e' lo stato adattivo? -> solo dopo
la diagnostica"*. Oggi la striscia del Livello 1 (§81) sta **sopra** i valori RMS, quindi la prima cosa che si
legge e' l'interpretazione invece della misura.

**Cosa NON e' stato fatto, ed e' la parte importante.** Lo screenshot di riferimento e' della v2.6 e non ha il
Livello 1 perche' allora non esisteva: prendere "questa impaginazione" alla lettera avrebbe significato buttare
via §81 e §82. Ho chiesto prima di toccare qualcosa, e la risposta e' stata netta — *"il Livello 1 ha una
funzione informativa e diagnostica diversa dalla riga RMS, quindi non voglio eliminarlo"*. **Ricollocazione,
non rimozione:** i cinque slot restano cinque, nello stesso ordine, con gli stessi tooltip. Cambia il posto,
non la funzione.

Nuovo ordine: RMS + Condizioni del Cielo -> Livello 1 -> Livello 2 (solo in deviazione) -> informazioni
operative -> diagnostica approfondita -> log.

**Secondo difetto, trovato leggendo il CSS mentre cercavo dipendenze di posizione.** `.gauges-row` dichiara
**quattro** colonne (`1fr 1fr 1fr 1.2fr`) ma l'HTML ci infilava **sei** card: RMS x3, Condizioni, Trasparenza
NINA e Recovery. Con NINA collegato le ultime due andavano a capo su una seconda riga spaiata — larghe un
quarto, con due buchi accanto. Non era un difetto teorico: misurato nel browser, la card Trasparenza da sola
occupava **279 px**, esattamente la larghezza di un riquadro RMS. Le due card sono andate dove la gerarchia di
Alessandro le colloca — fra le informazioni operative — in una riga `auto-fit` che si adatta: **1219 px** (tutta
la larghezza) quando e' sola, meta' ciascuna quando sono due.

La riga operativa **sparisce del tutto** quando nessuna delle due ha qualcosa da dire. Serve codice, non solo
CSS: `main-grid` e' un flex con `gap: 20px`, e una sezione vuota lascia comunque un buco verticale di 40 px.
`syncOpsRow()` la nasconde esplicitamente; sta nel ciclo di aggiornamento e non in coda alle due funzioni,
perche' entrambe hanno un `return` anticipato proprio nel caso in cui non c'e' niente da mostrare.

**Sui tooltip avevo sbagliato bersaglio, e la correzione e' nel §97.** In prima battuta ne avevo aggiunti sei,
scegliendoli fra i controlli *azionabili* scoperti: i due "Pulisci", il comando OFF, l'intestazione dei pannelli,
lo spillo e "PHD2 reale". Il criterio era "cio' che e' cliccabile e non si spiega". Alessandro ne ha imposto uno
migliore — *"il tooltip deve fornire il secondo livello di informazione quando un indicatore non e'
autoesplicativo"* — e con quel metro quattro dei sei erano rumore: chevron, spillo e i due Pulisci si capiscono
da soli. Sono stati rimossi nel §97. **Sopravvivono solo i due che rispondono a una domanda vera:** il comando
**OFF** (perche' la parola compare due volte nella stessa card con due significati) e **PHD2 reale** (§95), che
aveva tooltip solo in caso di disallineamento e a notte normale restava muto.

**Nessuna modifica all'architettura del motore.** AI Finder resta rimosso (§75: scavalcava il backoff §17, e
`test_star_lost_recovery.py:45` fallisce se l'interruttore torna); Modalita' Test resta fuori dalla testata
(§73), configurabile da TOML e visibile nel badge; `star_finder.py` resta al suo posto per il Path B.

**Verifica nel browser sulla pagina viva**, non solo sul sorgente: ordine renderizzato delle sette sezioni,
comparsa e scomparsa della riga operativa, larghezze misurate nei tre casi (due card / una sola / nessuna),
console senza errori JS. **412 test verdi** (invariati: la dashboard e' presentazione). ZIP **v2.17.0**
ricostruito e verificato dall'interno. Plugin invariato (1.11.0.0). NO commit.

---

## 97. La seconda profondita': non piu' informazioni a video, piu' significato — agente v2.17.0 (2026-08-20)

**Il criterio, dettato da Alessandro** dopo che nel §96 avevo scelto i tooltip col metro sbagliato: *"la dashboard
deve rimanere immediatamente leggibile a colpo d'occhio; il tooltip deve fornire il secondo livello di
informazione quando un indicatore non e' autoesplicativo"*. Non su ogni elemento cliccabile — sui **segnalatori
funzionali** che si vedono ma non si capiscono senza conoscere l'architettura dell'Agente. Le tre domande a cui
il testo deve rispondere, in quest'ordine: *che cos'e' -> a cosa serve -> che ruolo ha nelle decisioni*.

**Il metodo, e conta piu' del risultato.** Prima di scrivere una riga ho prodotto l'inventario completo di cio'
che gia' esisteva, distinguendo i tooltip statici nell'HTML da quelli assegnati a runtime in `app.js` — perche'
un `title` messo in pagina su un elemento che JS riscrive sarebbe stato silenziosamente inutile. Dall'inventario
sono uscite 23 proposte; Alessandro ne ha approvate 17, tagliando *Esposizione corrente*, `rms_high`/`rms_low`,
*Cap rms_high*, *Refresh* e i badge RA/DEC del cancello — questi ultimi perche' **la nota sotto la card li
spiega gia' a schermo**, e un tooltip che ripete e' rumore.

**Un testo e' cambiato per un controllo sul codice, non per stile.** Avevo scritto che "Steps sopra base" conta i
gradini di allungamento. Falso: `exposure_steps_above_base` viene toccato **solo dentro Path B** (righe 2351 e
2391). Se e' Path A ad alzare l'esposizione per segnale debole, quel contatore resta a zero. Il tooltip ora lo
dichiara — *"gli allungamenti decisi per segnale debole non entrano in questo conteggio"* — invece di far credere
che sia una vista completa. E' esattamente il tipo di bugia che un tooltip descrittivo produce quando lo si
scrive guardando l'etichetta invece del codice.

**Nessun numero nei testi.** Vincolo esplicito, e ha una ragione precisa: e' la lezione del §83, dove esistevano
tre copie della descrizione del monitor, ne erano state aggiornate due, e il difetto era emerso solo da uno
screenshot. Tutti i tooltip dicono "sopra questo valore", "il limite", "il massimo consentito": una ritaratura
della configurazione non puo' renderli bugiardi.

**Dove sono finiti.** Sulla **riga** (`param-row`, `mini-stat`), non sul solo numero: si legge passando
sull'etichetta, che e' il bersaglio naturale, ed e' la pratica gia' adottata dalle mini-stat di Recovery e
Trasparenza. Due eccezioni obbligate: il badge della fonte pixel scale (TOML/PHD2) e il chip **GATE CHIUSO**, che
**non esiste nell'HTML** — lo genera `setupDynamicPanels` (§74), quindi ha richiesto un campo `chipTip` nella
specifica del pannello.

Riepilogo: **17 aggiunti** (Condizioni del Cielo con la provenienza dei dati — PHD2 per la guida, NINA quando la
sua telemetria c'e' — piu' SNR/HFD/Spike; badge esposizione, Steps, Cooldown; Path B e il chip del cancello;
pixel scale, fonte, baseline RMS e progresso; i quattro di Adaptive MinMove), **4 rimossi** (i banali del §96),
**due conservati** (OFF e PHD2 reale), **nessun tooltip preesistente toccato**.

**Verifica sul DOM vivo, non sul sorgente.** Un aggiornamento di stato simulato completo, poi la risoluzione del
`title` **effettivo** risalendo gli antenati per ogni bersaglio — cosi' si prova che JS non li sovrascrive a
runtime: 17/17 presenti, "Base" e "PHD2 reale" ancora funzionanti, e le esclusioni davvero senza tooltip
(RA/DEC del cancello, i due Pulisci, l'intestazione dei pannelli). Zero errori JS in console, zero testi
duplicati. **412 test verdi**, ZIP **v2.17.0** ricostruito e verificato dall'interno. Plugin invariato (1.11.0.0).

---

## 98. Una sola scala, esplicita, per tutti e due i Path — agente v2.17.0 (2026-08-21)

**Come e' venuto fuori.** Alessandro chiede una verifica prima di chiudere il changelog: *"qual e' il valore di
partenza a ogni nuova sessione? la progressione e' davvero 2->3->4? la discesa arriva a 1 s o si ferma a 2?"*
Cinque domande secche, con la richiesta di mostrare le righe che determinano scala e valore iniziale.

**La verifica ha trovato un difetto che avevo lasciato aperto io nel §95.** La scala (`_exposure_ladder`) era
stata data **solo a Path A**. Path B era rimasto sulla formula moltiplicativa (righe 2333 e 2377), e `x1.5` /
`:1.5` **non sono simmetriche** una volta passate dallo snap ai tempi che PHD2 accetta: salita 2000 -> 3000, ma
discesa 4000 -> 2666 -> **2500**, un valore che sulla scala non esiste. Due percorsi diversi sullo stesso
parametro. Peggio: la mia nota §95 diceva *"Path A sale e scende a gradini come Path B faceva gia'"* — mezza
verita', perche' Path B era progressivo ma non simmetrico. Un'imprecisione che nessun test copriva.

Seconda cosa emersa dalla verifica: da base 1000 la scala moltiplicativa produceva **1 -> 1,5 -> 2 -> 3 -> 4**.
Il gradino a 1,5 s non e' un errore, e' aritmetica: un moltiplicatore non puo' dare passi additivi. Se si vuole
esattamente 1->2->3->4, il moltiplicatore va abbandonato.

**Le quattro regole decise da Alessandro**, dopo che gli ho presentato le decisioni aperte:

1. `max_steps_above_base = 2` resta **solo su Path B**. Con base 1 s Path B arriva a 3 s, con base 2 s a 4 s;
   Path A raggiunge il tetto da entrambe. L'asimmetria e' voluta: **Path A e' emergenza** (non perdere la
   stella), **Path B e' ottimizzazione speculativa**, ed e' giusto che il secondo sia piu' prudente.
2. La Base e' ammessa **solo sui due gradini piu' bassi** della scala. Niente valori intermedi trasformati in
   silenzio in una base diversa da quella scritta.
3. Scala **esplicita** in configurazione, comune ai due Path, in salita e in discesa.
4. Un gradino che PHD2 non offre **ferma** la progressione, non viene saltato.

La regola 4 e' quella che conta di piu' e non era ovvia: se la scala si limitasse a intersecare i tempi validi,
una camera senza i 3 s produrrebbe `[2000, 4000]` e **il salto 2 -> 4 rientrerebbe dalla finestra** — esattamente
il difetto che il §95 e questo §98 esistono per impedire. Meglio non salire che saltare.

**Verifica prima del codice.** Ho simulato le quattro regole in isolamento prima di toccare il controller, e le
sequenze richieste escono esatte: `1->2->3->4->3->2->1` da base 1 s, `2->3->4->3->2` da base 2 s. Poi ho
controllato la compatibilita' con cooldown (invariato: 2,2 min al tetto per Path A da 1 s), tetto (taglia la
scala), e i tre punti che assegnano la base — sono esattamente tre, tutti gia' coperti dal §95.

**Una previsione sbagliata, e vale la pena registrarla.** Avevo stimato che un test si sarebbe rotto
(`test_target_non_valido_viene_snappato`, che si aspetta 2600 -> 2500). Non e' successo: **la validazione vive
nel loader**, e quel test costruisce la configurazione a mano, aggirandolo. Il che ha rivelato una conseguenza
vera — una base fuori scala fa ricadere `_exposure_ladder()` sul vecchio comportamento moltiplicativo, **in
silenzio**, riportando i valori intermedi (2500 -> 3500). Il loader lo impedisce in pratica, ma una degradazione
silenziosa non si lascia in piedi: ora c'e' un WARNING all'avvio, accanto a quello del §95 sulla base che
coincide col tetto. Stesso principio: **una condizione che paralizza o degrada il controller deve dirlo, perche'
"nessuna azione" e' anche il comportamento di una notte tranquilla.**

**Coda del §98 — il test riallineato e l'audit dei tooltip.** `test_target_non_valido_viene_snappato`
documentava lo snap di 2600 -> 2500: non e' piu' la regola, e 2500 era per giunta proprio uno dei valori
intermedi che la scala elimina. Passava solo perche' costruiva la configurazione a mano, aggirando il loader.
Sostituito da `test_una_base_non_ammessa_viene_rifiutata_senza_degradare`, che segue la catena vera — TOML,
loader, controller, scala — e verifica le due cose che contano: che il rifiuto sia **esplicito** (ERROR nel log)
e che a valle **non resti nessuna degradazione silenziosa**, cioe' che nella scala non ricompaiano 2500 o 3500.

**Audit dei tooltip alla luce della nuova scala: nessuno e' diventato fuorviante, nessuno e' stato toccato.**
Verificati uno per uno Base, NOMINAL, Steps sopra base e PHD2 reale, piu' SNR, Cooldown e Path B. Il motivo per
cui reggono e' la regola che il §97 si era imposto: **parlare della funzione e mai del meccanismo, senza numeri
hard-coded**. Qui il meccanismo e' stato sostituito da cima a fondo — da moltiplicatore a scala esplicita — e
non una riga di testo ha dovuto cambiare. Gli unici numeri che compaiono nei tooltip dell'esposizione (`Base`,
`PHD2 reale`) sono interpolati dallo stato vivo, quindi non possono invecchiare.

**426 test verdi** (+14: scala esplicita dalle due basi, nessun valore intermedio, tetto che accorcia, gradino
mancante che ferma da entrambe le basi, le due sequenze complete di Path A, pavimento alla base, andata/ritorno
simmetrici di Path B come regressione sul 2500, limite di gradini solo su Path B, e le tre prove sulla base
ammessa). ZIP **v2.17.0** ricostruito e verificato dall'interno. Plugin invariato (1.11.0.0). NO commit.

---

## 99. Due misure diverse dello stesso errore — agente v2.17.0 (2026-08-22)

**Osservazione di Alessandro:** *"l'RMS che indica l'Agente spesso e' diverso da quello di PHD2, non capisco"*.
Screenshot a confronto: PHD2 0,62 / 0,43 / 0,75 arcsec, Agente 0,558 / 0,418 / 0,697. Vicini, ma non uguali.

**Le due formule, dal sorgente.** PHD2 non calcola un RMS: calcola una **deviazione standard**.

    PHD2    graph.cpp:986        m_stats.rms_ra = m_noDitherRA.GetPopulationSigma()
            guiding_stats.cpp:451  variance = (n*sumYSq - sumY^2)/n^2 = E[Y^2] - E[Y]^2
            finestra = selettore x della Storia (50/100/200/400)

    Agente  analyzer.py:344      _rms(vals) = sqrt(sum(v^2)/n)      <- attorno allo ZERO
            window_frames = 30

Entrambi partono dallo **stesso campo grezzo** (`RADistanceRaw`); l'Agente lo converte in arcosecondi con la
pixel scale che **legge da PHD2** (`use_phd2_pixel_scale = true`). La conversione non c'entra.

**Il risultato ribalta l'ipotesi di partenza.** Su 3796 frame reali della notte 17-18/8, scorrendo tutta la
sessione: PHD2 mediana **1,161"**, Agente mediana **1,164"**. Bias sistematico **+0,002"** — praticamente zero.
Non e' vero che l'Agente mostri "un numero piu' bello". I due effetti si compensano quasi esattamente:

| contributo | effetto |
|---|---|
| finestra 200 -> 30 (a formula uguale) | −0,057" |
| formula sigma -> rms (a finestra uguale) | +0,059" |
| **netto** | **+0,002"** |

Cio' che si vede non e' bias ma **dispersione**: escursione 1,272" per l'Agente contro 0,554" per PHD2, scarto
istantaneo da −0,549" a +0,584", e i due coincidono entro 0,05" **solo il 20% del tempo**. Due screenshot presi
a pochi secondi di distanza cadono comodamente dentro quella banda.

**Perche' NON si deve far coincidere le due misure.** Sottraendo la media, sigma rende **invisibile la deriva**:
una guida costantemente sbilanciata sembra stretta. Sul log la |media| su 30 frame in RA e' mediana 0,213" con
punte a **1,043"** — non e' rumore trascurabile, ed e' proprio il segnale che un agente che diagnostica DRIFT non
puo' buttare via. **sigma e' la misura giusta per un display** (quanto e' stretta la guida), **RMS attorno a zero
e' quella giusta per un controllore** (quanto e' grande l'errore, deriva inclusa). In piu' `rms_high`, `rms_low` e
la baseline auto-calibrata sono tarate su questa metrica: cambiarla invaliderebbe soglie e baseline apprese.

**Sul nome: non rinominato, ed e' una scelta.** "RMS RA" e' corretto — semmai e' PHD2 a chiamare "RMS Error" una
deviazione standard. Un nome proprietario tipo "RMS operativo" aggiungerebbe gergo e violerebbe la regola del
§81 (i nomi indicano cose reali, non etichette sintetiche). Serviva spiegare la metrica, non ribattezzarla: tre
tooltip, uno per card, che rispondono alla domanda vera — *perche' non e' il numero di PHD2* — ciascuno
specifico al proprio asse e nessuno copia letterale di un altro.

**Un mio errore, corretto dai dati.** Avevo cercato "dither" in `analyzer.py` e `controller.py`, non l'avevo
trovato, e avevo concluso che l'Agente includa i dither mentre PHD2 li esclude — stimando un gonfiamento di
+0,081" mediano fino a +0,616". **Falso.** La gestione c'e', sta in `main.py` ed e' agganciata agli eventi
invece che alla parola:

    main.py:399   if is_settling:  continue    # "Ignoriamo i GuideStep durante il dithering (falsi errori)"
    main.py:580   SettleBegin  -> is_settling = True
    main.py:588   SettleDone   -> analyzer.reset() + diagnostic_engine.reset("dither")
    main.py:547   percorso di riserva su AppState=Guiding

L'Agente **non ingerisce affatto** quei frame e in piu' azzera la finestra: difesa piu' forte di quella di PHD2,
che li accumula e poi li rimuove. Verificato sui dati veri: su **220 decisioni applicate, UNA** cade entro 60 s
da un dither, la diagnosi nella scia e' `INSUFFICIENT_DATA` al **98,6%** (contro 19% nel resto), e nel CSV si
vede `frame_count` ripartire da 1 quindici secondi dopo il dither. **Lezione: cercare un concetto per nome e'
un test debole** — la funzione esisteva, si chiamava con le parole di PHD2.

**412+14 = 426 test verdi** (invariati: i tooltip sono presentazione). Verifica di non-sovrascrittura fatta sul
codice invece che sul browser, ed e' conclusiva: `app.js` **non contiene un solo riferimento** a `gauge-card`,
quindi quelle card non vengono mai riscritte a runtime. ZIP **v2.17.0**. Plugin invariato (1.11.0.0).

---

## 100. Si registra cio' che il motore gia' calcola — agente v2.17.0 (2026-08-22)

**Come e' nata.** Analizzando la notte ciclica del 21-22/8 ho dovuto ricostruire il riferimento di trasparenza
per via indiretta (`riferimento = stelle / indice`, identita' valida solo se il fattore di fondo cielo vale 1) e
stabilire l'influenza della Luna calcolando un'**effemeride** dalle coordinate dell'osservatore lette nel log
NINA. Due fatiche entrambe evitabili: il tracker **conosce gia'** il fondo cielo misurato e il proprio
riferimento, li usa a ogni posa per calcolare l'indice, e non li scriveva da nessuna parte.

Alessandro: *"il bkg e' assolutamente una svolta, lo farei implementare da subito"*. Concordo, e la ragione e'
che questa e' la modifica col miglior rapporto valore/rischio della serie: **non tocca una sola decisione**,
rende osservabile una variabile che il motore possiede.

**Cinque colonne** (schema 6 -> 7, 39 -> 44 campi), collocate nel gruppo §94 delle misure che nessuno legge:
`bkg`, `base_bkg`, `base_stars`, `base_stars_session_best`, `ref_drift_pct`.

`base_bkg` era una **variabile locale** dentro `ingest()`: senza di essa il log non sarebbe autosufficiente,
perche' `bkg_factor = base_bkg / bkg` e' il secondo fattore dell'indice e resterebbe ricavabile solo per
inversione — impossibile proprio quando l'indice satura a 1.00, cioe' nelle notti serene. Ora e' conservata ed
esposta in `status_block()`.

**La domanda che rendono rispondibile**, ed e' quella che separa la trasparenza da tutto il resto:

    stelle in calo + fondo cielo che SALE   -> diffusione, probabile velatura
    stelle in calo + fondo cielo COSTANTE   -> non e' trasparenza

Verificato end-to-end: con stelle 1400 -> 980 e fondo 120 -> 210 la riga riporta `base_stars 1400` (il
riferimento non ha inseguito), `bkg 210` contro `base_bkg 120`, indice 0.40, stato CLOUD. **La riga si
interpreta da sola**; prima da quello stesso CSV si poteva solo congetturare.

**Cosa NON e' stato fatto, ed e' deliberato.** Nessun correttore. Le tre notti analizzate hanno sgonfiato due
candidati su tre appena messi alla prova: l'**HFR** ha il segno che si ribalta fra i filtri (3 positivi, 4
negativi — una compensazione correggerebbe al contrario su O, H, R); la **Luna** e' risultata totalmente
confusa col ciclo (i campioni "Luna sopra l'orizzonte" coincidono con il ciclo 1 per **tutti** i filtri, senza
una sola eccezione) e il tempismo non torna comunque, perche' gli aumenti di S (+20%) e R (+14%) avvengono ore
dopo il tramonto lunare delle 00:20. L'**airmass** resta telemetria: sopra i 30 gradi l'effetto e' sotto il
rumore (R^2 fra 0.01 e 0.10 contro 0.68 dell'HFR), e sotto i 30 gradi **non abbiamo un solo campione** — il
massimo osservato e' X 1.56.

**Il vincolo, blindato da un test:** `test_il_controller_non_consuma_le_colonne_nuove` fallisce se
`base_bkg`, `ref_drift_pct` o `base_stars_session_best` compaiono nel controller. E' strumentazione, non
algoritmo — e deve restarlo finche' un replay sui dati reali non dice altro.

**433 test verdi** (+7: colonne nello schema, collocazione nel gruppo in ombra, `base_bkg` esposto, valori
scritti uguali a quelli del tracker, lo scenario velatura, colonne vuote senza NINA, e l'invariante di
non-consumo). ZIP **v2.17.0** ricostruito. Plugin invariato (1.11.0.0).

**Da questo commit la v2.17.0 e' la piattaforma di raccolta dati.** Il §100 va trattato come *baseline
sperimentale*: si e' reso il sistema osservabile senza cambiarne il comportamento, e quella proprieta' si
spreca se si continua a modificare il motore mentre si cerca di capire cosa dicono i dati. La sequenza
concordata e': **§100 -> raccolta notti -> replay -> progetto memoria -> replay -> progetto N8 -> replay ->
eventuale Guardian**. Le linee guida che fissano questo ordine stanno in `docs/development/LINEE_GUIDA_TRASPARENZA.md`.

---

## 101. Ogni riga dice a chi appartiene — agente v2.17.0 (2026-08-22)

**Trovato durante l'audit della telemetria del fuoco.** Il modello di trasparenza e' indicizzato per
`(target, filtro)` — e' la chiave di `_stars_by_filter`, `_ref_stars_by_filter`,
`_best_stars_by_filter`. Ma il CSV non registrava **nessuna delle due**: quarantaquattro colonne di misure
di cui non si sapeva a chi appartenessero.

Non e' un difetto teorico e ne ho pagato il prezzo di persona: per ricostruire la notte ciclica 21-22/8
(sequenza O H S R G B L, tre cicli) ho dovuto parsare il log di NINA e riallineare a mano i blocchi filtro
con il CSV dell'Agente. Il **replay del modello di memoria** — quello a cui le linee guida ci impegnano —
era **impossibile dal solo CSV**.

**Costo zero:** `status_block()` esponeva gia' `target` e `filter` (righe 334 e 342). Nessuna modifica al
plugin, nessuna nuova DLL: stessa forma del §100. Schema 7 -> 8, 44 -> 46 colonne, collocate in TESTA al
blocco NINA cosi' che si legga come *"questo target, con questo filtro, ha misurato questi valori"*.
Verificato prima che nessun consumatore leggesse il CSV per posizione: `replay_*.py` e `analyze_logs.py`
usano tutti `DictReader`.

**Una nota sull'invariante, perche' qui il test del §100 NON si applica.** Per il fondo cielo l'invariante
era "questi nomi non compaiono nel controller". Per `target` e `filter` sarebbe assurdo: sono concetti
interni legittimi, il tracker ci costruisce sopra le proprie chiavi. L'invariante vero e' un altro — sono
un **passaggio diretto** di cio' che il tracker dichiara, senza trasformazioni — ed e' quello verificato.
Registrarlo esplicitamente evita che qualcuno, un giorno, aggiunga un test difensivo che non difende nulla.

**Un dettaglio emerso dal banco di prova:** `star_count` arriva al CSV **dallo snapshot** (il controller lo
copia da `_nina_shadow_block()`, controller.py:1228), mentre `target`/`filter`/`bkg` li legge il logger
**direttamente** dal tracker. Due strade per la stessa sorgente. Non e' un difetto — entrambe finiscono in
`status_block()` — ma va saputo, perche' un banco di prova che aggira il controller vede `star_count` vuoto.

**439 test verdi** (+6: esistenza, collocazione prima delle misure che indicizzano, fedelta' al tracker,
colonne vuote senza NINA, ricostruzione della serie per filtro dal solo CSV su una sequenza ciclica a 7
filtri, e cambio target visibile nella riga). ZIP **v2.17.0** ricostruito.

**Stadio B, non ancora fatto:** `focuser_position` + `focuser_temperature` per ogni LIGHT. Verificato che
esistano nell'SDK **pinnato** 3.2.0.9001 (`FocuserParameter`, `get_Focuser`, `get_Position`,
`get_Temperature`, `get_MechanicalPosition`), ma comporta plugin + nuova DLL: rilascio separato, cosi' se
qualcosa non torna si sa dove cercare.

---

## 102. Lo stato del fuoco viaggia con la posa — agente v2.17.0 + plugin v1.13.0.0 (2026-08-22)

**Stadio B**, dopo il §101. La notte 21-22/8 ha mostrato che un autofocus puo' spostare `star_count` del
**21,8%** su un filtro: il conteggio stelle, da solo, non distingue *"il cielo e' cambiato"* da *"il fuoco e'
cambiato"*. Due colonne nuove — `focuser_position`, `focuser_temperature` — danno la seconda dimensione
causale accanto a `star_count`/`bkg`.

**Nessuna causa e' codificata, ed e' il punto architetturale.** Una variazione di posizione NON significa
"autofocus": puo' essere l'offset del filtro — e **non tutti gli utenti usano gli offset** — la compensazione
termica, un AF per HFR, per temperatura, per tempo, o un intervento manuale. Si registra il **fatto**; la
probabilita' della causa la stabilisce il replay. Un test lo blinda: due sequenze che rappresentano un cambio
filtro con offset e un autofocus producono **la stessa riga**, perche' distinguerli non e' compito del logger.

**Perche' la posizione e non un flag "AF avvenuto".** NINA notifica solo l'inizio
(`BroadcastAutoFocusRunStarting`: tre volte quella notte, zero notifiche di fine), quindi dedurre `AF_END`
sarebbe un problema aperto. La posizione arriva **attaccata al frame**, senza allineamenti temporali, e copre
*ogni* movimento invece dei soli eventi etichettati.

**Tre cose che il compilatore ha stabilito, non l'inferenza.**

1. `FocuserParameter.Position` e' `int?`, `Temperature` e' `double`.
2. **`MechanicalPosition` non esiste** su `FocuserParameter`. Avevo dedotto il contrario da una ricerca piatta
   di stringhe nella DLL — che trova `get_MechanicalPosition` ma **non puo' attribuirlo alla sua classe**. La
   domanda "aggiunge informazione?" si e' risolta alla radice, ed e' il modo migliore in cui poteva risolversi.
   Lezione: leggere l'heap delle stringhe di un assembly dice cosa c'e' *da qualche parte*, non *dove*.
3. Il difetto piu' insidioso: `AddIfNumber` pretende `value >= 0` e avrebbe scartato **in silenzio** le
   temperature sotto zero. A 967 m di quota sono la norma per buona parte dell'inverno — cioe' proprio quando
   la deriva termica del fuoco e' piu' interessante. Nuovo helper `AddIfFinite`, e un test dedicato a −4,2 °C.

**Un disallineamento trovato per strada.** La csproj dichiarava `<Version>1.7.0.0</Version>` mentre la DLL
spedita era la **1.12.4.0**: con `GenerateAssemblyInfo=false` quelle proprieta' sono **inerti** e la versione
vera sta in `Properties/AssemblyInfo.cs`. Allineate e documentate, perche' un metadato che mente e' peggio di
un metadato assente — ci ho perso tempo io prima di accorgermene.

**La riga, alla fine.** Prova end-to-end: stelle 1400 -> 1710, focheggiatore 35435 -> 35525, temperatura
11,4 -> 10,8 °C, ma `bkg` fermo a 120 = `base_bkg`. Il quadro e' **fortemente compatibile con una
rifocheggiatura riuscita** — il fondo cielo, che e' la misura diretta della trasparenza, non si e' mosso — ma
**compatibile non vuol dire dimostrato**: la riga porta l'evidenza, non la causa. Prima quella stessa riga era
indistinguibile da un miglioramento della trasparenza; ora le due ipotesi si possono separare.

**448 test verdi** (+9: colonne e collocazione, `mechanical_position` assente, valori dal tracker, temperatura
negativa, zero come valore valido, stessa riga per cause diverse, nessun consumo dal controller, colonne vuote
senza focheggiatore e senza tracker). Schema 8 -> 9, 46 -> 48 colonne. Plugin **1.13.0.0** costruito Release
x64 (0 errori, 0 avvisi), installato e **verificato per hash**. ZIP **v2.17.0** ricostruito.

**Il vincolo resta quello del §100:** nessuna di queste colonne entra nelle decisioni. Prima si misura, poi si
replaya, poi si decide.
