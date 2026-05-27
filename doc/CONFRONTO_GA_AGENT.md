# Confronto: Guiding Assistant PHD2 vs AdaptiveController

**Data:** 2026-05-01  
**Basato su:** sorgente PHD2 `phd2-master/src/guiding_assistant.cpp`, `guide_algorithm.cpp`, `guiding_stats.h`; agente Python `phd2_agent/controller.py` + `analyzer.py`; config `config_rc8.toml`, `config_askar71f.toml`, `config_tecnosky115.toml`.

---

## 1. Guiding Assistant PHD2 — come funziona

### 1.1 Fase di osservazione e durata

Il GA opera in modalità **passiva**: disabilita completamente l'output di guida (`pMount->SetGuidingEnabled(false)`, riga 1668) e registra i movimenti stellari non corretti per un periodo scelto dall'utente.

- **Durata minima imposta:** `GA_MIN_SAMPLING_PERIOD = 120` secondi (2 minuti), costante hard-coded (riga 173).
- **Raccomandazione manuale:** Il testo nella UI suggerisce esplicitamente "almeno 2 minuti, di più se vuoi misurare l'accuratezza di tracking RA" (riga 719).
- **Finestra lunga:** se la sessione supera `1.2 × 120 = 144 secondi`, il GA usa sliding windows da 120s con overlap di 60s per minimizzare l'effetto del drift DEC (riga 1171-1219).
- **Campioni:** ogni GuideStep produce un campione; con esposizioni da 2s si raccolgono circa 60-80 campioni in 2 minuti.

Il GA esegue una callback `NotifyGuideStep()` ad ogni frame (riga 2021-2028), che chiama `UpdateInfo()`, accumulando statistiche in tempo reale.

### 1.2 Metriche raccolte

Tutte le metriche accumulate sono visibili nella struttura `GuidingAsstWin` (righe 235-252):

| Metrica | Struttura dati | Descrizione |
|---|---|---|
| **RA HPF-RMS** | `m_hpfRAStats` (DescriptiveStats) | RMS dei movimenti RA dopo High-Pass Filter |
| **Dec HPF-RMS** | `m_hpfDecStats` (DescriptiveStats) | RMS dei movimenti Dec dopo High-Pass Filter |
| **Total HPF-RMS** | calcolato come `hypot(rarms, decrms)` | RMS combinato (riga 1976) |
| **RA Peak** | `m_raAxisStats.GetMaxDelta()` | Massima variazione campione-campione in RA |
| **Dec Peak** | `m_decAxisStats.GetMaxDelta()` | Massima variazione campione-campione in Dec |
| **RA Peak-Peak** | `m_lpfRAStats.GetMaximum() - GetMinimum()` | Ampiezza totale del movimento RA low-passed |
| **RA Drift Rate** | `(ra_finale - ra_iniziale) / elapsed * 60.0` | Deriva RA totale in px/min (riga 2003) |
| **RA Max Drift Rate** | `maxRateRA` | Velocità massima istantanea RA via LPF (riga 1942-1945) |
| **Dec Drift Rate** | `decDriftPerMin` | Pendenza fit lineare su dati Dec (riga 1989-1990) |
| **Polar Alignment Error** | `alignmentError` | Stima errore PA in arcmin (riga 1991) |
| **SNR medio** | `sumSNR / n` | Media SNR sulla sessione |
| **StarMass medio** | `sumMass / n` | Media massa stellare |

**Filtraggio frequenze:**  
Il GA separa frequenze con due filtri configurati all'avvio (riga 1640-1647):
```cpp
double lp_cutoff = wxMax(6.0, 3.0 * exposure);  // cutoff LPF
double hp_cutoff = 1.0;                           // cutoff HPF fisso
m_raHPF = HighPassFilter(hp_cutoff, exposure);    // filtra drift lento
m_raLPF = LowPassFilter(lp_cutoff, exposure);     // rimuove seeing rapido
m_decHPF = HighPassFilter(hp_cutoff, exposure);
```
- **HPF (High-Pass Filter):** isola i movimenti rapidi (seeing, vibrazione); la soglia è 1 periodo di esposizione.
- **LPF (Low-Pass Filter):** isola il drift lento (tracking RA, polar misalignment); cutoff a `max(6s, 3×esposizione)`.

