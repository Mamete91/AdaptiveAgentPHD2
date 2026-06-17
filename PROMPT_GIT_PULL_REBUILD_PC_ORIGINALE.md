# PROMPT per Claude Code — Allineare il PC originale a GitHub + RIBUILDARE ZIP e Pacchetto_Distribuzione

> **Da eseguire sul PC ORIGINALE (Milano)** DOPO che §37+§38+§39 sono stati pushati su GitHub dal PC attivo.
> **Perché serve il rebuild:** il `git pull` porta SOLO il sorgente. Lo **ZIP** (`*.zip`) e la cartella **`Pacchetto_Distribuzione/`** sono `.gitignore` (artefatti da 100 MB, giustamente NON versionati) → NON arrivano col pull. Per averli aggiornati sul PC originale si **ribuilda da sorgente**. (Potrebbero comparire via OneDrive, ma è inaffidabile: NON fidarsi, ribuildare.)
> **AUTORIZZATO a:** operazioni git (fetch/pull) + ricostruzione venv se serve + `python build_dist.py`. Cautela: il PC originale è fermo a ~un mese fa e sta in OneDrive → possibile working tree disallineato.

## 0. PRE-FLIGHT — fotografare lo stato del PC originale (sola lettura, NON forzare)
```
cd "C:\Users\aless\OneDrive\Documents\ADAPTIVE AGENT PHD2\AdaptiveAgentPHD2"
git remote -v
git fetch origin
git status
git log --oneline -3
git log origin/master --oneline -3
```
Riportare ad Alessandro: a quanti commit è indietro il locale, e se il working tree è **pulito** o ha **modifiche locali**.

## 1. ALLINEARE IL SORGENTE A GitHub (scegliere il caso giusto)
- **Caso A — working tree pulito, solo indietro:** `git pull --ff-only origin master`. Fine.
- **Caso B — modifiche locali presenti (residui pre-riparazione o sync OneDrive):** NON forzare. Tutto il lavoro vero è su GitHub, quindi quasi certamente le modifiche locali sono spazzatura/rumore. **Confermare con Alessandro**, poi allineare in modo pulito:
  ```
  git stash            # mette al sicuro l'eventuale locale (recuperabile)
  git pull --ff-only origin master
  ```
  Solo se Alessandro conferma che non c'è nulla di valore in locale, in alternativa: `git reset --hard origin/master` (distruttivo sui tracked; gli ignorati come ZIP/Pacchetto restano).
- **Verifica:** `git log --oneline -1` deve mostrare il commit §37→§39 (lo stesso di `origin/master`).

## 2. RIBUILDARE ZIP + Pacchetto_Distribuzione
1. **Ambiente Python / PyInstaller** (PyInstaller è build-only, NON in `requirements.txt`):
   - Verificare il venv: `\.venv\Scripts\python.exe -m pip show pyinstaller`.
   - Se il venv manca o è incompleto: ricrearlo → `python -m venv .venv` → `\.venv\Scripts\python.exe -m pip install -r requirements.txt` → `\.venv\Scripts\python.exe -m pip install pyinstaller`.
2. **Build:** dal venv, `python build_dist.py` (mette `Scripts` nel PATH se serve, come fatto sull'altro PC).
3. Attendere il completamento (exit 0).

## 3. VERIFICA FINALE
- Esiste `Adaptive_Agent_PHD2_v2.5.zip` **fresco** (data odierna) e la cartella `Pacchetto_Distribuzione/` rigenerata.
- Il `config.toml` DENTRO il pacchetto contiene le chiavi §37-§39 attive: `hfd_gates_seeing = false`, `refs_always_form = true`, `preserve_refs_on_dither = true`.
- `python -m unittest` (dal venv) → suite verde (atteso 175 test), per confermare che il sorgente allineato gira.
- Confermare ad Alessandro: hash del commit allineato, esito build, nome/dimensione ZIP, presenza del Pacchetto_Distribuzione.

> **Nota two-PC:** d'ora in poi il PC originale è la macchina primaria. Regola: `git pull` prima di lavorare, `git push` dopo; lo ZIP/pacchetto si **ribuilda** localmente, non si tira da git. OneDrive resta solo backup secondario (un solo PC attivo per volta per non corrompere il `.git`).
