# PROMPT PER CLAUDE CODE (Antigravity) — BRANDING PROGETTO + IDENTITÀ AUTORE (rilascio pubblico v2.2)
# Da copiare e incollare integralmente nella conversazione con Claude Code.
# Lavorare nella cartella: PHD2_Assist_PATCHED/

> **NOTA OPERATIVA**: questa feature **non aggiunge logica all'Agente** e non
> modifica il comportamento di guida. È un passaggio di branding/identità
> propedeutico al primo rilascio pubblico del software in un gruppo Telegram di
> astrofotografi (~1000 utenti). L'obiettivo è che, ovunque l'utente finale
> incontri il software (banner d'avvio, dashboard web, manuale, file ZIP,
> metadata dell'`.exe` Windows, file `config.toml`, `Avvia.bat`), trovi sempre
> lo stesso nome di progetto, lo stesso autore, la stessa versione e i contatti
> per il feedback. Diventerà la sezione **§26** di `NOTE_CLAUDE.md`.
>
> CHIARIMENTI OPERATIVI fissati con Alessandro PRIMA di scrivere questo prompt
> (NON sono opzioni da rinegoziare, sono input fissi della specifica):
> - **Nome progetto**: `Adaptive Agent for PHD2`
> - **Autore**: `Alessandro Curci`
> - **Versione**: `2.2` (primo rilascio pubblico — segna §25 come ultima feature
>   logica entrata nel software prima del freeze per la release)
> - **Copyright/licenza**: `Copyright © 2026 Alessandro Curci`
> - **Canale di feedback unico**: gruppo Telegram della community.
>   URL: `https://t.me/+eewRNpvElSs5OWY8` (valore definitivo, NON placeholder).
>   **Nessuna email** in nessun file: tutti i feedback transitano dal gruppo
>   Telegram. Se in qualunque parte del codice/dei testi compare un riferimento
>   a un canale email, va rimosso.
>
> SCOPE — cosa NON si tocca: nessuna logica di `controller.py`, `analyzer.py`,
> `client.py`, baseline RMS, esposizione dinamica, escalation gate, refresh
> ciclico, Baseline Guardian. Nessuna modifica al protocollo JSON-RPC. Nessun
> cambio del nome dell'eseguibile (`PHD2_Agent.exe` resta tale per non rompere
> retrocompatibilità con `Avvia.bat`, lo `.spec`, e i path interni). Nessuna
> modifica ai `.py` di test né alla suite. Si modificano SOLO: testi di
> presentazione, banner, metadata, copertine documento, footer dashboard.

---

## 0. PRE-FLIGHT OBBLIGATORIO (leggere PRIMA di scrivere codice)

### File sorgente PHD2 da consultare

**Nessuno.** Questa feature non interagisce con PHD2: è puro branding lato
nostro. Salta il pre-flight su `phd2-master/`.

### File Python da consultare (architettura attuale)

1. **`phd2_agent/__init__.py`** — modulo radice. Verificare se esiste già una
   costante `__version__`. Se sì, considerarla single source of truth e
   convergere lì. Se no, va creato un modulo dedicato (vedi 2A).

2. **`main.py`** — entrypoint. Cercare il blocco di logging iniziale (es.
   `logger.info("Controller inizializzato. ...")` o simile) per individuare
   dove inserire il **banner d'avvio**. Verificare se esiste già una funzione
   che stampa intestazione/header (improbabile, ma controllare con
   `grep -n "banner\|header\|=== " main.py`).

3. **`server.py`** — endpoint FastAPI. Verificare la struttura della risposta
   `/status` (deve avere già `{"controller": ..., "exposure": ..., ...}` dopo
   §21/§22). Vedere se esiste o ha senso un nuovo endpoint `/about` (o un
   blocco `meta` dentro `/status`) con `project_name`, `short_name`, `author`,
   `version`, `copyright`, `license`, `contact_telegram` (NO `contact_email`).

4. **`dashboard/index.html`** — struttura DOM. Trovare l'`<header>` o il
   primo blocco di intestazione. Verificare se c'è già un titolo (es. `<h1>`
   o `<header class="topbar">`). Identificare un punto adatto per:
   - Riga "Adaptive Agent for PHD2 — by Alessandro Curci" subito sotto/dentro
     l'header esistente.
   - Footer fisso a piè pagina con copyright + contatti.

5. **`dashboard/style.css`** — definire stile minimale per `.brand-byline`
   (testo piccolo, colore tenue, mai bold appariscente) e `.brand-footer`
   (riga in basso, sticky o normal flow secondo lo stile esistente).
   Verificare le variabili colore già definite (probabile palette tipo
   `--text-primary`, `--text-muted`, `--bg`) per **non introdurre nuovi
   colori**: usa quelle esistenti.