### 1.3 Formula Polar Alignment Error

Basata sul paper di Barrett (citato nel codice, riga 1987):

```
alignmentError = 3.8197 × |decDriftPerMin| × pixelScale / cos(declination)
```

dove `decDriftPerMin` è la pendenza della regressione lineare in px/min, `pixelScale` è in arcsec/px. Il risultato è in arcmin. Se la declinazione è sconosciuta, si usa `cosdec = 1.0` e il risultato è un lower bound.

### 1.4 Formula MinMove raccomandato (cuore del GA)

La funzione `GetMinMoveRecs()` (righe 1144-1278) è la parte più sofisticata del GA. Logica:

**a) Stima del seeing (bestEstimate in pixel):**
- Per sessioni brevi (≤ 2.4 min): usa RMS Dec semplice, oppure RMS Dec dopo rimozione del drift (fit lineare), scegliendo il valore minore.
- Per sessioni lunghe (> 2.4 min): usa sliding windows da 120s con overlap 60s, tenendo il minimo valore di `correctedRMS` trovato.
- In modalità multi-star: `bestEstimate *= 0.9` e floor a 0.05 px (riga 1242).

**b) Moltiplicatori basati su scala immagine:**
```cpp
double multiplier_dec = (pxscale < 1.5) ? 1.28 : 1.65;
// 1.28 corrisponde al 10% activity target (scala fine)
// 1.65 corrisponde al 20% activity target (scala grossa)
double multiplier_ra = pMount->HasHPEncoders() ? 1.0 : 0.65;
// RA = 65% di Dec (meno sensibile per le montature normali)
```

**c) Arrotondamento e sanity check:**
```cpp
double roundUpEst = max(round(bestEstimate * multiplier_dec / 0.05 + 0.5) * 0.05, 0.05);
// Arrotondamento al multiplo di 0.05 pixel per eccesso
if (pxscale * roundUpEst <= 1.25) {
    // Min-move credibile (sotto 1.25 arcsec)
    RecDec = roundUpEst;
    RecRA = max(0.1, RecDec * multiplier_ra);
} else {
    // Fallback: usa SmartDefaultMinMove da focale/pixel
    RecDec = SmartDefaultMinMove(focalLength, pixelSize, binning);
    RecRA = max(0.1, RecDec * multiplier_ra / multiplier_dec);
}
```

Il sanity check `pxscale × roundUpEst <= 1.25 arcsec` serve ad escludere risultati patologici (sessione troppo breve, stella debole, mount non stabile).

**d) SmartDefaultMinMove (formula fallback, riga 64-68 in guide_algorithm.cpp):**
```cpp
SmartDefaultMinMove = max(0.1515 + 0.1548 / imageScale, 0.15)
// imageScale = pixelSize_µm × binning × 206.265 / focalLength_mm  (arcsec/px)
```

### 1.5 Raccomandazione esposizione (Drift-Limiting Exposure)

```cpp
drift_exp = ceil((1.0 × rarms / maxRateRA) / 0.5) * 0.5  // arrotondato a 0.5s
// oppure con min-move definitivo:
drift_exp = m_ra_minmove_rec / maxRateRA
```
Il valore mostra per quanto tempo il drift RA rimane sotto il MinMove raccomandato. Il range suggerito è `[max(1.0, min(drift_exp, ideal_min)), ideal_min + 2.0s]` dove `ideal_min = 2s` senza encoders, `4s` con encoders HP.

### 1.6 Raccomandazione algoritmo Dec (quando GA suggerisce Lowpass2)

Il GA suggerisce di passare a **Lowpass2** per Dec (con aggressiveness = 80%) **solo se** (riga 1535-1548):
```cpp
if (hasEncoders || smallBacklash) {        // mount con encoders O backlash < 100ms
    if (algoChoice == "ResistSwitch") {     // solo se l'utente usa attualmente ResistSwitch
        // suggerisce Lowpass2
    }
}
```
Non suggerisce mai di passare da Hysteresis a Lowpass2, né tocca RA.

### 1.7 Raccomandazione Backlash

- Se `backlashMs < 100` o mount ha encoders HP: nessuna compensazione.
- Se `100 ≤ backlashMs ≤ 3000`: suggerisce compensazione BLC arrotondata a 10ms verso il basso (`floor(ms/10)*10`), minimo 10ms.
- Se `backlashMs > 3000` (MAX_BACKLASH_COMP): suggerisce guida unidirezionale Dec.

