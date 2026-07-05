# PROMPT per Claude Code — Reattività delle leve / MinMove "congelato" (progettazione, item B v2.5)

> **Nota operativa.** NON è un prompt di implementazione. È una richiesta di **diagnosi sul sorgente + progettazione architetturale**. Gemello del `PROMPT_HFD_SAMPLING_AWARE.md` (§32): quello riguarda la *diagnosi*, questo l'*azione* (gestione leve). **Non toccare codice, non compilare, non committare.** Quando implementato sarà una sezione NOTE_CLAUDE successiva (verifica la numerazione al momento).
>
> Riferimento già preparato (leggilo come contesto e **contestalo sul codice**): `DESIGN_RATIONALE_LEVER_RESPONSIVENESS.md`. Log di campo allegati: `session_20260611_222057.csv` (+ `decisions`/`experimental` `_222057`) e `PHD2_GuideLog_2026-06-11_222036.txt`.

---

## 0. PRE-FLIGHT OBBLIGATORIO (sola lettura)

1. **`phd2_agent/diagnostic_engine.py`** — `classify()`: condizioni INSUFFICIENT (L185-191), ramo NOMINAL/satisfaction-gate (L197-209: `proposal = None if satisfied else LeverProposal(aggr=+1, minmove=-1)`), `reset()` (L142-148).
2. **`phd2_agent/analyzer.py`** — `StatisticsAnalyzer._compute()`: come vengono settati `implosion_detected` e `implosion_suspended` (§18 NOTE_CLAUDE: `_RMS_IMPLOSION_FACTOR=8.0`, sospensione 60 s), e per quanto restano appesi. **Questo è il punto centrale dell'indagine.**
3. **`phd2_agent/controller.py`** — il loop di valutazione: ogni quanto chiama `classify()` vs ogni quanto il logger scrive una riga CSV; i reset EMA su cambio esposizione (L1491/1512/1583/1620) e su cambio modalità (L1411); come la `LeverProposal` NOMINAL diventa cambio leva (entro `[limits]`).
4. **`phd2_agent/config.py`** — `[control]` (`interval_seconds=10`, `window_frames=30`), `[limits.ra]`/`[limits.dec]` (`minmove_min=0.15`, `minmove_max=0.85`, `aggr_max=90`, step), `[lever_optimization]`.
5. NOTE_CLAUDE §18 (implosion detector) e §30 (satisfaction gate).
6. **Logica leve v2.3 (CASO 1/2/3)** in `controller.py`: CASO 1 "seeing degradato" (rms>rms_high → MinMove SU, L903-945) e CASO 3 "guida ottima" (rms<rms_low → MinMove GIÙ, L970-1029); passi `aggr_step_down=5`/`aggr_step_up=2`, `minmove_step`. **Confronta con il ramo storico v2.3** in `PHD2_Assist_PATCHED/phd2_agent/controller.py` (CASO 1 ~L809-841, CASO 3 ~L878-926) per confermare che l'asimmetria è **identica e pre-2.4**.

**PHD2 C++:** non necessario (nessuna RPC nuova).

---

## 1. OBIETTIVO

