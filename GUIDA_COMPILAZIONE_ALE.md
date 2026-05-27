# 🔭 PHD2 Adaptive Agent v1.1 - Guida Compilazione (Mamete)

Questa guida ti porta da zero al nuovo `.exe` patchato sul tuo PC Windows.
Tempo stimato: **45-60 minuti** la prima volta, di cui solo 5 minuti di lavoro
attivo, il resto sono download e build automatici.

---

## 📋 Cosa contiene questo pacchetto

```
PHD2_Assist_PATCHED/
├── main.py                    ← patchato (graceful shutdown)
├── config.toml                ← default (per amico)
├── config_rc8.toml            ← TUO setup RC8
├── config_tecnosky115.toml    ← TUO setup Tecnosky
├── config_askar71f.toml       ← TUO setup Askar
├── PHD2_Agent.spec            ← aggiornato con scipy + numpy hidden imports
├── Diagnostica_Connessione.spec
├── requirements.txt           ← aggiornato con scipy
├── build_dist.py              ← script automatico (lo userai!)
├── server.py
├── diagnostic.py
├── analyze_logs.py
├── Sblocca_Firewall_8080.bat
├── README.md
├── phd2_agent/
│   ├── controller.py          ← patchato (Baseline Guardian + Saturation Timer + MinMove)
│   ├── star_finder.py         ← patchato (saturation detection)
│   ├── config.py              ← patchato (sezioni [setup] e saturation_timeout_s)
│   ├── analyzer.py
│   ├── client.py
│   ├── logger.py
│   └── __init__.py
├── dashboard/
├── simulator/
└── doc/
```

---

## STEP 1 — Installare Python (10 minuti)

Hai bisogno di Python 3.11 o 3.12. Probabilmente non ce l'hai installato.

1. **Scarica Python**: vai su https://www.python.org/downloads/
2. Scarica **Python 3.12.x** (Windows installer 64-bit)
3. Lancia l'installer
4. ⚠️ **IMPORTANTE**: nella prima schermata SPUNTA la casella
   **"Add python.exe to PATH"** (in basso). Se dimentichi questo passo,
   tutti i comandi successivi falliranno
5. Clicca "Install Now"
6. Aspetta che finisca, chiudi
7. **Verifica**: apri PowerShell (tasto Windows → digita "powershell"
   → Invio) e digita:
   ```powershell
   python --version
   ```
   Devi vedere `Python 3.12.x`. Se vedi un errore tipo "comando non trovato",
   l'installer non ha aggiunto Python al PATH: rilancialo, scegli
   "Modify", e spunta "Add Python to environment variables".

---

## STEP 2 — Estrarre il pacchetto e aprire la cartella (2 minuti)

1. Hai ricevuto il file `PHD2_Assist_PATCHED.zip`. Estrailo dove preferisci
   (ad es. nei tuoi Documenti). Usa **tasto destro → Estrai tutto**, NON
   dentro qualche cartella OneDrive che a volte fa casino con i file
2. Otterrai una cartella `PHD2_Assist_PATCHED/`
3. Apri PowerShell come segue:
   - Premi `Windows + E` per aprire Esplora File
   - Naviga dentro `PHD2_Assist_PATCHED/`
   - Clicca con tasto destro **DENTRO** la cartella (su uno spazio vuoto)
     tenendo premuto **Shift**
   - Scegli **"Apri finestra PowerShell qui"** o **"Apri terminale qui"**
   
   In alternativa più moderna: nella barra degli indirizzi di Esplora File,
   digita `powershell` e premi Invio.
4. Verifica di essere nella cartella giusta con:
   ```powershell
   ls
   ```
   Devi vedere `main.py`, `config.toml`, ecc.

---

## STEP 3 — Installare le dipendenze Python (5-10 minuti)

