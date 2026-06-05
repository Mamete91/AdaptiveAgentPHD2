# PROMPT PER CLAUDE CODE (Antigravity) — Plugin NINA v1.2.3 — Compatibilità NINA 3.2 stable
# Da copiare e incollare integralmente nella conversazione con Claude Code.
# Lavorare nella cartella: C:\Users\aless\Documents\N.I.N.A\AdaptiveAgentForPHD2.NinaPlugin\

> **NOTA OPERATIVA**: nelle scorse sessioni avevamo dato per scontato che
> NINA 3.3 fosse la versione stable corrente, ma in realtà **3.2 è la stable
> e 3.3 è la nightly**. Conseguenza: il plugin v1.2.2.0 attualmente in
> distribuzione è stato compilato contro `NINA.Plugin 3.2.0.9001` +
> `Microsoft.Web.WebView2 1.0.3650.58` + `CommunityToolkit.Mvvm 8.4.0`,
> che sono le versioni che **NINA 3.3 nightly ships nella propria
> directory**. Un astrofilo della community Telegram con NINA 3.2 stable
> ha riportato l'errore "Failed to load plugin Adaptive Agent for PHD2
> — Dashboard version 1.2.2.0" perché 3.2 stable usa versioni più vecchie
> di quei tre package e i type/method binding non risolvono.
>
> **Strategia**: ricompilare il plugin contro le versioni shipped da
> **NINA 3.2 stable**. NINA è forward-compatible — un plugin per 3.2
> gira anche su 3.3 e successivi senza problemi. Con una sola build
> coprirai entrambi i target (3.2 stable + 3.3 nightly). Bump versione
> 1.2.2.0 → 1.2.3.0. GUID INVARIATO come sempre.
>
> NESSUNA modifica funzionale al codice del plugin: tutto il C# resta
> identico. Cambiano solo i package NuGet di riferimento (compile-time
> only — `ExcludeAssets=runtime` resta su tutti, NINA continua a fornire
> le DLL a runtime dalla propria directory).

---

## 0. PRE-FLIGHT OBBLIGATORIO

### Step 1 — Scoprire le versioni reali shipped da NINA 3.2 stable

NINA si installa di default in `C:\Program Files\N.I.N.A. - Nighttime Imaging 'N' Astronomy\` oppure in un path simile (verifica con `Get-ChildItem "$env:ProgramFiles\N.I.N.A*"`).

Però **NINA 3.2 stable potrebbe non essere installato sul PC di Alessandro**
(lui ha la 3.3 nightly come default). Due strade per ottenere le info che ti servono:

**Strada A** (preferita se disponibile): scarica l'installer di NINA 3.2 stable
da `https://nighttime-imaging.eu/download/` e installalo in side-by-side
mode (in una cartella separata, NON sovrascrivere la 3.3 nightly).
Poi `ilspycmd` su `NINA.Plugin.dll` + ispezione delle DLL bundled
WebView2 + CommunityToolkit nella cartella di NINA 3.2 per leggere
`FileVersion` di:
- `Microsoft.Web.WebView2.Core.dll`
- `Microsoft.Web.WebView2.Wpf.dll`
- `CommunityToolkit.Mvvm.dll`
- `NINA.Plugin.dll` (riga `AssemblyVersion`)

