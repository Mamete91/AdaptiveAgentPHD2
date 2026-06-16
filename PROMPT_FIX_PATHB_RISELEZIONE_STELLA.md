# PROMPT per Claude Code — FIX: riselezione stella di guida all'aumento esposizione (Path B)

> **AUTORIZZAZIONE A IMPLEMENTARE**, isolato al **percorso dell'esposizione dinamica (Path B / escalation gate)** + la riselezione stella. NON toccare §31 (motore), §32/RECOVERY, §33/baseline, le leve, il backlash. Contesto già verificato: `ACCERTAMENTO_PATHB_RISELEZIONE_STELLA.md` + `PRINCIPIO_CONVERGENZA_PRESTAZIONE.md` (P1).
> **Numerazione:** `grep "^## [0-9]" NOTE_CLAUDE.md | tail -1` → usa N+1.

## 0. PRE-FLIGHT (sola lettura)

1. `phd2_agent/controller.py` — il blocco **escalation gate / Path B** (leve sature → `_apply_exposure` per aumentare l'esposizione) e la funzione **`_apply_exposure`**. **Confermare:** all'aumento esposizione NON c'è riselezione stella, solo cambio esposizione + reset analyzer/motore.
2. `phd2_agent/controller.py` — la gestione **saturazione esistente**: `is_saturated` (~L1921), `saturated_lock_since`, `last_saturation_info`, **`_evaluate_saturation_timer`** (~L1843, re-scan `find_star()` dopo `emergency.saturation_timeout_s` = 300s). **Confermare:** la saturazione è gestita SOLO da questo timer reattivo da 300s, NON agganciato a Path B.
3. `phd2_agent/star_finder.py` — `find_best_star` (ritorna `cx,cy,info` con `is_saturated`, `peak_adu`).
4. `client.py` — `set_exposure`, `set_lock_position`, `find_star`, `save_image`.

**Fatto verificato (NON ridiscutere):** una stella ben esposta a 1s **satura a 2s** quando Path B alza l'esposizione (picco flat-top, centroide in bias) → la guida peggiora proprio mentre Path B voleva migliorarla. Oggi il recupero arriva solo dopo **300s** (timer), e non è agganciato a Path B → ~5 minuti di guida su stella satura.

## 1. OBIETTIVO

Quando l'aumento di esposizione (Path B) **fa saturare la stella corrente**, **riselezionarla proattivamente** (entro pochi secondi, non 300s), scegliendo una stella **non satura e ben esposta** alla nuova esposizione. Path B deve così *migliorare* la prestazione (P1), non degradarla.

## 2. SPECIFICA

1. **Aggancio a Path B:** dopo che un aumento esposizione (`_apply_exposure` verso l'alto) ha avuto effetto, attendere **un breve settle** (1-2 frame / parametro `pathb_restar_settle_frames`) perché il nuovo tempo sia attivo.
2. **Check saturazione condizionale:** valutare se la stella corrente satura al nuovo tempo (via `find_best_star`/`is_saturated` su immagine fresca, o peak ADU vicino al fondo scala). **Solo se satura** si procede (la riselezione disturba: NON farla a ogni cambio esposizione).
3. **Riselezione:** scegliere la **migliore stella NON satura** (trade-off saturazione vs SNR: preferire non satura con SNR sufficiente), `set_lock_position`. **Riusare** `find_best_star` + la logica `is_saturated` esistente.
4. **Accorciare il buco:** questo sostituisce/anticipa l'attesa del timer 300s per il caso Path B (il timer resta come rete per gli altri casi).

## 3. REGOLE INDEROGABILI
- Isolato al path esposizione dinamica + riselezione. NON toccare §31/§32/§33, baseline, leve, backlash.
- **Condizionale:** riselezione SOLO se la stella satura davvero. Mai a ogni cambio esposizione (disturberebbe la guida).
- **Anti-flapping:** quando Path B **torna all'esposizione base**, la stella debole riselezionata può ridiventare troppo debole → gestire il ritorno (riselezione/ripristino) con cooldown, senza oscillare su/giù.
- PHD2 deve essere in stato valido (looping/guiding) per riselezionare; rispettare `find_star_delay` e il backoff find_star esistente (§17).
- Retrocompatibilità: a feature spenta, comportamento identico all'attuale (solo timer 300s).

## 4. CONFIG (nuove chiavi, default proposto da Code)
`[exposure_dynamic]` o `[emergency]`: es. `restar_on_pathb_saturation = true` (kill-switch), `pathb_restar_settle_frames = 2`, eventuale cooldown dedicato. A OFF: comportamento attuale.

## 5. TEST ATTESI
1. **Path B su + stella satura:** dopo il settle → riselezione una stella non satura (verificare `is_saturated=False` sulla nuova).
2. **Path B su + stella NON satura:** nessuna riselezione (no disturbo inutile).
3. **Ritorno a esposizione base:** niente flapping (cooldown rispettato).
4. **Riuso `find_best_star`/`is_saturated`:** la nuova stella scelta è non satura con SNR accettabile.
5. **OFF / feature spenta:** comportamento identico all'attuale (solo timer 300s).
6. **Backoff/stati:** se PHD2 non è in stato valido o find_star è in backoff, non forzare.

## 6. VALIDAZIONE
Sanity su simulatore se possibile; in campo: quando Path B scatta e la stella satura, verificare che la riselezione avvenga **in pochi secondi** (non 300s) e che il picco torni ben definito.

## 7. REBUILD + DOC
`python build_dist.py` → ZIP; NOTE_CLAUDE **§N+1** ("Riselezione stella all'aumento esposizione Path B") + CONTESTO. Non toccare gli altri item.

> **P1:** Path B (esposizione più lunga) è uno strumento per mediare il seeing; se satura la stella *peggiora* la prestazione → l'Agente deve adattare la selezione della stella perché l'azione sia davvero benefica. Questo fix rende Path B coerente con P1.
