# 🔭 PHD2 Adaptive Guiding Agent
 ⚠️ **Stato del documento**: questo README descrive il progetto a livello concettuale ed è ora allineato alla **versione 1.2**.
 
 Per lo stato aggiornato consultare:
 - **`CONTESTO_PROGETTO.md`** — stato globale e roadmap
 - **`NOTE_CLAUDE.md`** — cronologia tecnica dettagliata delle modifiche
 - **`doc/CONFRONTO_GA_AGENT.md`** — analisi vs Guiding Assistant PHD2
 - **`config.toml`** — **config unico** auto-configurante (dalla §22): la pixel scale di guida è letta da PHD2 e le
 soglie RMS sono derivate da una baseline misurata. La scelta del telescopio si fa selezionando il **profilo in PHD2**.
 I 3 vecchi TOML per-setup e i 6 `.bat` sono stati eliminati.

> Aggiornamento README completato il 2026-05-03. Ulteriori revisioni verranno fatte dopo le prossime sessioni reali se emergono nuovi comportamenti da documentare. 


Un agente Python che si connette a **PHD2** via TCP/IP (JSON-RPC 2.0) per monitorare la guida in tempo reale e applicare correzioni adattive ai parametri algoritmici — senza toccare il mouse.

---

## ✨ Funzionalità

| Funzione | Dettaglio |
|----------|-----------|
| **Monitor real-time** | Legge ogni `GuideStep` da PHD2 e calcola RMS RA/Dec, SNR, HFD, spike score, trend |
| **Pattern recognition** | Distingue seeing degradato, oscillazione (over-correzione), SNR basso |
| **Controllo adattivo** | Regola `Aggressiveness` e `MinMove` con guardrail di sicurezza |
| **DRY_RUN** | Modalità "solo log" per validare la logica prima di toccare PHD2 |
| **Dashboard web** | Grafico live, gauge RMS, log decisioni — apribile su `http://localhost:8080` |
| **CSV + JSONL log** | Ogni sessione viene salvata in `logs/` per analisi offline |
| **Simulatore** | Testa senza PHD2 reale con `--simulator` |
| **Baseline Guardian** | Salva i parametri PHD2 al startup e li ripristina al shutdown o crash (orphan recovery) |
| **MinMove dinamico** | Regola il MinMove in tempo reale insieme all'Aggressiveness, con cooldown 1.5x |
| **Saturation Timer** | Rileva stelle sature tracciate troppo a lungo e forza re-scan via find_star (dopo 300s default) |
| **Dithering aware** | Sospende valutazioni durante SettleBegin/SettleDone, reset statistiche al SettleDone |
| **find_star backoff** | Anti-loop sterile su crash camera: 3 tier (normale/slow/sospeso) con max 10 tentativi |
| **RMS implosion detector** | Rileva RMS che esplode 8x rispetto al riferimento EMA, sospende decisioni per 60s |
| **Soglie RMS adattive** | Clamp proporzionale alla pixel scale, rigetto baseline non rappresentative (§23) e refresh ciclico tightest-wins (§25) |
| **Plugin NINA opzionale** | Pannello dockable in NINA che incorpora la dashboard via WebView2 — l'utente non deve aprire il browser. Progetto separato (§27) |

---

## 🛠 Installazione

### Requisiti
- Python 3.11+ (usa `tomllib` stdlib)
- PHD2 2.6.x con **Tools → Enable Server** attivato

### Setup
```powershell
cd "PHD2 Assist"
python -m pip install -r requirements.txt
```

---

## 🚀 Avvio

### Avvio rapido da pacchetto compilato (consigliato)

Config unico, un solo file da lanciare:

1. Apri PHD2 e **seleziona il profilo del telescopio** in uso (la focale del profilo determina la pixel scale che
   l'agente legge da solo). Abilita il server (Strumenti → Abilita Server) e avvia la guida.
2. Doppio click su **`Avvia.bat`** nella cartella `Pacchetto_Distribuzione/`.
3. Apri la dashboard su `http://localhost:8080`: nella card "Auto-calibrazione" vedrai la pixel scale rilevata
   (badge **PHD2**) e il progresso della baseline.

Per cambiare telescopio basta selezionare un altro profilo in PHD2: pixel scale e soglie si adattano da sole.

#### Plugin NINA opzionale (alternativa al browser)

Per chi usa NINA come suite di acquisizione esiste un plugin C# separato — **Adaptive Agent for PHD2 — Dashboard** — che aggiunge a NINA un pannello dockable contenente la dashboard stessa, caricata via WebView2 da `http://localhost:8080`. Il plugin è opzionale: il browser web resta sempre il modo "ufficiale" di accedere alla dashboard, ed è obbligatorio per chi vuole guardarla da tablet, secondo monitor o PC remoto sulla stessa rete. Il plugin è solo una comodità per gli utenti NINA che vogliono evitare di tenere un browser aperto. Sequenza di avvio consigliata: PHD2 → `Avvia.bat` → NINA (il pannello carica la dashboard automaticamente; se NINA era già aperto basta premere "Riprova" nel pannello). Dettagli architetturali in `NOTE_CLAUDE.md §27`.

### Avvio da sorgente Python

#### 1. Solo monitoraggio (sicuro, zero controllo)
```powershell
python main.py --monitor-only
```

#### 2. Con simulatore PHD2 (nessun hardware necessario)
```powershell
python main.py --simulator --dry-run
```

#### 3. DRY_RUN con PHD2 reale (valida la logica, non tocca parametri)
```powershell
python main.py --dry-run
```

#### 4. Controllo live (config unico, `dry_run = false` già impostato)
```powershell
python main.py --config config.toml
```
> La scelta del telescopio avviene nel profilo PHD2, non nel config. I flag `--with-reducer`/`--no-reducer` restano
> per retrocompatibilità ma sono ininfluenti con l'auto-scala attiva.

### Dashboard
Apri il browser su: **http://localhost:8080**

---

## ⚙️ Configurazione (`config.toml`)

```toml
[control]
dry_run = true           # ← SEMPRE true finché non hai validato i log!
interval_seconds = 10    # Frequenza valutazione controller
window_frames = 30       # Frame nella sliding window

[thresholds]
rms_high = 0.80          # arcsec — abbassa aggressività
rms_low  = 0.45          # arcsec — aumenta gradualmente

[limits.ra]
aggr_min = 40
aggr_max = 80
aggr_step_down = 5       # Passo di riduzione (conservativo)
aggr_step_up   = 2       # Passo di aumento (molto conservativo)
```

### Config reali per setup
Esistono 3 configurazioni per setup reali con valori specifici calibrati sulla scala focale:

| Setup | rms_high | rms_low | RA aggr_max | DEC aggr_max | minmove_max RA/DEC |
|-------|----------|---------|-------------|--------------|---------------------|
| Askar 71F | 1.30 | 0.70 | 85 | 80 | 0.80 / 0.85 |
| Tecnosky 115 | 1.00 | 0.55 | 80 | 75 | 0.80 / 0.85 |
| RC8 | 0.85 | 0.50 | 75 | 70 | 0.80 / 0.85 |

---

## 🧠 Logica di controllo

```
Condizioni → [Analyzer] → AnalysisSnapshot → [Controller] → set_algo_param()
```

Il controller usa una **macchina a stati** (NORMAL → DEGRADED → CRITICAL → RECOVERING) con queste regole:

| Condizione | Azione |
|-----------|--------|
| RMS > `rms_high` per N frame | Abbassa Aggressività di `step_down` |
| RMS > `rms_high * 1.5` (critico) | Abbassa con `step_down * 2` |
| Oscillazione rilevata (trend alternato) | Abbassa Aggressività RA e DEC |
| RMS < `rms_low` per M frame | Aumenta gradualmente Aggressività |
| Cooldown non scaduto | Nessuna azione (evita oscillazioni nel controllore) |
| Oscillazione DEC rilevata | Abbassa Aggressività DEC (in aggiunta a RA) |
| Stella satura > 300s | Forza find_star() per cercare stella non satura |
| RMS implosion (>8x reference) | Sospende decisioni per 60s |
| find_star fallisce >5 volte | Aumenta intervallo a 30s; >10 volte sospende |
| SettleBegin/SettleDone | Pausa valutazioni durante dithering |

**Guardrail di sicurezza:**
- Mai scendere sotto `aggr_min` o sopra `aggr_max`
- Cooldown minimo tra modifiche: 30s (configurabile)
- In DRY_RUN nessun comando viene mai inviato a PHD2
- Le decisioni vengono sospese durante dithering, RMS implosion, e crash camera
- I parametri vengono salvati come baseline e ripristinati a shutdown/crash

---

## 📊 Log e analisi

I log vengono salvati in `logs/`:
- `session_YYYYMMDD_HHMMSS.csv` — una riga per frame di guida
- `decisions_YYYYMMDD_HHMMSS.jsonl` — ogni decisione del controller
- `session_YYYYMMDD_HHMMSS.summary.json` — statistiche di sessione

---

## 🔌 Architettura

```
PHD2 Server (TCP :4400)
    ↕ JSON-RPC 2.0
PHD2Client (socket thread)
    ↓ event_queue
SaturationDetector (verifica saturazione)
    ↓
StatisticsAnalyzer (sliding window)
    ↓ AnalysisSnapshot
AdaptiveController (macchina a stati)
    ↓ BaselineGuardian (ripristino stato)
    ↓ set_algo_param()
SessionLogger (CSV + JSONL)
    ↓
FastAPI Server (:8080)
    ↕ WebSocket
Dashboard (Chart.js)
```

---

## ⚠️ Note importanti

1. **Non disattivare DRY_RUN** senza aver verificato almeno una sessione di log
2. **PPEC di PHD2** è già un ML integrato — l'agente agisce *sopra*, non *contro* di esso
3. I nomi dei parametri (`Aggressiveness`, ecc.) dipendono dall'algoritmo scelto in PHD2; l'agente li scopre automaticamente all'avvio con `get_algo_param_names`
4. Il cooldown di 30s evita che l'agente stesso crei oscillazioni nella regolazione
5. **Filosofia operativa**: il progetto è validato esclusivamente in sessioni reali di astrofotografia. La prima notte con un setup nuovo gira sempre in DRY_RUN per calibrare le soglie sui dati reali, prima di passare a LIVE.
