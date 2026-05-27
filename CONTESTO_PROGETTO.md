# CONTESTO PROGETTO PHD2 Adaptive Agent — Stato per nuovo agente AI

## Chi sono
Alessandro, astrofotografo italiano (Borno, BS, montagna). Setup multi-tubo:
- RC8 + ASI2600 + OAG ASI220 Mini (focale 1624mm, lunga focale)
- Tecnosky 115/800 + ASI2600 + OAG (focale 800mm, media)
- Askar 71F + ASI2600 + OAG (focale 490mm, corta)
- Montature: AM5 (focali corte) e CEM70G (focali lunghe + planetario)

## Cos'è questo progetto
PHD2_Adaptive_Agent: un agente Python che si connette al software di guida 
PHD2 (porta TCP 4400 JSON-RPC) e regola dinamicamente i parametri di guida 
in base a seeing, vento e altri eventi. Ha una dashboard web su porta 8080.

Architettura: Python 3.12, FastAPI/uvicorn per dashboard, numpy/scipy per 
analisi statistica + saturation detection. Compilato con PyInstaller in 
eseguibile Windows.

## Storia del progetto
1. Versione 1.0 sviluppata da un amico astrofilo con l'aiuto di Claude
2. Review tecnica della v1.0 ha identificato problemi:
   - Bug runtime: import os mancante in controller.py (crash in LIVE)
   - MinMove dinamico promesso in config ma mai applicato dal codice
   - Baseline Guardian dichiarato ma non implementato
   - Saturation Timer dichiarato ma non implementato
   - Oscillazione DEC ignorata (gestita solo RA)
3. Patch v1.1 applicate (questo pacchetto):
   - Fix bug os
   - MinMove dinamico vero (con cooldown 1.5x)
   - Baseline Guardian completo (save/restore/orphan recovery/shutdown)
   - Saturation detection con timer 300s e CSV log persistente
   - Mitigazione bias centroide su stelle sature
   - Oscillazione DEC ora gestita
   - 3 config separati per i miei setup
4. Patch validate: sintassi OK, test funzionali su FITS sintetici OK,
   test integrazione controller (init/baseline/shutdown/saturation) OK

## Stato attuale — aggiornato al 2026-05-27 (auto-configurazione + config unico §22)

### Ambiente installato sul PC Windows (fatto)
- Python 3.12.10 installato via winget
- Dipendenze pip installate: fastapi 0.136.1, uvicorn 0.46.0, numpy 2.4.4,
  scipy 1.17.1, websockets 16.0, pydantic 2.13.3 e relative dipendenze
- PyInstaller 6.20.0 installato

### Modifica a build_dist.py (fatto)
- build_dist.py è stato modificato per usare PHD2_Agent.spec per la build
  dell'agente principale (invece degli argomenti inline che mancavano scipy).
  Il .spec include già tutti gli hidden imports corretti per scipy e numpy.

### Build completata (fatto)
- Eseguita con: python build_dist.py
- Output generato in: Pacchetto_Distribuzione/
  - PHD2_Agent.exe (11.5 MB, più _internal/ ~100 MB di dipendenze)
  - Diagnostica_Connessione.exe (48.4 MB, onefile)
  - config.toml (default)
  - config_rc8.toml, config_tecnosky115.toml, config_askar71f.toml (copiati a mano)
  - dashboard/, phd2_log/, LEGGIMI_PER_AVVIARE.txt
- ZIP finale: PHD2_Agent_Distribuzione.zip (100.9 MB) — pronto per distribuzione

### Test simulatore (fatto)
- Eseguito python main.py --simulator --dry-run (2 run sequenziali)
- Verificato: nessun ModuleNotFoundError, connessione simulatore OK,
  controller inizializzato, Baseline Guardian salva baseline.json