6. **`dashboard/app.js`** — verificare se c'è un `applyFullStatus()` o equivalente
   che riceve lo `/status`. Se si aggiunge il blocco `meta` allo `/status`,
   leggerlo qui e popolare il footer dal payload (è preferibile alla
   stringa hard-coded nell'HTML, così la versione viene da una sola fonte).

7. **`config.toml`** — l'unico TOML rimasto (dopo §22). Verificare le prime
   righe: oggi c'è verosimilmente un commento header con la tabella dei
   parametri. Da aggiornare con header brandizzato (commento TOML in
   italiano, righe `# ...`).

8. **`Avvia.bat`** — file unico di avvio. Verificare il primo `echo === ... ===`
   per inserire una riga di branding coerente con il banner Python.

9. **`build_dist.py`** — verificare:
   - Se richiama `PHD2_Agent.spec` (sì, da §2 e §11d in `NOTE_CLAUDE.md`).
   - Il nome dello ZIP finale (oggi `PHD2_Agent_Distribuzione.zip`). Da
     rinominare in `Adaptive_Agent_PHD2_v2.2.zip` (nome più descrittivo,
     mantiene `PHD2` per searchability ma adotta il nuovo brand).
   - Se copia `LEGGIMI_PER_AVVIARE.txt` come stub o se lo lascia in pace.

10. **`PHD2_Agent.spec`** — file PyInstaller. Cercare:
    - Sezione `EXE(...)` con parametro `name='PHD2_Agent'` → **NON modificare**
      (renaming dell'exe rompe `.bat`, `.spec` references e Baseline Guardian).
    - Eventuale parametro `version='version_info.txt'` o blocco
      `VSVersionInfo(...)`. **Se non esiste, va creato** un file
      `version_info.txt` (formato PyInstaller `VSVersionInfo`) e referenziato
      nello `.spec` con `version='version_info.txt'`, così l'`.exe` Windows
      espone metadata coerenti nelle proprietà del file (tab "Dettagli").

11. **`doc/Manuale_Utente_Agent.md`** — manuale utente principale (Markdown).
    Verificare la copertina/intro attuale: titolo, eventuale data, eventuale
    autore. Da estendere a copertina branded completa.

12. **`doc/Manuale_Utente_Agent .txt`** — gemello in plain text (nota: il
    file ha uno spazio prima di `.txt` nel nome — è intenzionale, **non
    rinominare**). Allinearne la copertina al .md.

13. **`doc/build_manual_pdf.py`** — script di generazione PDF da .md. Verificare:
    - I parametri `Document(... title=..., author=..., subject=..., creator=...)`
      passati a `reportlab` (o equivalente). Da impostare con i valori branded.
    - Se esiste già la chiamata `doc.build(story)` (nota: in §25 era stato fixato
      un bug latente in cui mancava — riverificare che sia presente e che lo
      script generi effettivamente il PDF).

14. **`Pacchetto_Distribuzione/LEGGIMI_PER_AVVIARE.txt`** — il README minimale
    nella distribuzione. Brandizzare anche questo (titolo + autore + versione
    in cima).

### Conclusioni del pre-flight (già verificate, da confermare)

A. Single source of truth: deve esistere **un solo file Python** che definisce
   `PROJECT_NAME`, `AUTHOR`, `VERSION`, `COPYRIGHT`, `CONTACT_TELEGRAM`
   (NO `CONTACT_EMAIL`). Tutti i banner, gli endpoint, i log header e le
   copertine documento leggono da lì. **Mai stringhe hard-coded duplicate**:
   bumpare la versione in futuro deve toccare un solo file.

B. La dashboard NON deve hard-codare il nome/versione nell'HTML: deve leggerli
   dall'endpoint `/status` (blocco `meta` nuovo) o `/about`. Così, quando in
   futuro si bumpa la versione in Python, basta rebuild senza toccare HTML.

C. Il manuale (md, txt, pdf) e il LEGGIMI hanno copertine **manuali**: lì il
   testo è hard-coded, ma è documentazione statica — accettabile. Lo script
   PDF (`build_manual_pdf.py`) PUÒ leggere le costanti Python e iniettarle nei
   metadata del PDF (consigliato).

D. L'unica identità di contatto è il gruppo Telegram della community
   `https://t.me/+eewRNpvElSs5OWY8` (URL definitivo, hard-coded nel modulo
   `__about__.py`). Nessun canale email viene esposto.

### Decisioni di design (già prese — implementare così)

a. **Modulo unico `phd2_agent/__about__.py`** (convenzione Python "dunder
   about"). Contiene tutte le costanti di branding + una funzione
   `banner_lines() -> list[str]` che restituisce le righe del banner ASCII
   da loggare all'avvio. `phd2_agent/__init__.py` espone almeno
   `__version__`, `__author__`, `__project_name__` importando da
   `__about__`.

b. **Endpoint `/about`** in `server.py` (nuovo) che restituisce il blocco
   meta come JSON. In alternativa: aggiungere il blocco `meta` dentro la
   risposta esistente di `/status`. **Preferire `/about` separato**:
   semantica più chiara, non gonfia `/status` (chiamato ogni ~secondo dalla
   dashboard).

c. **Banner d'avvio in `main.py`**: log INFO multilinea subito DOPO
   l'inizializzazione del logger e PRIMA della connessione PHD2. Esempio:
   ```
   ============================================================
   Adaptive Agent for PHD2 v2.2
   by Alessandro Curci
   Copyright © 2026 Alessandro Curci
   Telegram:
   https://t.me/+eewRNpvElSs5OWY8
   ============================================================
   ```

d. **Versione Windows EXE**: file `version_info.txt` con `VSVersionInfo`
   PyInstaller, referenziato dallo `.spec`. I campi `FileVersion`,
   `ProductVersion`, `CompanyName`, `FileDescription`, `LegalCopyright`,
   `ProductName`, `OriginalFilename` devono leggere i valori da
   `__about__.py` **al momento del build** (script che genera
   `version_info.txt` da template, vedi 2H).

e. **Rinomina dello ZIP**: `PHD2_Agent_Distribuzione.zip` →
   `Adaptive_Agent_PHD2_v2.2.zip`. Aggiornare `build_dist.py` e la procedura
   nel `LEGGIMI` se la menziona. Mantenere il vecchio nome come fallback NON
   è necessario: è un primo rilascio pubblico, non c'è retrocompat utente.

f. **Footer dashboard**: piè pagina con testo statico letto da `/about`:
   `Adaptive Agent for PHD2 v2.2 · by Alessandro Curci · Copyright © 2026
   Alessandro Curci · Community Telegram` — dove "Community Telegram" è un
   link cliccabile (`<a href="https://t.me/+eewRNpvElSs5OWY8" target="_blank"
   rel="noopener noreferrer">`). Stile sobrio, font piccolo, colore
   `--text-muted`. Niente loghi, niente immagini, niente email.

### Nessuna verifica → STOP

Se durante il pre-flight scopri:
- che `phd2_agent/__init__.py` ha già una versione `__version__` valorizzata
  che è incoerente con `2.2`, **fermati e riportamelo** prima di sovrascrivere;
- che `PHD2_Agent.spec` ha già un blocco `version=` che punta a un file
  esistente, **leggi quel file e capisci la struttura** prima di crearne uno
  nuovo (potrebbe bastare un edit);
- che esiste già un endpoint `/about` o `/info` con semantica diversa, **chiedi
  ad Alessandro come integrarci sopra**;
- che da una versione precedente del prompt sono rimaste tracce di un campo
  `__contact_email__` o di stringhe email (`@gmail.com`, `<EMAIL_CONTATTO>`,
  ecc.) in qualunque file: **rimuovile completamente**, non sono parte di
  questa specifica.

---

## OBIETTIVO TECNICO

Introdurre nel software un livello unico di branding/identità (modulo
`phd2_agent/__about__.py`) che alimenta in modo consistente: banner di avvio
console, log header, endpoint `/about` per la dashboard, footer dashboard,
metadata Windows dell'`.exe` PyInstaller, copertina e metadata del manuale
PDF, header di `config.toml`, `Avvia.bat`, `LEGGIMI_PER_AVVIARE.txt`, nome del
file ZIP di distribuzione. Tutti questi punti convergono su un singolo set di
costanti, così che bumpare la versione richieda l'edit di un solo file.

---

## REGOLE INDEROGABILI

- **NON toccare** la backlash compensation di PHD2 (regola assoluta).
- **NON modificare** nessuna logica funzionale dell'Agente: `controller.py`,
  `analyzer.py`, `client.py`, baseline RMS, esposizione dinamica, escalation
  gate, refresh ciclico (§25), Baseline Guardian, RMS implosion detector
  restano **identici**.
- **NON rinominare** l'eseguibile (`PHD2_Agent.exe` resta `PHD2_Agent.exe`):
  cambiare nome romperebbe `Avvia.bat`, lo `.spec`, il path Baseline Guardian e
  l'usabilità per chi ha già una scorciatoia/path. Il branding è
  esterno-al-binario (banner, metadata, dashboard, manuale, ZIP).
- **NON introdurre** nuove librerie esterne. Il modulo `__about__.py` è solo
  costanti e funzioni pure. PyInstaller `VSVersionInfo` è built-in.
- **NON modificare** la suite di test (`tests/`). I test esistenti devono
  continuare a passare invariati. Si aggiungono **solo** nuovi test mirati
  per le costanti di `__about__` (vedi sez. TEST).
- **NON inserire emoji** in nessuno dei file branded (banner, manuale,
  dashboard, copertine). Alessandro non li usa nel codice.
- **NON cambiare** `dry_run`, `enabled` o qualunque parametro di `config.toml`
  che non sia il commento header.
- **NON introdurre** campi email in nessun file: l'unico canale di contatto è
  il gruppo Telegram `https://t.me/+eewRNpvElSs5OWY8` (valore definitivo
  hard-coded nel modulo `__about__.py`, non ci sono placeholder da sostituire).

### MODALITÀ OPERATIVA

Questa è una feature di branding/refactor cosmetico: **non altera il
comportamento di guida né interagisce con PHD2**. Mantieni i valori di
`dry_run` e di tutti i flag `enabled` invariati rispetto a prima del refactor.
La distinzione DRY_RUN / LIVE qui non si applica. La validazione è puramente
visiva (banner, dashboard, PDF, proprietà Windows del file `.exe`).

---

## SPECIFICA FUNZIONALE

### 2A. Nuovo modulo `phd2_agent/__about__.py` (single source of truth)

Crea il file con questo contenuto esatto:

```python
"""
Identità del progetto Adaptive Agent for PHD2.

Modulo unico di branding: tutte le costanti di identità (nome, autore,
versione, copyright, canale di contatto) vivono qui. Banner d'avvio,
endpoint `/about`, footer dashboard, metadata `.exe`, copertina manuale e
header del config leggono tutti da queste costanti.

Aggiornare la versione qui significa aggiornarla ovunque. Non duplicare
stringhe hard-coded altrove nel codebase.
"""

from __future__ import annotations

# --- Identità progetto ------------------------------------------------------

__project_name__: str = "Adaptive Agent for PHD2"
__short_name__:   str = "Adaptive Agent"
__author__:       str = "Alessandro Curci"
__version__:      str = "2.2"
__version_tuple__: tuple[int, int, int, int] = (2, 2, 0, 0)  # major, minor, patch, build

# --- Licenza / copyright ----------------------------------------------------

__copyright__: str = "Copyright © 2026 Alessandro Curci"
__license__:   str = "All rights reserved"

# --- Canale di contatto unico (community Telegram) --------------------------

__contact_telegram__: str = "https://t.me/+eewRNpvElSs5OWY8"

# Nessuna email: tutti i feedback transitano dal gruppo Telegram sopra.

# --- Helper -----------------------------------------------------------------

def banner_lines() -> list[str]:
    """Righe del banner d'avvio (loggate da main.py prima della connessione)."""
    bar = "=" * 60
    return [
        bar,
        f"{__project_name__} v{__version__}",
        f"by {__author__}",
        __copyright__,
        "Telegram:",
        __contact_telegram__,
        bar,
    ]


def about_payload() -> dict[str, str]:
    """Payload JSON per l'endpoint /about della dashboard."""
    return {
        "project_name":     __project_name__,
        "short_name":       __short_name__,
        "author":           __author__,
        "version":          __version__,
        "copyright":        __copyright__,
        "license":          __license__,
        "contact_telegram": __contact_telegram__,
    }
```

Aggiorna `phd2_agent/__init__.py` per ri-esportare le costanti principali:

```python
from .__about__ import (
    __project_name__,
    __short_name__,
    __author__,
    __version__,
    __copyright__,
    __contact_telegram__,
)
```

Se `__init__.py` già ha un `__version__` (verificare in pre-flight), sostituirlo
con l'import dal nuovo modulo: zero duplicazione.

**Importante**: nessun campo `__contact_email__`. Se durante l'implementazione
trovi tracce di email residue in altri file, **rimuovile**.

### 2B. Banner d'avvio in `main.py`

Subito DOPO l'inizializzazione del logger e PRIMA della connessione a PHD2,
aggiungi:

```python
from phd2_agent.__about__ import banner_lines

for _line in banner_lines():
    logger.info(_line)
```

Il banner appare come prime righe del log della sessione e della console.
Quando un utente posta uno screenshot su un forum o telegrammma il log,
quelle righe sono visibili (= marketing involontario permanente).

### 2C. Endpoint `/about` in `server.py`

Aggiungi (in stile coerente con gli altri endpoint esistenti):

```python
from phd2_agent.__about__ import about_payload

@app.get("/about")
async def about() -> dict[str, str]:
    """Identità del progetto: nome, autore, versione, contatti."""
    return about_payload()
```

NON aggiungere il blocco `meta` dentro `/status`: `/status` è chiamato a
~1Hz dalla dashboard, non ha senso ri-trasmettere costanti ad ogni tick.
`/about` è chiamato una volta sola al caricamento della pagina.

### 2D. Dashboard `index.html` + `app.js` + `style.css`

**`dashboard/index.html`** — sotto l'`<header>` esistente, aggiungi una riga
sottotitolo nel chip già presente o subito sotto:

```html
<div class="brand-byline" id="brand-byline">
  Adaptive Agent for PHD2 — by Alessandro Curci
</div>
```

In fondo al `<body>`, prima della chiusura, aggiungi:

```html
<footer class="brand-footer" id="brand-footer">
  <!-- popolato da app.js da /about -->
</footer>
```

**`dashboard/app.js`** — al caricamento, fetcha `/about` una volta sola e
popola byline + footer dal payload. Il link Telegram deve essere cliccabile
(`<a>` con `target="_blank"` e `rel="noopener noreferrer"` per sicurezza).
Usare `textContent` per la byline (no HTML), e costruire l'`<a>` del footer
in modo sicuro:

```javascript
async function loadBrandInfo() {
  try {
    const resp = await fetch("/about");
    if (!resp.ok) return;
    const a = await resp.json();

    const byline = document.getElementById("brand-byline");
    if (byline) byline.textContent = `${a.project_name} v${a.version} — by ${a.author}`;

    const footer = document.getElementById("brand-footer");
    if (footer) {
      // Costruzione sicura del nodo <a> per il link Telegram
      footer.textContent = ""; // reset
      footer.append(
        `${a.project_name} v${a.version} · by ${a.author} · ${a.copyright} · `
      );
      const tgLink = document.createElement("a");
      tgLink.href = a.contact_telegram;
      tgLink.textContent = "Community Telegram";
      tgLink.target = "_blank";
      tgLink.rel = "noopener noreferrer";
      tgLink.className = "brand-contact";
      footer.appendChild(tgLink);
    }
  } catch (e) {
    // silent: branding non critico, dashboard funziona comunque
  }
}
window.addEventListener("DOMContentLoaded", loadBrandInfo);
```

**`dashboard/style.css`** — stili sobri, riusando le variabili colore già
definite:

```css
.brand-byline {
  font-size: 0.85rem;
  color: var(--text-muted, #8a8a8a);
  font-weight: 400;
  margin-top: 2px;
}

.brand-footer {
  margin-top: 24px;
  padding: 12px 16px;
  border-top: 1px solid var(--border, #2a2a2a);
  font-size: 0.78rem;
  color: var(--text-muted, #8a8a8a);
  text-align: center;
  line-height: 1.5;
}

.brand-contact {
  color: var(--accent, #4aa3df);
  text-decoration: none;
}

.brand-contact:hover {
  text-decoration: underline;
}
```

Se i nomi delle variabili colore reali nel CSS sono diversi (es. `--color-text`
invece di `--text-muted`), **adatta** ai nomi effettivamente presenti: non
introdurre variabili nuove.

### 2E. Header `config.toml`

Sostituisci/aggiungi il commento di testa del file con:

```toml
# ============================================================
# Adaptive Agent for PHD2 v2.2
# by Alessandro Curci
# Copyright (c) 2026 Alessandro Curci
# Community Telegram: https://t.me/+eewRNpvElSs5OWY8
# ============================================================
#
# Configurazione unica. La scelta del telescopio avviene selezionando
# il profilo dentro PHD2 (focale -> pixel scale auto-rilevata).
# Vedi NOTE_CLAUDE.md sezione 22 per il refactor a config unico.
#
# Per editare un parametro: trovare la sezione, leggere il commento
# inline, modificare il valore. Le sezioni feature-specific (es.
# [auto_calibration], [exposure_dynamic]) hanno default attivi.
#
```

**NON toccare** alcun valore parametrico: questa è solo l'intestazione di
commento. Nei commenti TOML usa `(c)` al posto di `©` per massima
compatibilità con shell/console legacy (il glifo `©` resta corretto in UTF-8
ma `(c)` è universalmente leggibile anche senza decoding UTF-8 forzato).

### 2F. Header `Avvia.bat`

Il `.bat` ha bisogno di chiusura `chcp 65001 > nul` (UTF-8 console) **solo se**
vuoi mostrare correttamente `©`. Se preferisci massima compatibilità, resta su
ASCII. Esempio (versione ASCII, più robusta):

```batch
@echo off
cd /d "%~dp0"
echo ============================================================
echo  Adaptive Agent for PHD2 v2.2
echo  by Alessandro Curci
echo  Copyright (c) 2026 Alessandro Curci
echo  Community Telegram: https://t.me/+eewRNpvElSs5OWY8
echo ============================================================
echo.
echo Avvio agente. Profilo attivo deciso dentro PHD2.
echo Dashboard: http://localhost:8080
echo.
PHD2_Agent.exe --config config.toml
pause
```

### 2G. Header `LEGGIMI_PER_AVVIARE.txt`

Sostituisci le prime righe con copertina branded analoga al banner Python.
Mantieni il resto del contenuto operativo invariato (istruzioni di lancio,
firewall, ecc.).

### 2H. Versione e metadata Windows dell'`.exe` (PyInstaller `VSVersionInfo`)

Crea `version_info_template.py` (nella root del progetto, accanto a
`build_dist.py`):

```python
"""
Genera version_info.txt da phd2_agent/__about__.py per PyInstaller.

Eseguito automaticamente da build_dist.py prima di richiamare lo .spec.
"""
from phd2_agent.__about__ import (
    __project_name__, __version__, __version_tuple__,
    __author__, __copyright__,
)

VS_TEMPLATE = """\
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({v0}, {v1}, {v2}, {v3}),
    prodvers=({v0}, {v1}, {v2}, {v3}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        u'040904B0',
        [
          StringStruct(u'CompanyName',      u'{author}'),
          StringStruct(u'FileDescription',  u'{project}'),
          StringStruct(u'FileVersion',      u'{ver}'),
          StringStruct(u'InternalName',     u'PHD2_Agent'),
          StringStruct(u'LegalCopyright',   u'{copyright}'),
          StringStruct(u'OriginalFilename', u'PHD2_Agent.exe'),
          StringStruct(u'ProductName',      u'{project}'),
          StringStruct(u'ProductVersion',   u'{ver}'),
        ]
      )
    ]),
    VarFileInfo([VarStruct(u'Translation', [0x0409, 1200])])
  ]
)
"""

def write_version_info(path: str = "version_info.txt") -> None:
    v0, v1, v2, v3 = __version_tuple__
    content = VS_TEMPLATE.format(
        v0=v0, v1=v1, v2=v2, v3=v3,
        author=__author__,
        project=__project_name__,
        ver=__version__,
        copyright=__copyright__,
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


if __name__ == "__main__":
    write_version_info()
    print("version_info.txt generato.")
```

Modifica `PHD2_Agent.spec` aggiungendo nel blocco `EXE(...)`:

```python
EXE(
    ...,
    name='PHD2_Agent',
    version='version_info.txt',  # <-- AGGIUNTO
    ...
)
```

Modifica `build_dist.py` perché chiami `version_info_template.write_version_info()`
**prima** del comando `pyinstaller PHD2_Agent.spec`:

```python
from version_info_template import write_version_info
write_version_info("version_info.txt")
run_cmd(["pyinstaller", "--noconfirm", "PHD2_Agent.spec"])
```

Verifica visiva: a build completata, click destro su
`Pacchetto_Distribuzione/PHD2_Agent.exe` → Proprietà → Dettagli. Devono apparire
`Adaptive Agent for PHD2`, `Alessandro Curci`, `2.2`, copyright.

### 2I. Nome dello ZIP di distribuzione

In `build_dist.py`, dove oggi crea `PHD2_Agent_Distribuzione.zip`, sostituisci
con un nome che legga la versione da `__about__`:

```python
from phd2_agent.__about__ import __short_name__, __version__
zip_name = f"Adaptive_Agent_PHD2_v{__version__}.zip"
```

(Usa underscore al posto degli spazi nel filename per evitare problemi cross-OS.)

### 2J. Copertina + metadata del manuale (md, txt, pdf)

**`doc/Manuale_Utente_Agent.md`** — sostituisci la prima sezione (titolo +
eventuale data) con copertina branded:

```markdown
# Adaptive Agent for PHD2 — Manuale Utente

**Versione 2.2**
**Autore: Alessandro Curci**
Copyright © 2026 Alessandro Curci

Community e supporto:

https://t.me/+eewRNpvElSs5OWY8

---

(resto del manuale invariato)
```

**`doc/Manuale_Utente_Agent .txt`** (nota lo spazio nel nome) — versione testo
piatta della stessa copertina (no markdown, no asterischi):

```text
ADAPTIVE AGENT FOR PHD2 - Manuale Utente

Versione 2.2
Autore: Alessandro Curci
Copyright (c) 2026 Alessandro Curci

Community e supporto:

  https://t.me/+eewRNpvElSs5OWY8

============================================================

(resto del manuale invariato)
```

**`doc/build_manual_pdf.py`** — popola i metadata PDF leggendo da `__about__`:

```python
from phd2_agent.__about__ import (
    __project_name__, __version__, __author__, __copyright__
)

doc = SimpleDocTemplate(
    output_pdf,
    title=f"{__project_name__} - Manuale Utente v{__version__}",
    author=__author__,
    subject=f"Manuale utente per astrofotografi - {__project_name__}",
    creator=f"{__project_name__} v{__version__}",
    keywords="PHD2, autoguida, astrofotografia, adaptive agent",
)
```

Verifica anche che `doc.build(story)` sia presente in fondo allo script
(bug latente già riscontrato in §25 — se ancora manca, ripristinarlo).

I metadata appaiono nelle Proprietà del PDF (Adobe Reader, anteprima web,
ecc.) e nei risultati di ricerca dei file manager: anche qui, tracciabilità
permanente del nome autore.

---

## TEST ATTESI

### Sanity check simulator (non-regressione)

```bash
python main.py --simulator
```

Verifica:
- Le **prime righe** del log mostrano il banner branded (6 righe con barre `=`).
- Nessun `ImportError` di `phd2_agent.__about__`.
- L'eventuale `from phd2_agent import __version__` in altri moduli continua a
  risolvere.
- Tutte le decisioni e le feature esistenti continuano a funzionare invariate
  (esposizione dinamica, escalation gate, auto-calibrazione, refresh ciclico).

### Test unitari nuovi (`tests/test_about.py`)

Aggiungi un file di test minimale (5 test). **Nessun test su email** — il
campo `__contact_email__` non esiste in questa specifica.

1. **test_constants_exist** — verifica che `phd2_agent.__about__` esporti tutte
   le costanti attese (`__project_name__`, `__short_name__`, `__author__`,
   `__version__`, `__copyright__`, `__license__`, `__contact_telegram__`) e
   che siano tutte stringhe non vuote. Verifica anche **l'assenza** di
   `__contact_email__` con
   `assert not hasattr(about, "__contact_email__")`: garantisce che future
   regressioni non re-introducano un campo email.

2. **test_version_format** — verifica che `__version__` matchi il pattern
   `r"^\d+\.\d+$"` (oggi `2.2`) e che `__version_tuple__` abbia 4 elementi
   int con i primi due coerenti con la stringa.

3. **test_banner_shape** — `banner_lines()` ritorna una lista di stringhe non
   vuote, contiene il nome progetto, l'autore, la versione, il copyright e
   l'URL Telegram (`https://t.me/+eewRNpvElSs5OWY8`); le righe `==` di
   delimitazione sono uguali in cima e in fondo. **Nessuna riga del banner
   contiene la sottostringa `@` o `mail`** (test esplicito anti-regressione
   email).

4. **test_about_payload_keys** — `about_payload()` ritorna un dict con
   esattamente queste chiavi: `project_name`, `short_name`, `author`,
   `version`, `copyright`, `license`, `contact_telegram`. **La chiave
   `contact_email` NON è presente** (asserzione esplicita
   `assert "contact_email" not in payload`).

5. **test_init_reexports** — `from phd2_agent import __version__, __author__,
   __contact_telegram__` funziona e ritorna gli stessi valori di `__about__`.
   `__contact_telegram__` esposto via `phd2_agent` deve essere l'URL completo
   `https://t.me/+eewRNpvElSs5OWY8`.

### Aggiornamento test esistenti — verificare regressioni

I test esistenti **non vanno toccati**. Devono passare 46/46 (numero attuale
dopo §25) senza modifiche. Eseguire:

```bash
python -m pytest tests/ -v
```

Risultato atteso: tutti i test pre-§26 verdi + 5 nuovi test `test_about.py`.

---

## VALIDAZIONE SUL CAMPO

### Sequenza operativa per Alessandro (validazione visiva)

1. **Console banner**: avviare `Avvia.bat`, verificare che le prime righe del
   log siano il banner brandizzato.

2. **Dashboard**: aprire `http://localhost:8080`, verificare:
   - Sotto l'header, la riga "Adaptive Agent for PHD2 v2.2 — by Alessandro
     Curci".
   - In fondo alla pagina, il footer con copyright + contatti.
   - Aprire DevTools → Network → ricaricare → verificare che `/about` sia
     chiamato una volta sola e ritorni JSON con tutti i campi.

3. **Proprietà Windows EXE**: click destro su
   `Pacchetto_Distribuzione/PHD2_Agent.exe` → Proprietà → tab "Dettagli".
   Verificare: `Nome prodotto`, `Versione prodotto`, `Versione file`, `Società`,
   `Descrizione del file`, `Copyright` tutti popolati correttamente.

4. **PDF metadata**: aprire `doc/Manuale_Utente_Agent.pdf` con un lettore PDF
   → Menu File → Proprietà. Verificare titolo, autore, oggetto, applicazione.

5. **ZIP**: verificare che `build_dist.py` produca
   `Adaptive_Agent_PHD2_v2.2.zip` e non più `PHD2_Agent_Distribuzione.zip`.

### Cosa cercare nei log

In `Pacchetto_Distribuzione/logs/decisions_*.jsonl` e `controller_*.log`:
- Nessuna nuova decisione anomala (la feature è cosmetica, non modifica
  decisioni).
- Il file di log della sessione inizia con le 6 righe del banner.

### Linee guida tuning post-prima-distribuzione

- **Footer dashboard troppo invasivo** (segnalazione utenti): ridurre
  `font-size` a `0.7rem` o `color` ancora più tenue.
- **Banner Python invade i log** in modalità debug verbose: declassare a
  livello `INFO` confermato (non `DEBUG`, non `WARNING`).
- **Metadati `.exe` non visibili**: ricontrollare che `version_info.txt` venga
  generato prima della build (e non dopo). Verificare con dumpbin/explorer.

---

## PROCEDURA REBUILD (obbligatoria post-modifica)

Nota: dall'§22 (2026-05-27) la distribuzione è collassata a un solo
`config.toml` + un solo `Avvia.bat`. `build_dist.py` copia automaticamente il
singolo `.bat`. La copia manuale dei 3 TOML per-setup e dei 6 .bat è stata
eliminata.

1. `python build_dist.py` (genera `version_info.txt` da `__about__.py`, esegue
   PyInstaller, copia automaticamente `Avvia.bat`).
2. Copiare manualmente in `Pacchetto_Distribuzione/` (build_dist.py NON copia
   questi):
   - `config.toml` (con header branded aggiornato)
   - `Sblocca_Firewall_8080.bat`
3. Verificare che `Avvia.bat` sia stato copiato:
   ```powershell
   Get-ChildItem Pacchetto_Distribuzione\Avvia.bat
   ```
4. Aprire `Pacchetto_Distribuzione/LEGGIMI_PER_AVVIARE.txt`, verificare che
   abbia la copertina branded (se `build_dist.py` lo sovrascrive con stub,
   ripristinarlo da `LEGGIMI_PER_AVVIARE.txt` nella root).
5. Click destro su `Pacchetto_Distribuzione/PHD2_Agent.exe` → Proprietà →
   Dettagli → verificare metadata.
6. Rigenerare il manuale PDF:
   ```powershell
   python doc/build_manual_pdf.py
   ```
   Verificare che `doc/Manuale_Utente_Agent.pdf` sia aggiornato (data file +
   metadata interni).
7. Ricreare ZIP con nuovo nome:
   ```powershell
   Remove-Item Adaptive_Agent_PHD2_v2.2.zip -ErrorAction SilentlyContinue
   Remove-Item PHD2_Agent_Distribuzione.zip -ErrorAction SilentlyContinue
   [System.IO.Compression.ZipFile]::CreateFromDirectory(
       (Resolve-Path "Pacchetto_Distribuzione").Path,
       (Join-Path (Get-Location) "Adaptive_Agent_PHD2_v2.2.zip"))
   ```

---

## AGGIORNAMENTO DOCUMENTAZIONE (procedura collaudata)

### `CONTESTO_PROGETTO.md`

Nella sezione `## Stato attuale — aggiornato al ...`:
- Aggiornare la data a `2026-06-XX` (data del completamento).
- Aggiornare il sottotitolo: `(branding identità autore + rilascio pubblico v2.2 §26)`.
- Aggiungere paragrafo **subito prima** di "Cosa NON è stato ancora fatto":

```markdown
### Branding progetto + identità autore (§26) — IMPLEMENTATA (2026-06-XX)
Introdotto il modulo `phd2_agent/__about__.py` come single source of truth per
nome progetto, autore, versione, copyright e canale di contatto (gruppo
Telegram della community, unico canale di feedback — nessuna email). Il banner
d'avvio in console, l'endpoint `/about` della dashboard, il footer della
dashboard (con link Telegram cliccabile), i metadata dell'`.exe` Windows
(VSVersionInfo via PyInstaller), la copertina e i metadata del manuale PDF,
l'header di `config.toml` e di `Avvia.bat`, e il nome del file ZIP di
distribuzione leggono tutti da questo modulo. Copyright semplificato a
`Copyright © 2026 Alessandro Curci`. Bumpare la versione richiede ora l'edit di
un solo file. Nessuna modifica logica all'Agente: tutte le feature §1-§25
invariate. Pacchetto pronto per il primo rilascio pubblico v2.2 nel gruppo
Telegram di astrofotografia. Dettaglio in NOTE_CLAUDE.md §26.
```

In `## Cosa NON è stato ancora fatto`:
- Aggiungere:
  ```
  - Distribuzione pubblica v2.2 nel gruppo Telegram di astrofotografia
    (~1000 utenti): raccolta feedback nel gruppo Telegram della community
    (https://t.me/+eewRNpvElSs5OWY8), triage delle segnalazioni, eventuali
    patch v2.2.x.
  ```

### `NOTE_CLAUDE.md`

Aggiungere in coda nuova sezione `## 26. Branding progetto + identità autore
(rilascio pubblico v2.2) (2026-06-XX)`.

Verificare PRIMA con grep che l'ultima sezione sia effettivamente §25:
```bash
grep "^## [0-9]" NOTE_CLAUDE.md | tail -1
```
Atteso: `## 25. Refresh ciclico baseline (tightest-wins) + rms_high_factor 1.3 (2026-05-30)`.

Contenuto strutturato della §26:

```markdown
---

## 26. Branding progetto + identità autore (rilascio pubblico v2.2) (2026-06-XX)

### Motivazione
Dopo §25, il software è funzionalmente pronto per il primo rilascio pubblico
in un gruppo Telegram italiano di astrofotografia (~1000 utenti). Distribuire
uno ZIP anonimo perderebbe sia la paternità del lavoro sia il valore del
feedback strutturato. Serve un livello di branding consistente che attraversi
ogni touchpoint del software: banner console, dashboard, manuale, metadata
Windows, file ZIP. Single source of truth in un solo modulo Python così che
bumpare la versione in futuro richieda un solo edit.

### Architettura
- Nuovo modulo `phd2_agent/__about__.py`: costanti `__project_name__`,
  `__short_name__`, `__author__`, `__version__`, `__version_tuple__`,
  `__copyright__`, `__license__`, `__contact_telegram__` (NO
  `__contact_email__`: l'unico canale di contatto è il gruppo Telegram della
  community, hard-coded a `https://t.me/+eewRNpvElSs5OWY8`).
  Helper `banner_lines()` e `about_payload()`.
- `phd2_agent/__init__.py` ri-esporta le costanti principali (compatibilità con
  eventuali import esterni).
- `main.py` logga `banner_lines()` come prime righe del log della sessione.
- `server.py` espone endpoint `/about` che ritorna `about_payload()`.
- Dashboard (`index.html`/`app.js`/`style.css`): byline sotto l'header + footer
  a piè pagina popolati da `/about` al caricamento.
- `version_info_template.py` (nuovo): genera `version_info.txt` PyInstaller
  da `__about__`. Richiamato da `build_dist.py` prima di PyInstaller.
- `PHD2_Agent.spec`: aggiunto parametro `version='version_info.txt'` nel
  blocco `EXE(...)`.
- `build_dist.py`: ZIP rinominato in `Adaptive_Agent_PHD2_v<version>.zip`.
- `config.toml`, `Avvia.bat`, `LEGGIMI_PER_AVVIARE.txt`: header branded.
- `doc/Manuale_Utente_Agent.md`, `.txt`: copertina branded.
- `doc/build_manual_pdf.py`: metadata PDF da `__about__`.

### Comportamento atteso
- Nessuna modifica logica all'Agente: tutte le feature §1-§25 inalterate.
- Banner Python presente nei log della sessione.
- Endpoint `/about` ritorna JSON con tutti i campi.
- Dashboard mostra byline + footer.
- Proprietà Windows dell'`.exe` mostrano `Adaptive Agent for PHD2`,
  `Alessandro Curci`, `2.2`, copyright.
- PDF manuale ha metadata branded.
- ZIP finale: `Adaptive_Agent_PHD2_v2.2.zip`.

### File modificati
- NUOVO: `phd2_agent/__about__.py`
- NUOVO: `version_info_template.py` (root)
- NUOVO: `tests/test_about.py` (5 test)
- `phd2_agent/__init__.py`: ri-esporto da `__about__`
- `main.py`: banner d'avvio
- `server.py`: endpoint `/about`
- `dashboard/index.html`: byline + footer
- `dashboard/app.js`: `loadBrandInfo()` su DOMContentLoaded
- `dashboard/style.css`: classi `.brand-byline`, `.brand-footer`, `.brand-contact`
- `PHD2_Agent.spec`: parametro `version`
- `build_dist.py`: chiama `write_version_info()`, ZIP rinominato
- `config.toml`: header commento brandizzato
- `Avvia.bat`: echo di banner
- `LEGGIMI_PER_AVVIARE.txt` (root + Pacchetto_Distribuzione): copertina
- `doc/Manuale_Utente_Agent.md`: copertina
- `doc/Manuale_Utente_Agent .txt`: copertina (allineata)
- `doc/build_manual_pdf.py`: metadata PDF da `__about__`

### Limiti dell'approccio
1. L'`.exe` PyInstaller mostra i metadata Windows solo dopo che
   `version_info_template.py` viene eseguito **prima** della build. Se per
   errore si lancia PyInstaller a mano senza passare da `build_dist.py`, i
   metadata possono restare vuoti.
2. Il footer della dashboard è statico per sessione (caricato a
   DOMContentLoaded). Se in futuro si bumpa la versione mentre la dashboard è
   aperta, l'utente deve ricaricare la pagina per vederla.
3. L'unico canale di feedback è il gruppo Telegram. Utenti che non hanno
   Telegram (caso raro nella nicchia astrofotografica italiana, ma esiste) non
   hanno un canale alternativo. Decisione consapevole per il primo rilascio:
   tutta la community converge in un solo posto, gestione centralizzata.

### Validazione raccomandata
1. Build completa con `python build_dist.py` → ispezione proprietà `.exe`.
2. Avvio `Avvia.bat` → verifica banner console.
3. Apertura dashboard → verifica byline + footer + `/about` JSON.
4. Apertura PDF → verifica metadata.
5. Verifica nome ZIP finale.
```

### `README.md` (se rilevante)

Se esiste `README.md` nella root e contiene una sezione "Autore" / "Versione"
non sincronizzata: aggiornare al nuovo branding. Se non esiste o non ha questi
campi: lasciare invariato.

---

## CHECKLIST FINALE PRIMA DI COMMIT

- [ ] Pre-flight obbligatorio eseguito: letti i file indicati in §0
- [ ] `phd2_agent/__about__.py` creato con tutte le costanti, **senza** campo
      `__contact_email__`
- [ ] `phd2_agent/__init__.py` ri-esporta dal nuovo modulo (senza email)
- [ ] `main.py` logga `banner_lines()` come prime righe della sessione (banner
      mostra URL Telegram, NESSUNA riga email)
- [ ] `server.py` espone endpoint `/about` con payload **senza** chiave
      `contact_email`
- [ ] Dashboard mostra byline + footer popolati da `/about`; footer ha link
      Telegram cliccabile (`<a target="_blank" rel="noopener noreferrer">`)
- [ ] `version_info_template.py` creato in root (copyright = `Copyright © 2026
      Alessandro Curci`)
- [ ] `PHD2_Agent.spec` ha parametro `version='version_info.txt'`
- [ ] `build_dist.py` chiama `write_version_info()` prima di PyInstaller
- [ ] `build_dist.py` rinomina ZIP in `Adaptive_Agent_PHD2_v<version>.zip`
- [ ] `config.toml` ha header brandizzato (commento, nessun valore toccato,
      URL Telegram nel commento, nessuna email)
- [ ] `Avvia.bat` ha echo di banner con URL Telegram, nessuna email
- [ ] `LEGGIMI_PER_AVVIARE.txt` ha copertina branded con URL Telegram,
      nessuna email
- [ ] `doc/Manuale_Utente_Agent.md` ha copertina branded ("Community e supporto:
      https://t.me/+eewRNpvElSs5OWY8" — niente email)
- [ ] `doc/Manuale_Utente_Agent .txt` ha copertina branded (allineata, niente
      email)
- [ ] `doc/build_manual_pdf.py` popola metadata PDF da `__about__`
- [ ] **Grep finale anti-regressione email**: `grep -rni "email\|@gmail\|@outlook\|mailto"`
      sui file modificati restituisce 0 occorrenze relative al branding
- [ ] `tests/test_about.py` con 5 test nuovi: 5/5 passano, inclusi test
      espliciti che `__contact_email__` NON esiste e che il banner non contiene `@`
- [ ] Test esistenti: 46/46 passano senza regressioni
- [ ] `python build_dist.py` completato senza errori
- [ ] Proprietà Windows dell'`.exe` mostrano `Copyright © 2026 Alessandro Curci`
- [ ] PDF manuale rigenerato con metadata branded (copyright nuovo)
- [ ] ZIP finale: nome `Adaptive_Agent_PHD2_v2.2.zip`
- [ ] `CONTESTO_PROGETTO.md`: data aggiornata + paragrafo §26 + voce "non fatto"
- [ ] `NOTE_CLAUDE.md`: sezione §26 aggiunta in coda
- [ ] Nessuna modifica alla logica delle feature §1-§25
- [ ] Nessuna modifica al nome dell'eseguibile `PHD2_Agent.exe`
- [ ] Nessuna modifica alla backlash compensation di PHD2
- [ ] Nessuna emoji aggiunta in nessun file

---

## DOMANDE DA FARMI PRIMA DI PROCEDERE (se servono)

Se durante l'implementazione trovi:
- Un `__version__` esistente in `phd2_agent/__init__.py` con valore diverso da
  `2.2` → **fermati e segnala**, non sovrascrivere senza conferma.
- `PHD2_Agent.spec` ha già `version='qualcosa.txt'` con file esistente →
  **leggi quel file e capisci la struttura** prima di rifarlo da zero.
- Endpoint `/about` o `/info` già presente in `server.py` con semantica
  diversa → **chiedi come integrare**.
- Variabili CSS `--text-muted` / `--accent` / `--border` non esistono → **usa
  i nomi reali** definiti nello stylesheet, non introdurre nuove variabili.
- Tracce di un campo `__contact_email__` o di stringhe email rimaste da
  versioni precedenti del prompt o da una prima passata di implementazione →
  **rimuovile**, non sono parte di questa specifica.

→ **Fermati e chiedi**, non improvvisare.

Se invece tutto è chiaro: procedi step-by-step, mostrami i diff prima di
applicarli ai file (preferisco vedere le modifiche prima del commit), poi
esegui il rebuild + rigenera il PDF + ricrea lo ZIP + aggiorna la
documentazione.

Grazie.