### 1.8 Soglie hard-coded notevoli

| Costante | Valore | Significato |
|---|---|---|
| `GA_MIN_SAMPLING_PERIOD` | 120 s | Durata minima osservazione |
| `MAX_BACKLASH_COMP` | 3000 ms | Limite max BLC applicabile |
| Sanity check MinMove | 1.25 arcsec | Sopra questa soglia i calc falliscono il check |
| SNR warning | < 10.0 | Suggerisce stella più luminosa |
| PA warning lieve | > 5 arcmin | Polar alignment non ottimale |
| PA warning grave | > 10 arcmin | Suggerisce Drift Align |
| HFD warning | > 4.5 px (solo con scale > 1 arcsec/px) | Focus migliorabile |
| multiplier_dec scala fine | 1.28 | pixelScale < 1.5 arcsec/px |
| multiplier_dec scala grossa | 1.65 | pixelScale >= 1.5 arcsec/px |
| multiplier_ra (normale) | 0.65 | RA = 65% di Dec |

---

## 2. Il nostro AdaptiveController — come funziona

### 2.1 StatisticsAnalyzer: metriche e sliding window

`StatisticsAnalyzer` (in `analyzer.py`) mantiene una `deque` degli ultimi `window_size` frame (default: 30 frame per tutti i config attuali). Ogni evento `GuideStep` produce un `FrameData` con: `ra_raw`, `dec_raw` (in arcsec), `ra_duration`, `dec_duration` (ms), `snr`, `hfd`, `star_mass`.

**Metriche calcolate ad ogni `_compute()` (righe 149-212):**

| Metrica | Formula Python | Note |
|---|---|---|
| `rms_ra` | `sqrt(sum(v² for v in ra_vals) / n)` | RMS sui valori grezzi (non filtrati HPF) |
| `rms_dec` | idem su dec_vals | |
| `rms_total` | `hypot(rms_ra, rms_dec)` | |
| `peak_ra` | `max(abs(v) for v in ra_vals)` | Massimo assoluto nella finestra |
| `peak_dec` | idem | |
| `snr_avg` | media aritmetica | |
| `hfd_avg` | media (solo valori > 0) | |
| `sigma_ra` | deviazione standard (deviazione da media) | |
| `sigma_dec` | idem | |
| `spike_score` | `outliers / n` dove outlier = valore oltre ±2σ | Percentuale [0,1] |
| `trend_ra` | pendenza regressione lineare OLS sui frame della finestra | arcsec/frame |
| `trend_dec` | idem | |

**Contatori consecutivi** (righe 194-206): `consecutive_high` e `consecutive_low` sono incrementati a ogni snapshot se `rms_total` supera rispettivamente `rms_high` o `rms_low`. In zona neutra vengono decrementati di 1 ad ogni passo (decay graduale).

**Soglia `is_ready`:** il sistema è considerato pronto quando la finestra ha almeno `max(5, window_size // 3)` frame (riga 143), ovvero 10 frame con window=30.

### 2.2 Classificazione condizioni (pattern recognition)

La funzione `_classify()` (righe 214-242) assegna una di queste condizioni:

1. **STAR_LOST**: se stellaPersa (flag da evento PHD2).
2. **LOW_SNR**: se `snr_avg < snr_low` e snr_avg > 0.
3. **OSCILLATING**: se `|trend_ra| > 0.05 arcsec/frame` AND `rms_ra > rms_low` AND `spike_score < 0.25`.
4. **DEGRADED_SEEING**: se `spike_score > spike_ratio_high` AND `rms_total > rms_high`; oppure se solo `rms_total > rms_high`.
5. **NOMINAL**: altrimenti.

### 2.3 AdaptiveController: macchina a stati e logica decisionale

**Stati del controller** (in `GuidingState`):
- `NORMAL`, `DEGRADED`, `CRITICAL`, `RECOVERING`, `STAR_LOST`, `INACTIVE`

**Transizioni di stato** (`_update_guiding_state()`, righe 462-477):
- `rms_total > rms_high × 1.5` → CRITICAL
- `rms_total > rms_high` → DEGRADED
- `rms_total < rms_low` da DEGRADED/CRITICAL → RECOVERING
- `rms_total < rms_low` da altri stati → NORMAL