- Verificato: orphan recovery funziona (run 2 rileva baseline orfana dal run 1)
- Il controller ha emesso decisioni DRY_RUN corrette:
  [TEST] RA Aggressiveness: 70.0 -> 72.0 (guida stabile, aumento graduale)

### Double initialize() — RISOLTO (2026-04-30)
Aggiunto `mark_uninitialized()` in `controller.py`. Handler `GuidingStopped`
chiama `controller.mark_uninitialized()`. Handler `StartGuiding` controlla
`if not controller.is_initialized()` prima di chiamare `initialize()`.

### Dithering/Settling — IMPLEMENTATO (2026-05-01)
Flag `is_settling` in `_event_loop`. Gestione eventi `SettleBegin`/`SettleDone`
(primario) e `AppState: Settling/Guiding` (backup). I GuideStep durante
il settling vengono scartati. `analyzer.reset()` alla fine del settling.

### BUG CRITICO SCALA aggression — TROVATO E RISOLTO IN CAMPO (2026-05-01)
PHD2 Hysteresis e Resist Switch espongono `aggression` in scala 0.0–1.0
(non 0–100 come tutti gli altri). Il controller leggeva 0.7, sommava
step_up=3, tentava di inviare 4 → RPC Error "could not set param".
Fix: `aggr_native_scale` in `AxisState`, conversione bidirezionale in
`_setup_axis` (lettura) e `_apply` (invio). Baseline v2 include la scala.
Vedere NOTE_CLAUDE.md sezione 13 per dettaglio completo.

### Sezione [phd2_log] e PHD2LogConfig — AGGIUNTO (2026-04-30)
Tutti i config_*.toml ora hanno [phd2_log]. `config.py` ha `PHD2LogConfig`
dataclass e relativo parsing in `load_config()`.

### Avvio rapido .bat — CREATI (2026-04-30)
`Avvia_Askar71F.bat`, `Avvia_Tecnosky115.bat`, `Avvia_RC8.bat` in
`Pacchetto_Distribuzione/`. Usare doppio click per avviare.

### Confronto GA-Agent + correzione pixel scale OAG (2026-05-01)
Prodotto `doc/CONFRONTO_GA_AGENT.md` (23 KB): analisi comparativa tra
PHD2 Guiding Assistant e l'agente adattivo, con formula SmartDefaultMinMove
verificata sul sorgente C++ PHD2. Identificati i sensori guida corretti:
- OAG Askar 71F: **ASI120MM Mini** (sensore AR0130CS, pixel 3.75 µm, 1280×960)
- OAG RC8 + Tecnosky 115: **ASI220MM Mini** (sensore SC2210, pixel 4.0 µm, 1920×1080)
Corretta pixel scale in `config_askar71f.toml`: era calcolata con 4.0 µm (sbagliato),
corretta a `1.58"/px` nativo, `1.97"/px` ridotto. Tabella SmartDefault ricalcolata
con pixel size corretti; SmartDefault RC8 nativo = 0.46 px (non 0.67 come con 2.33 µm).

### Estensione minmove_max (2026-05-01)
Tutti e tre i config (root + Pacchetto_Distribuzione) aggiornati:
- `[limits.ra]  minmove_max`: 0.55 → **0.80** (tutti i setup)
- `[limits.dec] minmove_max`: 0.55 → **0.85** (tutti i setup)
Motivazione: valore precedente troppo restrittivo; range esteso per consentire
al controller piena libertà di riduzione in condizioni di guida degradata.

### Filosofia operativa: solo sessioni reali (2026-05-01)
Decisione di non simulare artificialmente condizioni di guida (es. dati FITS
sintetici) per test di logica. Il test funzionale su simulatore è sufficiente
per verificare syntax/init. La validazione della logica adattiva avviene
esclusivamente su sessioni reali con cielo aperto, analizzando i log `decisions_*.jsonl`.

