# PROMPT per Claude Code — §42: Step 0 telemetria NINA — LATO PLUGIN (inoltro metriche per-posa → Agente)

> **Questo è il secondo metà dello Step 0.** Il lato Agente (`POST /nina/telemetry`, store, blocco `nina` in `/status`, contratto `schema_version=1`) è già fatto in **§41**. Qui si fa la sorgente: il **plugin NINA** si iscrive all'evento di posa salvata e **inoltra** le metriche per-posa all'Agente. Senza questo, l'endpoint §41 resta inerte.
>
> **⚠️ DUE COSE CHE CODE DEVE SAPERE SUBITO:**
> 1. **Il plugin è un REPO SEPARATO, in un'ALTRA cartella.** NON è in `AdaptiveAgentPHD2/` (dove hai lavorato per il §41). È in **`AdaptiveAgentForPHD2.NinaPlugin/`** (cartella sorella, repo GitHub `Mamete91/AdaptiveAgentPHD2-NinaPlugin`). Il sorgente C# vive in `AdaptiveAgentForPHD2.NinaPlugin/src/AdaptiveAgentForPHD2.NinaPlugin/`. **Apri quel repo prima di iniziare** — è il motivo per cui finora "non vedevi il plugin".
> 2. **Congelamento RIMOSSO (Alessandro, 2026-06-18).** Il sorgente del plugin su QUESTO PC è **identico** a quello del PC in riparazione → il PC in riparazione **non serve più**: si sviluppa, si builda e si valida **qui**. Resta solo un requisito di **toolchain**: serve il **.NET 8 SDK** (sul PC c'è solo il runtime). Vedi FASE 0.
>
> **Direttiva:** inoltro **opzionale e graceful** — se l'Agente è offline, il plugin **non deve mai disturbare NINA** (niente eccezioni nel pipeline di imaging, niente retry-storm). Toggle attivo (`true`) di default nelle settings (born-operative).
> **Contratto:** rispettare ESATTAMENTE lo schema §41 (`PROMPT_TELEMETRIA_NINA_STEP0.md` §2E, `schema_version=1`).
> Contesto: `REVISIONE_ARCHITETTURALE_v2.6.md` (§5, §6, §9), `ROADMAP_TELEMETRIA_NINA.md` (Step 0), `PRINCIPIO_CONVERGENZA_PRESTAZIONE.md` (P1).

## 0. FASE 0 — PREDISPORRE L'AMBIENTE + 2 PREREQUISITI (autorizzato)

**0.A — Installa il .NET 8 SDK se manca.** `dotnet --info`: se mostra solo *runtime* e "No SDKs were found", installa l'SDK (autorizzato da Alessandro):
```
winget install Microsoft.DotNet.SDK.8
```
Poi ricontrolla `dotnet --info` finché compare un SDK 8.x. Se `winget` non è disponibile o l'install fallisce per permessi, **riporta il comando esatto** così Alessandro lo lancia a mano (è una sola riga). NON proseguire al build finché l'SDK non c'è.

**0.B — Fix Agente (1 riga, lato Python) PRIMA del plugin.** Il modello `NinaImageMetrics` in `server.py` (§41) **non ha il campo `fwhm`**, e pydantic v2 **scarta i campi sconosciuti** → la FWHM (arcsec) inviata dal plugin verrebbe persa. Aggiungere:
```python
fwhm: Optional[float] = Field(default=None, ge=0)   # FWHM medio (arcsec) — cross-setup comparabile
```
accanto a `hfr` in `NinaImageMetrics`. (I 3 "buchi §41" della vecchia nota — sezione `[nina_telemetry]`, parsing in `config.py`, `NOTE §41` — risultano GIÀ chiusi: `config.toml:222`, `config.py:529`, `NOTE:2249`. Verificare e non rifarli.)

## 0bis. FASE 1 — PRE-FLIGHT (sola lettura, a SDK presente)

**1.1 — Apri il repo giusto.** `AdaptiveAgentForPHD2.NinaPlugin/` (sorella di `AdaptiveAgentPHD2/`). Conferma il git remote = `…-NinaPlugin`. Il sorgente è in `src/AdaptiveAgentForPHD2.NinaPlugin/`.

**1.2 — Build di base (con SDK installato).** `dotnet restore` (tira giù `NINA.Plugin 3.2.0.9001` + `Microsoft.Web.WebView2 1.0.3296.44` + `CommunityToolkit.Mvvm 8.4.0`, `ExcludeAssets=runtime`) e `dotnet build -c Release` del progetto **as-is** PRIMA di ogni modifica → conferma 0 errori e riporta i warning di partenza (baseline). Se il restore/build fallisce, riporta l'errore esatto e fermati.

**0.3 — Mapping API NINA — GIÀ VERIFICATO da Cowork sul sorgente aperto (`github.com/daleghent/nina`, branch `develop`, 2026-06-18).** Usa questa tabella; **conferma solo che la NINA installata (3.2.0.9001) esponga gli stessi tipi** (l'API è stabile da anni, ma `IImageStatistics` va ricontrollato — vedi nota). NON ripartire "a memoria": questo viene dal codice MPL-2.0 reale.

- **Evento:** `IImageSaveMediator.ImageSaved` → `event EventHandler<ImageSavedEventArgs>` (verificato in `NINA.WPF.Base/Mediator/ImageSaveMediator.cs` + `Interfaces/Mediator/IImageSaveMediator.cs`). Iniezione MEF nel costruttore plugin (`[ImportingConstructor] (IImageSaveMediator imageSaveMediator)`) — pattern identico al plugin Lightbucket.
- `ImageSavedEventArgs` (campi verificati): `ImageMetaData MetaData`, `BitmapSource Image`, `IImageStatistics Statistics`, `IStarDetectionAnalysis StarDetectionAnalysis`, `Uri PathToImage`, `FileTypeEnum FileType`, `bool IsBayered`, `double Duration`, `string Filter`.
- `IStarDetectionAnalysis` (verificato in `NINA.Image/Interfaces/IStarDetectionAnalysis.cs`): `double HFR` (unità **PIXEL**, `HFRUnit=Pixels`), `double FWHM` (unità **ARCSEC**, `FWHMUnit=Arcseconds`), `double Eccentricity` (**PRESENTE** — NON è da omettere), `double HFRStDev` (pixel), `int DetectedStars`, `List<DetectedStar> StarList`.

**Tabella contratto §41 `image.*` → proprietà NINA reale:**

| `image.*` (§41) | Proprietà NINA (`ImageSavedEventArgs e`) | Tipo / unità | Nota |
|---|---|---|---|
| `hfr` | `e.StarDetectionAnalysis.HFR` | double / **px** | |
| `hfr_std` | `e.StarDetectionAnalysis.HFRStDev` | double / px | |
| `star_count` | `e.StarDetectionAnalysis.DetectedStars` | int | proxy trasparenza primario |
| `eccentricity` | `e.StarDetectionAnalysis.Eccentricity` | double | **confermato presente** → segnale N4 elongazione |
| `fwhm` *(NUOVO, consigliato)* | `e.StarDetectionAnalysis.FWHM` | double / **arcsec** | cross-setup comparabile (come §36 per l'RMS) — aggiungilo al contratto |
| `mean_adu` | `e.Statistics.Mean` | double | ⚠️ confermare nome su `IImageStatistics` |
| `median_adu` | `e.Statistics.Median` | double | proxy fondo cielo ⚠️ confermare |
| `stdev_adu` | `e.Statistics.StDev` | double | ⚠️ confermare |
| `exposure_s` | `e.Duration` | double / s | |
| `filter` | `e.Filter` | string | |
| `ts_unix` | ora del POST (o `e.MetaData.Image.ExposureStart`) | | |

- ⚠️ **Unico punto da confermare sull'SDK/GitHub:** i nomi esatti di `IImageStatistics` (`Mean`/`Median`/`StDev`/`Max`/`Min`) — il file `NINA.Image/Interfaces/IImageStatistics.cs` non è stato leggibile via fetch (servito come binario). Code lo apra su GitHub (`daleghent/nina`) o nella DLL `NINA.Image.dll` installata e confermi i 3 nomi prima di mapparli.
- `StarDetectionAnalysis` può essere **null** (frame senza star detection / detection off) → **null-check e skip POST** (no payload spazzatura).
- **Per N7 (futuro):** esiste `BeforeFinalizeImageSaved` con `AddImagePattern(...)` → è il gancio per iniettare un pattern/keyword di qualità nella posa. Annotarlo, non usarlo ora.

**0.4 — Leggi l'architettura del plugin esistente** (per agganciarti senza romperla):
- `AgentServices.cs` — composition root statico (singleton `Lazy<>`). È qui che vive l'infrastruttura condivisa (Settings, HealthChecker, Safety).
- `Health/AgentHealthChecker.cs` — **riusa il pattern `HttpClient`** (timeout 3s, mai propaga eccezioni, `ConfigureAwait(false)`). Il tuo forwarder POST imita questo.
- `Plugin/AdaptiveAgentForPHD2Plugin.cs` — lifecycle `Initialize`/`Teardown` (dove iscrivere/disiscrivere l'evento).
- `Settings/PluginSettings.cs` — pattern settings persistite (`settings.json`); `DashboardUrl` già esiste (riusalo per l'URL del POST).
- `Safety/*` — **NON toccare** in §42 (il consumo della trasparenza per N6 è un prompt successivo).

**0.5 — Conferma il contratto §41.** Rileggi `AdaptiveAgentPHD2/PROMPT_TELEMETRIA_NINA_STEP0.md` §2E: `schema_version=1`, `source`, `ts_unix`, blocco `image{hfr,hfr_std,star_count,eccentricity,mean_adu,median_adu,stdev_adu,exposure_s,filter}`, blocco `context{}` **OPZIONALE** (rimandato a N2). L'endpoint è `POST <DashboardUrl>/nina/telemetry`.

## 1. OBIETTIVO (Fase 2, solo se il gate 0.2 è verde)

Il plugin si iscrive a `IImageSaveMediator.ImageSaved`; a ogni posa salvata mappa le metriche disponibili sul contratto §41 e le **POSTa** all'Agente, **fire-and-forget**, senza mai poter disturbare NINA. Toggle nelle settings (default ON). Nessun consumatore lato Agente cambia (resta §41): qui si riempie solo il tubo.

## 2. SPECIFICA

### 2A — Servizio `TelemetryForwarder` (nuovo)
1. Nuova classe (es. `Telemetry/AgentTelemetryForwarder.cs`) registrata nel composition root `AgentServices` (stesso pattern `Lazy<>`).
2. Inietta/riceve `IImageSaveMediator` e `PluginSettings`. In `Initialize` del plugin **si iscrive** a `ImageSaved`; in `Teardown` **si disiscrive** (simmetrico, idempotente).
3. **L'handler di `ImageSaved` deve essere veloce e non-throwing**: estrae i campi, costruisce il payload, e lancia il POST come **task fire-and-forget** (`_ = PostAsync(...)`). NON awaitare dentro l'handler in modo da rallentare/bloccare il salvataggio della posa.

### 2B — Mapping eventargs → contratto §41 (usa la tabella 0.3 verificata)
1. Costruisci il JSON `schema_version=1`, `source="nina-plugin"`, `ts_unix`, `image{…}` con la mappatura 0.3. `eccentricity` **è presente** (mappalo, non ometterlo). **Aggiungi `fwhm`** (arcsec) al contratto — è additivo e l'Agente §41 tollera campi extra; vale per la comparabilità cross-setup. Solo i 3 campi `*_adu` restano da confermare su `IImageStatistics`: se un nome non c'è, ometti quel singolo campo (il lato Agente tollera i mancanti), non bloccare il resto.
2. `context{}` **NON** in §42 (arriva con N2: serviranno `IFocuserMediator`/`ITelescopeMediator`/`IFilterWheelMediator`). Mandare solo `image`.
3. **Null-check `StarDetectionAnalysis`** (può essere null se la detection non ha girato): in tal caso **skip del POST** — niente payload senza star detection.

### 2C — POST graceful (riusa il pattern HttpClient)
1. `POST <Settings.DashboardUrl>/nina/telemetry`, `Content-Type: application/json`, timeout breve (≤3s).
2. **Swallow totale delle eccezioni** (Agente offline/timeout/refused/500 → log `Debug`/niente, MAI eccezione che risalga a NINA). Nessun retry aggressivo (al più un tentativo; la prossima posa riprova naturalmente).
3. Non creare un `HttpClient` per posa (socket exhaustion): client riusato (statico/singleton), come il `HealthChecker`.

### 2D — Settings
1. Nuovo toggle `ForwardTelemetryToAgent` (default **true**) in `PluginSettings`, persistito in `settings.json`, esposto nella `PluginSettingsView`. Quando `false`, il forwarder è iscritto ma **non POSTa** (kill-switch lato plugin).
2. Riusa `DashboardUrl` esistente (non duplicare l'URL).

### 2E — Versione & compatibilità (attenzione alla lezione WebView2)
1. Bump versione plugin (es. `1.2.x` → **`1.3.0.0`**) in `AssemblyInfo`/`.csproj` e nei punti dove la versione compare.
2. **NON toccare** le dipendenze `NINA.Plugin` / `Microsoft.Web.WebView2` / `CommunityToolkit.Mvvm`: il progetto ha già risolto un mismatch WebView2 3.2-vs-3.3 (downgrade mirato). Aggiungi solo funzionalità; mantieni `ExcludeAssets=runtime`. Ricompila e verifica che giri su NINA 3.2 stable.
3. GUID del plugin e del Safety Monitor **invariati**.

## 3. REGOLE INDEROGABILI
- **Repo plugin** (`AdaptiveAgentForPHD2.NinaPlugin/`), **non** l'Agente Python (§41 già fatto, non rimetterci mano).
- **Opzionale e graceful**: Agente offline → no-op silenzioso; NINA **mai** disturbata; nessuna eccezione dall'handler `ImageSaved`; nessun blocco del salvataggio posa.
- **NON toccare**: la shell WebView/dashboard, l'`AgentHealthChecker`, il **Safety Monitor** e il `SafetyDecisionEngine` (N6 = prompt successivo), le dipendenze NINA/WebView2.
- **Niente `context{}`** in §42 (N2). Solo `image{}`.
- Se manca il .NET 8 SDK (FASE 0.A) → installalo prima; non scrivere/buildare codice plugin finché `dotnet --info` non mostra un SDK 8.x.

## 4. TEST / VALIDAZIONE
1. **Build pulita** `dotnet build -c Release` (0 errori; riporta i warning, atteso come la baseline 0.2).
2. **Manuale con Agente vivo**: avvia l'Agente (§41), avvia NINA col plugin, scatta/lascia salvare una posa → su `GET http://localhost:8080/status` il blocco `nina` passa a `connected:true` con HFR/star_count reali; dopo `staleness_seconds` (180) torna `connected:false` conservando l'ultimo payload.
3. **Graceful con Agente spento**: Agente NON in esecuzione → la posa si salva regolarmente in NINA, **nessun errore/popup**, il plugin logga al più un Debug. NINA prosegue la sequenza.
4. **Toggle off**: `ForwardTelemetryToAgent=false` → nessun POST (verifica su `/status.nina.connected=false`).
5. **Campi mancanti**: se un campo opzionale non è disponibile (es. uno degli `*_adu` di `IImageStatistics` da confermare), il payload lo omette e l'Agente accetta lo stesso (§41 test 2). NB: `eccentricity` e `fwhm` SONO disponibili (verificati su GitHub) → mappali.
6. (Se esiste un progetto di test C#) unit test del mapping eventargs→JSON; altrimenti dichiarare la validazione come manuale.

## 5. BUILD/INSTALL + DOC
- **Build (Windows):** `cd src\AdaptiveAgentForPHD2.NinaPlugin; dotnet build -c Release` → `install-plugin.ps1` → riavvia NINA. (Il sandbox Linux non builda .NET: la build è sul PC di Alessandro.)
- **DOC plugin** (nel repo plugin): aggiorna `README.md` (nuova capability: inoltro telemetria, toggle, requisito Agente §41).
- **DOC progetto** (repo Agente): in `ROADMAP_TELEMETRIA_NINA.md` spunta **Step 0 — lato plugin `[ ]`→`[x]` (§42)**; aggiungi la nota in `CONTESTO_PROGETTO.md`.
- **Numerazione:** questo prompt plugin = **§42** in `NOTE_CLAUDE.md`. (Il §41 lato Agente — sezione `[nina_telemetry]`, parsing `config.py`, `NOTE §41` — risulta già chiuso: `config.toml:222`, `config.py:529`, `NOTE:2249`; verificare e non rifarlo. Unica aggiunta Agente: `fwhm`, FASE 0.B.)

## 6. CHECKLIST FINALE
- [ ] FASE 0: `.NET 8 SDK` installato (`dotnet --info` mostra SDK 8.x); **`fwhm` aggiunto** a `NinaImageMetrics` (0.B); §41 confermato già chiuso.
- [ ] FASE 1: repo plugin aperto; `dotnet restore` + build as-is OK (baseline warning riportata).
- [ ] Mapping 0.3 (già verificato su GitHub) applicato; `eccentricity` e `fwhm` mappati; solo i 3 `*_adu` confermati su `IImageStatistics`.
- [ ] `AgentTelemetryForwarder` iscritto in Initialize / disiscritto in Teardown; handler veloce e **non-throwing**; POST fire-and-forget.
- [ ] Payload `schema_version=1`, solo `image{}` (niente `context`); campi mancanti omessi; client HttpClient riusato.
- [ ] Toggle `ForwardTelemetryToAgent` (default true) in settings + view; kill-switch testato.
- [ ] Dipendenze NINA/WebView2 invariate; gira su NINA 3.2 stable; GUID invariati; versione bumpata.
- [ ] Test 1–5 (build pulita, Agente vivo→connected, Agente spento→graceful, toggle off, campi mancanti).
- [ ] **`fwhm`** aggiunto a `NinaImageMetrics` (FASE 0.B) — altrimenti la FWHM-arcsec viene scartata da pydantic.
- [ ] DOC: README plugin + ROADMAP Step 0 lato-plugin `[x]` + CONTESTO + NOTE_CLAUDE §42. Niente commit/push (prompt git dedicato).

> **P1.** Col §42 l'occhio ortogonale si apre davvero: l'Agente comincia a ricevere la forma reale delle stelle nella posa. Ancora nessuno agisce su quel dato (N2→N1→N8→N3/N4 sono i prossimi), ma da qui in poi ogni diagnosi del motore §31 potrà essere confrontata con l'esito di imaging vero — il primo passo per convergere verso la prestazione reale, non verso il proxy RMS.