**Logica per asse (`_evaluate_axis()`, righe 479-604):**

| Caso | Condizione trigger | Azione RA/Dec | Cooldown |
|---|---|---|---|
| 1: Seeing degradato | `rms > rms_high` per `consecutive_frames` frame | Aggressiveness DOWN di `aggr_step_down` (×2 se CRITICAL, cap 15) | `cooldown_seconds` |
| 1b: Seeing degradato | stessa condizione | MinMove UP di `minmove_step` | `cooldown × 1.5` |
| 2: Oscillazione | `condition == OSCILLATING` | Aggressiveness DOWN di `aggr_step_down` | `cooldown_seconds` |
| 3: Guida ottima | `rms < rms_low` per `consecutive_frames` frame | Aggressiveness UP di `aggr_step_up` | `cooldown × 2` |
| 3b: Guida ottima | stessa condizione | MinMove DOWN di `minmove_step` | `cooldown × 3` |

**Emergency routines:**
- `_evaluate_exposure()`: SNR basso → esposizione ×2 (cap a `max_exposure_ms`); SNR recuperato → ripristina esposizione base.
- `_evaluate_saturation_timer()`: se stella satura tracciata per > `saturation_timeout_s` (default 300s), forza `find_star()`.
- `_evaluate_star_lost()`: stella persa per > `find_star_delay` secondi → `find_star()` standard o AI Star Finder.

### 2.4 Valori hard-coded nei config_*.toml

| Parametro | RC8 (1624mm) | Tecnosky115 (800mm) | Askar71F (490mm) |
|---|---|---|---|
| `rms_high` | 0.85" | 1.00" | 1.30" |
| `rms_low` | 0.50" | 0.55" | 0.70" |
| `consecutive_frames` | 5 | 5 | 5 |
| `cooldown_seconds` | 30 | 30 | 30 |
| `window_frames` | 30 | 30 | 30 |
| RA `aggr_min/max` | 35-75 | 40-80 | 40-85 |
| RA `aggr_step_down/up` | 5/2 | 5/2 | 5/3 |
| RA `minmove_min/max` | 0.15-0.50 px | 0.15-0.55 px | 0.15-0.55 px |
| Dec `aggr_min/max` | 30-70 | 35-75 | 35-80 |
| Dec `minmove_min/max` | 0.20-0.55 px | 0.18-0.55 px | 0.18-0.55 px |
| `minmove_step` | 0.05 px | 0.05 px | 0.05 px |
| `snr_low` | 8.0 | 9.0 | 9.0 |

---

## 3. Sovrapposizioni

Le due architetture condividono il concetto di base ma lo realizzano in modo diverso:

**3.1 RMS come metrica principale**
Entrambi usano RMS degli errori stellari come indicatore di qualità della guida. Il GA usa HPF-RMS (filtrando il drift lento), il nostro agente usa RMS grezzo (raw). Entrambi calcolano separatamente RA e Dec e un totale.

**3.2 SNR come indicatore qualità stella**
Il GA soglia a SNR < 10 per suggerire una stella più luminosa (riga 1428). L'agente configura `snr_low` per classe e trigger l'emergenza esposizione.

**3.3 Drift RA**
Il GA calcola `maxRateRA` (velocità massima istantanea RA via LPF) e lo usa per determinare la "drift-limiting exposure". L'agente non usa direttamente questa metrica, ma il concetto di `trend_ra` (pendenza regressione lineare) è analogo seppur a granularità di frame.

**3.4 Dec drift come indicatore polar alignment**
Il GA usa la pendenza del fit lineare su Dec per stimare il polar alignment error (formula di Barrett). L'agente calcola `trend_dec` con lo stesso metodo (regressione lineare OLS), ma non lo usa per polar alignment — lo usa invece come input secondario per la classificazione OSCILLATING.

**3.5 Peak error**
Entrambi calcolano il peak error per RA e Dec. Il GA usa `GetMaxDelta()` (massima variazione campione-campione), l'agente usa `max(abs(v))` (massimo assoluto nella finestra, riga 168-169).

---

## 4. Differenze filosofiche

### 4.1 One-shot calibration (GA) vs controllo continuo (agente)