### Prima sessione LIVE Askar 71F (2026-05-01)
Prima sessione con `dry_run = false` e algoritmo Hysteresis RA / Resist Switch DEC.
Risultati guida nella fase stabile: RMS 0.11–0.20" RA, 0.13–0.43" DEC — ottimo
per la focale di 490 mm con AM5.

**Evento critico alle 00:12:45**: crash USB ASI120MM Mini. SDK ASI restituisce
`EXP_FAILED giving up` → PHD2 entra in StarLost loop → controller chiama
`find_star()` ogni ~10s senza backoff per ~6 minuti (130+ chiamate). I pochi
frame corrotti pervenuti mostravano RMS 17.86" RA / 12.17" DEC — fisicamente
impossibili alla scala di 1.58"/px — ma il controller li elaborava normalmente.
Sessione terminata manualmente.

### Mitigazione crash USB ASI120MM Mini (2026-05-01)
Due azioni intraprese:
1. **Hardware**: acquistato cavo Lindy Anthra Line USB-A/USB-C 0.5 m per
   sostituire il cavo USB problematico della camera guida.
2. **Architetturale**: PHD2 non espone via JSON-RPC alcun endpoint per reset/
   reinizializzazione camera. Il recovery automatico via software non è
   implementabile; la gestione si limita a stop/restart guiding.

### Soglie rms_low/rms_high da ricalibrare (dopo sessioni reali)
I valori attuali nei config sono stime a priori, non calibrati su seeing reale
di Borno. Dopo 2-3 sessioni con il profilo corretto applicare la formula:
- `rms_high = 1.5 × RMS_medio_tipico_della_notte`
- `rms_low  = 0.7 × RMS_medio_tipico_della_notte`
Leggere `mean_rms_total_arcsec` da `logs/session_*.summary.json`.

### Esposizione dinamica RMS-based — IMPLEMENTATA (2026-05-09)
Aggiunta sezione `[exposure_dynamic]` ai config con macchina a stati
`ExposureState` (NOMINAL / BOOSTED_FOR_SNR / BOOSTED_FOR_SEEING). Il path
RMS-based si attiva su DEGRADED_SEEING + spike + HFD + peak/rms ratio,
con esclusioni tassative di OSCILLATING e LOW_SNR (delegato al path A
preesistente). Cambio esposizione → `analyzer.reset()` obbligatorio.
Baseline Guardian aggiornato a v3 con persistenza dello stato esposizione.
`config_rc8.toml` ha `dry_run = false` e `enabled = true` per validazione LIVE
diretta sul grafico dashboard. (Dopo §21 anche gli altri due setup hanno
`dry_run = false` e `enabled = true`.)
Vedere NOTE_CLAUDE.md sezione 19 per dettaglio completo.

