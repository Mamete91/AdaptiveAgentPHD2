# PROMPT per Claude Code — FIX motore: recupero SIMMETRICO guidato dall'esito (banda morta bidirezionale)

> **AUTORIZZAZIONE A IMPLEMENTARE.** Alessandro autorizza questo fix, isolato. È una modifica al **control-law** (la catena CASO + §32), quindi: kill-switch, operativa e visibile in diretta, reversibile, ampiezza limitata (metodologia live). **NON** toccare: backlash PHD2, §31 (jitter/guardian/micro), §50 (INIT), §51 (cap MinMove), §44 (baseline), N1/N6/N8. Solo la logica di recupero leve nella **banda morta**.
>
> **Motivazione (evidenza di campo, sessione `session_20260702_215202`).** Prova con simulazione di seeing degradato + recupero + crash camera. Fase degradazione: motore corretto (leve ammorbidite senza derive, aggr al pavimento 35/35). Fase recupero: RMS torna a ~0,75" (poco sopra baseline, niente più SEEING), **ma le leve restano aperte** e l'aggressività **non risale mai in sessione continua** (DEC aggr = 10 azioni GIÙ / 0 SU nell'intera notte). Solo il crash→INIT (§50) ha riportato le leve allo standard, dopo di che il motore ha guidato bene → **conferma: il problema è la logica di RECUPERO in sessione continua, non la scelta dei valori.**
>
> **Causa individuata leggendo il codice (asimmetria del control-law):**
> - `controller.py`, ultimo `elif` (§32 "RECUPERO banda morta", ~L1436-1462): quando RMS è sopra la mediana nella banda morta fa `new_mm = old_mm + minmove_step` → **alza** il MinMove ("verso la morbidezza"). È un **secondo percorso di ammorbidimento**, non un recupero. Le micro-discese di MinMove osservate nel log erano il **cap §51** (`_cap_minmove_up`) che tagliava la richiesta di salita, non un recupero attivo.
> - L'**aggressività risale SOLO nel CASO3** (`rms < rms_low`, guida già ottima). Nella banda morta (rms_low < rms < rms_high) **nessun percorso alza l'aggressività** → resta al pavimento.
> - Risultato: ammorbidimento con trigger forti + espliciti; recupero assente per l'aggressività e nel verso sbagliato per il MinMove → **ratchet unidirezionale verso il morbido**.
>
> **Idea del fix:** trasformare la banda morta da ratchet-unidirezionale-morbido a **recupero BIDIREZIONALE guidato dall'esito**: quando le leve sono più morbide dello standard §50 e la guida è stabile, **provare a irrigidire verso lo standard** (aggr SU / MinMove GIÙ), **misurare l'esito**, tenere se l'RMS migliora o regge, ammorbidire solo se l'esito dimostra che serviva (allora è seeing vero). Chiude anche la metà "softening loop" (l'ammorbidimento §32 diventa gated dall'esito, non incondizionato).

---

## 0. PRE-FLIGHT OBBLIGATORIO (sola lettura, prima di toccare codice)

