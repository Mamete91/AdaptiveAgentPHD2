# PROMPT PER CLAUDE CODE (Antigravity) — Plugin NINA v1.2 — Safety Monitor Virtuale
# Da copiare e incollare integralmente nella conversazione con Claude Code.
# Lavorare nella cartella: C:\Users\aless\Documents\N.I.N.A\AdaptiveAgentForPHD2.NinaPlugin\

> **NOTA OPERATIVA**: questo è un'**estensione del plugin NINA v1.1.0.0**
> creato nelle sessioni precedenti (pannello dockable WebView2 + pulsante
> Avvia Agente + badge stato). La v1.1 funziona, è installata e validata sul
> campo. NON ricreare il progetto da zero.
>
> **Cosa aggiunge questa v1.2**: il plugin espone un **Safety Monitor
> virtuale** che NINA può consumare come driver `ISafetyMonitor` (sotto la
> categoria "N.I.N.A." nella tendina del Safety Monitor). Il driver riflette
> lo stato dell'Adaptive Agent: dichiara `IsSafe = false` quando la guida è
> in **`STAR_LOST` consolidato per almeno 5 minuti**; torna a `IsSafe = true`
> quando lo stato `guiding_state == "NORMAL"` ritorna per ~45 secondi
> (3 poll consecutivi al default di 15s). NINA decide cosa fare con il
> flag (pausa, parking, alert): il plugin si limita a riflettere lo stato
> dell'Agente, non prende decisioni al posto dell'utente.
>
> **Filosofia di design**: idiomatica in NINA. Il modello Safety Monitor
> esiste esattamente per questo (sensori che dicono "safe/unsafe", l'utente
> configura cosa NINA deve fare). Il plugin si limita a essere il "sensore
> guida": NINA è il decisore. Zero invasività su `ISequenceMediator`.
>
> **Bump versione**: `1.1.0.0` → `1.2.0.0` in `AssemblyInfo.cs`. GUID
> stabile `6F2E9C19-4F66-4F69-B7D3-E21D5AD7458B` INVARIATO. La DLL ora
> espone due capability (`IDockableVM` + `ISafetyMonitor`) ma resta un
> unico assembly.

---

## 0. PRE-FLIGHT OBBLIGATORIO

### Sorgenti NINA da decompilare (con `ilspycmd`, come per v1.1)

1. **Interfaccia `ISafetyMonitor`** — verosimilmente in
   `NINA.Equipment.Interfaces` (DLL `NINA.Equipment.dll`). Da ispezionare:
   - Property obbligatorie (`IsSafe`, `Connected`, `Name`, `Description`,
     `DriverInfo`, `DriverVersion`, `Id`, `Category`, `DisplayName`, ecc.)
   - Eventuali metodi sincroni/asincroni di lifecycle
     (`Connect`/`Disconnect`/`SetupDialog`)
   - Eventi (`PropertyChanged`, eventuali eventi custom)
   - Base class fornita (probabile `BaseINPC` o `BaseDriver` o equivalente,
     come per `DockableVM`)

2. **Pattern MEF di export per equipment custom**: NINA scopre i driver
   tramite `[Export(typeof(ISafetyMonitor))]` o `[ExportMetadata]` con
   chiavi specifiche. Verificare il pattern reale dal sorgente NINA: alcuni
   equipment richiedono un attributo aggiuntivo per popolare la categoria
   ("Plugin" / "N.I.N.A." / nome custom) nella tendina del Safety Monitor.

3. **Schema `/status`** dell'Agente: già consultato nel `PROMPT_PLUGIN_NINA_AUTOPAUSE.md`
   (file presente nella stessa cartella del prompt corrente). I campi che ci
   servono sono pochi:
   - `controller.guiding_state` (enum stringificato — il valore "STAR_LOST"
     è il trigger di unsafe)
   - Eventualmente `analyzer.condition` come secondario informativo
   Tutto il resto (escalation_gate, saturation, baseline, ecc.) **NON** va
   considerato nella logica unsafe in v1.2.

### Riferimenti ispettivi (allegati alla conversazione, se Alessandro li riallega)

- `ninaAPI.dll` — plugin reale che espone NINA via REST. Ispezionalo come
  hai già fatto per v1.0/v1.1 per pattern `Logger`, `INotificationManager`,
  settings persistence (ormai dovresti averli memorizzati nei project memory).
