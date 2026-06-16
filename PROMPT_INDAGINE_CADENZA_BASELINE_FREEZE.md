# PROMPT per Claude Code — Indagine + fix (condizionale): cadenza loop, logging per-frame, baseline lenta / "freeze" INSUFFICIENT

> **Compito in due fasi: (1) CONFERMA l'ipotesi sui dati/codice; (2) SE confermata, IMPLEMENTA il fix.** Se l'ipotesi è errata, **dillo e spiega perché**, senza forzare una soluzione. Abbiamo già avuto troppi lead sul "freeze" senza risolvere — questo va chiuso con una conferma sul codice, non con un'altra ipotesi.
> Contesto: `PRINCIPIO_CONVERGENZA_PRESTAZIONE.md` (P1). La baseline lenta si è ripresentata **anche sull'ultima build pulita** (cache rimossa), quindi NON è una build stantia: è un comportamento del codice.

## 0. L'IPOTESI DA CONFERMARE (dai log RC8 v2.5, session_20260615_000212)

Evidenza misurata (Cowork):
- **78% dei frame loggano `exposure_ms = 0`** ma con **SNR≈59 e HFD≈7.7 ottimi** → NON stelle perse, è un'anomalia di **lettura/logging** dell'esposizione.
- Quei frame `exposure=0` sono **~100% `diag_state = INSUFFICIENT_DATA`**; i frame `exposure=2000` (~22%) producono **diagnosi reali** (DRIFT/UNCERTAIN).
- `frame_count` è ~30 (finestra piena) in ENTRAMBI → **NON** è un reset di frame_count.
- La **baseline si forma al frame ~900 (~25 min)**, NON ai ~180 frame (~6 min) attesi dal fallback §33.

**Ipotesi:** il loop di valutazione del controller (engine `classify()` **e** accumulo baseline `_update_rms_baseline`) **non gira per ogni guide-frame (~2s) ma sulla cadenza di controllo `[control] interval_seconds = 10`** (~1 frame su 5). Il CSV logga ogni guide-frame: i frame "fuori-tick" (~78%) escono con **placeholder** (`exposure=0`, `diag_state=INSUFFICIENT`). Conseguenze:
1. **"Motore INSUFFICIENT ~85%" = artefatto di logging**, non un vero congelamento (vale su Askar/Mirko/RC8: ~82-87%).
2. **Baseline lenta**: il contatore `baseline_fallback_frames=180` conta i **tick da ~10s**, non i frame da ~2s → 180 tick ≈ 30 min (invece di ~6).

## 1. FASE 1 — CONFERMA (sola lettura)

Stabilire sul codice:
1. **Cadenza:** `_update_rms_baseline` e `diagnostic_engine.classify()` girano **per guide-frame** o **per tick `interval_seconds`**? (verifica il loop in controller.py: ogni quanto si entra nella valutazione vs ogni quanto il logger scrive una riga CSV).
2. **Origine di `exposure_ms=0`:** perché l'esposizione si logga 0 sui frame fuori-tick? (default non popolato? snapshot placeholder?).
3. **Origine dell'INSUFFICIENT sui frame `exposure=0`:** `frame_count` è 30, quindi NON è `frame_count<min_frames`. È `jitter_n<2`? `implosion`? un diag_state di default loggato quando `classify()` non gira? Determinare la causa esatta.
4. **Baseline lenta:** confermare che `_baseline_frames_seen` (o l'accumulo) avanza solo sui tick → 180 ≈ 30 min.

**Riporta il verdetto: ipotesi CONFERMATA / PARZIALE / ERRATA, con citazioni di codice (file:riga).**

## 2. FASE 2 — FIX (solo se confermata)

A seconda di cosa risulta:
- **Baseline veloce:** fare in modo che l'accumulo baseline (almeno il fallback §33) conti i **guide-frame reali**, non i tick da 10s → il fallback scatta in ~6 min come previsto. (Oppure tarare `baseline_fallback_frames` sulla cadenza reale, documentandolo.)
- **Logging non fuorviante:** sui frame fuori-tick, NON loggare un `diag_state=INSUFFICIENT` e `exposure_ms=0` placeholder che inquinano le metriche — loggare lo **stato reale corrente** (l'ultimo diagnosi valido) o marcare la riga come "non-valutazione", così l'"85% INSUFFICIENT" sparisce dalle statistiche e si vede il comportamento vero del motore.
- **Esposizione:** popolare correttamente `exposure_ms` su ogni riga (valore reale, non 0).

> **Nota P1 / scopo:** l'obiettivo è che baseline e diagnosi riflettano la **prestazione reale**, non un artefatto di cadenza. NON cambiare la logica del motore (§31), del RECOVERY (§32), del sampling-aware (§32 HFD) o delle leve: solo cadenza-accumulo-baseline + pulizia logging.

## 3. REGOLE
- Isolato a: loop di valutazione/cadenza, accumulo baseline, logging per-frame, lettura `exposure_ms`. NON toccare la logica diagnostica/leve.
- **Direttiva di progetto:** qualunque nuova chiave/feature nasce **già attiva (`true`) nel `config.toml`** del pacchetto — niente flag da abilitare a mano (born operative/live).
- Retrocompatibilità: a parità di comportamento reale del motore, cambiano solo cadenza-accumulo e qualità del logging.

## 4. TEST + VALIDAZIONE
- Test: baseline che si forma a ~180 guide-frame (non a ~180 tick); le righe fuori-tick non producono più INSUFFICIENT spuri; `exposure_ms` popolato.
- Replay/conferma su `session_20260615_000212`: ricalcolare la % INSUFFICIENT REALE (solo frame valutati) e il tempo-baseline atteso col fix.

## 5. REBUILD + DOC
Se si implementa: `python build_dist.py`; NOTE_CLAUDE §N+1 + CONTESTO; config.toml con le eventuali nuove chiavi **attive di default**. Niente commit/push.
