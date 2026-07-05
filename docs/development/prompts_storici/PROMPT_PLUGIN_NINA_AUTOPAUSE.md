# PROMPT PER CLAUDE CODE (Antigravity) — Plugin NINA v1.1 — Auto-Pausa Sequenza
# Da copiare e incollare integralmente nella conversazione con Claude Code.
# Lavorare nella cartella: C:\Users\aless\Documents\N.I.N.A\AdaptiveAgentForPHD2.NinaPlugin\

> **NOTA OPERATIVA**: questo è un **estensione del plugin NINA esistente**
> creato nella sessione precedente (v1.0.0.0 — pannello dockable WebView2 della
> dashboard dell'Adaptive Agent for PHD2). NON ricreare il progetto da zero.
> Il plugin compilato funziona, è installato in
> `%LOCALAPPDATA%\NINA\Plugins\3.0.0\AdaptiveAgentForPHD2.NinaPlugin\`, GUID
> stabile `6F2E9C19-4F66-4F69-B7D3-E21D5AD7458B` (NON cambiare).
>
> **Cosa aggiunge questa v1.1**: una logica di **polling periodico** dello
> stato dell'Agente Python (via `http://localhost:8080/status`) con
> **pausa/ripresa automatica della sequenza NINA** quando lo stato della guida
> degrada in modo sostenuto. Il pannello dockable WebView2 esistente resta
> invariato (continua a mostrare la dashboard). La nuova funzione vive in
> parallelo: un servizio in background + una settings page nel pannello
> plugin di NINA.
>
> **Bump versione**: `1.0.0.0` → `1.1.0.0`. Aggiornare in `AssemblyInfo.cs`
> sia gli attributi `[AssemblyVersion]`/`[AssemblyFileVersion]` sia i
> manifest `AssemblyMetadata` se previsto. GUID INVARIATO.
>
> **Allegati alla conversazione (riferimento ispettivo prioritario)**:
> `ninaAPI.dll`, `EmbedIO.dll`, `Swan.Lite.dll`. Il primo è un plugin NINA
> esistente (di altro autore) che espone NINA via REST API, e usa
> **esattamente** i servizi NINA che servono a noi: `ISequenceMediator` per
> pause/resume, `INotificationManager` per le notifiche, `Logger` per il
> logging. **Ispezionarlo con ILSpy/dotPeek/`ildasm` è il pre-flight più
> efficace**: trovi nomi reali di interfacce, firme reali dei metodi, modo
> reale di iniettarli via `[ImportingConstructor]`. NON copiare codice — usa
> come riferimento di pattern. `EmbedIO` e `Swan.Lite` sono dipendenze server
> di ninaAPI: non rilevanti per noi, ma utili per capire come ninaAPI ospita
> un server HTTP nel suo `[ImportingConstructor]`.

---

## 0. PRE-FLIGHT OBBLIGATORIO (leggere PRIMA di scrivere codice)

### Sorgenti reali da consultare (schema JSON dell'Agente)

1. **`C:\Users\aless\Downloads\PHD2_Assist_PATCHED\PHD2_Assist_PATCHED\server.py`**
   - Riga ~138: `@app.get("/status")` definisce la risposta JSON dell'endpoint.
   - Riga ~145-165: il blocco `analyzer_status` (campi top-level del JSON sotto
     la chiave `analyzer`): `rms_ra`, `rms_dec`, **`rms_total`** (RMS live in
     arcsec — questo è il campo da usare come "RMS corrente"),
     `snr_avg`, `hfd_avg`, `condition` (enum stringificato:
     `"NOMINAL"`, `"DEGRADED_SEEING"`, `"OSCILLATING"`, `"LOW_SNR"`).

2. **`C:\Users\aless\Downloads\PHD2_Assist_PATCHED\PHD2_Assist_PATCHED\phd2_agent\controller.py`**
   - Riga ~1390-1480: metodo `get_status()`, costruisce il blocco
     `controller` del JSON. Campi rilevanti per la pausa:
     - `guiding_state` — enum stringificato:
       `"INACTIVE"`, `"NORMAL"`, `"DEGRADED"`, `"CRITICAL"`,
       **`"STAR_LOST"`** (questo è il valore reale per "stella persa"),
       `"RECOVERING"`. **NON `"LostLock"` né `"Guiding"`** (quelli erano
       nomi presunti del briefing originale, non i valori reali).
     - `escalation_gate.ra`, `escalation_gate.dec` — bool.
     - `escalation_gate.enabled` — bool (la feature è opt-in; se è `false`
       i flag `ra`/`dec` non sono segnali significativi).
     - `saturation.active` — bool.
     - `auto_calibration.baseline_rms_arcsec` — mediana di calibrazione,
       può essere `null` durante la fase di campionamento o se rifiutata.
       **NON è l'RMS corrente.** Usalo solo per logica "baseline pronta sì/no".
     - `auto_calibration.baseline_done`, `baseline_rejected` — bool.
     - `auto_calibration.rms_high_active` — soglia high dinamica corrente.

3. **Schema JSON top-level reale** (eseguito a freddo, Agente con PHD2 non
   in guida). Quello che Alessandro ti ha mostrato nel briefing è
   INCOMPLETO — il vero JSON include anche il blocco `analyzer` accanto a
   `controller`:
   ```json
   {
     "controller": {
       "guiding_state": "INACTIVE",
       "escalation_gate": { "enabled": true, "ra": false, "dec": false },
       "saturation": { "active": false, "elapsed_s": 0.0, "info": {} },
       "auto_calibration": {
         "baseline_rms_arcsec": null,
         "rms_high_active": 1.0,
         "baseline_done": false,
         "baseline_rejected": false
       },
       ... (altri campi: ra, dec, exposure, ...)
     },
     "analyzer": {
       "rms_total": 0.0,
       "snr_avg": 0.0,
       "condition": "NOMINAL",
       ... (altri campi)
     }
   }
   ```
   Verifica dal vivo eseguendo `curl http://localhost:8080/status` o leggendo
   da PowerShell `Invoke-WebRequest`. Adatta la classe DTO C# allo schema
   REALE, non a quello presunto del briefing.

### File DLL allegati (riferimento ispettivo PRIORITARIO)

1. **`ninaAPI.dll`** — plugin NINA che espone NINA via server REST EmbedIO.
   Usa internamente:
   - `ISequenceMediator` (o variante) per pause/resume/lifecycle sequenza
   - `INotificationManager` (o variante) per toast/notifications
   - Logging tramite la classe `Logger` di NINA o servizio iniettato
   - Settings persistence dei propri config
   Decompilare con ILSpy/dotPeek (`dotnet-ildasm` se preferisci CLI),
   **leggere i nomi reali e le firme reali**. Adattare il nostro codice a
   quei pattern. NON copiare codice (è di altro autore, altra licenza),
   **copiare solo il pattern di uso delle API NINA**.

2. **`EmbedIO.dll`** e **`Swan.Lite.dll`** — server HTTP embedded che usa
   ninaAPI. **Per noi NON rilevanti**: noi siamo client HTTP, non server.
   Ignorabili.

### File Python da NON toccare

Tutto il codice dell'Adaptive Agent for PHD2 in
`C:\Users\aless\Downloads\PHD2_Assist_PATCHED\PHD2_Assist_PATCHED\` resta
**invariato**. Il plugin v1.1 è solo client HTTP: legge `/status`, non
scrive. Non `POST`, non `PUT`, non query parameter custom. Solo `GET /status`
periodico.

### Decisioni di design (già prese — implementare così)

a. **Polling = HttpClient long-lived** (NON un'istanza nuova per ogni call:
   esaurirebbe le socket). Idealmente singleton statico di servizio o
   iniettato via `IHttpClientFactory` se NINA lo espone.

b. **DTO C# allineato allo schema REALE** del JSON (vedi pre-flight 2 e 3),
   non a quello presunto. Usa `System.Text.Json` (built-in .NET 8). Marcare
   campi nullable: `string? guiding_state`, `double? baseline_rms_arcsec`,
   ecc. Mai assumere campi non-null.

c. **Settings persistite** secondo il pattern NINA standard (probabile
   `Properties.Settings` auto-generate, o file JSON in
   `%LOCALAPPDATA%\NINA\Plugins\Settings\<plugin-id>\`). Verifica dal
   template ufficiale o da ninaAPI.dll.

d. **Toggle "auto-pausa abilitata" = OFF di default**. Non automatismo
   silenzioso: l'utente deve esplicitamente attivare la funzione dalla
   settings page. Quando OFF, il polling continua (per mostrare lo stato
   live nella UI del plugin) ma nessuna chiamata `PauseSequence()` viene
   fatta.

e. **Hysteresis a 3 poll consecutivi** (default, configurabile 1-10). Sia
   per pausa che per ripresa. Evita flap quando le condizioni oscillano
   intorno alla soglia.

f. **Connection refused = silent stop**. Se `localhost:8080` non risponde
   (Agente non avviato o spento), il polling logga UNA volta a livello
   `Info` "Adaptive Agent non raggiungibile, polling in standby", poi
   continua a ritentare alla cadenza normale senza loggare a ogni tick.
   Quando l'Agente torna disponibile, logga "Adaptive Agent di nuovo
   raggiungibile". Mai propagare eccezioni di rete fuori dal servizio di
   polling — NINA non deve mai vedere stack trace HTTP per colpa nostra.

### Nessuna verifica → STOP

Se durante il pre-flight scopri:
- che `ISequenceMediator` in NINA 3.3 NON espone `PauseSequence()` /
  `ResumeSequence()` con quei nomi, ma con nomi diversi o tramite un
  modello a comandi (es. `Execute(PauseCommand)`) → **adatta al reale e
  segnalalo nel riepilogo**, non improvvisare nomi.
- che il toast/notification system di NINA usa un'API diversa da
  `INotificationManager` → **usa quella reale**.
- che NINA 3.3 ha già una "Safety Monitor" o "Pause on guide loss"
  built-in che fa già qualcosa di simile → **fermati e segnalalo**:
  potremmo voler offrire al plugin una modalità "passiva" (solo log,
  no pause) per non duplicare l'azione.

---

## OBIETTIVO TECNICO

Estendere il plugin NINA v1.0.0.0 esistente con un servizio di polling
periodico (`HttpClient → http://localhost:8080/status`) e una logica di
pausa/ripresa automatica della sequenza NINA basata su tre condizioni
sostenute per N poll consecutivi (default 3). Aggiungere una settings page
del plugin per configurare polling interval, N consecutivi, e il toggle
master "auto-pause enabled" (default OFF). Il pannello WebView2 esistente
resta invariato. Bumpare versione a `1.1.0.0`.

---

## REGOLE INDEROGABILI

- **NON modificare** il codice Python dell'Adaptive Agent for PHD2: il
  plugin è puro client HTTP, accede solo a `GET /status`.
- **NON rimuovere** il pannello dockable WebView2 esistente: la v1.1 lo
  affianca, non lo sostituisce.
- **NON cambiare** il GUID `6F2E9C19-4F66-4F69-B7D3-E21D5AD7458B` né
  l'`Id` del manifest plugin. Cambiarli farebbe sì che NINA tratti v1.1
  come plugin diverso, con doppia voce e perdita settings v1.0.
- **NON forzare** `auto-pause enabled = true` di default. Toggle OFF è
  un vincolo di sicurezza: il software non deve mai prendere il controllo
  della sequenza dell'utente senza un consenso esplicito.
- **NON propagare** eccezioni di rete fuori dal servizio polling. NINA
  non deve mai vedere stack trace HTTP per colpa nostra (sarebbe un crash
  reputazionale).
- **NON introdurre** dipendenze pesanti. Usa `HttpClient`,
  `System.Text.Json`, `System.Threading.Timer` (o `PeriodicTimer` .NET 6+)
  già presenti nel framework. Niente Polly, niente Refit, niente
  Newtonsoft.Json: il payload è semplice, lo stdlib basta.
- **NON loggare** a livello `Error` per situazioni normali (es. Agente
  spento). `Info` o `Debug` al massimo, per non sporcare i log NINA.
- **NON chiamare** `PauseSequence()` ripetutamente: se la sequenza è già
  in pausa, è no-op ma sporca i log. Mantieni stato interno
  `_sequencePausedByUs: bool` e agisci solo sulle transizioni.
- Mantenere stile C# idiomatico, type hints completi (`var` con tipo
  inferibile, `nullable` annotations), brace Allman.