Il Guiding Assistant è un **calibratore da eseguire all'inizio di ogni notte** (o dopo cambio di condizioni importanti). Opera con guida **disabilitata** per misurare la risposta del sistema senza retroazione. Produce raccomandazioni discrete che l'utente applica una volta.

Il nostro agente è un **regolatore in closed-loop continuo**: valuta snapshot ogni `interval_seconds = 10s`, opera **durante la guida attiva**, e aggiusta i parametri in piccoli step con cooldown per evitare oscillazioni. Non presuppone stazionarietà delle condizioni.

### 4.2 Scala temporale

- GA: 2-5 minuti di osservazione passiva, raccomandazione una-tantum.
- Agente: sliding window di ~30 frame (5 minuti a 10s/frame), azione ogni 10s con cooldown 30-90s. L'orizzonte effettivo di una decisione è quindi 5-10 minuti.

### 4.3 Qualità dei dati di input

- GA: dati **non corretti** (guida disabilitata). Misura quindi il comportamento del cielo e della meccanica nella loro forma pura, senza distorsioni da retroazione.
- Agente: dati **residui di guida** (errori dopo la correzione). Questi includono la retroazione stessa. Il comportamento del sistema influenza la misura.

### 4.4 Filtraggio frequenze

Il GA separa esplicitamente le frequenze con HPF/LPF: HPF per seeing/vibrazione, LPF per drift. L'agente lavora su RMS grezzo (senza separazione frequenze), ma usa lo `spike_score` (outlier oltre 2σ) come proxy per il contributo di seeing rapido.

### 4.5 Backlash e algoritmo Dec

Il GA misura il backlash direttamente con il BLT (Backlash Test) e suggerisce la compensazione. L'agente **non tocca** la compensazione backlash. Per la scelta dell'algoritmo Dec, il GA suggerisce Lowpass2 in presenza di backlash basso + encoders; l'agente è algoritmicamente neutro (lavora con qualsiasi algoritmo PHD2 già configurato).

---

## 5. Formule GA utilizzabili per validare i config

### 5.1 Validazione minmove_min tramite SmartDefaultMinMove

Il fallback del GA usa (da `guide_algorithm.cpp` riga 68):
```
SmartDefaultMinMove = max(0.1515 + 0.1548 / imageScale, 0.15)
dove imageScale = pixelSize_µm × binning × 206.265 / focalLength_mm
```

Applicato ai tre setup (binning 1, pixel size verificato per camera
guida reale di ciascun setup):

| Setup | Camera guida | Pixel | Focale guida | imageScale OAG | SmartDefault (px) | SmartDefault (arcsec) |
|---|---|---|---|---|---|---|
| RC8 nativo | ASI220MM Mini | 4.0 µm | 1624 mm | 0.51 "/px | max(0.152+0.304, 0.15) = **0.46 px** | 0.23 arcsec |
| RC8 ridotto | ASI220MM Mini | 4.0 µm | 1299 mm | 0.64 "/px | max(0.152+0.242, 0.15) = **0.39 px** | 0.25 arcsec |
| Tecnosky nativo | ASI220MM Mini | 4.0 µm | 800 mm | 1.03 "/px | max(0.152+0.150, 0.15) = **0.30 px** | 0.31 arcsec |
| Tecnosky ridotto | ASI220MM Mini | 4.0 µm | 640 mm | 1.29 "/px | max(0.152+0.120, 0.15) = **0.27 px** | 0.35 arcsec |
| Askar nativo | ASI120MM Mini | 3.75 µm | 490 mm | 1.58 "/px | max(0.152+0.098, 0.15) = **0.25 px** | 0.40 arcsec |
| Askar ridotto | ASI120MM Mini | 3.75 µm | 392 mm | 1.97 "/px | max(0.152+0.079, 0.15) = **0.23 px** | 0.45 arcsec |

**Confronto con minmove_max nei config (margine controller):**

| Setup | minmove_max config (px) | SmartDefault GA (px) | Margine sopra default |
|---|---|---|---|
| RC8 | 0.50 | 0.46 | +9% |
| Tecnosky | 0.55 | 0.30 | +83% |
| Askar | 0.55 | 0.25 | +120% |

**Osservazioni operative:**

