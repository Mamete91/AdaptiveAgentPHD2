# PROMPT per Claude Code — DUE implementazioni necessarie e indispensabili, in un unico intervento

> **Entrambe le parti vanno implementate.** Sono indipendenti nel codice ma entrambe richieste.
> **PARTE A** (cadenza loop / logging per-frame / baseline lenta-"freeze"): prima **CONFERMA** sul codice l'ipotesi, poi **IMPLEMENTA** il fix. Se l'ipotesi risultasse errata, **dillo e spiega perché** con citazioni di codice, e proponi la diagnosi corretta — NON forzare una soluzione sbagliata. Abbiamo già avuto troppi lead sul "freeze" senza chiuderlo: va risolto con una conferma sul codice, non con un'altra ipotesi.
> **PARTE B** (riselezione stella all'aumento esposizione Path B): **AUTORIZZATA A IMPLEMENTARE** direttamente, isolata al percorso esposizione dinamica.
>
> **DIRETTIVA DI PROGETTO (vale per TUTTE le chiavi nuove di entrambe le parti):** ogni nuova feature/chiave nasce **già attiva (`true`) e operativa nel `config.toml`** del pacchetto — niente flag da abilitare a mano, il pacchetto distribuito gira live con tutto acceso. Kill-switch presente nel TOML per eventuale A/B, ma il **valore shipped è ON**.
>
> **Contesto già verificato (NON ridiscutere):** `PRINCIPIO_CONVERGENZA_PRESTAZIONE.md` (P1), `ACCERTAMENTO_PATHB_RISELEZIONE_STELLA.md`. La baseline lenta si è ripresentata **anche sull'ultima build pulita** (cache rimossa) → è comportamento del codice, non build stantia.
> **Numerazione doc:** `grep "^## [0-9]" NOTE_CLAUDE.md | tail -1` → usa **N+1** per la Parte A e **N+2** per la Parte B.

---

# PARTE A — Cadenza loop / logging per-frame / baseline lenta ("freeze" INSUFFICIENT)

## A.0 — IPOTESI DA CONFERMARE (dai log RC8 v2.5, `session_20260615_000212`, 2149 frame)

Evidenza misurata (Cowork):
- **78% dei frame** loggano `exposure_ms = 0` ma con **SNR≈59 e HFD≈7.7 ottimi** → NON stelle perse: anomalia di **lettura/logging** dell'esposizione.
- Quei frame `exposure=0` sono **~100% `diag_state = INSUFFICIENT_DATA`**; i frame `exposure=2000` (~22%) producono **diagnosi reali** (DRIFT/UNCERTAIN).
- `frame_count` è ~30 (finestra piena) in ENTRAMBI i gruppi → **NON** è un reset di `frame_count`.
- La **baseline si forma al frame ~900 (~25 min)**, NON ai ~180 frame (~6 min) attesi dal fallback §33.

**Ipotesi:** il loop di valutazione del controller (`diagnostic_engine.classify()` **e** l'accumulo baseline `_update_rms_baseline`) **non gira per ogni guide-frame (~2s) ma sulla cadenza di controllo `[control] interval_seconds = 10`** (~1 frame su 5). Il CSV logga ogni guide-frame, quindi i frame "fuori-tick" (~78%) escono con **placeholder** (`exposure=0`, `diag_state=INSUFFICIENT`). Conseguenze:
1. **"Motore INSUFFICIENT ~85%" = artefatto di logging/cadenza**, non vera paralisi (coerente con Askar/Mirko/RC8: ~82-87%).
2. **Baseline lenta**: il contatore `baseline_fallback_frames=180` conta **tick da ~10s**, non frame da ~2s → 180 tick ≈ 30 min invece di ~6.

## A.1 — FASE 1: CONFERMA (sola lettura)

Stabilire sul codice e riportare con citazioni `file:riga`:
1. **Cadenza:** `_update_rms_baseline` e `classify()` girano **per guide-frame** o **per tick `interval_seconds`**? (verificare il loop in `controller.py`: ogni quanto si entra nella valutazione vs ogni quanto il logger scrive una riga CSV).
2. **Origine `exposure_ms=0`:** perché l'esposizione si logga 0 sui frame fuori-tick (default non popolato? snapshot placeholder?).
3. **Origine INSUFFICIENT sui frame `exposure=0`:** dato `frame_count`≈30 (quindi NON `frame_count<min_frames`) → è `jitter_n<2`? `implosion`? un diag_state di default loggato quando `classify()` non gira? Determinare la causa esatta.
4. **Baseline lenta:** confermare che l'accumulo (`_baseline_frames_seen` / fallback §33) avanza solo sui tick → 180 ≈ 30 min.

**Verdetto esplicito: ipotesi CONFERMATA / PARZIALE / ERRATA.**

## A.2 — FASE 2: FIX (solo se confermata, integralmente o in parte)

- **Baseline veloce:** l'accumulo baseline (almeno il fallback §33) deve contare i **guide-frame reali**, non i tick da 10s → il fallback scatta in ~6 min come previsto. In alternativa tarare `baseline_fallback_frames` sulla cadenza reale, documentandolo.
- **Logging non fuorviante:** sui frame fuori-tick NON loggare `diag_state=INSUFFICIENT`/`exposure_ms=0` placeholder che inquinano le metriche — loggare lo **stato reale corrente** (ultimo diagnosi valido) oppure marcare la riga come "non-valutazione", così l'"85% INSUFFICIENT" sparisce dalle statistiche e si vede il comportamento vero del motore.
- **Esposizione:** popolare correttamente `exposure_ms` su ogni riga (valore reale, non 0).

> **P1:** baseline e diagnosi devono riflettere la **prestazione reale**, non un artefatto di cadenza. NON cambiare la logica del motore (§31), del RECOVERY (§32), del sampling-aware HFD o delle leve: solo cadenza-accumulo-baseline + pulizia logging.

## A.3 — REGOLE PARTE A
- Isolato a: loop di valutazione/cadenza, accumulo baseline, logging per-frame, lettura `exposure_ms`. NON toccare la logica diagnostica/leve.
- Eventuali nuove chiavi → **attive (`true`) di default** nel `config.toml` (direttiva).
- Retrocompatibilità: a parità di comportamento reale del motore cambiano solo cadenza-accumulo e qualità del logging.

## A.4 — TEST PARTE A
- Baseline che si forma a ~180 **guide-frame** (non a ~180 tick); righe fuori-tick senza INSUFFICIENT spuri; `exposure_ms` popolato.
- Replay su `session_20260615_000212`: ricalcolare la % INSUFFICIENT **reale** (solo frame valutati) e il tempo-baseline atteso col fix.

---

# PARTE B — Riselezione stella di guida all'aumento esposizione (Path B)

## B.0 — PRE-FLIGHT (sola lettura)
1. `phd2_agent/controller.py` — blocco **escalation gate / Path B** (leve sature → `_apply_exposure` per aumentare l'esposizione) e funzione **`_apply_exposure`**. **Confermare:** all'aumento esposizione NON c'è riselezione stella, solo cambio esposizione + reset analyzer/motore.
2. `phd2_agent/controller.py` — gestione **saturazione esistente**: `is_saturated` (~L1921), `saturated_lock_since`, `last_saturation_info`, **`_evaluate_saturation_timer`** (~L1843, re-scan `find_star()` dopo `emergency.saturation_timeout_s`=300s). **Confermare:** saturazione gestita SOLO da questo timer reattivo da 300s, NON agganciato a Path B.
3. `phd2_agent/star_finder.py` — `find_best_star` (ritorna `cx,cy,info` con `is_saturated`, `peak_adu`).
4. `client.py` — `set_exposure`, `set_lock_position`, `find_star`, `save_image`.

**Fatto verificato (NON ridiscutere):** una stella ben esposta a 1s **satura a 2s** quando Path B alza l'esposizione (picco flat-top, centroide in bias) → la guida peggiora proprio mentre Path B voleva migliorarla. Oggi il recupero arriva solo dopo **300s** (timer), non agganciato a Path B → ~5 minuti di guida su stella satura.

## B.1 — OBIETTIVO
Quando l'aumento esposizione (Path B) **fa saturare la stella corrente**, **riselezionarla proattivamente** (entro pochi secondi, non 300s), scegliendo una stella **non satura e ben esposta** alla nuova esposizione. Path B deve così *migliorare* la prestazione (P1), non degradarla.

## B.2 — SPECIFICA
1. **Aggancio a Path B:** dopo che `_apply_exposure` verso l'alto ha avuto effetto, attendere un breve settle (1-2 frame / `pathb_restar_settle_frames`) perché il nuovo tempo sia attivo.
2. **Check saturazione condizionale:** valutare se la stella corrente satura al nuovo tempo (via `find_best_star`/`is_saturated` su immagine fresca, o peak ADU vicino al fondo scala). **Solo se satura** si procede — la riselezione disturba: NON farla a ogni cambio esposizione.
3. **Riselezione:** scegliere la **migliore stella NON satura** (trade-off saturazione vs SNR: preferire non satura con SNR sufficiente), `set_lock_position`. **Riusare** `find_best_star` + la logica `is_saturated` esistente.
4. **Accorciare il buco:** sostituisce/anticipa l'attesa del timer 300s per il caso Path B (il timer resta come rete per gli altri casi).

## B.3 — REGOLE INDEROGABILI PARTE B
- Isolato al path esposizione dinamica + riselezione. NON toccare §31/§32/§33, baseline, leve, backlash.
- **Condizionale:** riselezione SOLO se la stella satura davvero. Mai a ogni cambio esposizione.
- **Anti-flapping:** quando Path B torna all'esposizione base, la stella debole riselezionata può ridiventare troppo debole → gestire il ritorno con cooldown, senza oscillare su/giù.
- PHD2 in stato valido (looping/guiding) per riselezionare; rispettare `find_star_delay` e il backoff find_star (§17).
- Retrocompatibilità: a feature **disattivata** (kill-switch) comportamento identico all'attuale (solo timer 300s).

## B.4 — CONFIG PARTE B (nuove chiavi, **attive `true` di default** — direttiva)
`[exposure_dynamic]` o `[emergency]`: `restar_on_pathb_saturation = true` (kill-switch, **shipped ON**), `pathb_restar_settle_frames = 2`, eventuale cooldown dedicato. Scritte **esplicitamente** nel `config.toml` del pacchetto, non solo nei default dataclass.

## B.5 — TEST PARTE B
1. Path B su + stella satura → dopo settle, riselezione di una stella non satura (`is_saturated=False` sulla nuova).
2. Path B su + stella NON satura → nessuna riselezione.
3. Ritorno a esposizione base → niente flapping (cooldown rispettato).
4. Riuso `find_best_star`/`is_saturated`: nuova stella non satura con SNR accettabile.
5. Feature OFF → comportamento identico all'attuale (solo timer 300s).
6. PHD2 non in stato valido / find_star in backoff → non forzare.

---

# COMUNE A ENTRAMBE LE PARTI

## REBUILD + DOC
`python build_dist.py` → ZIP. `NOTE_CLAUDE.md`: **§N+1** (Parte A — "Cadenza loop / baseline reale / pulizia logging INSUFFICIENT") e **§N+2** (Parte B — "Riselezione stella all'aumento esposizione Path B") + aggiornare `CONTESTO_PROGETTO.md`. `config.toml` con **tutte le nuove chiavi attive di default**. Niente commit/push.

## CHECKLIST FINALE
- [ ] Parte A: verdetto CONFERMATA/PARZIALE/ERRATA dato con citazioni `file:riga`.
- [ ] Parte A: se confermata, baseline conta guide-frame reali (fallback ~6 min) + logging non più fuorviante + `exposure_ms` popolato.
- [ ] Parte B: riselezione condizionale agganciata a Path B, riuso `find_best_star`/`is_saturated`, anti-flapping con cooldown.
- [ ] Tutte le nuove chiavi **scritte e `true` nel `config.toml`** del pacchetto (born operative).
- [ ] Nessuna modifica a §31/§32/§33-logica, leve, backlash.
- [ ] Test Parte A + Parte B verdi; replay `session_20260615_000212` ricalcolato.
- [ ] `NOTE_CLAUDE.md` §N+1 e §N+2 + `CONTESTO_PROGETTO.md` aggiornati; ZIP generato.