**Strada B** (fallback se l'installer 3.2 non è facilmente recuperabile):
verifica sul **repository NuGet** quali versioni di `NINA.Plugin` sono
pubblicate. La 3.2.0.9001 sembra essere già marcata "stable" per NINA 3.2
(verifica leggendo le release notes su NuGet). In quel caso il problema
**non è la versione di NINA.Plugin** ma SOLO le versioni di WebView2 e
CommunityToolkit.Mvvm che dobbiamo abbassare.

In entrambi i casi, **riportami i numeri di versione esatti che hai trovato**
prima di procedere alla modifica del `.csproj`.

### Step 2 — Verificare che le API che usiamo esistano in 3.2

Tutto il codice del plugin (Dashboard, Health, Launch, Safety, Settings,
AgentServices, Plugin entry point) usa solo API che dovrebbero essere
presenti in NINA 3.2 stable senza modifiche:

- `IDockableVM`, `DockableVM` (Dashboard)
- `IPluginManifest`, `PluginBase` (entry point)
- `BaseINPC`, `IEquipmentProvider<T>`, `ISafetyMonitor` (Safety)
- `Logger`, `Notification.Notification` (logging + toast)
- `AsyncRelayCommand` (CommunityToolkit.Mvvm)
- `IProfileService` iniettato in DockableVM

Verifica con `ilspycmd` sul `NINA.Plugin.dll` di 3.2 stable (o dalle
release notes su NuGet) che queste interfacce esistano con le firme che
usiamo. **Atteso**: tutte presenti, perché sono nell'API plugin sin
dall'inizio della serie 3.x. Se trovi qualcosa cambiato in modo
incompatibile, **fermati e segnala** prima di toccare il `.csproj`.

---

## OBIETTIVO TECNICO

Ricompilare il plugin v1.2.2.0 con il `.csproj` aggiornato per puntare
alle versioni NuGet di `NINA.Plugin`, `Microsoft.Web.WebView2` e
`CommunityToolkit.Mvvm` shipped da NINA 3.2 stable. Bump versione a
1.2.3.0. Verificare che la build resti pulita (0 errori 0 warning) e che
nessuna API utilizzata risulti non più disponibile. La DLL risultante
deve caricare su NINA 3.2 stable AND su NINA 3.3 nightly.

---

## REGOLE INDEROGABILI

- **NON modificare** il codice C# del plugin in `src/AdaptiveAgentForPHD2.NinaPlugin/`
  (Dashboard/, Health/, Launch/, Safety/, Settings/, Plugin/, Resources/,
  AgentServices.cs). Cambia SOLO il `.csproj` (versioni package) e il
  bump versione in `AssemblyInfo.cs` + `.csproj`.
- **NON cambiare** il GUID plugin `6F2E9C19-4F66-4F69-B7D3-E21D5AD7458B`
  né il GUID Safety Monitor `10A715AD-903C-499E-9CC7-CA8E66A49B7C`.
- **NON rimuovere** `ExcludeAssets=runtime` sui tre PackageReference:
  NINA continua a fornire le DLL a runtime, non vogliamo duplicarle.
- **NON cambiare** `MinimumApplicationVersion`: resta a `3.0.0.0`
  (corretto e onesto: il plugin è compatibile dalla 3.0 in avanti grazie
  alla forward compatibility).
- **NON improvvisare** i numeri di versione dei package: usa quelli che
  hai verificato nel pre-flight Step 1.
- **NON aggiungere** nuove feature, nuovo codice, nuove dipendenze: questa
  è una pura ricompilazione mirata a estendere la compatibilità.

---

## SPECIFICA FUNZIONALE

### 2A. Aggiornare `.csproj`

Modifica `src/AdaptiveAgentForPHD2.NinaPlugin/AdaptiveAgentForPHD2.NinaPlugin.csproj`:
- `<Version>` e `<FileVersion>`: `1.2.2.0` → `1.2.3.0`
- `<PackageReference Include="NINA.Plugin" Version="3.2.0.9001">`:
  sostituisci con la versione confermata nel pre-flight. Se 3.2.0.9001 è
  effettivamente la stable per NINA 3.2 (verifica nelle release notes
  NuGet), lasciala. Altrimenti usa la versione corretta.
- `<PackageReference Include="Microsoft.Web.WebView2" Version="1.0.3650.58">`:
  sostituisci con la versione confermata nel pre-flight per NINA 3.2
  (probabilmente più vecchia, es. `1.0.27xx.xx` o `1.0.29xx.xx`).
- `<PackageReference Include="CommunityToolkit.Mvvm" Version="8.4.0">`:
  sostituisci con la versione confermata per NINA 3.2 (probabilmente
  `8.2.x` o `8.3.x`).

Tutti gli `ExcludeAssets=runtime` restano invariati.

### 2B. Aggiornare `AssemblyInfo.cs`

`Properties/AssemblyInfo.cs`:
- `[assembly: AssemblyVersion("1.2.2.0")]` → `1.2.3.0`
- `[assembly: AssemblyFileVersion("1.2.2.0")]` → `1.2.3.0`

GUID invariato. `MinimumApplicationVersion` resta a `3.0.0.0`.

### 2C. Build pulita

```powershell
cd C:\Users\aless\Documents\N.I.N.A\AdaptiveAgentForPHD2.NinaPlugin\src\AdaptiveAgentForPHD2.NinaPlugin
dotnet restore
dotnet build -c Release -p:Platform=x64
```

Atteso: 0 errori 0 warning. Se compaiono warning di binding redirect
(`NU1701`, `MSB3277`, `MSB3243`), segnala e analizziamo. Non lasciarli
silenziosi.

### 2D. Install + verifica versione

```powershell
cd C:\Users\aless\Documents\N.I.N.A\AdaptiveAgentForPHD2.NinaPlugin
powershell -ExecutionPolicy Bypass -File scripts\install-plugin.ps1 -NinaVersion 3.0.0
```

NINA chiuso prima. A install completato, verifica con
`(Get-Item "$env:LOCALAPPDATA\NINA\Plugins\3.0.0\AdaptiveAgentForPHD2.NinaPlugin\AdaptiveAgentForPHD2.NinaPlugin.dll").VersionInfo.FileVersion`
che riporti `1.2.3.0`.

---

## TEST ATTESI

### Test su NINA 3.3 nightly (Alessandro, regression test)

Riavvio NINA 3.3 → manager plugin mostra `1.2.3.0` → pannello dockable
funziona come prima (badge, pulsante Avvia, dashboard, settings,
Safety Monitor) → nessuna regressione visibile rispetto alla v1.2.2.0.

### Test su NINA 3.2 stable (astrofilo Telegram)

L'astrofilo che aveva riportato l'errore reinstalla la DLL v1.2.3.0:
plugin caricato correttamente da NINA 3.2 stable, manager plugin
mostra `1.2.3.0`, tutte le funzionalità accessibili.

---

## DISTRIBUZIONE

Dopo che entrambi i test passano:

1. **Aggiorna la cartella distribuzione plugin** nel repo Python:
   sostituisci la DLL in
   `C:\Users\aless\Downloads\PHD2_Assist_PATCHED\PHD2_Assist_PATCHED\AdaptiveAgentForPHD2.NinaPlugin\`
   con la nuova v1.2.3.0.

2. **Rigenera lo ZIP di distribuzione** con la stessa procedura della
   sessione precedente (`Adaptive_Agent_PHD2_v2.2.zip` mantenendo
   l'identico nome — l'Agente Python è invariato, è solo il plugin che
   è aggiornato):
   - Pulizia logs/ di sessione (anche se attesa vuota, run del comando
     come safety net)
   - Generazione ZIP entry-by-entry con `ZipArchive` (separatori `/`,
     1382 entry attesi come la sessione precedente)
   - Verifica top-level `AdaptiveAgentForPHD2.NinaPlugin/` +
     `Pacchetto_Distribuzione/` + DLL plugin v1.2.3.0 + LEGGIMI invariato

3. **Documentazione**: aggiorna §29 in `NOTE_CLAUDE.md` con una nota
   aggiuntiva a fine sezione tipo:

   > **Patch v1.2.3.0 (compatibilità NINA 3.2 stable)**: dopo distribuzione
   > pubblica, un astrofilo con NINA 3.2 stable ha riportato "Failed to
   > load plugin". Causa: il plugin era compilato contro le versioni di
   > NINA.Plugin/WebView2/CommunityToolkit.Mvvm shipped da NINA 3.3
   > nightly, che differiscono da quelle di 3.2 stable. Fix: ricompilato
   > contro le versioni shipped da 3.2 stable (forward-compatible con
   > 3.3 nightly). Una sola build copre entrambi i target. Nessuna
   > modifica funzionale al codice del plugin.

---

## CHECKLIST FINALE

- [ ] Pre-flight Step 1: versioni NuGet per NINA 3.2 stable confermate
      (NINA.Plugin, WebView2, CommunityToolkit.Mvvm)
- [ ] Pre-flight Step 2: tutte le API usate dal plugin esistono in 3.2
      con firme identiche
- [ ] `.csproj` aggiornato con le versioni package corrette
- [ ] `AssemblyVersion` + `FileVersion` + `<Version>` + `<FileVersion>`
      → 1.2.3.0
- [ ] GUID plugin INVARIATO
- [ ] GUID Safety Monitor INVARIATO
- [ ] `MinimumApplicationVersion` resta `3.0.0.0`
- [ ] `dotnet build -c Release` 0 errori 0 warning
- [ ] Install riuscito, DLL `FileVersion` 1.2.3.0
- [ ] Test su NINA 3.3 nightly: nessuna regressione
- [ ] Cartella distribuzione plugin aggiornata
- [ ] ZIP `Adaptive_Agent_PHD2_v2.2.zip` rigenerato con DLL v1.2.3.0
- [ ] §29 NOTE_CLAUDE aggiornata con paragrafo "Patch v1.2.3.0"

---

## DOMANDE PRIMA DI PROCEDERE

Se il pre-flight rivela:
- Una API che usiamo NON è presente in NINA 3.2 stable (es. una firma
  di `ISafetyMonitor` diversa, o `BaseINPC` con costruttore diverso)
  → **fermati e segnala**: dovremo cambiare strategia (eventualmente
  doppia build, o modificare il codice plugin per usare solo l'intersezione
  delle API tra 3.2 e 3.3).
- L'installer di NINA 3.2 stable non è facilmente recuperabile e le
  release notes NuGet non chiariscono le versioni shipped
  → segnala e decidiamo insieme se procedere "ad occhio" abbassando le
  versioni o se aspettare di poter installare 3.2 in side-by-side.

→ **Fermati e chiedi**, non improvvisare.

Stima: ~15 minuti di pre-flight + 5 minuti di modifiche + 5 minuti di
build/install + Alessandro riavvia NINA per regression test. Distribuzione
ZIP altri 10 minuti se i test passano.

Grazie.
