# PROMPT per Claude Code — Push del plugin NINA sul repo GitHub dedicato (repo già pronto)

> **AUTORIZZATO a operazioni git** nella cartella del sorgente plugin NINA. Solo git: NON modificare codice né `.gitignore`.
> **Situazione (già verificata da Cowork):** la cartella recuperata `C:\Users\aless\OneDrive\Documents\ADAPTIVE AGENT PHD2\AdaptiveAgentForPHD2.NinaPlugin` è **già un repo git pulito**: 1 commit `fd2bb3c "chore: initial commit (plugin v1.2.3.0 baseline)"`, working tree pulito, branch `master`, `.gitignore` C# corretto (bin/obj/.vs/packages/.claude esclusi), nessun artefatto di build tracciato, 22 file. **Manca solo il remote + il push.**
> Repo GitHub vuoto pronto: `https://github.com/Mamete91/AdaptiveAgentPHD2-NinaPlugin.git` (privato).

## 0. PRE-FLIGHT (sola lettura — confermare prima di toccare)
```
cd "C:\Users\aless\OneDrive\Documents\ADAPTIVE AGENT PHD2\AdaptiveAgentForPHD2.NinaPlugin"
git status --short            # atteso: VUOTO (working tree pulito)
git log --oneline -3          # atteso: fd2bb3c initial commit (plugin v1.2.3.0 baseline)
git remote -v                 # atteso: VUOTO (nessun remote)
git ls-files | grep -E "/bin/|/obj/|\.vs/" | wc -l   # atteso: 0
```
Se compaiono bin/obj tracciati → fermati e segnala. (Un eventuale file `PROMPT_*.md` non tracciato in cartella è innocuo: NON committarlo, non entra nel push.)

## 1. PASSI
1. **Aggiungi il remote:**
   ```
   git remote add origin https://github.com/Mamete91/AdaptiveAgentPHD2-NinaPlugin.git
   ```
   (Se esiste già un origin: `git remote set-url origin https://github.com/Mamete91/AdaptiveAgentPHD2-NinaPlugin.git`.)
2. **Push del branch esistente `master`** (lo si mantiene per coerenza con il repo AdaptiveAgentPHD2, anch'esso `master`; il repo remoto è vuoto, quindi `master` diventerà il default):
   ```
   git push -u origin master
   ```
   Se git chiede credenziali HTTPS, sono quelle salvate sulla macchina di Alessandro (come per l'altro repo). Non serve alcun nuovo commit né configurazione author (si pusha il commit esistente).

## 2. VERIFICA FINALE
```
git status                    # "Your branch is up to date with 'origin/master'"
git log --oneline -1 --decorate   # HEAD -> master, origin/master sullo stesso commit
```
Confermare ad Alessandro: esito del push (`* [new branch] master -> master`), che `origin/master == HEAD`, e che il repo GitHub ora contiene i 22 file sorgente (README/LICENSE/.gitignore + src/ + scripts/).

> **Nota:** se in futuro preferisci il branch `main` (default GitHub), opzionale: `git branch -M main && git push -u origin main` (e poi imposta `main` come default branch su GitHub). Per ora `master` va bene ed è coerente con l'altro repo. La `.dll` compilata resta fuori (artefatto); l'Agente continua a vendorizzarla.
