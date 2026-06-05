# PROMPT PER CLAUDE CODE (Antigravity) — Plugin v1.2 — Documentazione e nuovo ZIP di distribuzione
# Da copiare e incollare integralmente nella conversazione con Claude Code.

> **NOTA OPERATIVA**: la validazione sul campo del plugin v1.2.2.0 è
> confermata (Safety Monitor connesso e reattivo a `STAR_LOST` nel simulator;
> auto-reload WebView su transizione online; pannello stabile su cambio
> schermata NINA dopo il fix v1.2.2). Niente più modifiche al codice del
> plugin in questa sessione — chiudiamo solo il cerchio documentazione +
> distribuzione, stesso pattern dei task post-v1.1 che hai già fatto.

Quattro task in sequenza:

1. **§29 in `NOTE_CLAUDE.md`** del repo Python (copre v1.2.0.0 + v1.2.1.0 + v1.2.2.0 in un'unica sezione)
2. **Manuale (md + txt + PDF)** — sotto-paragrafo "Novità v1.2: Safety Monitor virtuale" dentro la sezione "Bonus: usare la dashboard dentro NINA"
3. **`LEGGIMI_PER_AVVIARE.txt`** — riga sul Safety opt-in nella sezione (*) installazione plugin
4. **Cartella plugin distribuzione + nuovo ZIP** — DLL v1.2.2.0, ZIP `Adaptive_Agent_PHD2_v2.2.zip` rigenerato

---

## Task 1 — `NOTE_CLAUDE.md` §29

Path: `C:\Users\aless\Downloads\PHD2_Assist_PATCHED\PHD2_Assist_PATCHED\NOTE_CLAUDE.md`

Verifica prima con `grep "^## [0-9]" NOTE_CLAUDE.md | tail -1` che l'ultima
sezione sia §28 — la nuova è §29. Struttura standard (Motivazione,
Architettura, Componenti, Comportamento atteso, File modificati,
Validazione, Limiti, Stato finale).

Punti chiave da catturare nella sezione (paragrafo unico che copre tutta
la v1.2):

**Motivazione**: estensione del modello safety nativo di NINA tramite un
driver virtuale che riflette lo stato della guida dell'Agente. Filosofia
"separation of concerns": il plugin osserva e segnala (flag IsSafe), NINA
decide e agisce in base alle policy configurate dall'utente. Idiomatica
nel modello equipment di NINA, zero invasività su `ISequenceMediator`.

**Architettura del Safety Monitor (v1.2.0.0)**:
- MEF: il pattern reale di NINA per equipment custom è
  `[Export(typeof(IEquipmentProvider))]` su una classe
  `AdaptiveAgentSafetyMonitorProvider : IEquipmentProvider<ISafetyMonitor>`,
  non `[Export(typeof(ISafetyMonitor))]` direttamente — questa scoperta
  è venuta dal pre-flight ilspycmd di Code prima di scrivere codice.
- Driver `AdaptiveAgentSafetyMonitor : BaseINPC, ISafetyMonitor` con
  Category `N.I.N.A.`, GUID stabile `10A715AD-903C-499E-9CC7-CA8E66A49B7C`
  (distinto dal GUID plugin `6F2E9C19-4F66-4F69-B7D3-E21D5AD7458B`).
- Decision engine: **una sola condizione** di unsafe —
  `guiding_state == "STAR_LOST"` consolidato per
  `StarLostConsolidationSeconds` (default 300 = 5 minuti).
  Esclusi esplicitamente `escalation_gate.ra && escalation_gate.dec`
  (apertura path B esposizione §19, NON emergenza), `saturation.active`
  (recovery AI Star Finder, NON fallimento), RMS oltre soglia (soglia
  dinamica, l'Agente sta già reagendo).
- Asimmetria temporale intenzionale: 5 minuti per dichiarare unsafe
  (alta evidenza), ~45s (3 poll consecutivi NORMAL) per tornare safe
  (reattività al recupero).
- Connected/Disconnected: il driver si auto-disconnette quando l'Agente
  smette di rispondere — NINA tratta la perdita di comunicazione come
  "safety scollegato" (più onesto che mantenere stale data).
- Settings nuove: una sola property `StarLostConsolidationSeconds`
  (default 300, range 30-1800).
- Polling esteso: `AgentHealthChecker` (v1.1) ora legge anche `/status`
  quando il safety è connesso; quando disconnesso, torna a leggere solo
  `/about` (efficienza).

**Auto-reload WebView (patch v1.2.1.0)**: risolve un retaggio di design
v1.0 in cui il pannello di fallback "Agente non raggiungibile" restava
visibile finché l'utente non premeva manualmente "Riprova", anche se il
poller v1.1 sapeva già che l'Agente era tornato online. Auto-reload del
WebView sulla transizione offline → online del poller tramite
sottoscrizione a `StatusChanged`. Pulsante "Riprova" manuale invariato
come fallback per casi limite. ~22 righe nel code-behind del View.

**Fix cambio schermata (patch v1.2.2.0)**: la v1.2.1 risolveva il caso
"Agente torna online durante la sessione", ma mancava il caso "View
ricaricato da NINA dopo cambio schermata". Quando NINA scarica/ricarica
un pannello dockable (es. cambio tab o cambio layout), il `Loaded` del
View provoca un nuovo `Navigate` del WebView2; se il primo
`NavigationCompleted` arriva con `IsSuccess = false` (timing sfortunato
con risorse sub-page), il fallback si attiva. Ma il poller dice già
online → niente transizione → handler v1.2.1 non scatta → fallback resta.
Fix: nel `Loaded` del View, dopo sottoscrizione, check immediato dello
stato corrente del poller; se online, schedula `NavigateToDashboard()`
ritardato di 500ms via `Dispatcher.BeginInvoke` con
`DispatcherPriority.Background`. Aggiunto guard difensivo
`if (!this.IsLoaded) return;` nell'handler. ~10-15 righe nette aggiunte.

**File modificati nel repo plugin (NON nel repo Python)**:
- `src/AdaptiveAgentForPHD2.NinaPlugin/Safety/AdaptiveAgentSafetyMonitorProvider.cs` (nuovo)
- `src/AdaptiveAgentForPHD2.NinaPlugin/Safety/AdaptiveAgentSafetyMonitor.cs` (nuovo)
- `src/AdaptiveAgentForPHD2.NinaPlugin/Safety/SafetyDecisionEngine.cs` (nuovo)
- `src/AdaptiveAgentForPHD2.NinaPlugin/Health/AgentHealthChecker.cs` (esteso: `StatusPollingEnabled`, `StatusUpdated`, probe `/status` mirato via `JsonDocument`)
- `src/AdaptiveAgentForPHD2.NinaPlugin/Settings/PluginSettings.cs` + `.xaml` (1 property nuova)
- `src/AdaptiveAgentForPHD2.NinaPlugin/AgentServices.cs` (`Lazy<SafetyDecisionEngine>`, `Lazy<AdaptiveAgentSafetyMonitor>`)
- `src/AdaptiveAgentForPHD2.NinaPlugin/Dashboard/AdaptiveAgentDashboardView.xaml.cs` (auto-reload + fix cambio schermata)
- `AssemblyInfo.cs` + `.csproj`: versione → 1.2.2.0, GUID plugin INVARIATO

**File modificati nel repo Python**:
- `Pacchetto_Distribuzione/LEGGIMI_PER_AVVIARE.txt`: una riga sul safety opt-in nella sezione (*) plugin
- `doc/Manuale_Utente_Agent.md` / `.txt` / `build_manual_pdf.py`: sotto-paragrafo "Novità v1.2: Safety Monitor virtuale" nella sezione "Bonus: usare la dashboard dentro NINA"
- Nessuna modifica al codice Python dell'Agente

**Validazione sul campo**:
- Simulator NINA + Agente simulator con `StarLostConsolidationSeconds=30` per test rapido: transizione safe→unsafe in ~30s di STAR_LOST consolidato, ritorno safe in ~45s di NORMAL ✓
- Auto-reload sulla transizione offline→online del poller ✓
- Pannello stabile su cambio schermata NINA dopo fix v1.2.2 ✓
- Pulsante "Riprova" manuale continua a funzionare ✓
- Pulsante "Avvia Adaptive Agent" v1.1 + badge stato v1.1 invariati ✓
- WebView v1.0 invariato ✓

**Limiti dell'approccio**:
1. Una sola condizione unsafe (STAR_LOST consolidato). Condizioni più
   sofisticate (combinazioni multi-criterio) potrebbero emergere dai
   feedback Telegram — eventuale v1.3.
2. Il fix v1.2.2 ricarica il WebView 500ms dopo il `Loaded` del View;
   in casi rari di apertura/chiusura rapidi del pannello potrebbe esserci
   un breve flash visivo. Accettabile per v1.2.
3. Le reazioni concrete a un unsafe (pausa sequenza, parking, ecc.) NON
   sono nel plugin — sono configurate dall'utente in NINA tramite
   Options → Safety (policy globale) o tramite Advanced Sequencer
   (`Trigger On Unsafe`, `Wait until safe`).

**Stato finale**: plugin v1.2.2.0 stabile, installato in
`%LOCALAPPDATA%\NINA\Plugins\3.0.0\AdaptiveAgentForPHD2.NinaPlugin\`,
validato sul campo. Pronto per la distribuzione opzionale dentro il
pacchetto Telegram della community insieme all'Agente Python v2.2.

---

## Task 2 — Manuale (md + txt + PDF)

Nei tre file:
- `doc/Manuale_Utente_Agent.md`
- `doc/Manuale_Utente_Agent .txt` (nota lo spazio nel nome — invariato)
- `doc/build_manual_pdf.py` → poi rigenerazione PDF

Trova la sezione **"Bonus: usare la dashboard dentro NINA (plugin opzionale)"**
e dopo il sotto-paragrafo esistente "Novità v1.1: pulsante Avvia e badge stato"
aggiungi un nuovo sotto-paragrafo "Novità v1.2: Safety Monitor virtuale" con
contenuto del tipo:

> **Novità v1.2: Safety Monitor virtuale (opzionale).** Il plugin v1.2
> espone anche un Safety Monitor virtuale che NINA può usare come driver
> di sicurezza accanto al pannello dockable. Il driver appare nella tendina
> Equipment → Safety Monitor di NINA sotto la categoria N.I.N.A. col nome
> "Adaptive Agent for PHD2 — Guide Safety". Selezionandolo e cliccando
> Connect, NINA inizia a riflettere lo stato della guida dell'Agente come
> flag safe/unsafe: il driver dichiara unsafe quando `STAR_LOST` persiste
> oltre il timeout configurato (default 5 minuti). Quando la guida torna
> stabile per ~45 secondi consecutivi, il driver torna safe.
>
> Importante: il driver Safety NON decide cosa fare al verificarsi
> dell'unsafe — segnala soltanto. Le reazioni concrete (pausa sequenza,
> parking, warm-up camera, ecc.) si configurano dentro NINA, in Options →
> Safety (policy globale) oppure nell'Advanced Sequencer (istruzione
> `Wait until safe` e Global Trigger `Trigger On Unsafe`). Per uso
> domestico con supervisione attiva, la configurazione consigliata è:
> abilitare "Pause sequence on unsafe" + "Resume on safe" nelle policy
> globali, senza azioni custom aggressive (parking, warm-up). Per uso
> remoto non sorvegliato, conviene aggiungere un `Trigger On Unsafe` con
> una sequenza custom di "safe shutdown".
>
> Se l'Agente Python smette di rispondere mentre il driver è connesso,
> il driver si auto-disconnette: NINA tratta la perdita di comunicazione
> come "safety scollegato" e applica la policy che hai impostato per
> quel caso (tipicamente alert + sospensione conservativa). Quando
> l'Agente torna disponibile, riconnetti manualmente il driver dalla
> tendina Safety Monitor.
>
> La feature è opzionale: chi vuole solo il pannello dashboard (v1.0) o
> il pulsante Avvia + badge (v1.1) non è toccato dal Safety. Si attiva
> esplicitamente selezionando il driver in NINA.

Tono coerente col resto del manuale (asciutto, prosa, niente bullet
eccessivi). Usa `[!IMPORTANT]` o `[!TIP]` solo se serve davvero
(probabilmente uno solo, per il "il driver NON decide, segnala soltanto").

Nel `.txt` riporta lo stesso testo senza markdown.

Nel `build_manual_pdf.py` inserisci il paragrafo equivalente nella sezione
PDF corrispondente — riusa lo stile dei sotto-paragrafi v1.1 già presenti.

**Rigenerazione PDF**: `python doc/build_manual_pdf.py`, verifica timestamp
aggiornato + parole chiave "Safety Monitor virtuale" e "Wait until safe"
trovate nel testo estraibile.

---

## Task 3 — `LEGGIMI_PER_AVVIARE.txt`

Path: `C:\Users\aless\Downloads\PHD2_Assist_PATCHED\PHD2_Assist_PATCHED\Pacchetto_Distribuzione\LEGGIMI_PER_AVVIARE.txt`

Nella sezione esistente "(*) COME INSTALLARE IL PLUGIN NINA", subito dopo
il blocco "NOVITA' v1.1 (Launch Agent + badge stato)", aggiungi un piccolo
blocco analogo:

```text
NOVITA' v1.2 (Safety Monitor virtuale opzionale):
Il plugin v1.2 espone anche un Safety Monitor virtuale che NINA puo'
usare come driver di sicurezza. Si attiva in NINA andando in Equipment
-> Safety Monitor, selezionando dalla tendina (sotto categoria N.I.N.A.)
"Adaptive Agent for PHD2 — Guide Safety" e cliccando Connect. Il driver
segnala unsafe quando la guida resta in STAR_LOST oltre 5 minuti (valore
configurabile nelle impostazioni del plugin). Le reazioni concrete
(pausa sequenza, parking, ecc.) si configurano dentro NINA in
Options -> Safety o nell'Advanced Sequencer. Per uso domestico la
configurazione consigliata e' "Pause on unsafe" + "Resume on safe".
La funzione e' opzionale: chi non la usa non e' impattato.
```

Mantieni il resto del LEGGIMI invariato.

---

## Task 4 — Cartella plugin distribuzione + nuovo ZIP

Path target: `C:\Users\aless\Downloads\PHD2_Assist_PATCHED\PHD2_Assist_PATCHED\`

**Sostituire** la cartella `AdaptiveAgentForPHD2.NinaPlugin\` esistente
(che contiene la DLL v1.1.0.0 della scorsa distribuzione) con il
contenuto aggiornato della cartella installata oggi in NINA:

```
%LOCALAPPDATA%\NINA\Plugins\3.0.0\AdaptiveAgentForPHD2.NinaPlugin\
```

Cioè la DLL v1.2.2.0 + eventuali file accessori che `install-plugin.ps1`
include nel deploy. Stessa filosofia del Task 3 della v1.1.

**Prima di rigenerare lo ZIP, pulisci i log delle mie sessioni di test**
dalla cartella `Pacchetto_Distribuzione/logs/`:

```powershell
Get-ChildItem "C:\Users\aless\Downloads\PHD2_Assist_PATCHED\PHD2_Assist_PATCHED\Pacchetto_Distribuzione\logs" -File | Remove-Item -Confirm:$false
```

Mantieni la cartella `logs/` esistente come directory (eventualmente vuota
nello ZIP); è il pattern della distribuzione v2.2 originale.

**Genera lo ZIP** mantenendo lo stesso naming della release v2.2 (non
bumpiamo il nome del pacchetto perché l'Agente Python è invariato — è
solo il plugin che è aggiornato, e il versionamento del plugin è interno):

```
Adaptive_Agent_PHD2_v2.2.zip
```

Struttura interna identica alla precedente:

```
Adaptive_Agent_PHD2_v2.2.zip/
  Pacchetto_Distribuzione/        ← intatto, con LEGGIMI aggiornato Task 3
  AdaptiveAgentForPHD2.NinaPlugin/  ← cartella plugin aggiornata, DLL v1.2.2.0
```

Sovrascrivi il file ZIP esistente. Riusa la stessa procedura PowerShell
della v1.1 (`[System.IO.Compression.ZipFile]::CreateFromDirectory(...)`
con esclusioni dei file di repo Python irrilevanti — esattamente come
nella sessione precedente).

Verifica finale: dimensione attesa simile alla v1.1 (143 MB ± qualche MB),
1404-1405 entry, top-level esattamente `Pacchetto_Distribuzione/` +
`AdaptiveAgentForPHD2.NinaPlugin/`, DLL plugin dentro la cartella a
versione 1.2.2.0, LEGGIMI dentro `Pacchetto_Distribuzione/` con il nuovo
blocco v1.2.

---

## Riepilogo schematico finale richiesto

Quando hai concluso tutti e quattro i task, rispondi con riepilogo
schematico:

| # | Task | Esito |
|---|------|-------|
| 1 | §29 in NOTE_CLAUDE.md | sì/no, righe aggiunte |
| 2 | Manuale (3 formati) | sì/no, paragrafo aggiunto, PDF rigenerato |
| 3 | LEGGIMI v1.2 block | sì/no |
| 4 | Cartella plugin + ZIP | sì/no, dimensione, path |

Più: comando PowerShell breve per verificare il contenuto dello ZIP, e
conferma esplicita che dentro `Pacchetto_Distribuzione/logs/` non ci sono
file di sessione miei.

Grazie.