### Refactor [setup] e supporto Riduttore Focale — IMPLEMENTATO (2026-05-09)
Spostata `guide_pixel_scale_arcsec` da `[exposure_dynamic]` a una nuova sezione
`[setup]` estesa con campi `_native`, `_reduced` e flag `reducer_active`.
La pixel scale effettiva è esposta come property calcolata `cfg.setup.guide_pixel_scale_arcsec`,
letta da tutte le feature future (oggi dall'esposizione dinamica path B).

Corretti i valori di pixel scale ridotta per i tre setup:
- Askar 71F: 1.58"/px nativo, 2.11"/px ridotto (riduttore 0.75x)
- Tecnosky 115: 1.03"/px nativo, 1.29"/px ridotto (riduttore 0.80x)
- RC8: 0.51"/px nativo, 0.68"/px ridotto (riduttore 0.75x)

Aggiunti flag CLI `--with-reducer` e `--no-reducer` in `main.py` come override
del valore TOML. Creati 3 nuovi `.bat` (`Avvia_<setup>_Ridotto.bat`) per
attivare la modalità riduttore con doppio click, senza editing del TOML.
`config_rc8.toml` configurato per validazione LIVE: `dry_run = false`,
`[exposure_dynamic].enabled = true`.
Vedere NOTE_CLAUDE.md sezione 20 per dettaglio completo.

### Dashboard §21: Pannello Stato Esposizione & Escalation Gate — IMPLEMENTATO (2026-05-12)
Estesa la dashboard con un nuovo pannello `mid-row-2` tra il grafico e il log:
- **Exposure card**: badge stato (NOMINAL / BOOSTED_FOR_SNR / BOOSTED_FOR_SEEING),
  esposizione corrente / base in ms, steps sopra base, cooldown bar con countdown.
- **Escalation Gate card**: badge abilitato, status RA/DEC (SATURATE / OK),
  nota contestuale sul gate aperto/chiuso.
- **Chart.js 4th dataset**: scatter triangoli (giallo = UP, verde = DOWN) sovrapposti
  al grafico RMS per marcare ogni cambio esposizione in tempo reale.
- `get_status()` esteso: blocco `escalation_gate` (enabled + ra + dec bool) e
  `cooldown_residuo_s` / `cooldown_total_s` nell'exposure block.
- Tutti e 3 i config_*.toml ora: `dry_run = false`, `[exposure_dynamic].enabled = true`.
- `build_dist.py` aggiornato per copiare tutti i 6 `.bat` (inclusi `_Ridotto`).
Vedere NOTE_CLAUDE.md sezione 21 per dettaglio completo.

### FIX difensive find_star backoff + RMS implosion detector (2026-05-03)
Due fix implementati a seguito della prima sessione LIVE:

**FIX 1 — find_star backoff** (`controller.py`, `_evaluate_star_lost`):
Tre tier progressivi per fallimenti consecutivi di `find_star()` in LIVE:
- Normale (< 5 fallimenti): tentativo ogni `find_star_delay` secondi
- Slow (5–9 fallimenti): tentativo ogni 30 s
- Suspended (≥ 10 fallimenti): nessuna chiamata, log WARNING ogni 60 s con
  indicazione "verificare connessione USB camera"
I contatori si azzerano su successo o su `initialize()` (nuovo `StartGuiding`).

**FIX 2 — RMS implosion detector** (`analyzer.py`, `StatisticsAnalyzer._compute`):
Reference EMA del `rms_total` (α=0.1, aggiornata solo su frame validi: sotto
soglia E SNR ≥ snr_low). Se `rms_total ≥ 8 × reference`: log CRITICAL, analisi
sospesa per 60 s (`implosion_suspended=True`), condizione forzata a NOMINAL
(controller non agisce), contatori consecutivi non aggiornati (evita CRITICAL
spurio al ritorno). Reset di reference e sospensione in `reset()`.

### Auto-configurazione + config unico — IMPLEMENTATA (2026-05-27)
L'agente legge la pixel scale di guida da PHD2 (`get_pixel_scale`, fallback TOML) e deriva le soglie RMS da una
baseline misurata sul campo (config efficace in memoria, TOML mai riscritto). MinMove e aggressività restano
scale-independent. La configurazione è collassata in un solo `config.toml` + un solo `Avvia.bat`: valori unificati
(max_exposure 4000ms, snr_low 8.0, spike_min 0.25, hfd_min 4.0"); i 3 TOML per-setup e i 6 .bat sono stati eliminati.
La scelta del telescopio avviene selezionando il profilo in PHD2. Dettaglio in NOTE_CLAUDE.md §22.

## Cosa NON è stato ancora fatto

- Validazione LIVE dell'auto-configurazione: sessioni reali su almeno 2 profili PHD2 diversi (es. RC8 e Askar
  ridotto), verificando che pixel scale e soglie cambino da sole. Tarare poi rms_high_factor in base ai log.

- Test graceful shutdown (Ctrl+C interattivo) su PHD2 reale: verificare che
  all'uscita compaiano "Shutdown controller - restore baseline..." e
  "Baseline file rimosso (shutdown pulito)".

- Test Baseline Guardian con kill brutale + restart (Task Manager) su PHD2
  reale: verificare messaggio "Trovata baseline.json orfana" e restore.

- Test Saturation Timer (con saturation_timeout_s = 30 temporaneo).

- Sessioni DRY_RUN aggiuntive (Tecnosky 115 e RC8) per taratura soglie:
    rms_low  = 0.7 × RMS_medio_tipico
    rms_high = 1.5 × RMS_medio_tipico

- Seconda sessione LIVE Askar 71F con nuovo cavo Lindy: verificare assenza
  crash USB e validare comportamento FIX 1 / FIX 2 nei log.

- Passaggio a LIVE Tecnosky 115 e RC8 (dopo validazione Askar 71F completa).

- Validazione LIVE dell'esposizione dinamica RMS-based su tutti i setup:
  almeno 2 sessioni reali per setup. Ora tutti i config_*.toml hanno `dry_run = false`
  e `[exposure_dynamic].enabled = true`. Osservare sulla dashboard:
  - pannello "Esposizione Dinamica": cambio stato e countdown cooldown
  - pannello "Escalation Gate": quando RA/DEC mostrano SATURATE
  - triangoli gialli (UP) e verdi (DOWN) sul grafico RMS
  Tarare `spike_min`, `hfd_min_arcsec`, `cooldown_s` in base alla frequenza
  dei trigger osservata nei `decisions_*.jsonl`.

## Workflow operativo per il nuovo agente AI

Se riprendi da questa conversazione:
1. L'ambiente è già pronto (Python 3.12, pip, PyInstaller tutto installato)
2. Il pacchetto compilato è in Pacchetto_Distribuzione/ e come ZIP (101 MB)
3. I prossimi task sono sessioni LIVE su campo (tutti i config già LIVE)
4. NON modificare la logica del codice senza prima discutere con Alessandro
5. NON cambiare dry_run = false nei config senza esplicita autorizzazione
6. MAI toccare la backlash compensation di PHD2
7. OGNI modifica a un .py richiede rebuild + copia file extra (vedi sotto)

## Come avviare per setup specifico
```
Doppio click su Avvia_Askar71F.bat      (490mm, AM5)
Doppio click su Avvia_Tecnosky115.bat   (800mm, AM5/CEM70G)
Doppio click su Avvia_RC8.bat           (1624mm, CEM70G)
```
Oppure da PowerShell:
```powershell
cd Pacchetto_Distribuzione
.\PHD2_Agent.exe --config config_askar71f.toml
```

## Procedura post-modifica sorgente (IMPORTANTE)
build_dist.py ricrea Pacchetto_Distribuzione da zero — dopo ogni rebuild:
1. `python build_dist.py`
2. Copiare `config_rc8.toml`, `config_tecnosky115.toml`, `config_askar71f.toml`
3. Copiare `Avvia_*.bat` e `Sblocca_Firewall_8080.bat`
4. Ripristinare `LEGGIMI_PER_AVVIARE.txt` (build_dist.py lo sovrascrive con uno stub)
5. Ricreare ZIP con `[System.IO.Compression.ZipFile]::CreateFromDirectory(...)`

## Politica di sicurezza
- L'agente in LIVE può modificare parametri di guida del telescopio.
  Testare SEMPRE in DRY_RUN prima di passare a LIVE.
- Ordine consigliato per il passaggio a LIVE:
  Askar 71F → Tecnosky 115 → RC8 (dal più tollerante al più critico).
- Il config.toml di default ha dry_run = true, NON cambiarlo.
- Mai toccare la backlash compensation di PHD2.

## Riferimento tecnico
Il pacchetto è stato preparato in conversazione con Claude (Anthropic) sulla
chat web claude.ai. Quella conversazione contiene il dettaglio tecnico
completo delle patch. Se servono chiarimenti su scelte di design specifiche,
Alessandro può recuperarle da quella chat.
