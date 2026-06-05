# PROMPT PER CLAUDE CODE (Antigravity) — Plugin NINA v1.2.1 — Auto-reload WebView su transizione online
# Da copiare e incollare integralmente nella conversazione con Claude Code.
# Lavorare nella cartella: C:\Users\aless\Documents\N.I.N.A\AdaptiveAgentForPHD2.NinaPlugin\

> **NOTA OPERATIVA**: questa è una **micro-patch** della v1.2.0.0 esistente
> (Safety Monitor virtuale già installato e validato). Non aggiunge feature,
> risolve un'irritazione di UX presente fin dalla v1.0.
>
> **Bump versione**: `1.2.0.0` → `1.2.1.0` in `AssemblyInfo.cs` e `.csproj`.
> GUID stabile `6F2E9C19-4F66-4F69-B7D3-E21D5AD7458B` INVARIATO.
> GUID Safety Monitor `10A715AD-903C-499E-9CC7-CA8E66A49B7C` INVARIATO.

---

## Problema osservato (validazione sul campo v1.2)

Il pannello dockable WebView2 ha due meccanismi indipendenti per determinare
se l'Agente è raggiungibile:

1. Il **poller** `AgentHealthChecker` (v1.1) che fa `GET /about` ogni N
   secondi e aggiorna il badge "Agente online vX.Y" / "Agente offline"
   in alto a sinistra.
2. Il **WebView2 control** che carica `http://localhost:8080` come pagina
   web e mostra il pannello di fallback "Agente non raggiungibile" se
   `NavigationCompleted.IsSuccess == false`.

