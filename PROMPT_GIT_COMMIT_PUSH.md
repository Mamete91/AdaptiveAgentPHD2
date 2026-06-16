# PROMPT per Claude Code — Commit + Push del traguardo validato (stage PULITO)

> **AUTORIZZATO a eseguire operazioni git** (stage, commit, push) sul repo locale `AdaptiveAgentPHD2` (branch `master`, remoto `origin` = github.com/Mamete91/AdaptiveAgentPHD2.git). Solo git: NON modificare codice.
> **Attenzione (verificato):** l'albero è sporco. `.venv/` (239 MB) **NON è nel .gitignore** → un `git add -A` lo committerebbe. `phd2-master/` (sorgente PHD2 vendorizzato, 617 MB) è **già tracciato** e ha ~centinaia di file "modificati" che sono **rumore di fine-riga** (CRLF/LF), da NON includere. I `*.zip` sono già ignorati.

## 0. PRE-FLIGHT
1. `git status` e `git remote -v`: confermare branch `master`, remoto `origin`, e che HEAD locale è allineato/avanti su `origin/master`.
2. Confermare che `.venv` NON è tracciato (`git ls-files | grep -c '^\.venv/'` = 0) e che `phd2-master/` È tracciato (le sue modifiche sono rumore fine-riga).

## 1. PASSI (in quest'ordine)
1. **Ignora `.venv`:** aggiungere `.venv/` al `.gitignore` (se non già presente). Verificare: `git check-ignore .venv` deve restituire `.venv`.
2. **Stage di tutto il resto, ESCLUDENDO il rumore:**
   - `git add -A` (ora `.venv/` è ignorato e non entra)
   - **Togliere dallo stage il vendor di PHD2** (solo rumore fine-riga): `git restore --staged phd2-master/` (oppure `git reset HEAD phd2-master/`).
   - Verificare che `.venv/` NON sia in stage (`git diff --cached --name-only | grep -c '^\.venv/'` deve essere 0).
3. **Rivedere lo staged prima di committare:** `git diff --cached --name-only | sort` → devono comparire SOLO file dell'Agente: `phd2_agent/`, `config.toml`, `main.py`, `server.py`, `dashboard/`, `tests/`, `simulator/`, `doc/`, gli script `*.py`, i `*.bat`/`*.spec`, i `.md` (NOTE_CLAUDE, CONTESTO, PROMPT_*, ACCERTAMENTO_*, DESIGN_*, README…), `.gitignore`. **NON** devono comparire `phd2-master/`, `.venv/`, `*.zip`, `build/`, `dist/`, `Pacchetto_Distribuzione/`.
4. **Commit** con messaggio:
   ```
   feat: Agent v2.5 §32→§36 — RECOVERY MinMove + baseline-sempre + cadenza/logging + Path B re-star + fix unita px→arcsec

   - §32 RECOVERY: risalita MinMove dalla banda morta (ancora baseline), anti-windup
   - §33 baseline sempre-forma (fallback best-fraction su tutti i frame)
   - §34 cadenza: baseline per-frame + logging non-fuorviante (INSUFFICIENT 81%->21%, baseline ~5 min)
   - §35 Path B: riselezione stella non-satura all'aumento esposizione (anti-flapping)
   - §36 FIX UNITA: RMS px->arcsec all'ingest (RC8 ~2->~0.9"); soglie gia arcsec ora corrette
   - Tutte le feature default-ON nel config.toml; schema_version log 2->3
   - Validato sul campo: RC8/CEM70G 2026-06-16, mediana 0.83" arcsec stabile 3h
   ```
5. **Push:** `git push origin master`. Se git chiede credenziali (HTTPS/token), è atteso: procedere con quelle salvate sulla macchina di Alessandro.

## 2. VERIFICA FINALE
- `git log --oneline -3` mostra il nuovo commit in cima.
- `git status` pulito salvo il rumore fine-riga di `phd2-master/` (atteso, lasciato fuori) e `.venv/` (ora ignorato).
- Confermare ad Alessandro: hash del commit, n° file inclusi, esito del push (es. `origin/master` aggiornato).

> **Nota:** se in futuro dà fastidio il rumore fine-riga di `phd2-master/`, valutare un `.gitattributes` (`phd2-master/** -text` o `text=auto`). Fuori scope ora: questo commit fotografa il traguardo §36 validato come restore point su GitHub.