---

## SPECIFICA FUNZIONALE

### 2A. Nuovo servizio `AgentStatusPoller`

File nuovo: `src/AdaptiveAgentForPHD2.NinaPlugin/AutoPause/AgentStatusPoller.cs`

Responsabilità:
- Mantenere un `HttpClient` long-lived
- Eseguire `GET /status` ogni `PollIntervalSeconds` (default 30)
- Deserializzare in DTO `AgentStatus`
- Esporre evento `StatusUpdated(AgentStatus)` o property con `INotifyPropertyChanged` per la UI
- Catturare ogni eccezione (`HttpRequestException`, `JsonException`,
  `TaskCanceledException`) e gestirle silenziosamente (vedi regole)

Schema DTO minimale (allineato a JSON reale del pre-flight, NON al briefing):

```csharp
public sealed class AgentStatus
{
    public ControllerStatus? Controller { get; set; }
    public AnalyzerStatus?   Analyzer   { get; set; }
}

public sealed class ControllerStatus
{
    public string? guiding_state { get; set; }                   // "INACTIVE" | "NORMAL" | "DEGRADED" | "CRITICAL" | "STAR_LOST" | "RECOVERING"
    public EscalationGate? escalation_gate { get; set; }
    public Saturation? saturation { get; set; }
    public AutoCalibration? auto_calibration { get; set; }
}

public sealed class EscalationGate
{
    public bool enabled { get; set; }
    public bool ra { get; set; }
    public bool dec { get; set; }
}

public sealed class Saturation
{
    public bool active { get; set; }
}

public sealed class AutoCalibration
{
    public double? baseline_rms_arcsec { get; set; }    // mediana cal, NON RMS live
    public double? rms_high_active { get; set; }
    public bool baseline_done { get; set; }
    public bool baseline_rejected { get; set; }
}

public sealed class AnalyzerStatus
{
    public double rms_total { get; set; }               // RMS live in arcsec — questo è il dato corretto
    public double snr_avg { get; set; }
    public string? condition { get; set; }
}
```

