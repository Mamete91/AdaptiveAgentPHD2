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