- RC8 ha margine molto stretto: il controller può alzare MinMove solo
  del 9% sopra il SmartDefault prima di sbattere contro minmove_max.
  Considerare di rivedere `minmove_max = 0.60-0.65 px` su RC8 dopo le
  prime sessioni reali per dare più spazio al controller in CRITICAL.

- minmove_min (floor) su RC8 = 0.15 px = 0.077" è sotto la risoluzione
  effettiva di centroide. Considerare di alzarlo a 0.20 px dopo le
  prime sessioni reali per evitare che il controller faccia lavoro
  inutile in seeing eccezionale.

- Tecnosky e Askar hanno margini ampi (83% e 120% rispettivamente). Il
  controller non rischia di saturare minmove_max in queste configurazioni.

- Tutti i minmove_min nei config restano floor assoluti di sicurezza,
  non valori iniziali. Il SmartDefault GA è il valore raccomandato
  *iniziale*, non il limite inferiore.

### 5.2 Calcolo bounds aggressiveness con formula GA

Il GA non impone bounds espliciti su Aggressiveness. Tuttavia, quando applica Lowpass2, usa **aggressiveness = 80%** come valore target (riga 878). Per Hysteresis, il default è `aggression = 0.7` (70% scala 0-1, cioè 70/100). Questo suggerisce che valori > 80% sono solitamente eccessivi senza encoders HP.

Implicazione per i config:
- `aggr_max = 75-85%` è in linea con la pratica del GA per Lowpass2.
- `aggr_max = 70-75%` per Dec è appropriato per mount con backlash (come da config RC8 Dec = 70).

### 5.3 Validazione rms_high tramite formula drift-limiting exposure

Dal GA: `drift_exp = m_ra_minmove_rec / maxRateRA`. Per 2s di esposizione la regola è che il drift non dovrebbe superare il MinMove ogni 2s. Se `maxRateRA` tipico è 0.05-0.15 px/s per buone montature, e `minmove = 0.20 px`, allora `drift_exp = 0.20/0.10 = 2s` — coerente.