I nomi PascalCase fanno scattare il default di `System.Text.Json` che
matcha case-insensitive, oppure usa
`[JsonPropertyName("guiding_state")]` per essere espliciti. Verifica nei
test che il payload reale viene deserializzato correttamente.

### 2B. Logica di trigger pausa (`AutoPauseDecisionEngine`)

File nuovo: `src/AdaptiveAgentForPHD2.NinaPlugin/AutoPause/AutoPauseDecisionEngine.cs`

Riceve in input ogni `AgentStatus` aggiornato e mantiene un contatore
"poll consecutivi in condizione critica" per ciascun trigger.

**Condizione di pausa** (almeno una vera per N poll consecutivi):

1. `guiding_state == "STAR_LOST"` → stella persa
2. `analyzer.rms_total > controller.auto_calibration.rms_high_active`
   AND `controller.auto_calibration.baseline_done == true`
   AND `controller.auto_calibration.rms_high_active != null`
   → RMS live oltre soglia high dinamica, con soglia significativa
3. `controller.escalation_gate.enabled == true`
   AND `controller.escalation_gate.ra == true`
   AND `controller.escalation_gate.dec == true`
   → entrambi gli assi saturi, guida al limite delle leve "cheap"
4. `controller.saturation.active == true` → stella satura tracciata
   (caso meno comune ma vale la pena gestire — l'Agente sta cercando di
   recuperare e qualsiasi scatto durante questa fase è da scartare)

