# PROMPT PER CLAUDE CODE (Antigravity) — Plugin NINA v1.1 — Launch Agent + Badge Stato
# Da copiare e incollare integralmente nella conversazione con Claude Code.
# Lavorare nella cartella: C:\Users\aless\Documents\N.I.N.A\AdaptiveAgentForPHD2.NinaPlugin\

> **NOTA OPERATIVA**: questo è un'**estensione del plugin NINA esistente**
> creato nella sessione precedente (v1.0.0.0 — pannello dockable WebView2 della
> dashboard dell'Adaptive Agent for PHD2). NON ricreare il progetto da zero.
> Il plugin compilato funziona, è installato in
> `%LOCALAPPDATA%\NINA\Plugins\3.0.0\AdaptiveAgentForPHD2.NinaPlugin\`, GUID
> stabile `6F2E9C19-4F66-4F69-B7D3-E21D5AD7458B` (NON cambiare mai).
>
> **Cosa aggiunge questa v1.1**: due rifiniture UX leggere che condividono
> uno stesso piccolo servizio di polling.
> 1. **Pulsante "Avvia Adaptive Agent"** sopra il WebView nel pannello
>    dockable: avvia il processo `Avvia.bat` dell'Agente con un click,
>    senza che l'utente debba aprire Esplora Risorse.
> 2. **Badge di stato Agente** sopra il WebView: "Agente online v2.2"
>    (verde) quando risponde, "Agente offline" (grigio) altrimenti.
>    Aggiornato ogni 15 secondi.
>
> Le due funzioni si appoggiano allo stesso poller leggero che fa
> periodicamente `GET http://localhost:8080/about`. Quando l'Agente è
> online il pulsante è disabilitato (non avrebbe senso lanciarlo due
> volte); quando è offline il pulsante è abilitato.
>
> **Cosa NON fa questa v1.1**: nessuna pausa automatica della sequenza
> NINA, nessuna logica di trigger su `/status`, nessuna interferenza col
> Sequencer. È una pura rifinitura di UX. (Versione futura potrà rivalutare
> auto-pause se emergerà la necessità dai feedback.)
>
> **Bump versione**: `1.0.0.0` → `1.1.0.0` in `AssemblyInfo.cs`. GUID
> INVARIATO.
>
> **Allegati alla conversazione (riferimento ispettivo)**: `ninaAPI.dll`,
> `EmbedIO.dll`, `Swan.Lite.dll`. Per noi `ninaAPI.dll` è quello utile:
> contiene esempi reali di come un plugin NINA usa `Logger`,
> `INotificationManager` (o nome reale), e il pattern di settings
> persistence. Ispezionalo con ILSpy/dotPeek per estrarre i nomi reali
> dei servizi NINA. Non copiare codice (è di altro autore): copia solo
> il pattern di chiamata alle API NINA.

---

## 0. PRE-FLIGHT (breve — niente cambio API drastiche rispetto a v1.0)

### Endpoint Agente da consultare

`http://localhost:8080/about` (definito in
`C:\Users\aless\Downloads\PHD2_Assist_PATCHED\PHD2_Assist_PATCHED\server.py`
riga ~131). Risposta JSON tipica:

```json
{
  "project_name": "Adaptive Agent for PHD2",
  "short_name": "Adaptive Agent",
  "author": "Alessandro Curci",
  "version": "2.2",
  "copyright": "Copyright © 2026 Alessandro Curci",
  "license": "All rights reserved",
  "contact_telegram": "https://t.me/+eewRNpvElSs5OWY8"
}
```

Usiamo `/about` (non `/status`) perché è leggero, stabile, non cambia mai
durante una sessione e basta per sapere se l'Agente è up + quale versione
gira.

### Cosa verificare in `ninaAPI.dll` (decompilato)

- Nome reale del logger di NINA usato dai plugin (probabile `Logger` di
  `NINA.Core.Utility`, con metodi `Info`, `Warning`, `Error`).
- Nome reale del notification system per i toast (probabile
  `INotificationManager` o `Notification` statico).
- Pattern di settings persistence (probabile `Properties.Settings`
  auto-generated, o file JSON in
  `%LOCALAPPDATA%\NINA\Plugins\<id>\settings.json`).

### File Python da NON toccare

`C:\Users\aless\Downloads\PHD2_Assist_PATCHED\PHD2_Assist_PATCHED\` resta
**invariato**. Il plugin v1.1 è puro client + launcher di processo.

---

## OBIETTIVO TECNICO

Aggiungere al plugin NINA v1.0.0.0 esistente: (1) un piccolo poller
`AgentHealthChecker` che ogni `N` secondi fa `GET /about`; (2) un
**pulsante "Avvia Adaptive Agent"** nel pannello dockable WebView,
abilitato solo quando l'Agente è offline, che lancia il processo `Avvia.bat`
con `Process.Start`; (3) un **badge di stato Agente** sopra il WebView
che mostra "Agente online v2.2" (verde) o "Agente offline" (grigio); (4)
una **settings page** minimale del plugin per configurare il path al
`Avvia.bat` e l'intervallo di polling. Bumpare versione a `1.1.0.0`.

---

## REGOLE INDEROGABILI

- **NON modificare** il codice Python dell'Adaptive Agent for PHD2.
- **NON rimuovere** il pannello dockable WebView2 esistente: il pulsante
  e il badge si aggiungono SOPRA il WebView, lui resta intatto.
- **NON cambiare** GUID né `Id` del manifest plugin
  (`6F2E9C19-4F66-4F69-B7D3-E21D5AD7458B`).
- **NON tentare** di mettere in pausa la sequenza NINA. Niente
  `ISequenceMediator`. Questa versione è puramente UX/launcher.
- **NON spawnare** processi se il path al `Avvia.bat` non è configurato:
  mostrare invece un messaggio chiaro che invita l'utente a impostarlo
  nelle settings del plugin.
- **NON propagare** eccezioni di rete o di processo fuori dai servizi:
  loggale, mostra un toast, ma non far crashare NINA per colpa nostra.
- **NON loggare** ogni singolo poll. Solo le transizioni di stato
  (online→offline, offline→online).
- Mantenere stile C# idiomatico, nullable annotations, brace Allman.

---

## SPECIFICA FUNZIONALE

### 2A. Nuovo servizio `AgentHealthChecker`

File nuovo: `src/AdaptiveAgentForPHD2.NinaPlugin/Health/AgentHealthChecker.cs`

Responsabilità:
- `HttpClient` long-lived con timeout 3 secondi (corto: se non risponde
  entro 3s lo trattiamo come offline).
- `PeriodicTimer` o `System.Threading.Timer` ogni
  `HealthCheckIntervalSeconds` (default 15s, configurabile 5-120).
- Tenta `GET http://localhost:8080/about`.
- Risposta 2xx con JSON valido → stato `Online`, espone
  `AgentVersion = <campo version>`.
- Connection refused / timeout / 5xx / JSON malformato → stato `Offline`.
- Espone evento `StatusChanged(AgentHealth health)` invocato SOLO sulle
  transizioni (non a ogni tick).
- `AgentHealth` è un piccolo record:

  ```csharp
  public sealed record AgentHealth(bool IsOnline, string? Version);
  ```

- Loggare via `Logger` NINA (Info) solo le transizioni:
  - "Adaptive Agent online v2.2" all'andata online
  - "Adaptive Agent offline" all'andata offline

`Start()` / `Stop()` / `IDisposable` per gestione lifecycle nel
plugin `Initialize`/`Teardown`.

### 2B. Nuovo servizio `AgentLauncher`

File nuovo: `src/AdaptiveAgentForPHD2.NinaPlugin/Launch/AgentLauncher.cs`

Responsabilità:
- Metodo `Task<LaunchResult> LaunchAsync(string batPath)` che:
  1. Valida che `batPath` non sia null/vuoto → ritorna
     `LaunchResult.NotConfigured`.
  2. Valida che il file esista → ritorna `LaunchResult.FileNotFound`.
  3. Avvia il processo con `Process.Start`:

     ```csharp
     var psi = new ProcessStartInfo
     {
         FileName        = batPath,
         WorkingDirectory = Path.GetDirectoryName(batPath) ?? "",
         UseShellExecute = true,    // serve per .bat
         CreateNoWindow  = false,   // mostra console: utile per vedere il banner Python
         WindowStyle     = ProcessWindowStyle.Minimized,
     };
     Process.Start(psi);
     ```

  4. Ritorna `LaunchResult.Launched` (NON aspetta che l'Agente sia
     effettivamente up — quella conferma arriva poi dal poller, entro
     10-30s).
  5. Gestisce le eccezioni con try/catch ampio: ogni problema
     → `LaunchResult.Error(string message)`.

```csharp
public sealed record LaunchResult(
    bool Success,
    string Message)
{
    public static LaunchResult Launched =>
        new(true, "Processo avviato. L'Agente sarà pronto tra qualche secondo.");
    public static LaunchResult NotConfigured =>
        new(false, "Path al file Avvia.bat non impostato. Configuralo nelle settings del plugin.");
    public static LaunchResult FileNotFound =>
        new(false, "Il file Avvia.bat indicato nelle settings non esiste. Verifica il percorso.");
    public static LaunchResult Error(string message) =>
        new(false, $"Errore nell'avvio: {message}");
}
```

### 2C. Settings page minimale del plugin

File nuovi:
- `src/AdaptiveAgentForPHD2.NinaPlugin/Settings/PluginSettings.cs`
  (modello con `INotifyPropertyChanged` + persistenza)
- `src/AdaptiveAgentForPHD2.NinaPlugin/Settings/PluginSettingsView.xaml`
  (UI)
- `src/AdaptiveAgentForPHD2.NinaPlugin/Settings/PluginSettingsView.xaml.cs`

Property minime:

```csharp
public string AgentBatPath { get; set; }              // default "", utente lo imposta
public int    HealthCheckIntervalSeconds { get; set; } // default 15, range 5-120
public string DashboardUrl { get; set; }              // default "http://localhost:8080"
```

UI XAML sobria:
- Label + TextBox + bottone "Sfoglia..." per `AgentBatPath`
  (apre `OpenFileDialog` filtrato a `*.bat`)
- Label + NumericUpDown (o TextBox numerico) per
  `HealthCheckIntervalSeconds`
- Label + TextBox per `DashboardUrl` (raramente modificato, ma utile se
  l'utente cambia porta dell'Agente)
- Bottone "Salva" (o persistenza automatica su PropertyChanged)

Persistenza: verifica dal pre-flight come fa `ninaAPI.dll` o il template
NINA. Se NINA offre un wrapper standard di settings, usa quello. Altrimenti
serializza JSON in `%LOCALAPPDATA%\NINA\Plugins\<id>\settings.json`.

Usa `DynamicResource` su `BackgroundBrush`, `ForegroundBrush`, ecc., per
ereditare il tema NINA. Niente colori hard-coded.

### 2D. Estensione del pannello dockable `AdaptiveAgentDashboardView.xaml`

Aggiungi una riga `<Grid>` sopra il WebView2 esistente con due elementi
allineati orizzontalmente:

- A sinistra: **badge di stato** (Border colorato + Label).
  - Online → sfondo verde tenue, testo "Agente online v2.2"
  - Offline → sfondo grigio tenue, testo "Agente offline"
- A destra: **pulsante "Avvia Adaptive Agent"**.
  - Abilitato quando stato = Offline E `AgentBatPath` configurato
  - Disabilitato quando stato = Online (con tooltip "Agente già in
    esecuzione")
  - Disabilitato con messaggio guida quando `AgentBatPath` vuoto
    (testo bottone "Configura percorso Avvia.bat nelle settings")

Mantieni lo stile sobrio: niente colori vividi fuori dai due stati del
badge. Usa le risorse colore del tema NINA dove possibile.

Esempio di struttura XAML (indicativo):

```xml
<Grid>
    <Grid.RowDefinitions>
        <RowDefinition Height="Auto" />   <!-- nuova: badge + pulsante -->
        <RowDefinition Height="Auto" />   <!-- header v1.0 esistente -->
        <RowDefinition Height="*" />      <!-- WebView2 esistente -->
        <RowDefinition Height="Auto" />   <!-- footer v1.0 esistente -->
    </Grid.RowDefinitions>

    <DockPanel Grid.Row="0" Margin="8,6">
        <Button DockPanel.Dock="Right"
                Content="{Binding LaunchButtonText}"
                IsEnabled="{Binding LaunchButtonEnabled}"
                Command="{Binding LaunchAgentCommand}"
                Padding="10,4" />
        <Border CornerRadius="3"
                Padding="6,3"
                Background="{Binding StatusBadgeBackground}">
            <TextBlock Text="{Binding StatusBadgeText}"
                       FontWeight="SemiBold" />
        </Border>
    </DockPanel>

    <!-- ... resto del XAML v1.0 invariato ... -->
</Grid>
```

### 2E. ViewModel — `AdaptiveAgentDashboardVM` esteso

Aggiungi al VM esistente:

- Property `StatusBadgeText` (string) — popolata dal
  `AgentHealthChecker.StatusChanged`
- Property `StatusBadgeBackground` (Brush) — verde/grigio
- Property `LaunchButtonText` (string) — "Avvia Adaptive Agent" oppure
  "Configura percorso Avvia.bat nelle settings"
- Property `LaunchButtonEnabled` (bool) — derivata
- `RelayCommand LaunchAgentCommand` che chiama
  `AgentLauncher.LaunchAsync(_settings.AgentBatPath)` e mostra un toast
  con `INotificationManager` per ogni `LaunchResult`:
  - `Launched` → toast informativo "Avvio in corso..."
  - `NotConfigured` → toast warning con istruzioni
  - `FileNotFound` → toast warning
  - `Error(msg)` → toast error con il messaggio

Iniettare `AgentHealthChecker` e `AgentLauncher` via
`[ImportingConstructor]` o costruzione manuale in
`AdaptiveAgentForPHD2Plugin.Initialize()`.

### 2F. Lifecycle in `AdaptiveAgentForPHD2Plugin.cs`

```csharp
public override Task Initialize()
{
    _settings = PluginSettings.Load();
    _launcher = new AgentLauncher(_logger);
    _healthChecker = new AgentHealthChecker(_settings, _logger);
    _healthChecker.Start();
    return Task.CompletedTask;
}

public override async Task Teardown()
{
    if (_healthChecker != null)
    {
        await _healthChecker.StopAsync();
        _healthChecker.Dispose();
    }
}
```

Verifica via pre-flight se NINA fornisce una `DI container` propria e
preferisci quella per il wiring (probabile, vista la presenza di MEF
nei pattern dei plugin).

---

## TEST ATTESI

### Test manuali

1. **Build pulita**: `dotnet build -c Release` → 0 errori 0 warning.
2. **Install + load**: install script copia DLL, NINA riavviato carica
   plugin v1.1.0.0.
3. **Pannello dockable invariato**: il WebView2 esistente continua a
   caricare la dashboard quando l'Agente è up.
4. **Badge offline al primo avvio**: con Agente non in esecuzione, il
   badge mostra "Agente offline" (grigio).
5. **Avviso path mancante**: clicchi il pulsante (o vedi il testo
   sostitutivo "Configura percorso Avvia.bat nelle settings") → vai
   nelle settings, imposta path. Pulsante torna abilitato come "Avvia
   Adaptive Agent".
6. **Avvio agente funzionante**: clicchi "Avvia Adaptive Agent" con
   path corretto → si apre la console del .bat (minimizzata), entro
   15-30 secondi il badge transita a "Agente online v2.2" (verde) e
   il pulsante si disabilita.
7. **Stop agente**: chiudi la console del .bat (Ctrl+C). Entro 15-30s
   il badge torna "Agente offline" e il pulsante torna abilitato.
8. **Path errato**: imposta nelle settings un path che non esiste,
   clicca → toast "Il file Avvia.bat indicato nelle settings non
   esiste".
9. **Cambio intervallo polling**: nelle settings cambia
   `HealthCheckIntervalSeconds` a 5 → verifica che il badge si aggiorni
   più velocemente.
10. **Log NINA**: nei log compaiono SOLO le transizioni online/offline,
    NON ogni singolo tick di polling.

### Test unitari (opzionali ma consigliati)

- `AgentHealthCheckerTests`:
  - Mock HttpClient → online detection corretta
  - Mock timeout → offline detection corretta
  - Mock JSON malformato → offline detection (non crash)
  - StatusChanged invocato solo sulle transizioni, non a ogni tick
- `AgentLauncherTests`:
  - Path vuoto → `NotConfigured`
  - Path non esistente → `FileNotFound`
  - (test di `Process.Start` reale solo manuale, non automatizzabile)

---

## VALIDAZIONE SUL CAMPO

1. Riavvia NINA dopo l'install. Verifica versione 1.1.0.0 nel manager
   plugin.
2. Apri il pannello dockable: badge visibile, pulsante visibile.
3. Imposta nelle settings il path al tuo `Avvia.bat`
   (probabilmente `C:\Users\aless\Downloads\PHD2_Assist_PATCHED\PHD2_Assist_PATCHED\Pacchetto_Distribuzione\Avvia.bat`
   o dove lo distribuisci).
4. Clicca "Avvia Adaptive Agent" → console del .bat parte → dashboard
   carica nel WebView → badge passa a verde con versione.
5. Chiudi la console → badge torna grigio dopo l'intervallo di polling.

Mantieni il plugin in uso per qualche sessione reale; se la UX è
fluida e nessun comportamento inatteso emerge, è pronto per essere
distribuito alla community Telegram come aggiornamento opzionale.

---

## PROCEDURA REBUILD E INSTALL

Identica alla v1.0:

```powershell
cd C:\Users\aless\Documents\N.I.N.A\AdaptiveAgentForPHD2.NinaPlugin\src\AdaptiveAgentForPHD2.NinaPlugin
dotnet build -c Release -p:Platform=x64
cd ..\..
powershell -ExecutionPolicy Bypass -File scripts\install-plugin.ps1 -NinaVersion 3.0.0
```

NINA va chiuso prima dell'install (DLL in uso).

---

## AGGIORNAMENTO DOCUMENTAZIONE

### `README.md` del repo plugin

Aggiungere una sezione "v1.1 — Launch Agent + badge stato" con: cosa fa,
come si configura (path al `Avvia.bat` nelle settings), link al gruppo
Telegram.

### `LEGGIMI_PER_AVVIARE.txt` del repo Python

Aggiornamento **manuale dopo la validazione** (NON ora): aggiungere alla
sezione "(*) COME INSTALLARE IL PLUGIN NINA" un'aggiunta tipo:
"Versione 1.1+: il plugin offre anche un pulsante 'Avvia Adaptive Agent'
per lanciare l'Agente con un click senza aprire Esplora Risorse —
imposta il path nelle settings del plugin la prima volta."

### `NOTE_CLAUDE.md` del repo Python

Aggiungere §28 SOLO dopo validazione sul campo. Struttura coerente con
gli altri capitoli: motivazione, architettura, file modificati, limiti.
Lo faremo manualmente.

---

## CHECKLIST FINALE PRIMA DI COMMIT

- [ ] Pre-flight: ispezione `ninaAPI.dll` per nomi reali di `Logger`,
      `INotificationManager`, pattern settings persistence
- [ ] Versione bumpata a `1.1.0.0` in `AssemblyInfo.cs`
- [ ] GUID `6F2E9C19-4F66-4F69-B7D3-E21D5AD7458B` INVARIATO
- [ ] Pannello WebView2 v1.0 invariato (dashboard continua a caricare)
- [ ] Badge stato sopra il WebView funzionante (verde/grigio)
- [ ] Pulsante "Avvia Adaptive Agent" funzionante, con tutti i casi
      gestiti (path vuoto, file inesistente, errore process)
- [ ] Settings page con `AgentBatPath`, `HealthCheckIntervalSeconds`,
      `DashboardUrl`, con persistenza tra riavvii NINA
- [ ] Health checker SOLO logga transizioni, NON ogni tick
- [ ] Nessuna chiamata a `/status` né a `ISequenceMediator`
- [ ] Nessuna modifica al codice Python dell'Agente
- [ ] `dotnet build -c Release` → 0 errori 0 warning
- [ ] Install script funzionante
- [ ] NINA carica v1.1.0.0 senza errori
- [ ] Test manuali 1-10 passati

---

## DOMANDE PRIMA DI PROCEDERE (se servono)

Se il pre-flight rivela:
- Pattern di settings persistence non standard in NINA 3.3 → segnala il
  pattern reale, decidiamo se adottare.
- Logger / NotificationManager con API diverse → usa quelli reali e
  segnala.
- Conflitti di tema XAML (DynamicResource non risolve `BackgroundBrush`
  ecc.) → segnala i nomi reali delle risorse colore disponibili.

→ **Fermati e chiedi**, non improvvisare.

Se tutto torna: procedi step-by-step. Mostrami i diff dei file più
critici (settings + ViewModel esteso + lifecycle plugin) prima di
applicarli. Le aggiunte sono leggere — target totale ~150-200 righe di
C# nuove. Se ti accorgi di superare le 300 righe, fermati e capiamo
insieme cosa abbiamo gonfiato troppo.

Grazie.
