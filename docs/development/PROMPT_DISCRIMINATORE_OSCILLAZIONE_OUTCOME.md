# PROMPT per Claude Code — Anti-spirale guide-side: CAP MinMove ADATTIVO + Discriminatore oscillazione + softening outcome-based

> **DUE protezioni in un piano, kill-switch separati:** (0) **cap MinMove in arcsec** (la "pistola fumante" fisica), (1-3) **discriminatore oscillazione fisiologica/patologica + softening outcome-based**. Attaccano la stessa spirale di sotto-correzione da lati diversi.
>
> **Evidenza fresca (3 sessioni, l'ultima 2026-06-20/21 con §44 GIÀ ATTIVO):** anche con la baseline bidirezionale che fa salire `rms_high`, **il DEC MinMove è tornato a 0,85 px = 1,34" di cielo** in entrambe le sessioni di stanotte (RMS per terzi 0,66→1,18→1,00, picco 2,39; e 0,80→0,61→0,90). → **§44 NON ha tolto il problema MinMove.** Un dead-band di 1,34" > RMS bersaglio fa **sotto-correggere per costruzione e fabbrica RMS** → conferma su 3 sessioni che il cap MinMove-arcsec è una protezione **fondamentale e immediata**, non futura.
> Inoltre: il controllore reagisce a movimento **fisiologico** come fosse overcorrection (es. v2.3 ha loggato *"Oscillazione rilevata (trend=+0,065…) → riduco Aggressività"* — un TREND/deriva trattato come oscillazione, segno sbagliato).
>
> **Obiettivo:** (0) impedire che il MinMove crei un dead-band più grande dell'RMS raggiungibile; (1-3) trattare l'oscillazione come patologica SOLO con evidenza forte/simultanea, **tollerare l'oscillazione fisiologica**, rendere il softening **outcome-based** (se non aiuta → stop + rollback). P1: non cercare la stella "perfetta"; massimizzare la qualità, non azzerare il movimento.
>
> **Ambito:** core engine/controller — **separato da §44** (già attivo). Metodologia (`METODOLOGIA_VALIDAZIONE_LIVE.md`): operativo + **visibile in diretta**, **reversibile** (kill-switch per sotto-feature, così validi 0 e 1-3 separatamente), GUARDIAN/fail-safe.
> **Numerazione:** `grep "^## [0-9]" NOTE_CLAUDE.md | tail -1` → usa due § liberi consecutivi (uno per il cap MinMove, uno per il discriminatore). Verifica.
> Contesto: `diagnostic_engine.py`, controller (CASO1/2 + §32 minmove_recovery + clamp leve), `config.py` `[limits]`, `VALIDAZIONE_CAMPO_v2.6.md`, [[phd2-rms-unit-bug]] (§36, stessa lezione "parametro cieco alla scala"), P1.

## FASE 0 — VERIFICA (sola lettura, riportare)
1. **Clamp del MinMove:** dove il controller applica `minmove_max` (in PIXEL) e dove §32 `minmove_recovery` alza il MinMove. Confermare che `minmove_max=0.85` è in pixel e che la pixel-scale viva è `cfg.setup.guide_pixel_scale_arcsec`. (Per N4/oscillazione serve anche il punto 3.)
2. **Dove si decide "oscillazione" oggi**, in DUE punti: (a) motore `diagnostic_engine.classify` → `oscillation = lag1_ra<=thr OR lag1_dec<=thr` (`lag1_oscillation_thresh=-0.35`) → OVERCORRECTION; (b) controller **v2.3 CASO2** *"Oscillazione rilevata (trend=…)"* → riduce aggressività. Riportare file:riga e come CASO2 definisce l'oscillazione (sembra un TREND → da correggere).
3. **Infrastruttura outcome** da riusare: `outcome_window_frames`(15), `_last_outcome`, §32 `recovery_no_progress_k`(3). Accesso alla **serie dei segni dell'errore** (`ra_raw`/`dec_raw`) per l'alternanza e all'**ampiezza** (jitter/peak).

## 0. CAP MINMOVE — ADATTIVO alla baseline (NON un assoluto fisso) — protezione fisica prioritaria
**Problema misurato:** `minmove_max=0.85` px è in PIXEL → su scala guida 1,579"/px = **1,34" di cielo**, più grande dell'RMS raggiungibile → sotto-corregge e fabbrica RMS (classe §36, parametro cieco alla scala).
**MA — punto chiave (Alessandro, condiviso): il cap deve essere ADATTIVO, non assoluto.** Il MinMove è una **soglia di inseguimento** (quanto rumore ignorare), non un target di RMS. Su RC8 in seeing mediocre un MinMove di 0,8-1,0" può essere **corretto** (evita di inseguire il seeing). Un cap fisso a 0,5" reintrodurrebbe una soglia rigida proprio dove §44 ha reso il sistema adattivo. → Il cap deve **crescere e calare con le condizioni reali**, come la baseline.

**Fix — cap PRINCIPALE relativo alla baseline:**
`minmove_max_eff_arcsec = k × baseline_rms` (con baseline §44, bidirezionale). `minmove_max_eff_px = minmove_max_eff_arcsec / pixel_scale`.
- **`k` < 1** (default **~0,8**, tarabile): il dead-band resta una **frazione** dell'RMS raggiungibile → non lo domina mai (evita anche un feedback baseline↔cap), ma sale/scende col cielo. Riferimento configurabile `baseline_rms` (preferito) **o** `rms_high` (A/B).
- **Esempi (la coerenza che cerchi):** 71F notte buona baseline 0,5" → cap ≈ **0,4"**; RC8 seeing mediocre baseline 1,2" → cap ≈ **0,96"**. Il limite segue il setup e la notte, non un numero unico.
- **Backstop di sanità (NON il cap operativo):** un tetto arcsec generoso `minmove_hard_ceiling_arcsec` (~1,2-1,5") solo per catturare valori assurdi se la baseline fosse anomala (il gate rifiuto §23 già la bound). E il floor resta `minmove_min`.
- **Fallback:** baseline non ancora formata/rifiutata → usa il cap px legacy (0,85) o un default finché la baseline non è pronta. Niente comportamento indefinito.
- Applicare su **entrambi gli assi** e a **TUTTI** i punti che alzano il MinMove (§32 recovery + micro GUARDIAN inclusi).
- Kill-switch `[limits] minmove_cap_adaptive_enabled=true` (a `false` = solo cap px legacy). Config: `minmove_cap_baseline_factor` (k), `minmove_cap_reference` (`baseline_rms`/`rms_high`), `minmove_hard_ceiling_arcsec`.
- **Esporre su `/status`/log:** MinMove efficace in arcsec **e** il cap adattivo corrente (così in dashboard vedi sia il dead-band reale sia il limite che si muove con la notte).

**Test:** baseline 0,5" (71F) → cap ≈0,4" → MinMove non supera ~0,25 px (mai 0,85=1,34"); baseline 1,2" (RC8 mediocre) → cap ≈0,96" → MinMove può salire coerentemente, **senza** essere tagliato a 0,5"; baseline che sale in nottata (§44) → il cap sale con essa (k<1 → resta sotto l'RMS); baseline non pronta → fallback px; backstop blocca un cap assurdo; §32/GUARDIAN rispettano il cap; kill-switch off → legacy. Suite verde.

## 1. CRITERIO A — Oscillazione patologica = 4 firme SIMULTANEE (no più trigger singolo)
OVERCORRECTION (e l'azione "riduci aggressività per oscillazione") richiede **TUTTE** queste condizioni insieme, su una finestra:
1. **lag-1 fortemente negativo** (non solo < −0,35): soglia "forte" tarabile (es. ≤ −0,5), su RA o DEC.
2. **Alternanza regolare dei segni** dell'errore: frazione di inversioni di segno consecutive **alta** su finestra (es. ≥ ~70% dei passi), non qualche inversione sparsa. (Il rumore fisiologico ha segni casuali, non alternanza regolare.)
3. **Ampiezza significativa — con FLOOR esplicito (richiesta Alessandro):** il jitter/peak dell'oscillazione deve superare un **pavimento doppio** `max(k_px × pixel_scale, k_base × baseline_rms)` → si **ignorano** le oscillazioni di ampiezza molto piccola rispetto alla **pixel scale** (rumore del centroide) o alla **baseline RMS** (microturbolenza fisiologica). Sotto quel floor = rumore, non oscillazione. `k_px`/`k_base` tarabili.
4. **Crescita dell'errore RMS**: RMS in **aumento** sulla finestra (trend RMS > 0). Una vera overcorrection peggiora le cose.

**Correzione del mislabel:** un **trend monotòno** (deriva) **NON** è oscillazione → non deve ridurre l'aggressività; è DRIFT (gestione separata, nessuna leva soft). Il CASO2 "oscillazione = trend" va sostituito da questo gate a 4 firme. Kill-switch `[diagnostic_engine] oscillation_strict=true` (a `false` = comportamento legacy per A/B).

## 2. CRITERIO B — Tolleranza dell'oscillazione FISIOLOGICA + SATISFACTION GATE ASSOLUTO
Il ramo oscillazione **perde l'autorità di ammorbidire** quando la guida è già buona — in senso **relativo O assoluto** — e non c'è degrado progressivo:
- **B1 relativo:** RMS ≤ mediana baseline × fattore **E** nessuna crescita dell'errore → non intervenire (satisfaction-gate §30 esteso all'oscillazione).
- **B2 ASSOLUTO (richiesta Alessandro):** se **RMS è già entro il target del setup** (es. ~0,45–0,55″ osservati in campo; soglia assoluta `oscillation_abs_target_arcsec`, default ~0,6″, idealmente per-setup dalla scala di imaging — cfr. N5) **E** nessun degrado progressivo → il ramo oscillazione **NON ha più autorità per ammorbidire le leve**, punto. Anche se qualche firma di alternanza è presente: con RMS già ottimo, quell'oscillazione è **fisiologica per definizione**.
- (futuro N4) stelle fotograficamente sane → ulteriore conferma "lasciala in pace".

**Principio (Alessandro):** l'obiettivo non è **eliminare ogni oscillazione**, ma **massimizzare la qualità della guida**. Se la guida è già ottima, il motore deve **considerare quel comportamento fisiologico e lasciarlo in pace** — non inseguire la stella "perfetta". Il satisfaction gate assoluto è ciò che impedisce l'ammorbidimento progressivo "senza beneficio reale" partendo da RMS 0,45–0,55″. Soglie `oscillation_physio_tolerance` + `oscillation_abs_target_arcsec` tarabili. (Nota: lo stesso gate assoluto è applicabile anche al ramo SEEING-softening come ulteriore freno anti-spirale — valutarlo, coerente col §30.)

## 3. CRITERIO C — Softening OUTCOME-BASED (anti-feedback) + rollback
Dopo un'azione di softening (aggr↓ o MinMove↑, sia da OVERCORRECTION sia da SEEING):
1. valutare l'esito su `outcome_window_frames`: **l'RMS è migliorato?**
2. **migliorato** → diagnosi confermata, prosegui.
3. **uguale o peggiore** → il softening **non sta aiutando** → **stop del softening** e, se si è a/oltre la zona morbida (vicino al pavimento aggr / tetto MinMove), **piccolo rollback** di un gradino (ripristina un po' di aggressività / abbassa di un gradino il MinMove), con **anti-flapping** (cooldown + isteresi, non oscillare tra soft e stiff). Riusa/estendi `recovery_no_progress_k`.
4. Questo vale come **guardia anti-spirale**: impedisce la catena "ammorbidisco → RMS non scende → ammorbidisco ancora".

## 4. VISIBILITÀ (obbligatoria, metodologia live)
- `evidence` del motore: mostrare **quali delle 4 firme** sono (non) soddisfatte e l'esito outcome. Es.: `lag-1 −0,28 (non forte) · alternanza 35% (no) · RMS stabile vicino baseline → OSCILLAZIONE FISIOLOGICA, nessuna azione`. Oppure: `lag-1 −0,55 · alternanza 80% · ampiezza alta · RMS in crescita → OVERCORRECTION reale → riduco aggr · [dopo 15 frame] RMS non sceso → STOP + rollback`.
- **Dashboard** (Seeing Diagnostic Engine): badge "oscillazione: fisiologica / patologica" + esito ultimo softening (helped / no-progress / rolled-back).
- **Grafico di guida:** marcatore sulle azioni di softening e sui rollback.
- Log: i 4 booleani (lag1_strong, alternation, amplitude, rms_growing), `softening_outcome` (improved/no_progress/worse), `rollback` sul frame.

## 5. CONFIG `[diagnostic_engine]` (born-operative, tarabili)
`oscillation_strict=true`; `lag1_strong_thresh=-0.5`; `oscillation_alternation_min=0.7`; `oscillation_amplitude_floor` come `max(k_px×pixel_scale, k_base×baseline_rms)` (floor anti-rumore-centroide); `oscillation_rms_growth_min`; `oscillation_physio_tolerance` (gate relativo B1); **`oscillation_abs_target_arcsec` (gate assoluto B2, default ~0.6, per-setup)**; `softening_outcome_check=true`; `softening_rollback=true` + cooldown/isteresi. Kill-switch per ciascuna sotto-feature (A/B).

## 6. TEST (Code DEVE validare)
1. **Fisiologico:** lag-1 lieve (−0,2/−0,3), segni casuali, RMS stabile vicino baseline → **NESSUNA** OVERCORRECTION, nessun softening (riproduce lo scenario di campo).
2. **Patologico vero:** lag-1 ≤ −0,5 + alternanza ~80% + ampiezza alta + RMS in crescita → OVERCORRECTION → riduci aggr.
3. **Deriva (anti-mislabel):** trend monotòno positivo, niente alternanza → **DRIFT, NON oscillazione**, nessuna riduzione aggr.
4. **Outcome+rollback:** softening seguito da RMS non in calo su 15 frame → stop + rollback di un gradino; anti-flapping verificato.
5. **Tolleranza fisiologica (relativa):** RMS ≈ baseline + no crescita → nessun intervento anche con qualche inversione di segno.
6. **Satisfaction gate ASSOLUTO (scenario Alessandro):** RMS 0,45–0,55″ (entro `oscillation_abs_target_arcsec`) + nessun degrado → il ramo oscillazione **non ammorbidisce**, anche con lag-1/alternanza presenti. **NON** deve esserci ammorbidimento progressivo a guida già ottima.
7. **Floor di ampiezza:** oscillazione di ampiezza < `max(k_px×pixel_scale, k_base×baseline_rms)` → **ignorata** (rumore centroide), nessuna azione.
8. **Reversibile/graceful:** ogni kill-switch a `false` → comportamento legacy; suite verde.

## 7. CHIUSURA
- **NON toccare:** backlash, esposizione, baseline §33/§40/§44, cap §24 (rms_high), telemetria §41/§42.
- **REBUILD** (`build_dist.py`, config con le nuove chiavi attive: `minmove_cap_adaptive_enabled`, `minmove_cap_baseline_factor`, `minmove_cap_reference`, `minmove_hard_ceiling_arcsec`, le chiavi oscillazione); **verifica il config nel pacchetto**; niente commit/push.
- **DOC:** `NOTE_CLAUDE.md` (due nuove §: cap MinMove adattivo + discriminatore) + `CONTESTO_PROGETTO.md` + `VALIDAZIONE_CAMPO_v2.6.md`.
- **Validazione live, una sotto-feature per volta** (kill-switch separati): consigliato attivare **prima il cap MinMove adattivo da solo** (effetto fisico immediato) e verificarlo, poi il discriminatore oscillazione.

## CHECKLIST
- [ ] FASE 0: riportati il clamp MinMove (px) + §32 recovery, i 2 punti "oscillazione" (lag-1 + CASO2 trend), l'infrastruttura outcome; accesso a segni/ampiezza.
- [ ] **§0 CAP MinMove ADATTIVO:** cap = `k × baseline_rms` (k~0,8 <1, riferimento baseline_rms/rms_high) → px via pixel_scale; su RA+DEC e su TUTTI i punti che alzano il MinMove (incl. §32 + micro GUARDIAN); backstop di sanità `minmove_hard_ceiling_arcsec`; fallback px se baseline non pronta; MinMove efficace + cap corrente in arcsec su /status/log; kill-switch `minmove_cap_adaptive_enabled`; test 71F/RC8 + baseline che sale.
- [ ] CRITERIO A: OVERCORRECTION solo con 4 firme simultanee (lag-1 forte + alternanza regolare + **ampiezza sopra il floor `max(k_px×pixel_scale, k_base×baseline_rms)`** + RMS in crescita); trend monotòno = DRIFT, non oscillazione; kill-switch `oscillation_strict`.
- [ ] CRITERIO B: tolleranza fisiologica **relativa** (RMS≈baseline + no crescita) **+ satisfaction gate ASSOLUTO** (RMS ≤ `oscillation_abs_target_arcsec` + no degrado → ramo oscillazione senza autorità di ammorbidire).
- [ ] CRITERIO C: softening outcome-based (RMS non migliora → stop + rollback con anti-flapping).
- [ ] Visibilità live (evidence 4 firme + esito, dashboard badge, marcatore grafico, log).
- [ ] Config tarabile (incl. `oscillation_abs_target_arcsec`, `oscillation_amplitude_floor`) + kill-switch per sotto-feature; **test 1-8**; rebuild; nessuna regressione; niente commit.

> **P1:** l'obiettivo non è una stella di guida immobile, ma la **prestazione raggiungibile date le condizioni**. Un po' di movimento È il seeing reale: il motore deve **tollerarlo** e agire solo su un'oscillazione **davvero** patologica (forte, regolare, crescente) e solo se l'azione **dimostra** di aiutare — altrimenti torna indietro. È l'anti-spirale, in diretta e visibile.