**Bug UX**: quando l'Agente cade e poi torna su, il poller riconosce la
transizione (badge diventa verde) ma **il WebView resta nel fallback finché
l'utente non preme manualmente "Riprova"**. I due meccanismi non si parlano.
È un retaggio di design della v1.0 (allora non c'era il poller). Ora che
il poller esiste, possiamo usarlo per auto-rinfrescare il WebView.

## Soluzione

Quando `AgentHealthChecker.StatusChanged` emette una transizione **offline →
online**, il code-behind del View deve chiamare `NavigateToDashboard()`
(metodo già esistente in v1.0) per ricaricare il WebView e nascondere il
fallback. Marshaling sul UI thread tramite `Dispatcher.Invoke`.

---

## PRE-FLIGHT (breve)

L'API necessaria già esiste:
- `AgentServices.Instance.HealthChecker.StatusChanged` (event con
  payload `AgentHealth(bool IsOnline, string? Version)`) — emesso SOLO
  sulle transizioni, già garantito dalla v1.1.
- `AdaptiveAgentDashboardView.NavigateToDashboard()` (private method) —
  esiste dalla v1.0, ricarica il WebView2 nascondendo il fallback.
- WPF `Dispatcher` per marshaling — pattern standard.

---

## OBIETTIVO TECNICO

Aggiungere nel code-behind `AdaptiveAgentDashboardView.xaml.cs` una
sottoscrizione all'evento `StatusChanged` del `HealthChecker`. Quando la
transizione è "offline → online", chiamare `NavigateToDashboard()` sul UI
thread per ricaricare automaticamente il WebView. Disiscriversi
correttamente quando il View viene scaricato (`Unloaded`).

---

## REGOLE INDEROGABILI

- **NON rimuovere** il pannello di fallback né la sua logica di
  attivazione (`NavigationCompleted.IsSuccess == false` continua a
  triggerare il fallback come prima).
- **NON rimuovere** il pulsante "Riprova" del fallback (resta come opzione
  manuale per chi vuole forzare un retry indipendentemente dal poller).
- **NON modificare** altri file oltre al code-behind del View + bump
  versione. In particolare: nessun cambio a `AgentHealthChecker.cs`,
  `AdaptiveAgentSafetyMonitor.cs`, `AgentLauncher.cs`, settings,
  decision engine, niente.
- **NON sottoscriversi** all'evento senza disiscriversi: leak di evento
  garantito altrimenti.
- Marshaling thread-safe sul UI thread tramite `Dispatcher` (l'evento
  arriva dal timer thread del poller).
- Il `NavigateToDashboard()` deve essere chiamato SOLO sulla transizione
  "offline → online" (cioè `e.IsOnline == true` quando il precedente era
  false). NON deve essere chiamato a ogni tick di polling.

---

## SPECIFICA FUNZIONALE

### 2A. Modifica `AdaptiveAgentDashboardView.xaml.cs`

Schema indicativo (adatta i nomi reali se diversi):

```csharp
public partial class AdaptiveAgentDashboardView : UserControl
{
    public AdaptiveAgentDashboardView()
    {
        InitializeComponent();
        Loaded   += OnLoaded;
        Unloaded += OnUnloaded;
    }

    private async void OnLoaded(object sender, RoutedEventArgs e)
    {
        // ... codice esistente per WebView2 init e NavigationCompleted ...

        // v1.2.1: sottoscrivi alle transizioni del poller per auto-reload
        AgentServices.Instance.HealthChecker.StatusChanged += OnAgentHealthChanged;
    }

    private void OnUnloaded(object sender, RoutedEventArgs e)
    {
        AgentServices.Instance.HealthChecker.StatusChanged -= OnAgentHealthChanged;
    }

    private void OnAgentHealthChanged(object? sender, AgentHealth health)
    {
        // Auto-reload solo sulla transizione offline -> online.
        // L'evento StatusChanged è già garantito essere emesso solo sulle
        // transizioni (v1.1), quindi se health.IsOnline == true significa
        // che siamo appena passati da offline a online.
        if (!health.IsOnline) return;

        // Marshaling sul UI thread (l'evento arriva dal timer del poller).
        Dispatcher.Invoke(() =>
        {
            NavigateToDashboard();
        });
    }
}
```

Verifica i nomi reali:
- Nome esatto dell'evento (`StatusChanged` o variante)
- Nome esatto del payload (`AgentHealth` record)
- Path di accesso al composition root (`AgentServices.Instance.HealthChecker`)

Se sono diversi da quanto ipotizzato, usa i nomi reali e segnalalo.

### 2B. Bump versione

In `AssemblyInfo.cs`:
- `[AssemblyVersion("1.2.1.0")]`
- `[AssemblyFileVersion("1.2.1.0")]`

In `.csproj` se la versione è duplicata anche lì:
- `<Version>1.2.1.0</Version>`
- `<FileVersion>1.2.1.0</FileVersion>`

GUID INVARIATO.

---

## TEST MANUALE

1. **Build pulita**: `dotnet build -c Release` → 0 errori 0 warning.
2. **Install**: `scripts\install-plugin.ps1 -NinaVersion 3.0.0` (NINA chiuso).
3. **Verifica versione**: NINA → Options → Plugins → "Adaptive Agent for PHD2 — Dashboard" → versione `1.2.1.0`.
4. **Test del bug fix**:
   - Apri NINA con l'Agente spento → pannello mostra fallback "Agente non raggiungibile".
   - Lancia l'Agente (pulsante "Avvia Adaptive Agent" o manualmente `Avvia.bat`).
   - Entro l'intervallo di polling (default 15s) il badge transita "offline → online" (verde).
   - **Atteso (nuovo comportamento v1.2.1)**: contemporaneamente al badge che diventa verde, il pannello di fallback sparisce e il WebView ricarica automaticamente la dashboard, **senza che tu debba premere "Riprova"**.
5. **Test che il pulsante "Riprova" manuale continua a funzionare**: forza il caricamento del fallback (es. spegnendo l'Agente con WebView aperto), premi "Riprova" → WebView tenta il reload manualmente. Funziona come prima.
6. **Test che la v1.2 Safety Monitor sia invariata**: in NINA → Equipment → Safety Monitor → driver connesso, badge "Sicuro", `IsSafe` reattivo a STAR_LOST simulato esattamente come in v1.2.0.0.

---

## PROCEDURA REBUILD E INSTALL

Identica a v1.0/v1.1/v1.2:

```powershell
cd C:\Users\aless\Documents\N.I.N.A\AdaptiveAgentForPHD2.NinaPlugin\src\AdaptiveAgentForPHD2.NinaPlugin
dotnet build -c Release -p:Platform=x64
cd ..\..
powershell -ExecutionPolicy Bypass -File scripts\install-plugin.ps1 -NinaVersion 3.0.0
```

NINA chiuso prima dell'install.

---

## DOCUMENTAZIONE

**Niente da aggiornare separatamente.** Quando si scriverà §29 in
`NOTE_CLAUDE.md` per la v1.2 (dopo validazione completa), si menzionerà
anche questo piccolo bug fix come parte dello stesso paragrafo
("Plugin v1.2.0.0 + patch v1.2.1.0 — auto-reload WebView su transizione
online"). Niente §29.1 separato, è una patch troppo piccola per meritare
una sezione propria.

---

## CHECKLIST FINALE

- [ ] Code modificato: solo `AdaptiveAgentDashboardView.xaml.cs` + `AssemblyInfo.cs` + `.csproj`
- [ ] Versione bumpata a 1.2.1.0 (assembly e file)
- [ ] GUID INVARIATI (plugin + Safety Monitor)
- [ ] Sottoscrizione a `StatusChanged` su `Loaded`, disiscrizione su `Unloaded` (no leak)
- [ ] Auto-reload SOLO su transizione offline → online
- [ ] Marshaling tramite `Dispatcher.Invoke`
- [ ] Pannello di fallback intatto, pulsante "Riprova" intatto e funzionante
- [ ] `dotnet build -c Release` → 0/0
- [ ] Safety Monitor v1.2 invariato (verificato dopo build)
- [ ] Test manuale del bug fix passato

---

## DOMANDE PRIMA DI PROCEDERE

Se trovi che il nome dell'evento `StatusChanged` è diverso, o che il
payload `AgentHealth` non è un record con `IsOnline`/`Version` esattamente
così, **usa i nomi reali** e segnalalo nel riepilogo finale. Non
improvvisare.

Stima: ~15-25 righe C# nuove totali. Se superi le 50 righe, fermati e
capiamo insieme cosa abbiamo gonfiato.

Grazie.
