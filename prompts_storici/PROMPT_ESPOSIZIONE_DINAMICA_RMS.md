# PROMPT PER CLAUDE CODE (Antigravity) — Implementazione Esposizione Dinamica RMS-based
# Da copiare e incollare integralmente nella conversazione con Claude Code.
# Lavorare nella cartella: PHD2_Assist_PATCHED/

---

## CONTESTO

Sto lavorando al progetto **PHD2 Adaptive Agent** (Python, agente che si connette
a PHD2 via JSON-RPC su porta 4400 e regola dinamicamente i parametri di guida).
Lo stato attuale del progetto è descritto in `CONTESTO_PROGETTO.md` e
`NOTE_CLAUDE.md` — leggili prima di iniziare per capire la struttura,
le convenzioni e le regole di sicurezza.

Devi implementare una nuova feature: **esposizione dinamica RMS-based**,
ovvero la capacità del controller di aumentare il tempo di esposizione della
camera di guida quando le metriche statistiche indicano seeing degradato
(non solo SNR basso, come avviene oggi).

La feature deve coesistere con la logica esistente di `_evaluate_exposure()`
che gestisce il caso `LOW_SNR`. I due path agiscono sulla stessa leva
(esposizione) ma per cause fisiche diverse, e devono essere coordinati da
una **macchina a stati esplicita** sull'esposizione.

---

## 0. PRE-FLIGHT OBBLIGATORIO (leggere PRIMA di scrivere codice)

Prima di toccare qualsiasi file Python, devi consultare il sorgente C++ di PHD2
e la User Guide presenti nella cartella di lavoro. Senza questa verifica
l'implementazione avrà bug latenti che si manifesteranno solo in campo.
Le scoperte qui sotto sono già verificate da Alessandro+Claude su `phd2-master/`,
ma tu devi rileggerle nel sorgente per confermare e pescare eventuali
dettagli che ho omesso.

### File da leggere e cosa cercare

1. **`phd2-master/phd2-master/src/event_server.cpp`**
   - Riga ~648: `get_exposure_durations` — ritorna la lista dei valori validi
     dalla camera connessa. Verificare che `client.get_exposure_durations()`
     in `phd2_agent/client.py` la mappi correttamente.
   - Riga ~737: `set_exposure` — chiama `pFrame->SetExposureDuration(exp->int_value)`.
     **Ritorna error 1 "could not set exposure duration"** se il valore non
     è nella lista. **Non c'è alcun controllo di stato Guiding/Looping**:
     il comando è accettato in entrambi i casi.
   - Riga ~3049: `NotifyConfigurationChange` con debouncer — è un evento
     emesso al cambio config; non sembra scattare per `set_exposure` ma
     conferma cercando se `OnExposureDurationSelected` scrive in `pConfig`.

2. **`phd2-master/phd2-master/src/myframe.cpp`**
   - Riga ~687: `MyFrame::SetExposureDuration(int val)` — chiama
     `dur_index(val)` per trovare l'indice nella lista valida; ritorna `false`
     se non trovato (snap obbligatorio prima di inviare). Se `val < 0`
     attiva la modalità **Auto Exposure** — non usarla mai dal controller.
   - Riga ~707: `SetAutoExposureCfg(minExp, maxExp, targetSNR)` — esiste un
     sistema di auto-exposure interno a PHD2. Se l'utente lo ha abilitato,
     PHD2 sovrascrive periodicamente l'esposizione che noi impostiamo.
     **Il controller deve verificare la stringa `ExposureDurationSummary()`
     all'`initialize()`** (via JSON-RPC se disponibile, altrimenti loggare
     un WARNING e chiedere all'utente di disabilitare Auto Exposure in PHD2).
   - Riga ~159: `OnExposureDurationSelected` è il callback. Verifica nel
     corpo della funzione se al cambio: (a) si interrompe il loop in corso,
     (b) si invalida lo stato dell'algoritmo di guida, (c) si emette qualche
     evento JSON-RPC. Questo è il punto più critico — leggi la funzione intera.

3. **`phd2-master/phd2-master/src/guide_algorithm_hysteresis.cpp` e
   `guide_algorithm_resist_switch.cpp`**
   - Cercare `Reset()` e qualsiasi stato interno (lastMove, lastDecision,
     hysteresisFactor cumulato). Se l'algoritmo ha memoria sui frame
     precedenti, un cambio di esposizione invalida quella memoria perché
     il dt cambia. Non possiamo chiamare un Reset dell'algoritmo via
     JSON-RPC — quindi documenta il comportamento atteso e includilo
     nella reason del log: "esposizione cambiata, primi N frame post-cambio
     potrebbero avere algoritmo non perfettamente sintonizzato".

