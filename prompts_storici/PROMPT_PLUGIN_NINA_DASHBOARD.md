# PROMPT PER CLAUDE CODE (Antigravity) — Plugin NINA per Dashboard Adaptive Agent for PHD2
# Da copiare e incollare integralmente nella conversazione con Claude Code.

> **NOTA OPERATIVA**: questo è un **progetto separato** dal pacchetto Python
> "Adaptive Agent for PHD2" che vive in `PHD2_Assist_PATCHED\`. È un plugin C#
> per NINA (Nighttime Imaging 'N' Astronomy) che si limita a mostrare in un
> pannello dockable la dashboard web già esposta dall'Agente su
> `http://localhost:8080`. Non c'è alcun import del codice Python, alcun
> contatto con PHD2 via JSON-RPC, alcuna lettura di file di configurazione: il
> plugin è una shell WebView2 attorno a un URL.
>
> **Scopo**: dare agli astrofotografi che usano NINA la possibilità di
> sorvegliare la dashboard dell'Agente senza dover tenere aperto un browser a
> parte. Niente di più. Tutta la logica adattiva vive nel processo Python
> separato (`PHD2_Agent.exe`).
>
> **Contesto della scelta architetturale (perché plugin minimale WebView e
> non altro)**. Alessandro ha valutato tre vie prima di scegliere questa:
> (1) **Pubblicazione su GitHub** — accantonata. Il progetto non ha basi per
> un ritorno economico nel breve termine, non c'è struttura di marketing, e
> la distribuzione via gruppo Telegram alla community italiana di
> astrofotografia (~1000 utenti) è già sufficiente come bacino di feedback
> qualificato. (2) **Plugin NINA nativo con logica C# riscritta** —
> scartata: richiederebbe riscrivere in C# tutta la logica adattiva oggi in
> Python (controller, analyzer, baseline, escalation gate, auto-calibrazione,
> refresh ciclico), mesi di lavoro, doppia implementazione da mantenere
> allineata, e perdita della velocità di iterazione di Python. Irrealizzabile
> nel breve termine, e tecnicamente sconsigliata anche nel lungo. (3) **Plugin
> NINA come WebView locale** — la soluzione minima e concreta: un plugin C#
> che aggiunge a NINA un pannello il cui unico contenuto è la dashboard già
> esistente dell'Agente, aperta via WebView2 su `http://localhost:8080`.
> Nessuna logica da riscrivere, nessuna duplicazione, valore puramente UX
> (vedere lo stato dell'Agente senza uscire da NINA). **Questa terza via è
> quella che stiamo implementando.** Implicazione operativa per te (Claude
> Code): la scelta minimalista è deliberata, non per scarsità. NON proporre
> di estendere il plugin con logica propria (start/stop dell'Agente,
> health-check, lettura config, ecc.). Quelle sono evoluzioni v1.1 e
> successive, non v1.0.
>
> **Identità del plugin** (fissata, NON rinegoziare):
> - Nome interno (assembly + cartella): `AdaptiveAgentForPHD2.NinaPlugin`
> - Nome utente-visibile in NINA: `Adaptive Agent for PHD2 — Dashboard`
> - Autore: `Alessandro Curci`
> - Versione iniziale: `1.0.0.0` (allineata semanticamente alla v2.2
>   dell'Agente, ma il plugin ha il suo ciclo di vita)
> - Copyright: `Copyright © 2026 Alessandro Curci`
> - Canale supporto: `https://t.me/+eewRNpvElSs5OWY8` (lo stesso gruppo
>   Telegram della community dell'Agente)
> - GUID assembly: **DEVE essere generato univoco** (es. `Guid.NewGuid()` o
>   `uuidgen`/`New-Guid` PowerShell). **NON** copiare GUID da esempi trovati
>   online: ogni plugin NINA deve avere il proprio GUID stabile.
>
> **Riferimento dal mio storico**: tu vedrai allegata in conversazione una
> bozza di codice C# che mi era stata proposta in passato (struttura
> `PHD2AdaptiveAgentPlugin/`, `.csproj` con `net10.0-windows`,
> `NINA.Plugin Version=2.0.0`, ecc.). **Quella bozza contiene errori
> sostanziali** (`.NET 10` non esiste come target stabile, il package NuGet
> citato è errato, il GUID è hard-coded e duplicato). Usala SOLO come traccia
> della struttura a 6 file, NON copiarne valori. La fonte di verità è il
> repository ufficiale NINA, da consultare nel pre-flight.
>
> **Esempi binari allegati alla conversazione** (preziosi, da ispezionare nel
> pre-flight): `nina.plugin.phd2tools-28d1c731.dll` +
> `nina.plugin.phd2tools-dce3f00b.pdb`. È un plugin NINA reale e funzionante
> di un altro autore (non di Alessandro) che maneggia PHD2. Te lo passo come
> **riferimento ispettivo** per capire come è fatto un plugin NINA che
> compila e si carica davvero in NINA 3.3: che `PackageReference` ha nel
> manifest assembly, che signature ha il costruttore `DockableVM`, che chiavi
> `AssemblyMetadata` usa nel manifest plugin, quali `[Export]` MEF dichiara.
> Usa `ildasm`, `dotPeek`, `ILSpy` o equivalente per ispezionarlo. Il `.pdb`
> aggiunge nomi di file e righe sorgente per leggibilità. **Regola
> tassativa**: ispezionalo per *imparare la struttura*, poi scrivi codice
> originale per il nostro plugin. NON copiare GUID, nome assembly, nome
> namespace, manifest `Id`, autore: sono di un altro plugin di un altro
> autore — il nostro deve avere identità completamente propria
> (vedi sezione "Identità del plugin" sopra).

---

## 0. PRE-FLIGHT OBBLIGATORIO (leggere PRIMA di scrivere codice)

### Fonti ufficiali da consultare

1. **Repository ufficiale NINA**: `https://github.com/NighttimeImaging/nina`
   - **Versione target fissa: NINA 3.3** (versione installata sul PC di
     Alessandro, confermata direttamente dall'About di NINA).
     Cerca nel repo il tag/branch corrispondente a `3.3` (o `3.3.0`,
     `release/3.3`, equivalente) per leggere le sorgenti reali dell'SDK
     plugin di quella versione.
   - La versione determina:
     - Il `TargetFramework` corretto del `.csproj` del plugin (per NINA 3.3
       è verosimilmente `net8.0-windows` con `<UseWPF>true</UseWPF>` —
       confermare dal `.csproj` del template ufficiale del branch 3.3,
       **non** `net10.0-windows`).
     - I nomi esatti dei package NuGet (storicamente
       `NINACustomControlLibrary`, `NINA.Core`, `NINA.WPF.Base`, ecc. —
       **verificare** sul branch 3.3, non improvvisare).

2. **Plugin template ufficiale di NINA**: cercare nel repo principale (o in un
   repo dedicato tipo `nina-plugin-template`) il template ufficiale di plugin.
   Questo template è la fonte autorevole per:
   - I namespace e le interfacce: `NINA.Plugin.PluginBase`, gli attributi MEF
     (`[Export(typeof(IPluginManifest))]`, `[Export(typeof(IDockableVM))]`),
     l'interfaccia `IDockableVM` o la classe base `DockableVM` con i membri
     veramente esistenti (es. `Title`, `ContentId`, `ImageGeometry`, e quali
     overridable).
   - Il **manifest** del plugin (storicamente un blocco di
     `[assembly: AssemblyMetadata("...", "...")]` in `AssemblyInfo.cs` con
     chiavi tipo `Id`, `Name`, `Author`, `Homepage`, `Repository`,
     `LongDescription`, `FeaturedImageURL`, `ChangelogURL`, `MinimumApplicationVersion`).
     **Verificare i nomi esatti delle chiavi** dal template: improvvisarli fa
     fallire silenziosamente il caricamento del plugin.

3. **WebView2**: il package NuGet è `Microsoft.Web.WebView2`. Verificare la
   versione stabile più recente (al momento siamo oltre `1.0.2900+`). Il
   runtime WebView2 è preinstallato su Windows 11 e su Windows 10 aggiornato;
   sui Windows 10 più datati potrebbe mancare e va segnalato all'utente
   (ma il plugin NON lo deve installare da solo).

4. **DLL + PDB di esempio allegati alla conversazione**:
   `nina.plugin.phd2tools-28d1c731.dll` + `nina.plugin.phd2tools-dce3f00b.pdb`.
   Sono i binari di un plugin NINA reale che maneggia PHD2 (non di Alessandro,
   di un altro autore). **Risparmiano metà del pre-flight su Internet** perché
   contengono i valori reali di un plugin che si carica davvero su NINA 3.3.
   Ispezionali con `ildasm`, `dotPeek`, `ILSpy` o `dotnet ildasm` per
   estrarre:
   - I `PackageReference` reali (dal manifest assembly o dai `using` decompilati)
   - La firma reale del costruttore `DockableVM` (con quali parametri viene
     chiamato il `[ImportingConstructor]`)
   - Le chiavi esatte del manifest plugin (gli `AssemblyMetadata` con i loro
     nomi precisi)
   - Quali `[Export(typeof(...))]` MEF vanno dichiarati per essere visibili
   Il `.pdb` aggiunge nomi di file e numeri di riga per leggibilità.

   **REGOLA TASSATIVA**: ispeziona per *capire la struttura*, poi scrivi
   codice originale. **NON copiare**: GUID, namespace, nome assembly, autore,
   `Id` del manifest. Sono valori specifici di quel plugin di quell'autore.
   Il nostro plugin deve avere identità completamente propria (vedi
   "Identità del plugin" nella nota operativa in testa al prompt).

### Conclusioni del pre-flight (da confermare prima di procedere)

A. **Versione NINA target**: fissata a **NINA 3.3** (confermata da
   Alessandro dall'About di NINA). Usa il `TargetFramework` esatto del
   template ufficiale del branch 3.3. `net10.0-windows` **non esiste** come
   target stabile a oggi: non usarlo.

B. **Package NuGet NINA**: identificare i nomi esatti dei package dell'SDK
   plugin per la versione target. Se si trova un solo metapackage che porta
   dietro tutto, ottimo; se servono più riferimenti separati, elencarli tutti
   nel `.csproj`.

C. **Interfaccia dockable**: `IDockableVM` esiste come interfaccia, e c'è
   tipicamente una classe base `DockableVM` da estendere. Verificare quali
   membri sono `abstract` o `virtual`, e quali property usare per il titolo
   visibile, l'icona, la possibilità di chiudere il pannello.

D. **Cartella di installazione plugin (NINA 3.3)**:
   `C:\Users\aless\AppData\Local\NINA\Plugins\3.3\` — la versione installata
   sul PC di Alessandro è NINA 3.3 (confermata dall'About di NINA). Una
   sotto-cartella `3.0.0\` esiste come residuo di un'installazione
   precedente: **ignorarla**, è sbagliata. Al primo run del pre-flight
   verifica con:
   ```powershell
   Get-ChildItem $env:LOCALAPPDATA\NINA\Plugins\
   ```
   quale sottocartella `3.x` è effettivamente quella attiva (probabile
   `3.3\` o `3.3.0\`). Lo script di install (vedi 2I) usa `3.3` come
   default — se NINA 3.3 dovesse usare un naming a tre componenti
   (`3.3.0\`), adattare il default e segnalarmelo nel riepilogo finale.

### Decisioni di design (già prese — implementare così)

a. **Nessuna dipendenza dal pacchetto Python dell'Agente**: il plugin punta a
   `http://localhost:8080` e basta. Se l'URL non risponde, mostra una pagina
   di fallback con messaggio "L'Agente non è in esecuzione. Avvia
   `Avvia.bat` dal pacchetto Adaptive Agent for PHD2." + pulsante "Riprova".
   NON cercare di avviare il processo Python da qui.

b. **URL configurabile via UI ma con default 8080**: in fase di plugin v1.0
   l'URL è fisso `http://localhost:8080`. Esporre come property pubblica per
   facilitare un futuro override (settings page del plugin), senza
   implementare ora la settings page.

c. **WebView2 single-instance**: il pannello istanzia un solo WebView2 al
   caricamento. Reload manuale tramite pulsante (`Reload`) nel header.
   Niente policy di reload automatico (la dashboard si aggiorna da sola via
   WebSocket, non serve un timer del plugin).

d. **No telemetria, no analytics, no chiamate esterne**: il plugin parla solo
   con `localhost:8080`. NON includere CDN, NON includere font web, NON
   inviare alcuna metrica. Il manifest può citare l'URL Telegram come
   "homepage/supporto" — è statico, non un endpoint.

e. **Niente toggle modale o impostazioni complesse**: header con titolo +
   URL + pulsante Reload, e il WebView sotto. Punto.

### Nessuna verifica → STOP

Se durante il pre-flight scopri:
- che la versione NINA di riferimento ha un `TargetFramework` o un package
  set diverso da quello che ricordo (probabile), **adeguati al reale, non al
  template che ti ho dato**;
- che il manifest plugin usa chiavi differenti da quelle elencate, **usa
  quelle del template ufficiale**;
- che `DockableVM` ha cambiato superficie API (es. richiede oggi
  `ContentId`, `Title`, e altri membri non presenti nella mia bozza),
  **adattati e segnalamelo nel riepilogo finale**;
- che esiste già un plugin NINA chiamato `Adaptive Agent for PHD2 — Dashboard`
  o simile (sicuramente no, ma controlla un attimo): **fermati e dimmi**.

---

## OBIETTIVO TECNICO

Creare da zero un plugin C# WPF per NINA (versione stabile corrente, target
.NET coerente con quella versione) che registra un pannello dockable con
nome utente-visibile "Adaptive Agent for PHD2 — Dashboard". Il pannello
incorpora un controllo `Microsoft.Web.WebView2.Wpf.WebView2` puntato a
`http://localhost:8080`, mostra un header con titolo, URL corrente e un
pulsante Reload, e gestisce con grazia il caso "URL non raggiungibile" con
una pagina di fallback informativa. Nessun'altra funzionalità.

---

## REGOLE INDEROGABILI

- **NON includere** dipendenze al codice Python dell'Agente. Il plugin non
  legge file di configurazione dell'Agente, non importa `phd2_agent`, non
  conosce il file system del pacchetto PHD2.
- **NON tentare** di avviare `PHD2_Agent.exe` dal plugin (lifecycle separato:
  l'utente lo lancia per conto suo dal `.bat`).
- **NON includere** GUID di esempio o presi da altri progetti: generare
  GUID univoco proprio per `[assembly: GuidAttribute(...)]` e per
  l'`Id` del manifest.
- **NON usare** `net10.0-windows`: non esiste come target stabile. Usare
  quello del template NINA ufficiale (probabile `net8.0-windows`).
- **NON aggiungere** dipendenze esterne oltre a `Microsoft.Web.WebView2` e
  il package NuGet ufficiale di NINA. Niente Newtonsoft.Json, niente
  Serilog, niente HTTP client custom: non servono.
- **NON includere** emoji nei nomi file, nei namespace, nei manifest o nel
  codice. Sono ammessi solo nei commenti se chiarificano (sconsigliato).
- **NON committare** binari (`bin/`, `obj/`) nel repository. Aggiungere
  `.gitignore` `dotnet`-standard.
- Mantenere lo stile C# idiomatico: PascalCase per classi/membri, brace
  Allman, `using` diretti in alto, `partial` per code-behind XAML.

---

## SPECIFICA FUNZIONALE

### 2A. Struttura cartelle del nuovo repository

```
AdaptiveAgentForPHD2.NinaPlugin/
├── AdaptiveAgentForPHD2.NinaPlugin.sln           (solution file)
├── README.md                                      (descrizione + istruzioni)
├── LICENSE                                        (testo: All rights reserved)
├── .gitignore                                     (dotnet standard)
├── src/
│   └── AdaptiveAgentForPHD2.NinaPlugin/
│       ├── AdaptiveAgentForPHD2.NinaPlugin.csproj
│       ├── Properties/
│       │   └── AssemblyInfo.cs                    (manifest plugin via AssemblyMetadata)
│       ├── Plugin/
│       │   └── AdaptiveAgentForPHD2Plugin.cs      (entry point: PluginBase)
│       ├── Dashboard/
│       │   ├── AdaptiveAgentDashboardVM.cs        (DockableVM)
│       │   ├── AdaptiveAgentDashboardView.xaml    (UserControl WPF)
│       │   └── AdaptiveAgentDashboardView.xaml.cs (code-behind WebView2 init)
│       ├── Resources/
│       │   └── DataTemplates.xaml                 (DataTemplate VM → View)
│       └── Assets/
│           └── PluginIcon.svg                     (icona vettoriale 24x24 sobria,
│                                                   eventuale; se troppo lavoro,
│                                                   omettere e referenziare null)
└── scripts/
    └── install-plugin.ps1                         (script PowerShell che copia
                                                    la DLL build nella cartella
                                                    plugin NINA dell'utente)
```

**Working directory (FISSA)**:
`C:\Users\aless\Documents\N.I.N.A\AdaptiveAgentForPHD2.NinaPlugin\`

Questa cartella è già stata selezionata da Alessandro come root del progetto
nella sessione Claude Code corrente. Crea qui la struttura `src/`,
`scripts/`, README, LICENSE, ecc. NON committare nulla dentro
`PHD2_Assist_PATCHED\` (è il repo del progetto Python Adaptive Agent for
PHD2 e va tenuto pulito).

**NON usare come working directory la cartella plugin di NINA**
(`C:\Users\aless\AppData\Local\NINA\Plugins\3.3\`). Quella è SOLO il
target di installazione runtime — è dove va depositata la DLL compilata,
non dove vive il sorgente. NINA legge i file `.dll` da lì all'avvio e
ignora tutto il resto (`.csproj`, `.sln`, `.cs`, `.xaml`); inoltre `bin/`
e `obj/` generati dal build di `dotnet` la sporcherebbero con file
temporanei che NINA non sa cosa farsene. Il flusso corretto è:
sviluppo nella working directory sopra → build → copia DLL nella cartella
plugin → NINA la carica al prossimo riavvio. Questo è esattamente quello
che fa lo script `scripts/install-plugin.ps1` (vedi 2I).

Il repository è pronto per essere pubblicato su GitHub in futuro (ma per
v1.0 lo sviluppo è puramente locale, vedi paragrafo "Contesto della scelta
architetturale" in testa).

### 2B. `AdaptiveAgentForPHD2.NinaPlugin.csproj`

Schema (i valori reali di `TargetFramework` e dei package vanno presi dal
template NINA ufficiale dopo il pre-flight):

```xml
<Project Sdk="Microsoft.NET.Sdk">

  <PropertyGroup>
    <TargetFramework>net8.0-windows</TargetFramework>  <!-- conferma dal template NINA -->
    <UseWPF>true</UseWPF>
    <LangVersion>latest</LangVersion>
    <Platforms>x64</Platforms>
    <Nullable>disable</Nullable>
    <RootNamespace>AdaptiveAgentForPHD2.NinaPlugin</RootNamespace>
    <AssemblyName>AdaptiveAgentForPHD2.NinaPlugin</AssemblyName>
    <AppendTargetFrameworkToOutputPath>false</AppendTargetFrameworkToOutputPath>
    <Copyright>Copyright (c) 2026 Alessandro Curci</Copyright>
    <Authors>Alessandro Curci</Authors>
    <Version>1.0.0.0</Version>
    <FileVersion>1.0.0.0</FileVersion>
  </PropertyGroup>

  <!-- Riferimenti SDK NINA — confermare nomi e versioni dal template -->
  <ItemGroup>
    <PackageReference Include="NINACustomControlLibrary" Version="..." />
    <PackageReference Include="NINA.Core" Version="..." />
    <PackageReference Include="NINA.WPF.Base" Version="..." />
    <PackageReference Include="NINA.Plugin" Version="..." />
  </ItemGroup>

  <!-- WebView2 -->
  <ItemGroup>
    <PackageReference Include="Microsoft.Web.WebView2" Version="..." />
  </ItemGroup>

</Project>
```

### 2C. `Properties/AssemblyInfo.cs` — manifest plugin NINA

Questo file è il **manifest del plugin**. NINA lo legge tramite attributi
`AssemblyMetadata`. Le chiavi esatte (es. `Id`, `Author`, `Homepage`,
`Repository`, `ChangelogURL`, `FeaturedImageURL`, `MinimumApplicationVersion`,
`Tags`) vanno **prese dal template ufficiale del pre-flight**, non
inventate. Schema indicativo:

```csharp
using System.Reflection;
using System.Runtime.InteropServices;

// GUID univoco generato per QUESTO plugin — NON copiare da altre fonti
[assembly: Guid("XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX")]

[assembly: AssemblyTitle("Adaptive Agent for PHD2 — Dashboard")]
[assembly: AssemblyDescription("Pannello dockable per NINA che mostra la dashboard web dell'Adaptive Agent for PHD2 in esecuzione su localhost:8080.")]
[assembly: AssemblyCompany("Alessandro Curci")]
[assembly: AssemblyProduct("Adaptive Agent for PHD2 — Dashboard")]
[assembly: AssemblyCopyright("Copyright (c) 2026 Alessandro Curci")]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]
[assembly: ComVisible(false)]

// --- Manifest plugin NINA (chiavi verificate dal template ufficiale) ---
[assembly: AssemblyMetadata("Id", "XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX")]  // stesso GUID
[assembly: AssemblyMetadata("Name", "Adaptive Agent for PHD2 — Dashboard")]
[assembly: AssemblyMetadata("Author", "Alessandro Curci")]
[assembly: AssemblyMetadata("Homepage", "https://t.me/+eewRNpvElSs5OWY8")]
[assembly: AssemblyMetadata("Repository", "")]   // vuoto finché non si pubblica
[assembly: AssemblyMetadata("LongDescription", "Plugin minimale: aggiunge a NINA un pannello dockable che incorpora la dashboard web dell'Adaptive Agent for PHD2 (esposta su http://localhost:8080). Non interagisce con PHD2, non legge file di configurazione, non avvia processi: si limita a mostrare la dashboard. L'Agente deve essere avviato separatamente.")]
[assembly: AssemblyMetadata("ChangelogURL", "")]
[assembly: AssemblyMetadata("FeaturedImageURL", "")]
[assembly: AssemblyMetadata("Tags", "PHD2,Guiding,Dashboard,Adaptive Agent")]
[assembly: AssemblyMetadata("MinimumApplicationVersion", "3.3.0.0")]  // NINA 3.3 (versione installata sul PC di Alessandro)
```

### 2D. `Plugin/AdaptiveAgentForPHD2Plugin.cs` — entry point

```csharp
using NINA.Plugin;
using NINA.Plugin.Interfaces;
using System.ComponentModel.Composition;
using System.Threading.Tasks;

namespace AdaptiveAgentForPHD2.NinaPlugin.Plugin
{
    [Export(typeof(IPluginManifest))]
    public class AdaptiveAgentForPHD2Plugin : PluginBase
    {
        [ImportingConstructor]
        public AdaptiveAgentForPHD2Plugin()
        {
            // Nessuna inizializzazione: il pannello WebView2 si carica
            // quando l'utente apre il dockable dal menu di NINA.
        }

        public override Task Initialize() => Task.CompletedTask;
        public override Task Teardown()   => Task.CompletedTask;
    }
}
```

Verificare con il template ufficiale se servono parametri da iniettare via
`[ImportingConstructor]` (es. `IProfileService`, `IOptionsVM`): se sì,
prenderli ma non usarli (questo plugin non richiede stato della sessione
NINA).

### 2E. `Dashboard/AdaptiveAgentDashboardVM.cs` — ViewModel dockable

```csharp
using NINA.WPF.Base.DockableVM;       // namespace da confermare
using NINA.Core.Utility;              // namespace da confermare
using System.ComponentModel.Composition;

namespace AdaptiveAgentForPHD2.NinaPlugin.Dashboard
{
    [Export(typeof(IDockableVM))]
    public class AdaptiveAgentDashboardVM : DockableVM
    {
        public const string DefaultDashboardUrl = "http://localhost:8080";

        private string _dashboardUrl = DefaultDashboardUrl;
        public string DashboardUrl
        {
            get => _dashboardUrl;
            set { _dashboardUrl = value; RaisePropertyChanged(); }
        }

        [ImportingConstructor]
        public AdaptiveAgentDashboardVM(IProfileService profileService)
            : base(profileService)
        {
            Title       = "Adaptive Agent for PHD2";
            ContentId   = nameof(AdaptiveAgentDashboardVM);
            ImageGeometry = null;  // nessuna icona custom in v1.0
            CanClose    = true;    // l'utente può chiudere il pannello (sblocca
                                   // poi solo se vuole riaprirlo dal menu)
        }
    }
}
```

I namespace `NINA.WPF.Base.DockableVM` e simili sono indicativi: il
pre-flight sul template ufficiale **deve** confermarli. La firma esatta del
costruttore base `DockableVM(IProfileService profileService)` va anch'essa
confermata.

### 2F. `Dashboard/AdaptiveAgentDashboardView.xaml`

```xml
<UserControl
    x:Class="AdaptiveAgentForPHD2.NinaPlugin.Dashboard.AdaptiveAgentDashboardView"
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    xmlns:wv2="clr-namespace:Microsoft.Web.WebView2.Wpf;assembly=Microsoft.Web.WebView2.Wpf"
    xmlns:local="clr-namespace:AdaptiveAgentForPHD2.NinaPlugin.Dashboard"
    Background="{DynamicResource BackgroundBrush}">

    <Grid>
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto" />
            <RowDefinition Height="*" />
            <RowDefinition Height="Auto" />
        </Grid.RowDefinitions>

        <!-- HEADER -->
        <DockPanel Grid.Row="0" Margin="8,6">
            <Button DockPanel.Dock="Right"
                    Content="Reload"
                    Padding="10,3"
                    Click="OnReloadClick" />
            <StackPanel>
                <TextBlock Text="Adaptive Agent for PHD2 — Dashboard"
                           FontWeight="Bold" FontSize="13" />
                <TextBlock Text="{Binding DashboardUrl}"
                           FontSize="10" Opacity="0.7" />
            </StackPanel>
        </DockPanel>

        <!-- WEB VIEW -->
        <wv2:WebView2 Grid.Row="1"
                      x:Name="WebViewControl"
                      DefaultBackgroundColor="Transparent" />

        <!-- FALLBACK PANEL (visibile solo quando WebView non riesce a caricare) -->
        <Border Grid.Row="1"
                x:Name="FallbackPanel"
                Visibility="Collapsed"
                Background="{DynamicResource BackgroundBrush}">
            <StackPanel VerticalAlignment="Center" HorizontalAlignment="Center"
                        MaxWidth="420" Margin="20">
                <TextBlock Text="Agente non raggiungibile"
                           FontSize="16" FontWeight="Bold"
                           HorizontalAlignment="Center" Margin="0,0,0,8" />
                <TextBlock TextWrapping="Wrap"
                           HorizontalAlignment="Center"
                           Text="La dashboard dell'Adaptive Agent for PHD2 non risponde su localhost:8080. Avvia il file Avvia.bat nella cartella del pacchetto Adaptive Agent for PHD2, attendi qualche secondo che la dashboard parta, poi premi Riprova." />
                <Button Content="Riprova"
                        Padding="20,6" Margin="0,16,0,0"
                        HorizontalAlignment="Center"
                        Click="OnReloadClick" />
            </StackPanel>
        </Border>

        <!-- FOOTER -->
        <TextBlock Grid.Row="2" Margin="8,4"
                   FontSize="10" Opacity="0.6"
                   HorizontalAlignment="Center"
                   Text="Adaptive Agent for PHD2 — Dashboard v1.0  ·  by Alessandro Curci  ·  Copyright (c) 2026" />
    </Grid>
</UserControl>
```

### 2G. `Dashboard/AdaptiveAgentDashboardView.xaml.cs`

```csharp
using System;
using System.Windows;
using System.Windows.Controls;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.Wpf;

namespace AdaptiveAgentForPHD2.NinaPlugin.Dashboard
{
    public partial class AdaptiveAgentDashboardView : UserControl
    {
        public AdaptiveAgentDashboardView()
        {
            InitializeComponent();
            Loaded += OnLoaded;
        }

        private async void OnLoaded(object sender, RoutedEventArgs e)
        {
            try
            {
                await WebViewControl.EnsureCoreWebView2Async();
                WebViewControl.CoreWebView2.NavigationCompleted += OnNavigationCompleted;
                NavigateToDashboard();
            }
            catch (Exception ex)
            {
                ShowFallback($"Errore inizializzazione WebView2: {ex.Message}");
            }
        }

        private void NavigateToDashboard()
        {
            FallbackPanel.Visibility = Visibility.Collapsed;
            WebViewControl.Visibility = Visibility.Visible;

            // Legge la property dal VM se presente, altrimenti default.
            var url = (DataContext as AdaptiveAgentDashboardVM)?.DashboardUrl
                      ?? AdaptiveAgentDashboardVM.DefaultDashboardUrl;
            WebViewControl.Source = new Uri(url);
        }

        private void OnNavigationCompleted(object sender, CoreWebView2NavigationCompletedEventArgs e)
        {
            if (!e.IsSuccess)
            {
                ShowFallback(null);
            }
        }

        private void OnReloadClick(object sender, RoutedEventArgs e)
        {
            if (WebViewControl?.CoreWebView2 != null)
            {
                NavigateToDashboard();
            }
        }

        private void ShowFallback(string optionalDebug)
        {
            WebViewControl.Visibility = Visibility.Collapsed;
            FallbackPanel.Visibility  = Visibility.Visible;
            if (optionalDebug != null)
            {
                System.Diagnostics.Debug.WriteLine(optionalDebug);
            }
        }
    }
}
```

### 2H. `Resources/DataTemplates.xaml`

```xml
<ResourceDictionary
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    xmlns:dash="clr-namespace:AdaptiveAgentForPHD2.NinaPlugin.Dashboard">

    <DataTemplate DataType="{x:Type dash:AdaptiveAgentDashboardVM}">
        <dash:AdaptiveAgentDashboardView />
    </DataTemplate>

</ResourceDictionary>
```

Verificare dal template NINA come questo dictionary va registrato (es. via
`MergedDictionaries` in `Themes/Generic.xaml`, o via convenzione di nome).

### 2I. `scripts/install-plugin.ps1`

Script PowerShell per copiare la DLL appena buildata nella cartella plugin
di NINA, in modo che Alessandro non debba farlo a mano ogni volta:

```powershell
# install-plugin.ps1
# Copia la DLL del plugin nella cartella plugin di NINA.
# Default NinaVersion = "3.3" (versione installata su PC di Alessandro,
# confermata da About di NINA). Se NINA 3.3 usa naming a tre componenti
# (es. "3.3.0"), passare il valore esatto con -NinaVersion.
param(
    [string]$Configuration = "Release",
    [string]$NinaVersion   = "3.3"
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot  = Split-Path -Parent $scriptDir
$projDir   = Join-Path $repoRoot "src\AdaptiveAgentForPHD2.NinaPlugin"
$dllName   = "AdaptiveAgentForPHD2.NinaPlugin.dll"
$srcDll    = Join-Path $projDir "bin\$Configuration\$dllName"
$targetDir = Join-Path $env:LOCALAPPDATA "NINA\Plugins\$NinaVersion"

if (-not (Test-Path $srcDll)) {
    Write-Error "DLL non trovata: $srcDll. Esegui prima: dotnet build -c $Configuration"
}
New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
Copy-Item $srcDll -Destination $targetDir -Force
Write-Host "Plugin installato in: $targetDir"
Write-Host "Chiudi e riavvia NINA per caricarlo."
```

---

## BUILD E INSTALLAZIONE

### Build

```powershell
cd <repo-root>\src\AdaptiveAgentForPHD2.NinaPlugin
dotnet build -c Release -p:Platform=x64
```

Output atteso:
- `bin\Release\AdaptiveAgentForPHD2.NinaPlugin.dll`
- (eventuali DLL dipendenti che NINA non porta già: WebView2)

### Installazione

Dalla root del repo:
```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-plugin.ps1 -NinaVersion 3.3
```

Path finale atteso (NINA 3.3 sul PC di Alessandro):
```
C:\Users\aless\AppData\Local\NINA\Plugins\3.3\AdaptiveAgentForPHD2.NinaPlugin.dll
```

Se invece NINA 3.3 usa naming a tre componenti (`3.3.0\`), passare il
valore esatto:
```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-plugin.ps1 -NinaVersion 3.3.0
```

Riavvio NINA → menu `Window` (o equivalente del template UI di NINA) → il
pannello `Adaptive Agent for PHD2 — Dashboard` deve comparire tra i
dockable disponibili.

---

## TEST ATTESI

### Test manuale (non automatizzabile)

1. **Build riuscita**: `dotnet build` finisce con `0 Errors`. Warning
   accettabili solo se non riguardano membri obsoleti di NINA o del template.
2. **Installazione**: lo script copia la DLL nella cartella plugin NINA.
3. **Caricamento da NINA**: avviando NINA, la barra di stato segnala
   "Plugin caricati" senza errori. Nessun popup di errore manifest.
4. **Pannello visibile**: il pannello `Adaptive Agent for PHD2 — Dashboard`
   compare nel menu dei pannelli dockable di NINA.
5. **Caso happy path**: con `PHD2_Agent.exe` in esecuzione (lanciato dal
   `.bat` del pacchetto Adaptive Agent), aprire il pannello → la dashboard
   web si carica nel WebView2 entro 2-3 secondi.
6. **Caso fallback**: chiudere `PHD2_Agent.exe`, aprire il pannello (o premere
   Reload) → compare il pannello di fallback con il messaggio "Agente non
   raggiungibile" e il pulsante "Riprova".
7. **Reload**: rilanciare l'Agente, premere "Riprova" → la dashboard torna
   visibile.

### Test unitari

Per un plugin di sola UI come questo i test unitari non sono indispensabili.
Se vuoi aggiungerne uno solo come sanity check, va bene un test in xUnit che
istanzia `AdaptiveAgentDashboardVM` con un `IProfileService` mockato (es.
con `Moq`) e verifica che `Title`, `ContentId` e `DashboardUrl` abbiano i
valori attesi. NON aggiungere test sul WebView2 (richiederebbe un host WPF e
non vale la complessità).

---

## LIMITI NOTI v1.0 (documentare nel README)

1. **URL fisso**: la dashboard è hard-coded a `http://localhost:8080`. Se in
   futuro qualcuno cambia la porta della dashboard nel `config.toml`
   dell'Agente, il plugin non si aggiorna. Versione futura potrebbe avere
   una settings page.
2. **WebView2 runtime non installato**: su Windows 10 datati senza WebView2
   il plugin mostrerà schermo bianco (perché il controllo `WebView2` non
   riesce a inizializzare e il fallback potrebbe non scattare se l'errore è
   pre-navigation). Nel README inserire nota esplicita: "Se il pannello
   appare bianco e il messaggio di fallback non compare, installa
   **Microsoft Edge WebView2 Runtime** dal sito Microsoft
   (`https://developer.microsoft.com/en-us/microsoft-edge/webview2/`) e
   riavvia NINA." Il plugin NON deve scaricare o installare il runtime
   in autonomia.
3. **Niente riconoscimento automatico dello stato Agente**: il fallback
   scatta solo dopo un fallimento di navigazione, non da un health-check
   proattivo. Va bene per v1.0.
4. **Scope NINA**: testato su NINA 3.3. NINA 2.x e versioni 3.x precedenti
   potrebbero avere differenze nell'SDK plugin; non supportate esplicitamente.

---

## CHECKLIST FINALE PRIMA DI COMMIT

- [ ] Pre-flight eseguito: confermati `TargetFramework`, package NuGet NINA,
      chiavi manifest, firma costruttore `DockableVM` dal template ufficiale
- [ ] GUID univoco generato (NON copiato da altri progetti) e usato
      in `[assembly: Guid(...)]` E nel manifest `AssemblyMetadata("Id", ...)`
- [ ] Nessun riferimento al codice Python dell'Agente
- [ ] Nessun tentativo di avviare `PHD2_Agent.exe` da codice
- [ ] WebView2 puntato a `http://localhost:8080` con fallback funzionante
- [ ] Header con Reload + footer con copyright presenti
- [ ] Script `install-plugin.ps1` testato e funzionante
- [ ] `.gitignore` standard dotnet (esclude `bin/`, `obj/`, `*.user`)
- [ ] README.md con: cosa fa, prerequisiti (NINA installato, WebView2 runtime,
      Adaptive Agent for PHD2 in esecuzione), build, install, link Telegram
- [ ] LICENSE con testo "All rights reserved — Copyright (c) 2026 Alessandro
      Curci"
- [ ] Nessuna emoji in file di codice, manifest o nomi cartelle
- [ ] Build `dotnet build -c Release` chiude con 0 errori
- [ ] Plugin caricato in NINA senza errori, pannello visibile, dashboard
      visualizzata in WebView2

---

## DOMANDE DA FARMI PRIMA DI PROCEDERE (se servono)

Se durante l'implementazione trovi:
- Versione di NINA "stable" che il template ufficiale espone come 3.3
  ha un SDK plugin sostanzialmente diverso da quello atteso (es. nuove
  interfacce, manifest separato, namespace ribattezzati) → **fermati e
  segnalamelo** prima di adattare arbitrariamente lo schema.
- Il template ufficiale NINA usa pattern UI molto diversi dai miei
  (es. `ContentControl` invece di `DockableVM`, o un sistema di
  registrazione pannelli completamente diverso) → **adatta al template e
  segnalalo nel riepilogo finale**, senza mantenere la mia struttura ipotetica
  se è obsoleta.
- WebView2 non funziona dentro un dockable WPF di NINA per qualche ragione
  legacy del rendering theme → **prova prima `WindowsFormsHost` come
  fallback**, e segnalami che non era praticabile la via diretta.
- Il manifest plugin in formato `AssemblyMetadata` non funziona più ed è
  stato sostituito da un `manifest.xml` o `plugin.json` separato → **usa
  quel formato**, è la forma attuale.

→ **Fermati e chiedi**, non improvvisare.

Se invece il pre-flight conferma la struttura attesa, procedi step-by-step:
prima la solution + csproj + build a vuoto (assicurati che NINA SDK risolva),
poi il manifest, poi il VM dockable, poi la View con WebView2, poi il
fallback, infine lo script di install. Mostrami i diff prima di applicarli
ai file più critici (`.csproj`, `AssemblyInfo.cs`, code-behind del WebView).

Grazie.
