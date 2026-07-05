# PROMPT per Claude Code — Esperimento: motore OUTCOME-FIRST, disattivare il ramo oscillazioni (reversibile)

> **Direzione architetturale (Alessandro, 2026-06-21):** il motore deve reagire al **risultato misurabile** della guida, non **pre-classificare le cause**. Con RMS reale + §44 baseline bidirezionale + Guardian + outcome validation + NINA + confidence, una vera oscillazione patologica **si manifesta comunque come peggioramento dell'RMS/outcome** → non serve un ramo dedicato a classificarla. *"Non mi interessa se la stella oscilla; mi interessa se la guida peggiora."*
>
> **Cosa fa questo prompt:** **DISATTIVA** (kill-switch, NON cancella) il ramo oscillazioni e **NON** introduce il cap MinMove → testiamo la **configurazione semplificata** sul campo. È un **esperimento reversibile**: il codice resta dormiente dietro il flag; si cancella solo dopo che 3-4 sessioni confermano (metodologia: validare prima di rimuovere strutturalmente).
>
> **Nota onesta dai log (da tenere a mente nell'osservazione):** nei dati la OVERCORRECTION del motore (lag-1) ha inciso ~1%; il driver dominante della spirale / del MinMove fuori scala è stato il **SEEING-softening ("DEGRADED_SEEING → ↓aggr") + §32 minmove-recovery**, NON l'oscillazione. → Disattivare il solo ramo oscillazioni **potrebbe non eliminare** la spirale. **Va benissimo: è proprio ciò che l'esperimento deve rivelare.** Per questo il prompt **strumenta** l'attribuzione (sorgente di ogni softening + esito), così la prossima sessione dice con certezza chi è il vero responsabile.
>
> **Metodologia (`METODOLOGIA_VALIDAZIONE_LIVE.md`):** operativo, visibile, reversibile. **Numerazione:** `grep "^## [0-9]" NOTE_CLAUDE.md | tail -1` → prossimo libero. Verifica.
> Contesto: `diagnostic_engine.py`, controller (CASO2 + §32 + SEEING-softening), `VALIDAZIONE_CAMPO_v2.6.md`, P1.

## RESTA OPERATIVO (NON toccare): §44 baseline bidirezionale, Guardian, SEEING-softening, §32 minmove-recovery, outcome validation, NINA §41/§42, confidence/N8 (quando attivo), RMS come metrica primaria, backlash, esposizione.

## FASE 0 — VERIFICA (sola lettura)
1. **Punti del ramo oscillazioni** da gateare: (a) motore `diagnostic_engine.classify` → `oscillation`/stato **OVERCORRECTION** (lag-1) e la sua **proposta di leva** (aggr↓); (b) controller **v2.3 CASO2** *"Oscillazione rilevata (trend=…)"* → riduzione aggressività. Riportare file:riga.
2. **Sorgenti di softening che RESTANO** (per la strumentazione §B): SEEING-softening, §32 minmove-recovery, micro GUARDIAN. Riportare come e dove emettono azioni e con quale `reason`.
3. Infrastruttura outcome (`outcome_window_frames`, `_last_outcome`) per il logging esito.

## §A — Disattivazione del ramo oscillazioni (kill-switch, default DISATTIVO)
1. Nuova chiave `[diagnostic_engine] oscillation_branch_enabled` (**default `false`** = configurazione proposta da Alessandro; `true` = comportamento legacy, reversibile).
2. Con `false`:
   - il motore **non emette alcuna azione leva** in conseguenza di OVERCORRECTION (lag-1): nessuna riduzione di aggressività "perché oscilla". Lo stato può ancora essere **calcolato e loggato come informativo** (non gating), ma `proposal=None` per quel ramo. In pratica un sospetto-oscillazione **senza** peggioramento dell'outcome non produce nulla.
   - il **CASO2 v2.3 "oscillazione=trend"** è disattivato → un trend (deriva) non riduce più l'aggressività spacciandosi per oscillazione.
3. **Il codice resta in sede, dormiente** dietro il flag (reversibile). Nessuna cancellazione ora.
4. SEEING/§32/Guardian/§44 **invariati** (restano gli unici attori del softening).

## §B — Strumentazione per attribuire (leggera, visibile)
Serve a capire, sul campo, CHI guida la spirale ora che l'oscillazione è spenta:
1. Su **ogni azione leva** loggare: **`softening_source`** (`SEEING` / `minmove_recovery_§32` / `guardian_micro` / `other`), il **MinMove efficace in arcsec** (px×pixel_scale), e l'**esito** su `outcome_window_frames` (`improved` / `flat` / `worse` rispetto al pre-azione).
2. (Opzionale, leggero) contatore **"oscillation_would_have_fired"**: quante volte il ramo oscillazione AVREBBE agito (shadow, **nessuna azione**) e se in quei frame l'RMS stava davvero peggiorando → quantifica cosa abbiamo tolto (verifica la tesi "se non peggiora l'outcome, non esiste").
3. **Dashboard:** badge "ramo oscillazioni: DISATTIVO (sperimentale)" + breakdown delle sorgenti di softening dell'ultima sessione. Coerente con la validazione live.

## NON in questo prompt (deferiti): cap MinMove (adattivo o fisso) — si valuta DOPO l'esperimento; discriminatore oscillazione (`PROMPT_DISCRIMINATORE_OSCILLAZIONE_OUTCOME.md`) PARCHEGGIATO (torna solo se l'oscillazione si dimostra rilevante).

## TEST (Code DEVE validare)
1. `oscillation_branch_enabled=false`: nessuna azione leva da OVERCORRECTION/lag-1; nessuna riduzione aggr da CASO2-trend. Verificato su replay/sintetico.
2. SEEING-softening, §32, GUARDIAN, §44 **invariati** (le loro azioni continuano come prima).
3. Strumentazione: ogni azione ha `softening_source` + MinMove-arcsec + esito; (se implementato) il contatore would-have-fired conta senza agire.
4. Reversibile: `oscillation_branch_enabled=true` → comportamento legacy bit-identico. Suite verde.

## CHIUSURA
- **REBUILD** (`build_dist.py`, config con `oscillation_branch_enabled=false` attivo nel pacchetto); verifica config nel pacchetto; niente commit/push.
- **DOC:** `NOTE_CLAUDE.md` (nuova §: esperimento outcome-first, ramo oscillazioni disattivo + strumentazione) + `CONTESTO_PROGETTO.md` + `VALIDAZIONE_CAMPO_v2.6.md`.

## CHECKLIST
- [ ] FASE 0: riportati i punti oscillazione (motore + CASO2) e le sorgenti di softening che restano.
- [ ] §A: `oscillation_branch_enabled` (default false); OVERCORRECTION/lag-1 → nessuna azione (solo informativo); CASO2-trend disattivato; codice dormiente reversibile.
- [ ] §B: logging `softening_source` + MinMove-arcsec + esito su ogni azione; (opz.) contatore would-have-fired; badge dashboard.
- [ ] §44/Guardian/SEEING/§32/outcome/NINA invariati; nessun cap MinMove; discriminatore non implementato.
- [ ] Test 1-4; reversibile; rebuild; nessuna regressione; niente commit.

> **Cosa osservare sul campo (l'esperimento):** dopo una sessione con ramo oscillazioni spento → la spirale di sotto-correzione e il MinMove DEC fuori scala **spariscono** (allora l'oscillazione era il driver) **oppure persistono** (allora il driver è il SEEING-softening + §32, e il passo giusto successivo è rendere quel softening **outcome-gated e bidirezionale** — non un cap). In entrambi i casi avremo, per la prima volta, un dato **pulito** non più influenzato dal ramo oscillazioni. È esattamente la verifica che proponi.