4. **`PHD2_User_Guide 2.6.14.pdf`**
   Sezioni da leggere (Ctrl+F sui titoli):
   - **"Exposure Time"** o **"Camera Exposure"** — raccomandazioni ufficiali
     PHD2 sulla scelta dell'esposizione di guida.
   - **"Auto Exposure"** — funzionamento e quando disabilitarla.
   - **"Server Interface"** o **"Event Monitoring"** — comportamento
     documentato di `set_exposure` durante una sessione di guida attiva.
   - **"Hysteresis"** e **"Resist Switch"** — eventuali note sul
     comportamento al cambio di sample rate (esposizione).
   - **"Predictive PEC"** (se presente) — questo è l'algoritmo più
     sensibile al cambio di esposizione perché apprende il periodo
     dell'errore periodico in funzione del numero di frame.

### Decisioni di design da PRENDERE in base alle verifiche sopra

A. **Snap obbligatorio**: leggere `client.get_exposure_durations()` UNA volta
   in `controller.initialize()` e memorizzare in `self._valid_exposures: list[int]`.
   Funzione helper `_snap_exposure(target_ms: int) -> int` che ritorna il
   valore valido più vicino ≤ `max_exposure_ms`. Mai chiamare `set_exposure(N)`
   con `N` arbitrario.

B. **Auto Exposure**: in `initialize()` verifica via `client.get_variable_delay_settings`
   o via `pConfig` (se esposto) se Auto Exposure è attiva. Se sì:
   - Loggare un **WARNING CRITICO** una volta sola: "Auto Exposure di PHD2
     attiva — l'esposizione dinamica del controller verrà sovrascritta da
     PHD2. Disabilitare Auto Exposure in PHD2 (Brain → Camera → Use Auto Exposure)
     prima di attivare `[exposure_dynamic].enabled`."
   - **Non disabilitare automaticamente**: è una scelta dell'utente.
   - Il path B (`_evaluate_exposure_seeing`) deve **rifiutarsi di operare**
     se Auto Exposure è attiva (return immediato con log INFO una volta sola).
   - Il path A (LOW_SNR esistente) può continuare a operare ma con WARNING.

C. **Evento `ConfigurationChange`**: dopo `set_exposure` PHD2 potrebbe emettere
   `ConfigurationChange`. Verificare in `main.py` `_event_loop` cosa fa
   l'agent oggi su questo evento. Se non lo gestisce, va bene così. Se lo
   gestisce (es. per ricaricare baseline), aggiungere un flag temporaneo
   `_self_triggered_config_change` per ignorare l'evento immediatamente
   dopo i nostri `set_exposure`.

D. **Avvertenza Hysteresis/PPEC nel log**: la `reason` della `ControlAction`
   deve includere: "ATTENZIONE: cambio esposizione invalida memoria interna
   dell'algoritmo di guida; primi 2-3 frame post-cambio potrebbero
   mostrare comportamento transitorio."

E. **Verifica `SetAutoExposureCfg`**: se esiste un comando JSON-RPC per
   leggere lo stato Auto Exposure, usalo. Altrimenti documenta che la
   verifica va fatta lato utente in PHD2 GUI.

### Nessuna verifica → STOP

Se durante il pre-flight scopri qualcosa di incompatibile con la specifica
sotto (es. PHD2 non accetta `set_exposure` durante Guiding, oppure
`OnExposureDurationSelected` interrompe il loop), **fermati e riporta**
ad Alessandro prima di procedere. Non improvvisare.

---

## OBIETTIVO TECNICO

Aggiungere a `phd2_agent/controller.py` un secondo path di regolazione
esposizione che si attivi quando il classifier identifica seeing degradato
(non LOW_SNR). Il path deve:

1. Essere governato da una macchina a stati `ExposureState` con stati mutuamente
   esclusivi:
   - `NOMINAL` — esposizione = `base_exposure_ms`
   - `BOOSTED_FOR_SNR` — il path esistente LOW_SNR ha aumentato l'esposizione
   - `BOOSTED_FOR_SEEING` — il nuovo path RMS-based ha aumentato l'esposizione