Il `rms_high` nei config (0.85" per RC8, 1.00" per Tecnosky, 1.30" per Askar) è calibrato come 1.5× il RMS tipico atteso per il setup, coerente con il principio GA di riconoscere come "degradato" solo ciò che è patologico per il setup specifico.

---

## 6. Aree che l'agente NON deve toccare

### 6.1 Backlash compensation (BLC)

**Motivo:** La compensazione backlash è un parametro meccanico misurato una volta con il BLT del GA, che richiede movimenti Dec di ampiezza controllata (tens of arcseconds). L'agente vede solo gli errori residui in guida — non può distinguere un errore da backlash da seeing senza questa misura dedicata. Applicare compensazione errata in modo adattivo causerebbe oscillazioni DEC gravi.

**Dove NON toccare:** il parametro `BacklashComp.SetBacklashPulseWidth()`, gestito da `OnDecBacklash()` in `guiding_assistant.cpp` riga 894-901.

### 6.2 Calibration step size

**Motivo:** Il calibration step size determina la lunghezza dei pulse inviati durante la calibrazione per determinare la scala pixel-arcsec. Un valore sbagliato produce una calibrazione scorretta con conseguenze su tutte le correzioni successive. La calibrazione deve essere stabile per tutta la notte.

**Dove NON toccare:** `calstep_dialog.cpp` e i parametri relativi alla calibrazione.

### 6.3 Polar alignment

**Motivo:** L'errore di polar alignment è fisico (posizione della testa equatoriale) e non correggibile via software se non con strumenti fisici (Drift Align). Il GA stima l'errore PA dal drift Dec usando la formula di Barrett, ma questa misura richiede la guida **disabilitata** per campionare il drift puro. L'agente non ha questa precondizione.

**Dove NON toccare:** la suggerisce di usare Drift Align tool (phd2/drift_tool.cpp). L'agente può al più loggare un warning.

### 6.4 Scelta algoritmo guiding

**Motivo:** La scelta dell'algoritmo (Hysteresis, Lowpass2, ResistSwitch, GP Guider) è decisione one-time dell'utente basata sulle caratteristiche della montatura. Il GA suggerisce Lowpass2 solo in condizioni precise (encoders HP + backlash basso). Cambiare algoritmo a runtime, specialmente in modalità adattiva, potrebbe produrre comportamenti inattesi.

**Dove NON toccare:** `OnDecAlgoChange()` in `guiding_assistant.cpp` riga 862-891. L'agente opera sui parametri dell'algoritmo esistente, non sceglie l'algoritmo.

### 6.5 Camera binning

**Motivo:** Il binning cambia la pixel scale e invalida la calibrazione corrente. È un parametro di setup, non di sessione.

---

## 7. Trigger "suggerisci re-run Guiding Assistant"

Condizioni in cui l'agente dovrebbe emettere un log-warning del tipo:
`"Considera di ri-eseguire il Guiding Assistant: [motivo]"`.

### 7.1 Drift Dec persistente elevato

**Condizione:** `abs(trend_dec)` (in arcsec/frame) rimane elevato per un'intera sessione (es. >30 minuti), anche durante snapshot NOMINAL.

**Soglia indicativa:** `abs(trend_dec) > 0.10 arcsec/frame` con esposizione 2-3s equivale a > ~6 arcsec/min di drift Dec, che è compatibile con polar alignment error > 5 arcmin.

**Motivo:** Il GA con osservazione passiva può stimare il polar alignment con la formula di Barrett e consigliare azioni. L'agente vede solo i residui corretti.

### 7.2 RMS strutturalmente sopra rms_high per molti cicli

**Condizione:** `consecutive_high` che tocca valori > 20-30 (ossia 200-300 secondi continui di seeing degradato) senza mai scendere sotto `rms_low`, con il controller già al `aggr_min`.

**Motivo:** Il controller ha esaurito lo spazio di manovra sui parametri. Potrebbe essere cambiato il setup (nuova focale, diversa camera guida), seeing strutturalmente diverso dalla baseline, o necessità di ricalibrare. Il GA produrrebbe nuove raccomandazioni di MinMove basate sulle condizioni attuali.

### 7.3 SNR strutturalmente basso con esposizione già massima

**Condizione:** `in_emergency_exposure == True` per > 30 minuti consecutivi (esposizione già portata al massimo e SNR ancora sotto `snr_low`).

**Motivo:** La stella guida è sbagliata, c'è velatura persistente, o la camera guida ha un problema. Il GA eseguirebbe la selezione stella e ricalcolerebbe i parametri.

### 7.4 Cambio di setup rilevato (setup_id diverso)

**Condizione:** Al startup, se il `setup.profile_name` cambia rispetto alla baseline salvata (`baseline.py` righe 314-319).

**Motivo:** I valori ottimali di MinMove, Aggressiveness e i bounds del config sono funzione del setup ottico. Un cambio di telescopio o camera richiede una nuova sessione GA.

### 7.5 Spike score anomalo e persistente

**Condizione:** `spike_score > 0.50` (>50% dei frame sono outlier oltre 2σ) persistente per > 10 cicli di valutazione.

**Motivo:** Questo pattern può indicare vibrazioni meccaniche, fuoco molto scarso, o problemi con la stella guida che vanno oltre la capacità dell'agente di compensare via parametri. Il GA misurerebbe le caratteristiche del problema con guida disabilitata per isolare la sorgente.

---

## Appendice: Mappa rapida dei file sorgente rilevanti

| File | Ruolo |
|---|---|
| `phd2-master/src/guiding_assistant.cpp` | Logica completa GA, formule MinMove, PAE |
| `phd2-master/src/guide_algorithm.cpp` | SmartDefaultMinMove formula fallback |
| `phd2-master/src/guide_algorithm_hysteresis.cpp` | Default: MinMove=0.2, aggression=0.7, hysteresis=0.1 |
| `phd2-master/src/guide_algorithm_lowpass2.cpp` | Default: MinMove=0.2, Aggressiveness=80.0 |
| `phd2-master/src/guiding_stats.h` | HighPassFilter, LowPassFilter, DescriptiveStats, AxisStats |
| `phd2_agent/analyzer.py` | StatisticsAnalyzer, sliding window, classificazione |
| `phd2_agent/controller.py` | AdaptiveController, macchina a stati, baseline guardian |
| `config_rc8.toml` | Parametri per RC8 (1624mm, scala fine) |
| `config_tecnosky115.toml` | Parametri per Tecnosky115 (800mm, scala media) |
| `config_askar71f.toml` | Parametri per Askar71F (490mm, scala grossa) |
