# PROMPT per Claude Code — Backup del sorgente plugin NINA in un repo GitHub DEDICATO

> **AUTORIZZATO a operazioni git** sul SORGENTE RECUPERATO del plugin NINA (C#/.NET), in un **repo nuovo e separato** (NON dentro AdaptiveAgentPHD2). Solo git + creazione `.gitignore`: NON modificare il codice C#.
> **Obiettivo:** mettere in salvo su GitHub il sorgente appena recuperato (era sul PC in riparazione → massima priorità backup off-machine).

## PREREQUISITI (Alessandro, PRIMA di lanciare)
- [ ] **A** — Sorgente recuperato in una cartella nota. Indicare a Code il percorso: `____________________`
- [ ] **B** — Creato un repo GitHub **vuoto** (senza README/license/.gitignore, per evitare conflitti al primo push). Incollare l'URL: `____________________` (es. `https://github.com/Mamete91/AdaptiveAgentPHD2-NinaPlugin.git`)

## 0. PRE-FLIGHT (sola lettura)
1. Elencare la cartella del sorgente: individuare il `.sln` e/o i `.csproj`, e **confermare che è il SORGENTE COMPLETO** (file `.cs`, `.csproj`, eventuale `manifest`/`dataobject` NINA) e non solo la `.dll` compilata.
2. Verificare se la cartella è **già** un repo git (`.git` presente). Se sì → si riusa; se no → `git init`.
3. Misurare la dimensione e individuare le cartelle di **artefatti di build** da NON committare: `bin/`, `obj/`, `.vs/`, `packages/`, file `*.user`, `*.suo`. Riportare cosa c'è.

## 1. .gitignore C#/.NET (crearlo nella radice del sorgente)
Contenuto minimo (standard Visual Studio / .NET):
```
## Build results
[Bb]in/
[Oo]bj/
## Visual Studio
.vs/
*.user
*.suo
*.userosscache
*.sln.docstates
## Rider / VSCode
.idea/
## NuGet
packages/
*.nupkg
## OS
Thumbs.db
.DS_Store
```
(Se serve, integrare col gitignore ufficiale `VisualStudio.gitignore`.) La `.dll` compilata è un **artefatto**: NON committarla nel repo sorgente (eventuali release come GitHub Releases, fuori scope).

## 2. PASSI
1. `cd` nella cartella del sorgente.
2. `.gitignore` creato (passo 1). Se non già repo: `git init`.
3. **Identità git** (coerente con l'altro repo, solo `--local`): `git config user.name "Mamete91"`, `git config user.email "alessandro1.curci@libero.it"`.
4. **Remote:** `git remote add origin <URL del prereq. B>` (o `git remote set-url origin <URL>` se esiste già).
5. **Stage:** `git add -A` (con `.gitignore` attivo, `bin/obj/.vs/packages` restano fuori).
6. **GATE DI SICUREZZA — rivedere lo staged:** `git diff --cached --name-only | sort` → devono comparire SOLO sorgenti (`*.cs`, `*.csproj`, `*.sln`, manifest, risorse) e il `.gitignore`. **NON** devono comparire `bin/`, `obj/`, `.vs/`, `packages/`, `*.dll`, `*.user`. Se compaiono → correggere il `.gitignore` e ripetere.
7. **Commit:** messaggio es. `chore: import iniziale sorgente plugin NINA AdaptiveAgentForPHD2 (backup recuperato)`. Aggiungere il trailer `Co-Authored-By: Claude <noreply@anthropic.com>`.
8. **Branch + push:** allineare il nome branch al default del repo remoto vuoto (GitHub oggi crea `main`): `git branch -M main` poi `git push -u origin main`. (Se il remoto fosse `master`, usare quello.)

## 3. VERIFICA FINALE
- `git log --oneline -2` mostra il commit iniziale.
- `git status` pulito (artefatti di build ignorati).
- `HEAD` allineato a `origin/<branch>` (push riuscito).
- Confermare ad Alessandro: nome repo, n° file sorgente inclusi, artefatti esclusi, esito push. Segnalare la versione del plugin trovata nel manifest (es. compat NINA) se presente.

> **Nota:** questo è il backup del SORGENTE. Il rapporto con l'Agente resta invariato: l'Agente continua a vendorizzare solo la `.dll` compilata. I due repo hanno cicli di vita indipendenti.