2. Essere disattivabile per setup (Askar 71F deve restare disattivato di default
   perché non beneficia: scala di guida 1.97"/px troppo generosa).
3. Includere `analyzer.reset()` immediato dopo ogni cambio di esposizione
   (la finestra statistica con esposizioni miste non è confrontabile).
4. Salvare/ripristinare lo stato corrente nel Baseline Guardian.

---

## REGOLE INDEROGABILI

- **NON modificare** la logica esistente di `_evaluate_exposure()` per LOW_SNR
  oltre a quanto strettamente necessario per integrarla nella macchina a stati.
- **NON toccare** la backlash compensation di PHD2.
- **NON introdurre** modifiche al ramo aggressiveness/MinMove esistente.
- **NON aggiungere** una libreria nuova (resta su Python 3.12 stdlib + numpy/scipy
  già presenti).
- Mantenere lo stile e le convenzioni di codice già presenti nel file
  (logging in italiano, docstring, dataclass, type hints).

### MODALITÀ OPERATIVA (importante — letta da Alessandro)

La feature deve essere **testabile direttamente in LIVE**, non in DRY_RUN.
Motivo: Alessandro vuole vedere sul grafico della dashboard l'effetto reale
del cambio di esposizione sul comportamento del loop di guida; il puro log
`decisions_*.jsonl` non gli basta perché la prova del nove è la
risposta dinamica della guida, non l'emissione della decisione.

Per questo motivo:

- I config restano **come sono oggi** (NON forzare `dry_run = true`).
- La sicurezza è garantita dal flag **per-feature** `[exposure_dynamic].enabled`,
  che parte a `false` su tutti i setup e va attivato manualmente da Alessandro.
- Quando Alessandro attiverà `enabled = true` su `config_rc8.toml` e lancerà
  l'agente con `dry_run = false`, la feature deve emettere comandi reali
  `set_exposure()` a PHD2 e i log devono comunque essere prodotti normalmente
  (`decisions_*.jsonl` funziona in entrambe le modalità).
- La decisione di andare in LIVE è di Alessandro, non del codice. Il codice deve
  rispettare i due flag (`dry_run` globale + `[exposure_dynamic].enabled`
  per-setup) e comportarsi di conseguenza, niente di più.

---

## SPECIFICA FUNZIONALE DETTAGLIATA

### A. Configurazione TOML — nuova sezione `[exposure_dynamic]`

Il pixel scale di guida è hardcodato per ciascun config sul valore **nativo**
(senza riduttore). Sono valori già verificati nel `CONTESTO_PROGETTO.md`
sezione "Confronto GA-Agent + correzione pixel scale OAG".

#### `config_askar71f.toml`
```toml
[exposure_dynamic]
# Esposizione dinamica RMS-based (oltre al path LOW_SNR esistente).
# Si attiva su seeing degradato verificato da metriche multiple,
# SOLO DOPO che aggressiveness e MinMove hanno saturato i loro limiti.
# Non agisce mai durante OSCILLATING (peggiorerebbe il lag) né LOW_SNR.
#
# Su Askar 71F (1.58"/px nativo) il beneficio è marginale: la scala di guida
# è già abbastanza generosa da rendere l'integrazione via esposizione poco
# influente. Default OFF, da attivare solo per esperimenti.
enabled                  = false
guide_pixel_scale_arcsec = 1.58   # nativo; mettere 1.97 se monti il riduttore 0.8x
step_factor              = 1.5
max_steps_above_base     = 2
cooldown_s               = 90
spike_min                = 0.30
hfd_min_arcsec           = 4.5
peak_to_rms_ratio_min    = 3.0
nominal_for_seconds      = 60
```

#### `config_tecnosky115.toml`
```toml
[exposure_dynamic]
# Su Tecnosky 115 (1.03"/px nativo) il beneficio è marginale ma reale in
# nottate turbolente. Default OFF, attivabile in fase di test.
enabled                  = false
guide_pixel_scale_arcsec = 1.03   # nativo; mettere 1.29 se monti il riduttore 0.8x
step_factor              = 1.5
max_steps_above_base     = 2
cooldown_s               = 90
spike_min                = 0.25
hfd_min_arcsec           = 4.0
peak_to_rms_ratio_min    = 3.0
nominal_for_seconds      = 60
```

#### `config_rc8.toml`
```toml
[exposure_dynamic]
# Su RC8 (0.51"/px nativo) il seeing entra dritto nel sub di guida e
# l'integrazione via esposizione è una leva potente. Questo è il setup
# primario candidato all'attivazione e validazione della feature.
enabled                  = false   # da attivare manualmente per i test
guide_pixel_scale_arcsec = 0.51    # nativo; mettere 0.64 se monti il riduttore 0.8x
step_factor              = 1.5
max_steps_above_base     = 2
cooldown_s               = 90
spike_min                = 0.20
hfd_min_arcsec           = 4.0
peak_to_rms_ratio_min    = 3.0
nominal_for_seconds      = 60
```

#### `config.toml` (default)
```toml
[exposure_dynamic]
# Default config — pixel scale neutra, soglie permissive.
# Setup specifici sovrascrivono questi valori.
enabled                  = false
guide_pixel_scale_arcsec = 1.0
step_factor              = 1.5
max_steps_above_base     = 2
cooldown_s               = 90
spike_min                = 0.25
hfd_min_arcsec           = 4.0
peak_to_rms_ratio_min    = 3.0
nominal_for_seconds      = 60
```

Tutti `enabled = false` di default. L'utente attiverà manualmente la feature
sul setup di interesse (RC8 in primis) e potrà testarla **direttamente in LIVE**
(`dry_run = false` nel medesimo config) per osservare l'effetto sul grafico
della dashboard. La sicurezza è garantita dal fatto che `enabled` parte OFF
e dalla logica di escalation: il trigger non scatta finché aggressiveness
e MinMove non hanno saturato i limiti (vedi sezione D, requisito #11 nuovo).

### B. Nuova dataclass in `phd2_agent/config.py`

```python
@dataclass
class ExposureDynamicConfig:
    enabled: bool = False
    guide_pixel_scale_arcsec: float = 1.0
    step_factor: float = 1.5
    max_steps_above_base: int = 2
    cooldown_s: float = 90.0
    spike_min: float = 0.25
    hfd_min_arcsec: float = 4.0
    peak_to_rms_ratio_min: float = 3.0
    nominal_for_seconds: float = 60.0
```

Aggiungerla al `AppConfig` come `exposure_dynamic: ExposureDynamicConfig`,
e parsarla in `load_config()` con valori di default se la sezione manca
(retrocompatibilità con config esistenti).

### C. Macchina a stati in `phd2_agent/controller.py`

Aggiungere a livello modulo:

```python
from enum import Enum, auto

class ExposureState(Enum):
    NOMINAL              = auto()  # esposizione = base
    BOOSTED_FOR_SNR      = auto()  # path A: LOW_SNR (logica esistente)
    BOOSTED_FOR_SEEING   = auto()  # path B: RMS-based (nuova feature)
```

In `AdaptiveController.__init__()` (o in `initialize()`):

```python
self.exposure_state: ExposureState = ExposureState.NOMINAL
self.exposure_steps_above_base: int = 0
self.last_exposure_action_time: float = 0.0
self._nominal_since: Optional[float] = None  # per trigger DOWN su seeing
```

**Importante**: il flag esistente `self.in_emergency_exposure` può restare per
compatibilità interna ma deve essere **derivato** da `self.exposure_state ==
BOOSTED_FOR_SNR`. Se preferisci, sostituiscilo del tutto con `exposure_state`
(scelta architetturalmente più pulita, accettata).

### D. Modifica a `_evaluate_exposure()`

Riorganizzarla in modo che chiami due valutazioni separate:

```python
def _evaluate_exposure(self, snapshot: AnalysisSnapshot) -> list[ControlAction]:
    actions: list[ControlAction] = []
    if self.base_exposure_ms is None or self.base_exposure_ms <= 0:
        return actions

    # Path A: LOW_SNR (priorità più alta — già esistente, refattorizzato)
    actions.extend(self._evaluate_exposure_snr(snapshot))

    # Path B: seeing degradato RMS-based (nuovo, solo se path A non attivo)
    if self.exposure_state != ExposureState.BOOSTED_FOR_SNR:
        actions.extend(self._evaluate_exposure_seeing(snapshot))

    return actions
```

`_evaluate_exposure_snr(snapshot)` contiene la logica attuale, ma con:
- transizione di stato `NOMINAL → BOOSTED_FOR_SNR` su trigger UP
- transizione `BOOSTED_FOR_SNR → NOMINAL` su trigger DOWN
- chiamata a `self.analyzer.reset()` dopo ogni cambio confermato in LIVE

`_evaluate_exposure_seeing(snapshot)` è la nuova funzione. Logica:

**Trigger UP (NOMINAL → BOOSTED_FOR_SEEING)**:

Condizioni AND, tutte verificate:

1. `self.cfg.exposure_dynamic.enabled is True`
2. `snapshot.condition == SeeingCondition.DEGRADED_SEEING`
3. `snapshot.condition != SeeingCondition.OSCILLATING` (mai durante oscillazione)
4. `snapshot.condition != SeeingCondition.LOW_SNR` (delegato al path A)
5. `not snapshot.implosion_suspended`
6. `snapshot.consecutive_high >= self.cfg.thresholds.consecutive_frames`
7. `snapshot.spike_score >= self.cfg.exposure_dynamic.spike_min`
8. `snapshot.hfd_avg * self.cfg.exposure_dynamic.guide_pixel_scale_arcsec >=
   self.cfg.exposure_dynamic.hfd_min_arcsec`
9. `(snapshot.peak_ra / max(snapshot.rms_ra, 0.01)) >= peak_to_rms_ratio_min` OR
   `(snapshot.peak_dec / max(snapshot.rms_dec, 0.01)) >= peak_to_rms_ratio_min`
10. `self.exposure_steps_above_base < self.cfg.exposure_dynamic.max_steps_above_base`
11. **Escalation gate (NUOVO requisito chiesto da Alessandro)** — Almeno UNO
    dei due assi deve avere **entrambe** le difese cheap già saturate da
    almeno un cooldown:

    ```python
    def _axis_levers_saturated(axis_state, limits) -> bool:
        # current_aggr in scala config (0-100) anche per i parametri 0-1
        aggr_at_min = axis_state.current_aggr <= (limits.aggr_min + 1.0)
        mm_at_max   = axis_state.current_minmove >= (limits.minmove_max - limits.minmove_step)
        # entrambe le leve devono essere sature da almeno cooldown_seconds
        elapsed_aggr = time.monotonic() - axis_state.last_action_time
        elapsed_mm   = time.monotonic() - axis_state.last_minmove_action_time
        return (aggr_at_min and mm_at_max
                and elapsed_aggr >= self.cfg.control.cooldown_seconds
                and elapsed_mm   >= self.cfg.control.cooldown_seconds * 1.5)

    escalation_ok = (_axis_levers_saturated(self._ra,  self.cfg.ra) or
                     _axis_levers_saturated(self._dec, self.cfg.dec))
    ```

    **Razionale**: aggressiveness/MinMove sono interventi "cheap" (reversibili,
    cooldown breve, nessun reset finestra). Esposizione è "expensive" (cambia
    il segnale in ingresso, richiede `analyzer.reset()`, altera il
    comportamento appreso da Hysteresis/PPEC). Ha senso esaurire prima la
    prima linea di difesa. La condizione "almeno un asse saturato" è
    deliberata: il vincolo binding è sempre l'asse peggiore — se DEC ha
    esaurito le difese e RA no, è la DEC che sta facendo divergere RMS_total.

12. Cooldown dedicato esposizione: `(time.monotonic() - self.last_exposure_action_time) >= cooldown_s`

Se tutti soddisfatti:
- Calcolare `new_exp_target = current_exposure_ms * step_factor`
- Snap al valore valido più vicino di `self.client.get_exposure_durations()`
- Se il valore snap-pato è effettivamente maggiore del corrente:
  - `_apply_exposure(current, new, reason="DEGRADED_SEEING ...")`
  - Se non dry_run: `self.exposure_state = BOOSTED_FOR_SEEING`,
    `self.exposure_steps_above_base += 1`,
    `self.current_exposure_ms = new`,
    `self.last_exposure_action_time = time.monotonic()`,
    `self.analyzer.reset()`
- `reason` deve includere: `rms_total`, `spike_score`, `hfd_avg`, peak/rms ratio.

**Trigger DOWN (BOOSTED_FOR_SEEING → NOMINAL, gradualmente)**:

Condizioni AND:

1. `self.exposure_state == ExposureState.BOOSTED_FOR_SEEING`
2. `snapshot.condition == SeeingCondition.NOMINAL`
3. `snapshot.consecutive_low >= 2 * self.cfg.thresholds.consecutive_frames`
4. `self._nominal_since is not None and
    (time.monotonic() - self._nominal_since) >= self.cfg.exposure_dynamic.nominal_for_seconds`
5. Cooldown: `(time.monotonic() - self.last_exposure_action_time) >= cooldown_s * 1.5`

Se soddisfatti:
- Calcolare `new_exp_target = current_exposure_ms / step_factor`
- Snap al valore valido più vicino, ma non sotto `base_exposure_ms`
- Se snap-pato è minore del corrente:
  - `_apply_exposure(current, new, reason="seeing recuperato ...")`
  - Se non dry_run: `self.exposure_steps_above_base -= 1`,
    `self.current_exposure_ms = new`,
    `self.last_exposure_action_time = time.monotonic()`,
    `self.analyzer.reset()`
  - Se `exposure_steps_above_base == 0`: transizione `BOOSTED_FOR_SEEING → NOMINAL`

**Tracking `_nominal_since`** (helper interno):
- Aggiornare in cima a `evaluate()`: se `snapshot.condition == NOMINAL` e
  `_nominal_since is None`, settarlo a `time.monotonic()`.
  Se `snapshot.condition != NOMINAL`, settarlo a `None`.

### E. Baseline Guardian — estensione

In `save_baseline()` e `restore_baseline()`:

- Aggiungere campi: `current_exposure_ms`, `exposure_state` (str), `exposure_steps_above_base`.
- Bumpare `version` a 3 (la 2 era stata introdotta per `aggr_native_scale`).
- Su restore di baseline v3: ripristinare anche l'esposizione corrente con
  `self.client.set_exposure(...)` (solo se diversa dalla base).
- Su restore di baseline v2: log INFO "baseline v2 — esposizione dinamica
  resettata a base", procedere con restore standard senza tornare allo stato
  exposure pre-crash.

### F. Logging azioni

Le `ControlAction` per esposizione devono avere:
- `axis = "camera"`
- `param = "exposure_seeing"` per il path B (per distinguerlo dal `param = "exposure"` del path A — cambiare anche il path A in `param = "exposure_snr"` per simmetria)
- `reason` deve includere le metriche scatenanti come stringa formattata

In `decisions_*.jsonl` devono comparire entrambi i path con causa distinta.

### G. Dashboard (modifiche minime)

In `controller.get_status()`, aggiungere al dict di ritorno:

```python
"exposure": {
    "state": self.exposure_state.name,
    "current_ms": self.current_exposure_ms,
    "base_ms": self.base_exposure_ms,
    "steps_above_base": self.exposure_steps_above_base,
}
```

Non modificare il frontend dashboard (`dashboard/app.js`). L'utente lo
visualizzerà via JSON quando necessario.

---

## TEST ATTESI (sanity check, simulator)

Dopo l'implementazione esegui un test di non-regressione con il simulatore:

```bash
python main.py --simulator --dry-run --config config_rc8.toml
```

Il simulatore PHD2 non emette eventi DEGRADED_SEEING reali, quindi NON
vedrai azioni `[TEST] camera/exposure_seeing` da questo run. Il test serve
solo per verificare la non-regressione:

- Nessun `ImportError` o `AttributeError` all'avvio
- `_evaluate_exposure_seeing()` chiamata nel loop senza errori
- Baseline v3 salvata/ripristinata correttamente
- Dashboard `/api/status` ritorna il blocco `exposure` nuovo
- Le decisioni esistenti (RA/DEC aggressiveness, MinMove) continuano a essere
  emesse come prima, senza regressioni

Test unitari (consigliati, da aggiungere in `test_exposure_dynamic.py`):
1. Trigger UP soddisfatto + escalation gate aperto → verifica `_apply_exposure`
   chiamato e stato cambiato
2. Trigger UP soddisfatto + **escalation gate chiuso** (aggressiveness
   non al minimo) → verifica nessuna azione esposizione
3. Trigger UP con `OSCILLATING` → verifica nessuna azione
4. Trigger UP con `LOW_SNR` → verifica path B non chiamato (priorità A)
5. Trigger DOWN dopo `nominal_for_seconds` → verifica esposizione torna a base

Usa `unittest.mock.MagicMock` per il client PHD2 e snapshot fittizi.

## VALIDAZIONE LIVE SUL CAMPO (procedura primaria)

Questa è la modalità principale di validazione richiesta da Alessandro.
Il simulatore serve solo a sanity check; la verifica del comportamento
si fa **in LIVE** con osservazione del grafico della dashboard in tempo reale.

### Sequenza operativa per Alessandro (primo test sul campo, RC8)

1. Setup hardware: RC8 + ASI2600 + OAG + ASI220MM Mini, montatura CEM70G,
   PHD2 in guida normale e stabile da almeno 5 minuti.
2. Editare `Pacchetto_Distribuzione/config_rc8.toml`:
   ```toml
   [control]
   dry_run = false              # LIVE — necessario per vedere effetto reale
   
   [exposure_dynamic]
   enabled = true               # attiva la nuova feature SOLO per questo test
   ```
3. Avviare con `Avvia_RC8.bat` o:
   ```powershell
   .\PHD2_Agent.exe --config config_rc8.toml
   ```
4. Aprire dashboard su `http://localhost:8080`.
5. Osservare grafico RMS e blocco "exposure" (nuovo) nella dashboard.
6. La feature **non scatterà** finché non si verifica DEGRADED_SEEING reale
   AND aggressiveness/MinMove di almeno un asse non saturano i limiti.
   In nottata buona potrebbe non scattare mai: è il comportamento corretto.
7. Quando scatta: il grafico RMS dovrebbe mostrare riduzione del rumore ad
   alta frequenza dopo 1–2 finestre statistiche post `analyzer.reset()`.
   Se invece l'RMS aumenta o si vede over-correzione, abortire (Ctrl+C) e
   riportare i log `decisions_*.jsonl` + screenshot dashboard.

### Cosa verificare nei log dopo la sessione

In `logs/decisions_*.jsonl` cercare:
- Decisioni `axis="camera" param="exposure_seeing"` (path B nuovo)
- Verificare nel campo `reason` quali metriche hanno scatenato il cambio
- Verificare che il cambio sia avvenuto solo dopo che le precedenti decisioni
  RA/DEC avessero già saturato aggressiveness e MinMove
- Contare quanti UP e DOWN sono stati emessi: se >5 UP/DOWN per ora il
  cooldown è troppo corto o le soglie troppo permissive

### Linee guida tuning post-prima-sessione

- **Nessun trigger emesso** in una nottata mediamente turbolenta:
  abbassare `spike_min` di 0.05 e/o `hfd_min_arcsec` di 0.5 nel config RC8.
- **Trigger frequenti (>5/h)**: alzare `cooldown_s` a 120, oppure `spike_min`
  di 0.05.
- **Trigger durante OSCILLATING** (non dovrebbe mai succedere): bug, riportare.
- **Trigger DOWN che non scatta mai**: verificare `nominal_for_seconds` non
  troppo lungo (provare 45 s).

---

## PROCEDURA REBUILD (obbligatoria post-modifica)

1. `python build_dist.py`
2. Copiare in `Pacchetto_Distribuzione/`:
   - `config_rc8.toml`, `config_tecnosky115.toml`, `config_askar71f.toml`
   - `Avvia_Askar71F.bat`, `Avvia_Tecnosky115.bat`, `Avvia_RC8.bat`
   - `Sblocca_Firewall_8080.bat`
3. Ripristinare `LEGGIMI_PER_AVVIARE.txt` (build_dist.py lo sovrascrive con uno stub)
4. Ricreare ZIP con:
   ```powershell
   Remove-Item PHD2_Agent_Distribuzione.zip -ErrorAction SilentlyContinue
   [System.IO.Compression.ZipFile]::CreateFromDirectory(
       (Resolve-Path "Pacchetto_Distribuzione").Path,
       (Join-Path (Get-Location) "PHD2_Agent_Distribuzione.zip"))
   ```

---

## AGGIORNAMENTO DOCUMENTAZIONE (procedura collaudata, da eseguire SEMPRE)

### 1) `CONTESTO_PROGETTO.md`

Nella sezione `## Stato attuale — aggiornato al ...`:
- Aggiorna la data alla data di completamento della feature
- Aggiungi nuovo paragrafo **subito prima** di "Cosa NON è stato ancora fatto":

```markdown
### Esposizione dinamica RMS-based — IMPLEMENTATA (YYYY-MM-DD)
Aggiunta sezione `[exposure_dynamic]` ai config con macchina a stati
`ExposureState` (NOMINAL / BOOSTED_FOR_SNR / BOOSTED_FOR_SEEING). Il path
RMS-based si attiva su DEGRADED_SEEING + spike + HFD + peak/rms ratio,
con esclusioni tassative di OSCILLATING e LOW_SNR (delegato al path A
preesistente). Cambio esposizione → `analyzer.reset()` obbligatorio.
Baseline Guardian aggiornato a v3 con persistenza dello stato esposizione.
Default `enabled = false` su tutti e tre i config: la feature nasce disattiva
e va abilitata manualmente solo dopo validazione in DRY_RUN.
Vedere NOTE_CLAUDE.md sezione 19 per dettaglio completo.
```

In `## Cosa NON è stato ancora fatto`:
- Rimuovi eventuali voci non più valide
- Aggiungi:
  ```
  - Validazione LIVE dell'esposizione dinamica RMS-based su RC8 (almeno
    2 sessioni reali con `[exposure_dynamic].enabled = true` e
    `dry_run = false`). Osservare sulla dashboard l'andamento dell'RMS
    prima e dopo i trigger; verificare che il cambio esposizione avvenga
    solo dopo che aggressiveness/MinMove di almeno un asse hanno saturato
    i limiti (escalation gate). Tarare `spike_min`, `hfd_min_arcsec`,
    `cooldown_s` in base alla frequenza dei trigger osservata.
  ```

### 2) `NOTE_CLAUDE.md`

Aggiungi in coda nuova sezione (numero progressivo successivo, oggi 19):

```markdown
---

## 19. Esposizione dinamica RMS-based (YYYY-MM-DD)

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
- `config.toml`, `config_askar71f.toml`, `config_tecnosky115.toml`,
  `config_rc8.toml` — sezione `[exposure_dynamic]`
- `Pacchetto_Distribuzione/config_*.toml` — copie aggiornate post-rebuild

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
  ortogonale (l'esposizione cambia il segnale in ingresso, l'aggressivita
  cambia la risposta a quel segnale).
- Il `step_factor = 1.5` è meno aggressivo del `× 2` del path A, perché
  il seeing è un continuum (a differenza della perdita stella che è on/off).
```

### 3) `README.md` (modifica minima)

Se nel README c'è una tabella delle feature, aggiungi riga:
"Esposizione dinamica RMS-based (configurabile per setup, default OFF)".
Altrimenti non toccare.

---

## CHECKLIST FINALE PRIMA DI COMMIT

- [ ] **Pre-flight obbligatorio eseguito**: letti i file indicati in sezione 0
      (`event_server.cpp`, `myframe.cpp`, `guide_algorithm_*.cpp`, User Guide
      sezioni Exposure/Auto Exposure/Server Interface)
- [ ] **Snap obbligatorio**: `_valid_exposures` letta in `initialize()` da
      `get_exposure_durations()`, helper `_snap_exposure()` usato per ogni
      cambio (sia path A che path B)
- [ ] **Auto Exposure**: verificato in `initialize()`; se attiva, path B si
      rifiuta di operare e WARNING CRITICO loggato una volta sola
- [ ] **Evento `ConfigurationChange`**: gestito (o ignorato deliberatamente)
      con riferimento al codice esistente in `main.py`
- [ ] **`reason` della ControlAction**: include avvertenza
      "primi N frame post-cambio possono mostrare transitorio"
- [ ] Valori `dry_run` nei config NON modificati (lasciati come trovati)
- [ ] Tutti gli `enabled = false` di default in `[exposure_dynamic]`
- [ ] `guide_pixel_scale_arcsec` hardcodato per ciascun setup (1.58 / 1.03 / 0.51)
- [ ] `analyzer.reset()` chiamato dopo ogni cambio esposizione effettivo (non in DRY_RUN)
- [ ] Macchina a stati: BOOSTED_FOR_SNR e BOOSTED_FOR_SEEING mutuamente esclusivi
- [ ] Path B non attivo quando condition è OSCILLATING o LOW_SNR
- [ ] **Escalation gate**: path B non scatta senza saturazione di
      aggressiveness E MinMove di almeno un asse, persistente da ≥ cooldown
- [ ] Baseline v3 salva/ripristina i 3 campi esposizione nuovi
- [ ] `decisions_*.jsonl` distingue `camera/exposure_snr` da `camera/exposure_seeing`
- [ ] Test simulatore: nessun crash, dashboard espone il nuovo blocco `exposure`
- [ ] Rebuild eseguita, ZIP rigenerato (vedi sezione PROCEDURA REBUILD)
- [ ] `CONTESTO_PROGETTO.md` aggiornato (data + paragrafo nuovo + voce "non fatto")
- [ ] `NOTE_CLAUDE.md` aggiornato con sezione #19 completa
- [ ] Nessuna modifica alla logica aggressiveness/MinMove esistente
- [ ] Nessuna modifica alla backlash compensation di PHD2
- [ ] La feature è testabile in LIVE (Alessandro userà `dry_run = false` +
      `enabled = true` per osservare il comportamento sul grafico dashboard)

---

## DOMANDE DA FARMI PRIMA DI PROCEDERE (se servono)

Se durante l'implementazione trovi:
- Ambiguità su come integrare la macchina a stati senza rompere il path A esistente
- Necessità di aggiungere un parametro `pixel_scale_arcsec_per_px` nei config
  (valuta se prenderlo da `[setup]` esistente o aggiungere nuovo campo)
- Una scelta di design non coperta da questo brief

→ **Fermati e chiedi**, non improvvisare.

Se invece tutto è chiaro: procedi step-by-step, mostrami i diff prima di
applicarli ai file (preferisco vedere le modifiche prima del commit), poi
esegui il rebuild e aggiorna la documentazione.

Grazie.