**Condizione di ripresa** (TUTTE vere per N poll consecutivi):

1. `guiding_state == "NORMAL"` (NON `"Guiding"` — quello non esiste)
2. `analyzer.rms_total <= controller.auto_calibration.rms_high_active`
   (oppure soglia non significativa, es. baseline non pronta — allora
   passa)
3. NOT (`escalation_gate.ra && escalation_gate.dec`)
4. NOT `saturation.active`

**Stati ignorati** (no-op):
- `guiding_state == "INACTIVE"`: l'Agente è connesso ma PHD2 non sta
  guidando. Plugin attende, non fa né pause né resume.
- `guiding_state == null` o `controller == null`: payload incompleto,
  ignorare il poll.

Stato interno minimale:

```csharp
private int _pauseTriggerStreak = 0;      // poll consecutivi che chiedono pause
private int _resumeTriggerStreak = 0;     // poll consecutivi che chiedono resume
private bool _sequencePausedByUs = false; // abbiamo NOI messo in pausa?
```

Quando uno streak raggiunge `N` (default 3): emette comando
`PauseSequence` / `ResumeSequence` al mediator e logga + notifica con
motivo specifico ("Stella persa", "Seeing critico sostenuto", "Guida al
limite — leve sature", "Stella satura").

### 2C. Integrazione con NINA `ISequenceMediator`

File nuovo: `src/AdaptiveAgentForPHD2.NinaPlugin/AutoPause/SequenceController.cs`

Wrapper sull'interfaccia mediator di NINA (nome reale da confermare dal
pre-flight). Espone:

