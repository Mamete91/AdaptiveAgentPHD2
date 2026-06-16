# PROMPT per Claude Code — HFD declassato a SOLO INFORMATIVO (rimozione dal gate diagnostico SEEING)

> **AUTORIZZATO A IMPLEMENTARE.** Isolato al **motore diagnostico (diagnostic_engine.py)**: l'HFD esce dalla decisione SEEING e resta **solo calcolato/loggato**. NON toccare §32/RECOVERY, §33/baseline, §34, §35, §36, le leve, il backlash, la catena RMS.
> **Motivo (verificato sul campo):** su tutti i setup e tutte le notti l'HFD resta piatto (`hfd_avg/hfd_ref ≈ 1.0`) alla scala/SNR della camera di guida → non scatta MAI come gate AND, e quindi blocca la diagnosi SEEING (resta a 0). Conferma 2026-06-16 RC8: SEEING=0 con guida ottima a 0.83″. L'HFD è cieco al seeing sulla camera di guida; il segnale di seeing vero arriverà in futuro dalla camera di ripresa (roadmap NINA). → smettere di far gateare la diagnosi a uno strumento non informativo (coerente con P1).
> **Direttiva di progetto:** il comportamento nuovo nasce **già attivo nel `config.toml`** (born operative). Kill-switch presente per A/B ma shipped sul comportamento nuovo.
> **Numerazione doc:** `grep "^## [0-9]" NOTE_CLAUDE.md | tail -1` → usa **N+1** (atteso §37).
> Contesto: `PRINCIPIO_CONVERGENZA_PRESTAZIONE.md` (P1); design storico `DESIGN_RATIONALE_HFD_SAMPLING_AWARE.md` / `PROPOSTA_§32_HFD_SAMPLING_AWARE.md` — questa è la via **semplice** scelta da Alessandro (declassamento netto) al posto del weighting sampling-aware; segnalarlo in NOTE.

## 0. PRE-FLIGHT (sola lettura)
1. `phd2_agent/diagnostic_engine.py` — la condizione **SEEING** (gate AND ~L222) e i fattori `jitter_high_factor` (1.6) e `hfd_high_factor` (1.25). **Confermare** la formula attuale: SEEING richiede jitter elevato **AND** hfd elevato (e l'eventuale termine RMS). Confermare che è proprio il termine HFD a impedire SEEING.
2. Confermare dove l'HFD entra in ALTRE diagnosi (NOMINAL/OVERCORRECTION/DRIFT/UNCERTAIN/INSUFFICIENT) — l'obiettivo è toglierlo da **ogni** decisione, lasciandolo solo calcolato/loggato.
3. Confermare che `hfd_avg`/`hfd_ref` restano colonne CSV + card dashboard (informative): NON rimuoverle.

## 1. OBIETTIVO
L'HFD non concorre più ad alcuna **decisione** del motore: resta misurato, loggato e mostrato in dashboard (informativo). La diagnosi **SEEING** deve restare possibile dai soli segnali dinamici (jitter + firma RMS), senza il vincolo HFD che oggi la azzera.

## 2. SPECIFICA
1. **Togliere l'HFD dal gate SEEING.** Ridefinire SEEING sulla sola firma dinamica: jitter elevato (`jitter_rms > jitter_ref * jitter_high_factor`) **AND** RMS elevato (`rms_total > rms_high_active`), **distinto** da OVERCORRECTION (lag1 ≤ soglia oscillazione) e da DRIFT (trend). Code definisce la condizione finale ma deve restare **specifica** (non far scattare SEEING su semplice rumore).
2. **Togliere l'HFD da ogni altra decisione** se presente (es. eventuali contributi a NOMINAL/UNCERTAIN). HFD = solo lettura.
3. **HFD informativo:** continuare a calcolare/loggare `hfd_avg`, `hfd_ref` e a mostrarli in dashboard. `hfd_high_factor` resta nel config ma usato **solo** per un'eventuale annotazione informativa (o marcato "informativo/non-gating" nel commento).
4. **Guardian invariato:** in modalità guardian il motore resta **revisore** (CONFIRM/ATTENUATE/BLOCK). Verificare che riabilitare SEEING senza HFD **non** generi nuove azioni spurie: in guardian deve restare review, non pilotare.

## 3. REGOLE
- Isolato a `diagnostic_engine.py` (+ eventuale config/commenti). NON toccare controller leve/CASO, §32/§33/§34/§35/§36, catena RMS, dashboard salvo lasciare la card HFD.
- Kill-switch nel config, **shipped sul comportamento nuovo**: es. `[diagnostic_engine] hfd_gates_seeing = false` (false = HFD NON gatea = informativo, **valore shipped**; true = vecchio comportamento per A/B).
- Retrocompatibilità: con `hfd_gates_seeing = true` il comportamento torna identico all'attuale.

## 4. TEST ATTESI
1. Con `hfd_gates_seeing=false` (default): un frame con jitter alto + RMS alto (HFD piatto) → **SEEING** diagnosticato (oggi NON lo sarebbe).
2. SEEING non scatta su jitter alto da solo senza RMS alto (resta specifico) né si confonde con OVERCORRECTION/DRIFT.
3. HFD piatto NON impedisce più SEEING; `hfd_avg`/`hfd_ref` ancora loggati.
4. In guardian: nessuna nuova azione spuria rispetto al baseline (review-only).
5. Con `hfd_gates_seeing=true`: comportamento identico al pre-fix (regressione).
6. Replay su `session_20260615_211617` (RC8): contare quante volte SEEING scatterebbe ora; verificare che siano eventi reali di alta turbolenza, non rumore.

## 5. REBUILD + DOC
`python build_dist.py` → ZIP. `NOTE_CLAUDE.md` **§N+1** ("HFD declassato a informativo: fuori dal gate SEEING; SEEING su firma jitter+RMS; HFD solo loggato; supera la via sampling-aware §32") + `CONTESTO_PROGETTO.md`. `config.toml` con `hfd_gates_seeing=false` **attivo**. Niente commit/push (lo fa un prompt dedicato).

## 6. CHECKLIST
- [ ] HFD rimosso da OGNI decisione del motore; SEEING ora su jitter+RMS, specifico.
- [ ] `hfd_avg`/`hfd_ref` ancora calcolati/loggati + card dashboard intatta.
- [ ] Kill-switch `hfd_gates_seeing=false` shipped ON; `=true` ripristina il vecchio comportamento.
- [ ] Guardian resta review-only (nessuna azione spuria nuova).
- [ ] Test 1-6 verdi; replay `211617` ispezionato.
- [ ] NOTE §N+1 + CONTESTO aggiornati; ZIP generato.

> **P1:** una leva/segnale che non porta informazione non deve condizionare le decisioni. L'HFD sulla camera di guida non discrimina il seeing → declassarlo a informativo libera la diagnosi SEEING dai segnali dinamici reali, senza pretendere un dato che lo strumento non può dare.
