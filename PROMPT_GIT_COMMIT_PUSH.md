# PROMPT per Claude Code — Commit + Push "motore diagnostico operativo, §37→§39"

> **PRECONDIZIONE:** eseguire SOLO dopo che Alessandro ha validato i log della notte con §37/§38/§39 attivi. Se la validazione non è OK, NON committare.
> **AUTORIZZATO a operazioni git** (stage, commit, push) sul repo `AdaptiveAgentPHD2` (branch `master`, remoto `origin` = github.com/Mamete91/AdaptiveAgentPHD2.git). Solo git: NON modificare codice.
> **Cosa aggiunge questo commit:** §37 (HFD informativo) + §38 (jitter_ref/hfd_ref sempre-forma) + §39 (riferimenti sopravvivono al dither + logging `reset_cause`), sopra al traguardo §36 già committato (`13d2848`). Include anche i nuovi `.md` (PROMPT_*, PUNTO_FOCALE, ecc.).
> **Attenzione (già noto):** `.venv/` è già nel `.gitignore` dal commit precedente; `phd2-master/` (sorgente PHD2 vendorizzato) è tracciato e le sue eventuali modifiche sono **rumore di fine-riga** (CRLF/LF), da NON includere; `*.zip`, `build/`, `dist/`, `Pacchetto_Distribuzione/` sono ignorati.

## 0. PRE-FLIGHT
1. `git status` e `git remote -v`: confermare branch `master`, remoto `origin`, HEAD su/allineato a `origin/master` (ultimo commit atteso `13d2848`).
2. Confermare `.venv` ignorato (`git check-ignore .venv` → `.venv`) e non tracciato (`git ls-files | grep -c '^\.venv/'` = 0).

## 1. PASSI
1. **Stage escludendo il rumore:**
   - `git add -A` (`.venv/` è già ignorato → non entra).
   - Togliere dallo stage il vendor PHD2 se presente come rumore: `git restore --staged phd2-master/`.
   - Verificare: `git diff --cached --name-only | grep -c '^\.venv/'` = 0.
2. **Rivedere lo staged (gate di sicurezza):** `git diff --cached --name-only | sort` → SOLO file dell'Agente: `phd2_agent/` (diagnostic_engine.py, config.py, controller.py, logger.py, …), `config.toml`, `main.py`, `tests/`, gli script `*.py`, i `.md` (NOTE_CLAUDE, CONTESTO, PUNTO_FOCALE, PROMPT_*), `.gitignore`. **NON** devono comparire `phd2-master/`, `.venv/`, `*.zip`, `build/`, `dist/`, `Pacchetto_Distribuzione/`.
3. **Commit** con messaggio:
   ```
   feat: motore diagnostico operativo §37→§39 — HFD informativo + jitter_ref sempre-forma + reset solo a vero cambio regime

   - §37 HFD declassato a informativo: fuori dal gate SEEING (e da OVERCORRECTION/DRIFT); SEEING ora su jitter+RMS, non-oscillante. Kill-switch hfd_gates_seeing=false
   - §38 jitter_ref/hfd_ref sempre-forma (best-fraction su finestra mobile, warmup ~15); refs_ready dipende solo da jitter_ref (hfd_ref scollegato post-§37). Kill-switch refs_always_form=true
   - §39 i riferimenti di calma sopravvivono a dither/settle; reset solo su exposure/target/pixel-scale; logging reset_cause nel CSV; schema_version 3->4. Kill-switch preserve_refs_on_dither=true
   - Tutte default-ON nel config.toml. 175 test verdi
   - Effetto: refs_ready ~12% -> ~98% (sintetico); il motore puo finalmente diagnosticare SEEING (prima 0)
   - Validazione di campo piena (notte con reset_cause loggato) ancora da fare — vedi NOTE_CLAUDE §37-§39
   ```
4. **Push:** `git push origin master`. Eventuali credenziali HTTPS = quelle salvate sulla macchina.

## 2. VERIFICA FINALE
- `git log --oneline -3` mostra il nuovo commit sopra `13d2848`.
- `git status` pulito (salvo il rumore fine-riga di `phd2-master/`, lasciato fuori).
- `HEAD == origin/master`. Confermare ad Alessandro: hash del commit, n° file inclusi, esito del push.

> **Nota:** lo ZIP e `Pacchetto_Distribuzione/` NON entrano nel commit (sono artefatti, giustamente ignorati). Per averli sul PC originale si fa **pull + rebuild** (vedi `PROMPT_GIT_PULL_REBUILD_PC_ORIGINALE.md`), non si versionano i 100 MB.