```csharp
public Task PauseAsync(string reason);
public Task ResumeAsync(string reason);
public bool IsSequenceRunning { get; }   // se NINA espone questa info
```

Implementazione consigliata: iniettare `ISequenceMediator` (o nome reale)
nel costruttore via `[ImportingConstructor]`, chiamare il metodo Pause/Resume
verificato dal pre-flight. Loggare ogni azione tramite `Logger` NINA, e
inviare notifica tramite `INotificationManager` (o nome reale).

**Idempotenza**: se l'utente ha già messo in pausa la sequenza manualmente
quando il plugin decide di pausare, non chiamare il mediator (verifica
stato via `IsSequenceRunning` se disponibile, altrimenti mantieni
solo il flag `_sequencePausedByUs`). Stessa cosa al contrario per la
ripresa: se la sequenza non è stata messa in pausa DA NOI, non riprendere.

### 2D. Settings page del plugin

File nuovi:
- `src/AdaptiveAgentForPHD2.NinaPlugin/Settings/PluginSettings.cs`
  (modello con `INotifyPropertyChanged`, property con backing field e
  persistenza)
- `src/AdaptiveAgentForPHD2.NinaPlugin/Settings/PluginSettingsVM.cs`
  (ViewModel per UI)
- `src/AdaptiveAgentForPHD2.NinaPlugin/Settings/PluginSettingsView.xaml`
  (UI: toggle, input numerici)

Property minime:

```csharp
public bool AutoPauseEnabled { get; set; }         // default FALSE
public int  PollIntervalSeconds { get; set; }      // default 30, range 5-300
public int  ConsecutivePollsToTrigger { get; set; }// default 3,  range 1-10
public string DashboardUrl { get; set; }           // default "http://localhost:8080"
```

Persistenza tramite il meccanismo NINA standard (verifica dal pre-flight
come fa ninaAPI o il template ufficiale: `Properties.Settings`, file JSON
in `%LOCALAPPDATA%\NINA\Settings\<plugin-id>\settings.json`, o altro).

UI XAML sobria, coerente con i tema NINA (`DynamicResource` su
`BackgroundBrush`, `ForegroundBrush`, ecc.). Niente colori hard-coded.

### 2E. Registrazione settings page nel plugin