Progettare (NON implementare) come ottenere una **leva MinMove viva e bidirezionale**: che (a) non si **congeli** perché il motore passa il tempo in INSUFFICIENT, e (b) sappia **alzarsi** per ammorbidire il vento, oltre che abbassarsi in aria calma. **Floor 0,15 da NON modificare** (preferenza esplicita dell'utente: il problema è la dinamica, non il limite).

## 2. REGOLE INDEROGABILI

- Read-only: nessuna modifica/compilazione/commit. Solo documento di proposta.
- Retrocompatibilità: a feature spenta, comportamento identico al §31/§30 attuale.
- **Non alzare `minmove_min`** come "soluzione": l'utente vuole mantenere 0,15 come floor e ottenere dinamica, non un floor più alto.
- Non toccare backlash, esposizione dinamica, CASO 1/2/3 v2.3, `review()`/`micro_proposal()` se non strettamente necessario; in tal caso segnalalo.
- Niente taratura di soglie sui dati di una notte: proponi default provvisori, marcati come da-calibrare.

## 3. COMPITI (in ordine)

**3.1 DIAGNOSI — priorità assoluta. Perché il motore è in INSUFFICIENT per l'82% della sessione?**
Dato di partenza (verificato sul CSV): dei 1872 frame INSUFFICIENT, solo **261** hanno `frame_count<30`, **18** `jitter_n<2`, **0** STAR_LOST; **1611** non rientrano in nessuna delle tre, hanno `rms_total` medio 0,49″ (guida buona, nessuna implosione reale) e il contatore frame si è resettato solo **8 volte**. Quindi:
- Stabilisci sul sorgente la **via esatta** che porta quei 1611 frame a INSUFFICIENT. Ipotesi da verificare/scartare: (a) `implosion_suspended` che resta appeso oltre il dovuto; (b) interazione tra cadenza di valutazione (`interval_seconds=10`) e logging per-frame (~2 s) che scrive uno stato non-pronto/stale; (c) altra via.
- **Questo determina tutto il resto:** la leva si "scongela" solo se il motore resta attivo.

**3.2 Ramo NOMINAL bidirezionale.** Oggi la NOMINAL (L197-209) o non agisce o spinge verso la reattività (`minmove-1`). Progetta un percorso che **alzi** MinMove quando il jitter è elevato rispetto al riferimento — anche sotto la soglia SEEING (1,6×) — lasciando invariato il floor 0,15. Definisci: soglia di "regime turbolento", verso e ampiezza del rialzo (a gradini `minmove_step` o proporzionale), interazione col satisfaction-gate §30.

**3.3 Asimmetria strutturale di recupero leve (PRE-§31, la causa storica).** Alessandro osserva da 2.2/2.3 che MinMove scende al floor e non recupera, anche quando l'analyzer entra in DEGRADED. Verifica e **quantifica** sul codice:
- I trigger asimmetrici della logica CASO: MinMove GIÙ su `rms<rms_low` (frequente) vs SU su `rms>rms_high` (raro), con la **banda morta** `rms_low–rms_high` in cui nessuno scatta; e il fatto che la condizione **DEGRADED dell'analyzer ≠ `rms>rms_high`**, per cui in DEGRADED-ma-sotto-soglia MinMove non recupera.
- Conferma che è **identica in v2.3** (`PHD2_Assist_PATCHED`) → strutturale, non un effetto §31.
- L'asimmetria **doppia** dell'aggression (`aggr_step_down=5` vs `aggr_step_up=2`): da preservare come scelta prudente, ma documentare quanto rallenta il recupero.
- Sul log `_222057`: quanti frame stavano in banda morta / DEGRADED senza superare `rms_high` (= recuperi MinMove mancati).
Proposta: un **percorso di recupero "soft" guidato dal jitter** che alzi MinMove (verso valori più morbidi, floor 0,15 invariato) quando il jitter è elevato anche **senza** che l'RMS superi `rms_high` — sanando la banda morta — preservando la prudenza del passo aggression.

**3.4 Relazione con §32 e col reset EMA.** Mostra come questo item e il §32 si compongono (segnale jitter ↔ azione). Riconsidera la tesi "reset EMA = keystone": su questa notte pesa il 14%; va riallineata.

## 4. COSA RESTITUIRE

1. **Verdetto sulla causa 3.1**, con citazioni di codice (file:riga) e, se possibile, la spiegazione dei 1611 frame.
2. Mappa d'impatto (diff concettuali, non applicati).
3. Proposta per il NOMINAL bidirezionale + chiavi config nuove (default retrocompatibili).
4. Controindicazioni: rischio di "pompaggio" di MinMove (su/giù oscillante), interazione con dithering/settle, effetti su Guardian/Jitter.
5. Piano di test unitari (`tests/test_diagnostic_engine.py`): jitter elevato in NOMINAL → MinMove sale; jitter basso → scende verso 0,15; motore resta attivo dove prima andava INSUFFICIENT.
6. Replay: come misurare sul log `_222057` quanti frame "guida buona" sarebbero rimasti attivi col fix, e quante volte MinMove sarebbe salito nella coda ventosa.
7. Decisioni aperte.

## 5. REVISIONE CRITICA (rispondi prima di proporre)
- La causa 3.1 è davvero quella che dici, o stai assumendo? Mostra il codice.
- Alzare MinMove nel vento può **peggiorare** in qualche regime? (es. drift reale dove serve reattività).
- C'è rischio che il fix renda le leve instabili (oscillazione MinMove)?

## 6. COSA NON FARE
- Non implementare; non aggiornare NOTE_CLAUDE/CONTESTO ora.
- Non alzare il floor `minmove_min`.
- Non tarare sui dati di una notte; non allargare lo scope a Guardian/Jitter/esposizione senza necessità dimostrata.