1. `phd2_agent/controller.py` — catena **CASO 1/2/3** + **§32 RECUPERO** (l'ultimo `elif`, ~L1355-1462). Confermare:
   - CASO3 (guida ottima, `rms < rms_low`): unico posto dove **aggr SALE** (`aggr_step_up`, gated §30 satisfaction) e MinMove SCENDE (`minmove_step`).
   - §32 banda morta (`minmove_recovery_enabled`, `_recovery_consec`, `_recovery_threshold()`): oggi **alza** MinMove (`old_mm + minmove_step`) poi `_cap_minmove_up` (§51). **Solo MinMove, mai aggr.**
   - Stato di recupero già presente: `_update_recovery_state`, `_finalize_recovery_windup`, `_recovery_consec`, `_recovery_anchor_rms`, `_recovery_actions_since_anchor`, `_recovery_blocked` (~L294-301, L1474-1500). **Riusare questa macchina**, non crearne una nuova.
2. `phd2_agent/controller.py` — i valori nominali §50 (INIT standard): dove sono salvati gli aggr/MinMove nominali per asse (RA Hyst 0.70/0.20 native, DEC ResistSwitch 1.00/0.20). **Sono l'àncora del recupero** ("verso lo standard"). Riusare `aggr_native_scale` per il confronto morbido/reattivo.
3. `phd2_agent/controller.py` — `_apply_with_guardian(...)`, `limits.aggr_step_up`, `limits.minmove_step`, `aggr_max/minmove_min`, `cooldown`/`minmove_cooldown`, e la review Guardian per `caso="RECOVERY"` (caso ignoto → CONFIRM; §31 intatto).
4. `phd2_agent/config.py` — blocco `lever_optimization` (dove stanno `minmove_recovery_enabled`, `minmove_recovery_factor`, `target_factor`). Aggiungere lì le nuove chiavi (o un sotto-blocco coerente).
5. `phd2_agent/analyzer.py` — trend RMS disponibile per l'outcome gate (rms in salita/piatto/discesa; già usato altrove). Riusare, non ricalcolare.

**DECISIONE DI DESIGN (confermata da Alessandro): posture della banda morta = RECUPERO-FIRST guidato dall'esito.** Quando le leve sono morbide e la guida è stabile, la banda morta **prova prima a recuperare** (irrigidire) e ammorbidisce (§32 attuale) **solo** se l'esito dimostra che il recupero peggiora l'RMS. (Alternativa scartata: tenere §32 soften-first e aggiungere un recupero separato → mantiene il ratchet.)

## 1. OBIETTIVO TECNICO
Eliminare l'asimmetria allargamento/recupero: rendere la reazione della **banda morta bidirezionale e guidata dall'esito**, estesa **all'aggressività** (oggi senza recupero), con àncora = valori standard §50. L'RMS che resta poco sopra baseline con leve morbide deve innescare un **rientro verso lo standard** (per chiudere il gap), non un ulteriore ammorbidimento — a meno che l'esito non provi il contrario.

## 2. REGOLE INDEROGABILI
- **NON** toccare backlash PHD2; **NON** toccare §31/§44/§50/§51/N1/N6/N8. Il cap §51 resta il tetto: il recupero abbassa il MinMove **verso** lo standard, mai sotto `minmove_min`; l'aggr sale **verso** il nominale §50, mai sopra (il sotto-standard/più-reattivo resta di competenza del CASO3).
- **Ampiezza limitata:** un solo gradino per cooldown per asse; target = valori standard §50 (non oltre). Nessun salto.
- **Anti-flapping:** recupero e ammorbidimento **non** possono scattare nello stesso tick/asse; l'isteresi (`_recovery_blocked`) deve impedire l'oscillazione recupero↔ammorbidimento.
- **Kill-switch** `symmetric_recovery_enabled` (default **true**, nata operativa/live). A `false` → comportamento attuale (§32 solo-MinMove verso il morbido).
- **P1 (convergenza alla prestazione):** il recupero è coerente con P1 — riporta lo *strumento* (leva) allo standard quando l'ammorbidimento non serve più; l'esito è il giudice. Se la guida è **soddisfatta** (rms ≤ target §30) le leve non vengono toccate (né recupero né ammorbidimento): guida buona = lasciare stare.

## 3. SPECIFICA FUNZIONALE

### 3A — Rilevare lo stato "morbido" e la stabilità (banda morta, per asse)
Nel ramo banda morta (ultimo `elif`, dopo CASO1/2/3), quando `_recovery_consec >= consecutive_frames`:
- `is_softened` = (`current_aggr` < nominale_aggr §50) **oppure** (`current_minmove` > nominale_minmove §50), confronto in scala nativa/arcsec coerente.
- `is_stable` = RMS **non in salita** (trend piatto/discesa da analyzer) **e** non-SEEING **e** (advisory) N1 non-CLOUD.

### 3B — RECUPERO bidirezionale guidato dall'esito
- **Se `is_softened and is_stable`** → entra in **RECOVERING**:
  - àncora l'RMS a inizio run (`_recovery_anchor_rms`).
  - un gradino per cooldown verso lo standard: **aggr** `min(nominale_§50, current + aggr_step_up)`; **MinMove** `max(nominale_§50, current − minmove_step)` (mai sotto `minmove_min`). Estendere all'**aggressività** riusando `_apply_with_guardian(..., caso="RECOVERY")`.
  - **Outcome gate** (il cuore): su una finestra `recovery_outcome_window_frames`, confronta rms corrente vs `_recovery_anchor_rms`:
    - migliora o regge (entro `recovery_outcome_tolerance_factor`, es. ≤ anchor×1.05) → **continua** il recupero (prossimo gradino), ri-ancora.
    - peggiora oltre tolleranza → **STOP**: `_recovery_blocked=True`, **tieni** le leve correnti; l'ammorbidimento §32 (3C) è ora legittimo (era seeing vero). Riusare `_finalize_recovery_windup`.
- **Se NON `is_softened`** (leve già allo standard) → nessun recupero possibile; passa a 3C.

### 3C — Ammorbidimento §32 come FALLBACK (non più ratchet)
Il vecchio "alzo MinMove verso la morbidezza" resta, ma **subordinato**: scatta solo se (a) `is_softened` è falso (niente da recuperare) **oppure** (b) l'outcome gate 3B ha bloccato il recupero (peggiora → è seeing). Così sparisce il ratchet unidirezionale e l'ammorbidimento diventa **evidence-based**.

### 3D — Visibilità live (metodologia)
- **Log** per ogni azione di recupero: verso (STIFFEN/SOFTEN), leva, old→new, `anchor_rms`, `rms` corrente, verdetto (KEEP/STOP). Italiano, coerente col logger.
- **/status**: piccolo blocco `recovery` con `state` (RECOVERING/HOLDING/IDLE), leva in movimento, `anchor_rms` vs `rms`, `blocked`. (La card dashboard è un follow-up; il campo `/status` è la visibilità live richiesta ora.)

### 3E — Config (nuove chiavi in `lever_optimization`, mirror stile §51)
- `symmetric_recovery_enabled = true`
- `recovery_stiffen_aggression = true`  (estende il recupero all'aggressività)
- `recovery_outcome_window_frames = 6`  (tarabile per-setup)
- `recovery_outcome_tolerance_factor = 1.05`
- riusa `minmove_recovery_factor`, `aggr_step_up`, `minmove_step`, cooldown. Presenti in tutti e 3 i config `config_askar71f.toml` / `config_tecnosky115.toml` / `config_rc8.toml` con gli stessi default.

## 4. TEST ATTESI (`tests/test_recovery_symmetric.py`)
1. Banda morta + leve morbide + RMS stabile poco sopra baseline → genera azioni di **STIFFEN** (aggr SU e/o MinMove GIÙ) verso lo standard; **non** azioni di ammorbidimento.
2. **Aggressività recupera** (regressione dell'asimmetria): partendo da aggr al pavimento con RMS stabile, l'aggr risale verso il nominale §50 (prima il test falliva: aggr non risaliva mai in banda morta).
3. Recupero che **peggiora** l'RMS oltre `tolerance_factor` → STOP + `_recovery_blocked` + fallback ammorbidimento §32.
4. Aggr non supera mai il nominale §50; MinMove non scende mai sotto `minmove_min`; il cap §51 resta il tetto in salita.
5. Guida **soddisfatta** (rms ≤ target §30) → nessuna azione (né recupero né ammorbidimento).
6. `symmetric_recovery_enabled=false` → comportamento identico all'attuale §32 (solo-MinMove verso il morbido); nessuna regressione ai test esistenti di CASO3/§32/§30.
7. Anti-flapping: nessun tick con recupero **e** ammorbidimento sullo stesso asse.

## 5. VALIDAZIONE SUL CAMPO
Lanciare il `.bat` del setup (es. RC8) LIVE. Riprodurre lo scenario della prova: simulare seeing degradato, poi **terminare la simulazione**. Osservare in dashboard/`/status` e nei log:
- durante la degradazione: ammorbidimento come prima (nessuna regressione);
- **a simulazione finita, con RMS poco sopra baseline: l'aggressività e il MinMove RIENTRANO verso lo standard §50** (blocco `recovery` = RECOVERING → verdetti KEEP), il gap RMS si chiude;
- se irrigidire peggiora l'RMS → STOP visibile (HOLDING) e l'ammorbidimento riprende → è seeing vero, comportamento corretto.
Confronto atteso vs `session_20260702_215202`: l'aggr non deve più restare inchiodata al pavimento dopo il recupero.

## 6. PROCEDURA REBUILD
`python build_dist.py` (rigenera exe + copia i .bat); copiare i 3 config aggiornati nel `Pacchetto_Distribuzione/`; verificare che le nuove chiavi `recovery_*` siano nel pacchetto; rigenerare lo ZIP. Niente commit/push finché non validato sul campo.

## 7. AGGIORNAMENTO DOCUMENTAZIONE
- `NOTE_CLAUDE.md`: **verifica `grep "^## [0-9]" NOTE_CLAUDE.md | tail -1`** (atteso §52) → nuova sezione **§53 "Recupero simmetrico guidato dall'esito: banda morta bidirezionale (aggr + MinMove) — chiude l'asimmetria allargamento/recupero"**. Documentare la causa (§32 = softening ratchet, aggr senza recupero) e il fix (outcome-gated bidirezionale, àncora §50).
- `CONTESTO_PROGETTO.md`: un paragrafo sul recupero simmetrico.
- `VALIDAZIONE_CAMPO_v2.6.md`: registrare la sessione `20260702_215202` come evidenza dell'asimmetria e il fix §53.

## 8. CHECKLIST FINALE
- [ ] §0 pre-flight: catena CASO/§32, macchina `_recovery_*`, valori nominali §50, trend analyzer, `_apply_with_guardian` — verificati.
- [ ] 3A stato morbido + stabilità per asse (scala nativa/arcsec, trend, non-SEEING, N1 advisory).
- [ ] 3B recupero bidirezionale + **aggressività estesa** + outcome gate (KEEP/STOP, riusa anchor/anti-windup).
- [ ] 3C ammorbidimento §32 subordinato all'esito (niente più ratchet).
- [ ] Àncora = standard §50; aggr ≤ nominale, MinMove ≥ `minmove_min`; cap §51 tetto intatto.
- [ ] Satisfaction gate §30 rispettato (guida buona → nessuna azione).
- [ ] Anti-flapping recupero↔ammorbidimento; kill-switch `symmetric_recovery_enabled`.
- [ ] `/status.recovery` + log dettagliati (verso, anchor, rms, verdetto).
- [ ] Config `recovery_*` nei 3 TOML; test `test_recovery_symmetric.py` (7 casi) verdi; nessuna regressione §30/§32/CASO3.
- [ ] Rebuild + chiavi nel pacchetto + ZIP; §53 in NOTE_CLAUDE (numerazione verificata); niente commit.

> **Perché conta:** l'asimmetria è un vuoto di progetto, non una taratura. Finché l'unico modo per riportare l'aggressività allo standard è un crash+INIT, ogni degradazione lascia le leve aperte a strascico. Il recupero guidato dall'esito chiude il cerchio Outcome-First: si prova a tornare reattivi, e la misura — non una classificazione — decide se tenere.