Modifica a `Plugin/AdaptiveAgentForPHD2Plugin.cs`:
- Aggiungere export `[Export(typeof(IPluginManifest))]` esistente (lasciare
  com'è)
- Aggiungere export della settings page se NINA usa pattern di
  registrazione settings (es. `[Export(typeof(IPluginSettings))]` o
  metodo `GetSettingsView()`): verifica dal pre-flight.

### 2F. Integrazione del poller nel lifecycle plugin

Modifica a `Plugin/AdaptiveAgentForPHD2Plugin.cs`:

```csharp
public override async Task Initialize()
{
    // Avvio del poller solo se l'utente ha abilitato la feature
    // (o sempre, e il decision engine decide se agire — preferire questo:
    //  così la UI può mostrare lo stato live anche se auto-pause OFF)
    _poller = new AgentStatusPoller(_settings, _logger);
    _poller.StatusUpdated += OnStatusUpdated;
    await _poller.StartAsync();
}

public override async Task Teardown()
{
    if (_poller != null)
    {
        _poller.StatusUpdated -= OnStatusUpdated;
        await _poller.StopAsync();
        _poller.Dispose();
    }
}
```

`Teardown` deve essere pulito: disposing `HttpClient`, cancellando il
`CancellationToken` del timer, joinando l'eventuale background task.

### 2G. UI status del polling nel pannello WebView (opzionale ma consigliato)

Aggiungi un piccolo strip sopra la WebView esistente con:
- Stato connessione: "Connesso" (verde) / "Agente non raggiungibile" (grigio)
- Ultimo aggiornamento: "5s fa"
- Stato auto-pausa: "OFF" (grigio) / "ARMATA" (verde) / "PAUSA ATTIVA"
  (ambra, quando il plugin ha appena pausato)

Se questo aggiunge troppa complessità per v1.1, **omettilo**: la priorità
è la logica di pausa, non la UI status. Può andare in v1.2.

---

## TEST ATTESI

### Test manuali

1. **Build pulita**: `dotnet build -c Release` finisce con 0 errori.
2. **Install + load**: lo script `install-plugin.ps1` (già presente)
   sostituisce la DLL. Riavviando NINA il plugin appare in lista
   con versione `1.1.0.0`.
3. **Settings page**: nel pannello settings di NINA compare la pagina
   "Adaptive Agent for PHD2 — Dashboard" con le quattro property.
   Default visibili: AutoPauseEnabled = false, PollIntervalSeconds = 30,
   ConsecutivePollsToTrigger = 3, DashboardUrl = "http://localhost:8080".
4. **Polling con Agente acceso**: avvia `Avvia.bat`, apri NINA. Nei log
   NINA compare ogni 30s un `Debug` o `Info` di acquisizione status (un
   tick non più frequente — solo una riga per poll).
5. **Polling con Agente spento**: spegni l'Agente. Dopo il primo
   poll fallito compare un `Info` "Adaptive Agent non raggiungibile,
   polling in standby". I poll successivi NON sporcano i log fino a
   quando l'Agente torna su.
6. **Trigger pause non scatta a feature OFF**: anche se la guida va
   chiaramente in `STAR_LOST` per minuti, NINA non viene messa in pausa
   finché `AutoPauseEnabled = false`. (Verifica con NINA in modalità
   simulator + Agente in simulator.)
7. **Trigger pause scatta a feature ON**: attiva il toggle, simula
   `STAR_LOST` per 3 poll consecutivi (90s default). Al terzo poll
   consecutivo: `PauseSequence()` chiamato, notifica visibile, log
   loggato con motivo.
8. **Resume scatta solo dopo 3 poll consecutivi normali**: dopo che la
   guida torna `NORMAL` e RMS sotto soglia, sequenza riprende dopo 3
   poll (90s).
9. **Idempotenza**: se l'utente mette manualmente in pausa la sequenza
   prima del plugin, il plugin non chiama Pause su pausa già esistente.
   Se dopo l'utente preme Resume manualmente, il plugin non chiama
   Resume su sequenza già in esecuzione (il flag `_sequencePausedByUs`
   si resetta correttamente).

### Test unitari (consigliati, non obbligatori per v1.1)

- `AutoPauseDecisionEngineTests`:
  - Pause solo dopo N poll consecutivi (non al primo)
  - Streak si resetta se anche un solo poll è "OK"
  - INACTIVE non triggera pause né resume
  - Payload con `controller == null` non triggera nulla
  - `baseline_done == false` → non valutare condizione 2 (RMS vs
    soglia), considerala "OK"
- `AgentStatusPollerTests`:
  - HttpClient timeout 5s → poll fallito gestito silenziosamente
  - JSON malformato → gestito senza crash
  - 503 / 500 / qualsiasi non-2xx → gestito come "non raggiungibile"

---

## VALIDAZIONE SUL CAMPO

1. Aggiorna il plugin (build → install script). Riavvia NINA.
2. Verifica versione 1.1.0.0 nel manager plugin di NINA.
3. Apri la settings page del plugin: tutte le property visibili, OFF di
   default.
4. Senza attivare auto-pause: verifica solo che il polling funzioni e che
   la dashboard WebView2 esistente continui a caricare.
5. Una sera, con NINA che acquisisce e Agente attivo, attiva il toggle.
   Se durante la sessione c'è un `STAR_LOST` reale (es. nuvola, dither
   con perdita stella), verifica che dopo ~90s la sequenza vada in pausa
   con notifica.
6. Quando la guida torna stabile, verifica che dopo ~90s la sequenza
   riprenda da sola.

Mantieni il toggle OFF nelle prime sessioni di osservazione di
comportamento. Attivalo solo dopo aver visto che la logica di rilevazione
è corretta sul tuo setup.

---

## PROCEDURA REBUILD E INSTALL

Identica alla v1.0:

```powershell
cd C:\Users\aless\Documents\N.I.N.A\AdaptiveAgentForPHD2.NinaPlugin\src\AdaptiveAgentForPHD2.NinaPlugin
dotnet build -c Release -p:Platform=x64
cd ..\..
powershell -ExecutionPolicy Bypass -File scripts\install-plugin.ps1 -NinaVersion 3.0.0
```

NINA va chiuso prima dell'install (la DLL è in uso dal processo NINA).

---

## AGGIORNAMENTO DOCUMENTAZIONE

### `README.md` del plugin (nel repo plugin)

Aggiungere una sezione "v1.1 — Auto-pausa sequenza" con: descrizione della
feature, settings configurabili, toggle OFF di default, comportamento
hysteresis, link al gruppo Telegram per feedback.

### `LEGGIMI_PER_AVVIARE.txt` (nel repo Python Adaptive Agent for PHD2)

**Solo quando il plugin v1.1 è validato sul campo**: aggiungere alla
sezione "(*) COME INSTALLARE IL PLUGIN NINA" una riga "Versione 1.1+:
include la pausa automatica della sequenza NINA quando la guida degrada.
Disabilitata di default — attivala nelle settings del plugin se vuoi
usarla". Questa modifica la faremo manualmente dopo la validazione, NON
ora.

### `NOTE_CLAUDE.md` del repo Python

Non aggiungere una sezione §28 finché il plugin v1.1 non è validato sul
campo (almeno una sessione reale di NINA in cui scatta l'auto-pausa
correttamente). Quando sarà validato, si potrà aggiungere come §28.

---

## CHECKLIST FINALE PRIMA DI COMMIT

- [ ] Pre-flight eseguito: schema JSON reale verificato leggendo
      `server.py` e `controller.py` del repo Python, NON solo il briefing
- [ ] Pre-flight eseguito: ninaAPI.dll ispezionato per pattern reale
      uso `ISequenceMediator`, `INotificationManager`, `Logger`
- [ ] DTO C# allineato al JSON REALE (campo `analyzer.rms_total`, NON
      `controller.auto_calibration.baseline_rms_arcsec` come "RMS live")
- [ ] Stati `guiding_state` corretti: `"STAR_LOST"` (NON `"LostLock"`),
      `"NORMAL"` (NON `"Guiding"`)
- [ ] Versione bumpata a `1.1.0.0` in `AssemblyInfo.cs`
- [ ] GUID `6F2E9C19-4F66-4F69-B7D3-E21D5AD7458B` INVARIATO
- [ ] Pannello WebView2 v1.0 invariato (la dashboard continua a caricare)
- [ ] Settings page registrata e visibile in NINA
- [ ] Toggle `AutoPauseEnabled` default FALSE
- [ ] Hysteresis a 3 poll consecutivi default (configurabile 1-10)
- [ ] Polling fallito = silent stop (logga UNA volta)
- [ ] Idempotenza pause/resume: flag `_sequencePausedByUs` corretto
- [ ] Nessuna modifica al codice Python dell'Agente
- [ ] `dotnet build -c Release` con 0 errori 0 warning
- [ ] Install script funzionante: DLL aggiornata nella cartella plugin
- [ ] NINA carica v1.1.0.0 senza errori
- [ ] Test manuali 1-9 passati

---

## DOMANDE DA FARMI PRIMA DI PROCEDERE (se servono)

Se il pre-flight rivela:
- API NINA per pause/resume diversa da `ISequenceMediator.PauseSequence()` →
  segnala il nome reale prima di scrivere il wrapper.
- Notification system con API custom → segnala il modo reale.
- Persistence settings con pattern non standard → segnala come fa ninaAPI o
  il template, decidiamo insieme se adottare.
- NINA 3.3 ha già un "Safety Monitor on guide loss" built-in → segnala,
  decidiamo se affiancare o sostituire.
- Schema JSON reale di `/status` diverso da quello che ho ricostruito (es.
  campi rinominati, blocco `analyzer` assente, ecc.) → segnala lo schema
  reale prima di scrivere i DTO.

→ **Fermati e chiedi**, non improvvisare.

Se invece tutto torna: procedi step-by-step. Mostrami il DTO C# prima di
scrivere la logica decisionale (è il punto di rischio massimo: se il DTO
sbaglia un campo, tutta la logica sopra crolla). Poi il decision engine,
poi l'integrazione mediator, poi la settings page, poi i test.

Grazie.