Sempre dalla PowerShell aperta dentro la cartella, digita questi comandi
**uno alla volta** (Invio dopo ognuno):

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller
```

Cosa fanno:
- Il primo aggiorna pip (gestore di pacchetti Python)
- Il secondo installa fastapi, uvicorn, numpy, scipy (le dipendenze del progetto)
- Il terzo installa PyInstaller (il compilatore da .py a .exe)

**Possibili problemi e soluzioni:**

> "pip non riconosciuto come comando interno..."
> 
> → Python non è nel PATH. Disinstalla Python e reinstalla SPUNTANDO
>   "Add to PATH". Oppure usa `py -m pip` invece di `python -m pip`.

> "ERROR: Could not find a version that satisfies..."
> 
> → Hai installato Python 3.10 o vecchio. Devi avere Python 3.11+.
>   Disinstalla e prendi 3.12.

> Tempo: scipy in particolare è grosso (~50 MB), ci mette qualche minuto.

---

## STEP 4 — Test rapido prima di compilare (2 minuti)

Prima di costruire l'`.exe`, verifica che il codice funzioni senza
ricompilare. Lancia:

```powershell
python main.py --simulator --dry-run
```

Cosa succede:
- Parte un simulatore PHD2 finto
- L'agente si collega, inizia a "guidare"
- Vedrai log scorrere
- La dashboard si apre su http://localhost:8080 (apri il browser)

**Se vedi log che scorrono e la dashboard si apre → tutto OK.**
Premi `Ctrl+C` per fermarlo, e verifica nei log finali queste righe:
- `Baseline salvata in baseline.json (setup=default)`
- `Shutdown controller - restore baseline...`
- `Baseline file rimosso (shutdown pulito)`

Se vedi queste tre righe, **il Baseline Guardian funziona**. 🎯

**Se vedi errori**, copiali in chat e te li risolvo. Errori tipici:
- `ModuleNotFoundError: No module named 'scipy'` → ripeti `pip install -r requirements.txt`
- `Address already in use: 8080` → un'altra app usa la porta 8080. Modifica
  in `config.toml` la riga `port = 8080` mettendo `port = 8081`

---

## STEP 5 — Compilare i nuovi `.exe` (5-10 minuti, automatici)

Il tuo amico ha già scritto uno script di build che fa tutto da solo.
Lancia:

```powershell
python build_dist.py
```

Cosa fa, in ordine:
1. Pulisce le vecchie build
2. Compila `PHD2_Agent.exe` (con tutte le librerie incluse, ~150-200 MB)
3. Compila `Diagnostica_Connessione.exe`
4. Crea la cartella `Pacchetto_Distribuzione/` con tutto pronto
5. Zippa anche tutto in `PHD2_Agent_Distribuzione.zip`

Il processo richiede **5-10 minuti**. Vedrai molto output, è normale.
Il messaggio finale è:
```
✅ Completato! Il file 'PHD2_Agent_Distribuzione.zip' è pronto...
```

**Se la build fallisce con errori "module not found" durante PyInstaller**:
spesso è scipy che non viene incluso. Soluzione di backup, lancia direttamente:

```powershell
pyinstaller --noconfirm PHD2_Agent.spec
pyinstaller --noconfirm Diagnostica_Connessione.spec
```

Lo `.spec` aggiornato include esplicitamente `scipy` nei hidden imports,
quindi dovrebbe funzionare.

---

## STEP 6 — Trovare e provare il nuovo `.exe`

Dopo la build, dentro la cartella del progetto trovi:
```
Pacchetto_Distribuzione/
├── PHD2_Agent.exe                  ← il tuo nuovo eseguibile patchato
├── Diagnostica_Connessione.exe
├── config.toml
├── _internal/                      ← dipendenze (non toccare)
├── dashboard/
├── phd2_log/
└── LEGGIMI_PER_AVVIARE.txt
```

**Aggiungi i tuoi config personalizzati** (importante!):

Copia i 3 file dei tuoi setup dentro la cartella `Pacchetto_Distribuzione/`:
- `config_rc8.toml`
- `config_tecnosky115.toml`
- `config_askar71f.toml`

Ora puoi:
- Cliccare `PHD2_Agent.exe` per usarlo col `config.toml` di default
- O da PowerShell, lanciarlo specificando un setup:
  ```powershell
  cd Pacchetto_Distribuzione
  .\PHD2_Agent.exe --config config_askar71f.toml
  ```

---

## 🎯 Workflow operativo per le prime sessioni

### Sessione 1-2: validazione su Askar 71F (scala generosa, perdona errori)

1. Monta Askar 71F + ASI2600 + OAG con ASI220 Mini
2. Avvia PHD2, attiva Server (Strumenti → Abilita Server)
3. Inizia la guida normalmente in PHD2
4. Lancia: `PHD2_Agent.exe --config config_askar71f.toml`
5. **VERIFICA `dry_run = true` in config_askar71f.toml** → l'agente NON
   modificherà nulla, logga soltanto
6. Apri http://localhost:8080
7. Lascia girare per una sessione completa
8. A fine notte controlla:
   - `logs/session_*.csv` (i dati di guida)
   - `logs/decisions_*.jsonl` (cosa l'agente AVREBBE fatto)
   - `phd2_log/` (importazione automatica log PHD2 nativi)

### Sessione 3-5: ancora dry run su altri setup

Ripeti su Tecnosky 115 e RC8, sempre in DRY_RUN, per accumulare dati.

### Sessione 6+: passaggio a LIVE su Askar 71F

Quando ti senti sicuro:
1. Modifica `config_askar71f.toml`: cambia `dry_run = true` → `dry_run = false`
2. **TEMPORANEAMENTE rendi i passi ultra-conservativi**: in `[limits.ra]` e
   `[limits.dec]` metti `aggr_step_down = 2` e `aggr_step_up = 1` (era 5 e 3)
3. Lancia
4. Monitora attentamente: la dashboard mostrerà `[LIVE]` invece di `[TEST]`
   nelle decisioni
5. Dopo 3-5 sessioni di validazione, riporta i passi ai valori normali

### Solo dopo: passaggio a LIVE su RC8 (lunga focale = meno tollerante)

Quando l'agente si è dimostrato affidabile su Askar, replica il processo
su Tecnosky e poi RC8. **Non saltare i passaggi**: il RC8 a 1624mm punisce
ogni errore di guida, è il setup peggiore per debug iniziale.

---

## 🔒 Test specifici da fare (uno volta, per validare le patch)

### Test Baseline Guardian (kill brutale)

Serve a verificare che dopo un crash, al riavvio i parametri vengano ripristinati.

1. Lancia in LIVE con un setup di test
2. Aspetta che faccia almeno 1-2 modifiche di parametri
3. Apri Task Manager (Ctrl+Shift+Esc), trova `PHD2_Agent.exe`,
   tasto destro → **Termina processo** (kill brutale, non chiusura pulita)
4. **NON chiudere PHD2** — lascialo aperto coi parametri "sporchi"
5. Riavvia `PHD2_Agent.exe`
6. Nel log iniziale dovresti vedere:
   ```
   Trovata baseline.json orfana - sessione precedente non chiusa correttamente
   Ripristino baseline (origine=orphan_recovery, eta=...
   Baseline ripristinata con successo
   ```

Se vedi questo, il Baseline Guardian funziona perfettamente.

### Test Saturation Timer (in dry run, accelerato)

1. Per validazione rapida, modifica temporaneamente `saturation_timeout_s = 30`
   (invece di 300) nel config che usi
2. Avvia in DRY_RUN
3. Dalla dashboard, attiva manualmente l'AI Star Finder e forza l'attivazione
   in un momento in cui hai stelle un po' fuori fuoco (palloni)
4. Aspetta 30 secondi
5. Nel log dovresti vedere:
   ```
   AI Star Finder ha selezionato stella satura (peak=XXXXX ADU)
   ...
   Stella satura tracciata da 30s ... forzo re-scan find_star standard
   ```

Una volta validato, **rimetti `saturation_timeout_s = 300`** per uso normale.

---

## 📊 Come tarare i config dopo le prime sessioni

Dopo 2-3 sessioni reali su un setup, hai dati per ricalibrare le soglie.

Apri il file `logs/session_YYYYMMDD_HHMMSS.summary.json` con Notepad. Trovi:
```json
{
  "total_frames": 1234,
  "peak_rms_total_arcsec": 1.85,
  "mean_rms_total_arcsec": 0.62,
  ...
}
```

Regola pratica per il `config_*.toml` del setup:
- `rms_low` = 0.7 × `mean_rms_total_arcsec` (soglia "ottimo")
- `rms_high` = 1.5 × `mean_rms_total_arcsec` (soglia "degraded")

Esempio: se la tua media è 0.62", metti `rms_low = 0.43` e `rms_high = 0.93`.

I valori di partenza nei config che ho preparato sono volutamente
**conservativi**: l'agente reagirà solo a degrado vero, non a piccole
oscillazioni di seeing. Va bene così per le prime sessioni.

---

## 🚨 Quando NON usare l'agente in LIVE

- Sessioni rare/preziose (target che non rivedi per mesi). Su quelle,
  meglio DRY_RUN o lasciar perdere l'agente
- Setup mai testato prima in DRY_RUN
- Dopo aver cambiato hardware (focheggiatore, OAG, prisma, camera guida)
- Con PPEC ATTIVO la prima volta — l'agente non interferisce direttamente,
  ma vale la pena fare 1-2 sessioni DRY_RUN per essere sicuri
- Sessioni con cambio frequente di filtri narrowband 3nm su lunga focale
  finché non hai validato che la saturation detection funziona bene sul tuo
  setup specifico

---

## 📞 Risoluzione problemi comuni

| Problema | Soluzione |
|----------|-----------|
| Dashboard non si apre su localhost:8080 | Esegui `Sblocca_Firewall_8080.bat` come amministratore |
| `.exe` parte e si chiude subito | Lancialo da PowerShell, vedrai l'errore. Manda log |
| "Connessione PHD2 fallita" | Verifica Server attivo in PHD2 (Strumenti → Abilita Server) |
| Build PyInstaller fallisce | Vedi step 5, prova lancio diretto con `pyinstaller PHD2_Agent.spec` |
| Antivirus blocca il `.exe` | Comune con PyInstaller. Aggiungi eccezione o disattiva temporaneamente |

---

## ✅ Checklist finale prima di considerare il lavoro chiuso

- [ ] Python 3.12 installato e nel PATH
- [ ] Dipendenze installate senza errori (`pip install -r requirements.txt`)
- [ ] Test simulatore funziona (`python main.py --simulator --dry-run`)
- [ ] Build completata, `Pacchetto_Distribuzione/` creato
- [ ] I 3 config personalizzati copiati in `Pacchetto_Distribuzione/`
- [ ] Test del Baseline Guardian fatto (kill brutale + restart)
- [ ] Sessione DRY_RUN reale fatta su Askar 71F (setup più tollerante)
- [ ] Log della sessione DRY_RUN analizzati: numero modifiche ragionevole,
      nessun crash

Se hai TUTTI i tick, sei pronto per la prima sessione LIVE.

---

## Versione

PHD2 Adaptive Guiding Agent v1.1.0 — Patched per Mamete (2026-04-28)

**Patch applicate vs versione originale del tuo amico:**
1. Bug fix: import os mancante (crash garantito su AI Finder LIVE)
2. MinMove dinamico effettivamente applicato
3. Baseline Guardian completo (save/restore/orphan recovery/shutdown)
4. Saturation Detection + Timer 300s con CSV log persistente
5. Mitigazione bias centroide su stelle sature
6. Oscillazione DEC ora gestita (era hardcoded solo RA)
7. Espressione ternaria ambigua riscritta
8. config.py aggiornato con [setup] e saturation_timeout_s
9. requirements.txt aggiornato con scipy
10. PHD2_Agent.spec aggiornato con hidden imports per scipy
11. 3 config separati per i tuoi setup (RC8, Tecnosky, Askar)

**Validazione fatta da me prima della consegna:**
- Sintassi Python valida (parser AST)
- Import e cross-reference tra moduli verificati
- 5 test funzionali su `find_best_star()` con FITS sintetici (tutti OK)
- Test integrazione completi: init/baseline/orphan recovery/shutdown/saturation timer
- Caricamento di tutti e 4 i config TOML verificato
