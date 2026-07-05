# 🔭 Adaptive Agent for PHD2

**Versione 2.7 — motore "Outcome-First"** · Licenza **BSD-3-Clause**

Un agente Python che si connette a **PHD2** via TCP/IP (JSON-RPC 2.0) per monitorare la guida in tempo reale e applicare correzioni adattive ai parametri algoritmici — senza toccare il mouse. L'agente regola `Aggressiveness` e `MinMove` **solo quando l'esito misurato lo giustifica**, con kill-switch su ogni intervento e ripristino garantito dei parametri utente a fine sessione.

## 📚 Documentazione

**Documenti ufficiali (root):**
- **[`ARCHITETTURA_MOTORE.md`](ARCHITETTURA_MOTORE.md)** — *com'è fatto*: architettura del motore Outcome-First — baseline RMS bidirezionale (§44), INIT ai valori standard PHD2 (§50), cap MinMove adattivo (§51), recupero simmetrico guidato dall'esito (§53) — e del filone NINA (N1 trasparenza, N8 fusione confidence, N6 sicurezza).
- **[`STUDIO_PHD2_DESIGN.md`](STUDIO_PHD2_DESIGN.md)** — *perché quelle scelte*: studio del design di PHD2 e delle sue leve, che motiva ogni decisione del motore.
- **[`CHANGELOG.md`](CHANGELOG.md)** — sintesi delle milestone e delle versioni.
- **[`CONTRIBUTING.md`](CONTRIBUTING.md)** — come provare l'agente sul campo e riportare i risultati.
- **[Manuale utente (PDF)](doc/Manuale_Utente_Agent.pdf)** — guida operativa passo-passo all'installazione e all'uso.

**Percorso di sviluppo completo — [`docs/development/`](docs/development/):** tracciabilità integrale dell'evoluzione del progetto. `NOTE_CLAUDE.md` (cronologia tecnica §-by-§), `CONTESTO_PROGETTO.md` (stato globale e roadmap), `VALIDAZIONE_CAMPO_v2.6.md`, i prompt di implementazione e le note di design. Mantenuti pubblici per trasparenza, fuori dalla root per leggibilità.

> **Config unico auto-configurante** (`config.toml`): la pixel scale di guida è letta da PHD2 e le soglie RMS derivano da una baseline misurata. La scelta del telescopio si fa selezionando il **profilo in PHD2**.

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
git clone https://github.com/Mamete91/AdaptiveAgentPHD2.git
cd AdaptiveAgentPHD2
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

Per chi usa NINA come suite di acquisizione esiste un plugin C# separato — **Adaptive Agent for PHD2 — Dashboard** — che aggiunge a NINA un pannello dockable contenente la dashboard stessa, caricata via WebView2 da `http://localhost:8080`. Il plugin è opzionale: il browser web resta sempre il modo "ufficiale" di accedere alla dashboard, ed è obbligatorio per chi vuole guardarla da tablet, secondo monitor o PC remoto sulla stessa rete. Il plugin è solo una comodità per gli utenti NINA che vogliono evitare di tenere un browser aperto. Sequenza di avvio consigliata: PHD2 → `Avvia.bat` → NINA (il pannello carica la dashboard automaticamente; se NINA era già aperto basta premere "Riprova" nel pannello). Dettagli architetturali in `docs/development/NOTE_CLAUDE.md §27`.

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

### Auto-configurazione (config unico)
Il progetto usa un **unico `config.toml` auto-configurante**: non servono configurazioni
per-setup. La pixel scale di guida è letta dal **profilo PHD2 attivo** e le soglie RMS sono
derivate da una **baseline misurata** sul campo. Per cambiare telescopio basta selezionare
un altro profilo in PHD2 — pixel scale e soglie si adattano da sole. I valori mostrati sopra
sono solo un esempio: in esercizio non vanno impostati a mano.

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