- Eventuali altri plugin NINA che esportano `ISafetyMonitor` (cerca tra i
  plugin nella cartella `%LOCALAPPDATA%\NINA\Plugins\3.0.0\` se ne trovi).

### Decisioni di design (già prese — implementare così)

a. **Identità del driver**: visibile in NINA come categoria "N.I.N.A." (o
   "Plugin" se MEF lo posiziona automaticamente). Il `DisplayName` esposto:
   `"Adaptive Agent for PHD2 — Guide Safety"`. La `Description`:
   `"Riflette lo stato della guida dell'Adaptive Agent: dichiara unsafe quando STAR_LOST persiste oltre il timeout configurato (default 5 minuti)."`
   `DriverInfo`: nome plugin + versione 1.2.0.0.
   `Id`: deve essere un GUID stabile **distinto** dal GUID del plugin
   stesso (es. genera un secondo GUID con `Guid.NewGuid()` UNA VOLTA SOLA
   e hard-codalo). Suggerimento: `B-7F1A2C5D-9E3F-4B6A-A2C8-D4E5F60718A9`
   (verifica che sia un GUID valido e univoco prima di usarlo).

b. **Stati esposti**:
   - `Connected = true` quando il driver è collegato in NINA E l'Agente
     risponde (sia a `/about` sia a `/status` entro timeout 3s).
   - `Connected = false` quando l'Agente non risponde o smette di
     rispondere — il plugin si auto-disconnette silenziosamente. NINA
     vedrà il driver disconnesso e applicherà la sua policy di
     "safety disconnesso" (configurabile dall'utente nelle settings NINA).
   - `IsSafe = false` quando `guiding_state == "STAR_LOST"` per N tick
     consecutivi (N = `StarLostConsolidationSeconds / HealthCheckIntervalSeconds`,
     default 300/15 = 20 tick = 5 minuti). All'arrivo del primo tick non-STAR_LOST
     prima del consolidamento, il contatore si resetta.
   - `IsSafe = true` quando la condizione torna `guiding_state == "NORMAL"`
     per 3 poll consecutivi (~45s al default), oppure all'avvio del
     driver (default "safe" finché non si dimostra il contrario).

c. **Asimmetria intenzionale dei tempi**:
   - Verso unsafe: 5 minuti consolidati (alta evidenza richiesta —
     l'Agente con AI Star Finder DOVREBBE recuperare entro 5 minuti se è
     possibile recuperare; oltre quel tempo è un'emergenza vera).
   - Verso safe: ~45s (bassa soglia — appena la guida torna stabile vogliamo
     riprendere la sequenza in fretta per non perdere finestre di
     acquisizione).
   Documentare questa asimmetria nei commenti del decision engine.

d. **Stati NEUTRALI** (non triggerano nulla, contatore unsafe si resetta):
   - `guiding_state == "INACTIVE"` (PHD2 non sta guidando: stato di
     transito normale tra target, sequenza tra scatti, ecc.)
   - `guiding_state == "DEGRADED"`, `"CRITICAL"`, `"RECOVERING"`
     (l'Agente sta lavorando attivamente per mitigare — non è
     un'emergenza)
   - `guiding_state == null` o payload incompleto (no-op silenzioso,
     contatore non si tocca)

e. **Settings**: riuso `HealthCheckIntervalSeconds` della v1.1 (stesso
   intervallo di polling per badge e safety). Una sola nuova property:
   `StarLostConsolidationSeconds` (default 300, range 30-1800). Nessun
   toggle "Safety enabled" lato plugin — è la selezione in NINA che
   decide: se l'utente seleziona il nostro driver nella tendina del
   Safety Monitor di NINA, è attivo; altrimenti il MEF export esiste ma
   non viene mai connesso.

f. **Polling**: il poller `AgentHealthChecker` v1.1 va esteso a chiamare
   anche `GET /status` quando il safety driver è connesso. Quando NON è
   connesso, continua a fare solo `GET /about` come oggi (efficienza:
   non sprecare banda su payload più pesante se non serve). Pattern:
   il driver Safety Monitor "abbona" se stesso al poller in
   `Connect()` e si disabbona in `Disconnect()`.

### Nessuna verifica → STOP

Se durante il pre-flight scopri:
- L'interfaccia reale non è `ISafetyMonitor` ma ha un altro nome
  → segnala e adattati.
- Il pattern MEF richiede un wrapper più complesso (es. una factory)
  → segnala prima di scrivere il driver.
- Una base class fornita da NINA (es. `BaseSafetyMonitor`, `BaseINPC`)
  semplifica molto l'implementazione → usa quella e segnalalo.
- Conflitti di `Id` GUID con altri driver esistenti (raro ma possibile)
  → rigenera l'Id e segnala.

→ **Fermati e chiedi**, non improvvisare.

---

## OBIETTIVO TECNICO

Estendere il plugin NINA v1.1.0.0 esistente con un secondo MEF export
`[Export(typeof(ISafetyMonitor))]` rappresentato dalla nuova classe
`AdaptiveAgentSafetyMonitor`. Il driver è auto-contenuto, non interferisce
con il pannello dockable WebView2 esistente, e si appoggia al poller
`AgentHealthChecker` v1.1 (esteso per leggere `/status` quando il driver
è connesso). Decisione `IsSafe` basata su singola condizione (`STAR_LOST`
consolidato 5 minuti), `IsSafe → true` rapido (~45s). Settings minimali:
una sola nuova property. Bumpare versione a `1.2.0.0`. GUID plugin
invariato.

---

## REGOLE INDEROGABILI

- **NON modificare** il codice Python dell'Adaptive Agent for PHD2.
- **NON cambiare** GUID assembly né `Id` del manifest plugin
  (`6F2E9C19-4F66-4F69-B7D3-E21D5AD7458B`). Il GUID del Safety Monitor
  (property `Id`) è invece un GUID separato univoco da generare una sola
  volta e hard-codare nella classe.
- **NON rimuovere** né modificare le funzionalità v1.0 (pannello WebView2
  intatto) e v1.1 (pulsante Avvia + badge stato — intatti).
- **NON chiamare** `ISequenceMediator.PauseSequence()`. Il driver si limita
  ad aggiornare la property `IsSafe`. NINA decide cosa fare.
- **NON includere** altre condizioni di unsafe oltre a `STAR_LOST`. In
  particolare:
  - NON includere `escalation_gate.ra && escalation_gate.dec` (è uno stato
    in cui l'Agente sta giustamente per attivare il path B esposizione, NON
    un'emergenza).
  - NON includere `saturation.active` (è un'azione di recovery dell'AI
    Star Finder, NON un fallimento).
  - NON includere RMS oltre soglia (la soglia è dinamica, e quando viene
    superata l'Agente sta già reagendo).
- **NON propagare** eccezioni di rete fuori dai servizi: gestione
  silenziosa come per v1.1.
- **NON loggare** ogni singolo tick di polling. Solo le transizioni
  (`safe → unsafe`, `unsafe → safe`, `connected → disconnected`,
  `disconnected → connected`).
- **NON forzare** il driver come "selezionato di default" in NINA. Resta
  che l'utente debba esplicitamente scegliere il nostro Safety Monitor
  dalla tendina.

---

## SPECIFICA FUNZIONALE

### 2A. Nuova classe `AdaptiveAgentSafetyMonitor`

File nuovo: `src/AdaptiveAgentForPHD2.NinaPlugin/Safety/AdaptiveAgentSafetyMonitor.cs`

Eredita da `BaseINPC` (o equivalente NINA), implementa `ISafetyMonitor`.
Marcata `[Export(typeof(ISafetyMonitor))]` via MEF, eventuali metadata
aggiuntivi come scoperti nel pre-flight.

Property minime (verifica firma esatta dal pre-flight):

```csharp
public string Name        => "Adaptive Agent for PHD2 — Guide Safety";
public string DisplayName => Name;
public string Description => "Riflette lo stato della guida dell'Adaptive Agent for PHD2. Dichiara unsafe quando STAR_LOST persiste oltre il timeout configurato (default 5 minuti).";
public string DriverInfo  => $"Adaptive Agent for PHD2 v1.2.0.0 — Safety Monitor virtuale";
public string DriverVersion => "1.2.0.0";
public string Category    => "N.I.N.A."; // o stringa attesa da NINA per popolare la categoria — verifica
public string Id          => "B7F1A2C5D-9E3F-4B6A-A2C8-D4E5F60718A9"; // GUID stabile, distinto dal GUID plugin
public bool IsSafe        { get; private set; } = true;  // ottimistico all'avvio
public bool Connected     { get; private set; } = false;
```

Metodi (verifica firma esatta dal pre-flight):

```csharp
public Task<bool> Connect(CancellationToken token);
public void Disconnect();
public bool HasSetupDialog => false;
public void SetupDialog();   // no-op
```

Il `Connect` deve:
1. Abbonarsi al poller condiviso (`AgentServices.HealthChecker`) per
   ricevere gli aggiornamenti dello stato.
2. Istruire il poller a iniziare a leggere `/status` (oltre a `/about`).
3. Inizializzare il decision engine.
4. Tentare il primo `/status` immediato per popolare lo stato iniziale.
5. Se riesce: `Connected = true`, `IsSafe = true`, ritorna `true`.
6. Se fallisce (timeout/errore): `Connected = false`, ritorna `false`.

Il `Disconnect`:
1. Resetta `Connected = false`, `IsSafe = true` (stato neutro).
2. Disabbona dal poller e istruisce il poller a fermare la lettura di
   `/status` (torna a solo `/about`).
3. Resetta il decision engine.

### 2B. Estensione del poller `AgentHealthChecker`

File esistente da modificare: `src/AdaptiveAgentForPHD2.NinaPlugin/Health/AgentHealthChecker.cs`.

Aggiungere:
- Property/metodo `bool StatusPollingEnabled` con setter pubblico (chiamato
  dal SafetyMonitor in `Connect`/`Disconnect`).
- Quando `StatusPollingEnabled == true`, il tick di polling oltre a fare
  `GET /about` fa anche `GET /status` con timeout 3s.
- Evento `StatusUpdated(AgentStatusSnapshot snap)` che propaga i campi
  rilevanti deserializzati. DTO minimale `AgentStatusSnapshot`:

  ```csharp
  public sealed record AgentStatusSnapshot(
      string? GuidingState,    // controller.guiding_state
      bool IsValid             // false se payload null/incompleto
  );
  ```

  NON deserializzare tutto il JSON — leggi solo i due campi che servono.
  Usa `System.Text.Json.JsonDocument` per accesso mirato senza creare DTO
  pesanti.
- Se `/status` fallisce o ritorna payload malformato: emetti
  `AgentStatusSnapshot(null, false)` — il decision engine lo tratterà come
  no-op.

### 2C. Decision Engine `SafetyDecisionEngine`

File nuovo: `src/AdaptiveAgentForPHD2.NinaPlugin/Safety/SafetyDecisionEngine.cs`

Stato interno:

```csharp
private int _starLostStreakTicks;   // tick consecutivi in STAR_LOST
private int _normalStreakTicks;     // tick consecutivi in NORMAL (per resume)
private bool _currentlyUnsafe;
```

Metodo principale (chiamato ad ogni tick di polling dal `Connect`-time poller):

```csharp
public SafetyDecision Evaluate(AgentStatusSnapshot snap, PluginSettings settings)
{
    if (!snap.IsValid) {
        // No-op: payload incompleto, mantieni stato precedente
        return SafetyDecision.NoChange;
    }

    bool isStarLost = snap.GuidingState == "STAR_LOST";
    bool isNormal   = snap.GuidingState == "NORMAL";

    if (isStarLost) {
        _starLostStreakTicks++;
        _normalStreakTicks = 0;
        int consolidationTicks = settings.StarLostConsolidationSeconds
                                / settings.HealthCheckIntervalSeconds;
        if (!_currentlyUnsafe && _starLostStreakTicks >= consolidationTicks) {
            _currentlyUnsafe = true;
            return SafetyDecision.BecameUnsafe;
        }
    } else if (isNormal && _currentlyUnsafe) {
        _normalStreakTicks++;
        _starLostStreakTicks = 0;
        const int RESUME_TICKS = 3;  // ~45s al default 15s
        if (_normalStreakTicks >= RESUME_TICKS) {
            _currentlyUnsafe = false;
            return SafetyDecision.BecameSafe;
        }
    } else {
        // INACTIVE, DEGRADED, CRITICAL, RECOVERING, o altro stato neutro:
        // reset solo del contatore STAR_LOST (siamo "fuori dall'emergenza"
        // ma non ancora "confermato ritorno alla normalità")
        _starLostStreakTicks = 0;
        if (!isNormal) _normalStreakTicks = 0;
    }

    return SafetyDecision.NoChange;
}
```

```csharp
public enum SafetyDecision { NoChange, BecameUnsafe, BecameSafe }
```

Il `SafetyMonitor` riceve la decisione, aggiorna `IsSafe`, logga e notifica.

### 2D. Settings page — una sola nuova property

File esistente da modificare: `src/AdaptiveAgentForPHD2.NinaPlugin/Settings/PluginSettings.cs`.

Aggiungere:

```csharp
public int StarLostConsolidationSeconds { get; set; } = 300;  // 5 minuti default, range 30-1800
```

Aggiornare il file XAML della settings page per esporla con tooltip:
"Tempo in secondi che `STAR_LOST` deve persistere prima che il Safety Monitor dichiari unsafe. Default 5 minuti. Aumentando il valore si riducono i falsi positivi al prezzo di un riconoscimento più lento; diminuendo si rischia di triggerare unsafe su STAR_LOST transienti che l'Agente avrebbe recuperato."

Persistenza JSON: il file `settings.json` esistente accoglierà la nuova
chiave; gli utenti che aggiornano da v1.1 si ritroveranno il default 300
applicato automaticamente al primo run.

### 2E. Integrazione nel composition root `AgentServices`

File esistente da modificare: `src/AdaptiveAgentForPHD2.NinaPlugin/AgentServices.cs`.

Aggiungere come `Lazy<T>`:

```csharp
public Lazy<SafetyDecisionEngine> SafetyEngine { get; }
    = new(() => new SafetyDecisionEngine());
```

Il `AdaptiveAgentSafetyMonitor` accede al poller e al decision engine
tramite il composition root (stesso pattern di v1.1, evita di rompere
la firma del costruttore MEF).

### 2F. Lifecycle nel plugin entry point

File esistente da modificare: `Plugin/AdaptiveAgentForPHD2Plugin.cs`.

`Initialize` resta com'è (`HealthChecker.Start()`). `Teardown` resta com'è.
Il driver Safety Monitor è gestito da NINA via il proprio lifecycle
(`Connect`/`Disconnect`), non dal plugin.

### 2G. Logging e notifiche

Tramite `Logger` NINA (Info livello), loggare SOLO le transizioni:
- "Adaptive Agent Safety Monitor: connesso — Agente online"
- "Adaptive Agent Safety Monitor: disconnesso — Agente non raggiungibile"
- "Adaptive Agent Safety Monitor: UNSAFE — STAR_LOST consolidato da N minuti"
- "Adaptive Agent Safety Monitor: SAFE — guida tornata NORMAL"

Tramite `Notification.ShowWarning` (o equivalente):
- Sulla transizione UNSAFE: toast con messaggio
  "Adaptive Agent: guida persa da 5 minuti — Safety Monitor unsafe".
- Sulla transizione SAFE: toast informativo (Info, non Warning)
  "Adaptive Agent: guida ripristinata — Safety Monitor safe".

---

## TEST ATTESI

### Test manuali

1. **Build pulita**: `dotnet build -c Release` → 0 errori 0 warning.
2. **Install + load**: install script copia DLL v1.2.0.0, NINA riavviato
   carica plugin senza errori.
3. **Driver visibile in NINA**: nella tendina Equipment → Safety Monitor,
   sotto la categoria N.I.N.A., compare
   "Adaptive Agent for PHD2 — Guide Safety".
4. **Connect riuscito con Agente acceso**: selezioni il driver, click
   Connect, badge verde "Sicuro" nella view Safety Monitor di NINA.
5. **Connect fallito con Agente spento**: spegni l'Agente, click Connect,
   il driver fallisce e si auto-disconnette. Log informativo, niente
   crash.
6. **Disconnessione automatica su perdita Agente**: con driver connesso,
   spegni l'Agente. Entro il tempo di polling il driver passa a
   Disconnected. Toast notifica.
7. **Transizione UNSAFE**: simula con NINA simulator + Agente simulator
   un `STAR_LOST` persistente. Dopo 5 minuti (verifica con un valore di
   test ridotto, es. `StarLostConsolidationSeconds = 30` per facilitare
   il test), il driver passa a `IsSafe = false`, NINA notifica.
8. **Transizione SAFE**: dopo unsafe, simula ritorno a NORMAL. Dopo ~45s
   il driver torna `IsSafe = true`.
9. **Stati neutrali**: `DEGRADED`, `CRITICAL`, `RECOVERING`, `INACTIVE`
   non triggerano alcun cambio di stato (contatore STAR_LOST si resetta
   se non in STAR_LOST). Verifica esplicita con simulator.
10. **v1.1 invariata**: il pannello WebView2 + il pulsante Avvia
    Adaptive Agent + il badge stato funzionano esattamente come prima.

### Test unitari (consigliati)

- `SafetyDecisionEngineTests`:
  - Streak STAR_LOST → BecameUnsafe al raggiungimento consolidamento
  - Streak interrotto da NORMAL → reset (non triggera)
  - Streak interrotto da DEGRADED → reset (non triggera)
  - Resume NORMAL × 3 dopo unsafe → BecameSafe
  - Payload IsValid=false → NoChange e nessun reset
  - Calcolo consolidamento ticks corretto (300/15=20)

---

## VALIDAZIONE SUL CAMPO

Dopo l'install, in NINA:
1. Verifica versione 1.2.0.0 nel manager plugin.
2. Vai in Equipment → Safety Monitor, selezione il nostro driver dalla
   tendina, clicca Connect. Badge verde "Sicuro" deve apparire.
3. Lascia il driver connesso per qualche sessione reale di acquisizione.
   Osserva i log NINA: deve esserci una sola riga "connesso" all'avvio,
   eventuali transizioni connected/disconnected sulla base della
   reachability dell'Agente, e niente rumore.
4. Quando capita un `STAR_LOST` reale che persiste oltre 5 minuti (es.
   passaggio nuvoloso pesante senza recovery dell'AI Star Finder),
   verifica che il driver transiti a unsafe e che NINA reagisca secondo
   la tua configurazione safety (alert, pausa, ecc.).

---

## PROCEDURA REBUILD E INSTALL

Identica alla v1.0/v1.1:

```powershell
cd C:\Users\aless\Documents\N.I.N.A\AdaptiveAgentForPHD2.NinaPlugin\src\AdaptiveAgentForPHD2.NinaPlugin
dotnet build -c Release -p:Platform=x64
cd ..\..
powershell -ExecutionPolicy Bypass -File scripts\install-plugin.ps1 -NinaVersion 3.0.0
```

NINA chiuso prima dell'install.

---

## AGGIORNAMENTO DOCUMENTAZIONE

**Da fare solo dopo validazione sul campo** (regola di sempre):
- §29 in `NOTE_CLAUDE.md` del repo Python con struttura standard.
- Estensione della sezione "Bonus: usare la dashboard dentro NINA" del
  manuale (md + txt + PDF) con un sotto-paragrafo "Novità v1.2: Safety
  Monitor virtuale".
- Aggiunta opzionale nel `LEGGIMI_PER_AVVIARE.txt`.

NON aggiornare ora questi file.

---

## CHECKLIST FINALE PRIMA DI COMMIT

- [ ] Pre-flight: ispezionata `ISafetyMonitor` con `ilspycmd`, firme reali
      confermate
- [ ] Versione bumpata a `1.2.0.0` in `AssemblyInfo.cs`
- [ ] GUID plugin INVARIATO
- [ ] GUID Safety Monitor `Id` separato e univoco
- [ ] Pannello WebView2 v1.0 invariato (verifica dopo build)
- [ ] Pulsante Avvia + badge v1.1 invariati (verifica dopo build)
- [ ] Driver Safety Monitor visibile e selezionabile in NINA
- [ ] Connect/Disconnect funzionanti con auto-disconnessione su perdita
      Agente
- [ ] Decision engine corretto: solo STAR_LOST consolidato 5 min triggera
      unsafe, solo NORMAL × 3 tick triggera safe
- [ ] Nessuna delle altre condizioni (escalation_gate, saturation, RMS)
      triggera unsafe
- [ ] Settings esposte: `StarLostConsolidationSeconds` con default 300,
      range 30-1800
- [ ] `dotnet build -c Release` 0 errori 0 warning
- [ ] NINA carica v1.2.0.0 senza errori
- [ ] Test manuali 1-10 passati

---

## DOMANDE PRIMA DI PROCEDERE (se servono)

Se pre-flight rivela:
- `ISafetyMonitor` con metodi/property significativamente diversi dal
  modello qui descritto → adatta al reale e segnalalo.
- Pattern MEF per popolare la categoria custom non esiste → usa la
  categoria di default (probabile "Plugin") e segnalalo.
- Conflitti di build dovuti al fatto che ora la DLL esporta due
  interfacce MEF → risolvi e segnala.

→ **Fermati e chiedi**, non improvvisare.

Se tutto torna: procedi step-by-step. Mostra il diff del driver
`AdaptiveAgentSafetyMonitor` prima di applicarlo (è il punto di rischio
massimo: se la firma dell'interfaccia sbaglia, NINA non vede il driver).
Stima totale ~250-350 righe C# nuove (driver + decision engine + estensione
poller + settings + lifecycle). Se superi le 500, fermati e capiamo
insieme cosa abbiamo gonfiato.

Grazie.
