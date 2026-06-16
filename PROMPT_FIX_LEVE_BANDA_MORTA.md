# PROMPT per Claude Code — FIX (implementazione) recupero MinMove nella banda morta

> **AUTORIZZAZIONE A IMPLEMENTARE.** Questo NON è solo-analisi: Alessandro autorizza l'implementazione di QUESTO fix, **isolato** e urgente. NON toccare il §32 (HFD sampling-aware), NON toccare l'indagine sul congelamento/INSUFFICIENT, NON toccare la logica §31 (jitter/guardian review/micro). Solo la logica di recupero leve v2.3 (CASO).
> Documenti di contesto già verificati: `DESIGN_RATIONALE_LEVER_RESPONSIVENESS.md`. Log di validazione allegati: `session_20260611_003714.csv` (GUARDIAN, 1253 frame) e `session_20260611_222057.csv` (JITTER).
> **Numerazione:** verifica `grep "^## [0-9]" NOTE_CLAUDE.md | tail -1` (atteso §31). Questa, essendo la prima feature implementata, sarà la **§32** (il documento HFD usa "§32" come etichetta provvisoria: andrà rinumerato dopo).

---

## 0. PRE-FLIGHT OBBLIGATORIO (sola lettura, prima di toccare codice)

1. `phd2_agent/controller.py` — la catena **CASO 1/2/3** (CASO 1 "seeing degradato" rms>rms_high → MinMove SU + aggr giù, L903-945; CASO 2 oscillazione L947-968; CASO 3 "guida ottima" rms<rms_low → aggr su + MinMove GIÙ, L970-1029). Nota: `if self._engine_owns_levers(): return []` (L900) → in **jitter** la catena CASO è SOSPESA.
2. `phd2_agent/controller.py` — il satisfaction gate §30 dentro CASO 3 (L975-994): usa `self._rms_baseline_value` (mediana baseline) e `self.cfg.lever_optimization.target_factor`. **Riusa questa mediana come àncora del recupero** (vedi §2).
3. `phd2_agent/config.py` — `[limits.*]` (`minmove_min=0.15`, `minmove_max=0.85`, `minmove_step=0.05`, cooldown via `[control]`), `[lever_optimization]`.
4. `phd2_agent/analyzer.py` — definizione della condition `DEGRADED_SEEING` (per confermare il punto sotto).

**Fatto verificato sui log (NON ridiscuterlo, costruiscici sopra):**
- Su **entrambe** le notti, `DEGRADED_SEEING` coincide con `rms > rms_high` (003714: 19/19 sopra soglia; 222057: 482/482). **Quindi NON è un segnale di banda morta** — non usarlo per il recupero.
- Nel log guardian 003714: **745/1253 frame (59%) stanno nella banda morta** (`rms_low < rms < rms_high`), quasi tutti con condition NOMINAL → nessun CASO scatta → MinMove resta fermo.
- **Asimmetria di opportunità ~35:1**: `consec_low>=5` raggiunto in **663** frame (CASO 3 può scendere) vs `consec_high>=5` in **19** (CASO 1 può salire). MinMove scende di continuo e recupera quasi mai.

## 1. OBIETTIVO

Far sì che le leve **recuperino verso la prestazione (RMS vs baseline) quando l'RMS risale nella banda morta**, invece di restare bloccate all'estremo reattivo (MinMove al floor / Aggression alta) finché non si tocca `rms > rms_high` (evento raro). Senza abbassare il floor `0.15`, senza toccare §31/§32. **Quali leve** (solo MinMove vs MinMove+Aggression coordinate) è una decisione di Code — vedi §2.

## 2. SPECIFICA FUNZIONALE (cosa implementare)

Aggiungere, nella catena CASO della v2.3 (attiva a **motore OFF e GUARDIAN**; in jitter resta sospesa — vedi §5), un **ramo di recupero MinMove** simmetrico, ancorato alla mediana baseline:

- **Trigger di recupero:** quando `rms > recovery_threshold` per `consecutive_frames` frame, con `recovery_threshold = self._rms_baseline_value × recovery_factor` (riusa la mediana baseline del §30; `recovery_factor` default **1.0** = "sopra la mediana inizia a recuperare"). Il recupero agisce **nella banda morta** (sotto `rms_high`, dove oggi non scatta nulla) e si ferma naturalmente sopra, dove subentra CASO 1.
- **Azione:** `new_mm = min(minmove_max, old_mm + minmove_step)` — un gradino verso l'alto (più morbido). **NESSUN tetto al MinMove iniziale di sessione** (vedi nota di principio sotto): il recupero prosegue, gradino dopo gradino, finché l'RMS non rientra nel corridoio baseline; l'unico limite superiore è `minmove_max`. Il floor `minmove_min=0.15` resta il limite inferiore e **non si tocca**.
- **Condizione di STOP del recupero (performance-based, non lever-based):** il recupero continua finché `rms > mediana × corridor_factor` e si arresta quando l'RMS rientra nel corridoio (idealmente **≤ mediana**, leggermente sotto). Il riferimento è la **qualità della guida (RMS vs baseline)**, NON un valore di leva.

> **Nota di principio (richiesta esplicita di Alessandro):** l'obiettivo non è riportare le leve a un valore storico/neutro, ma riportare l'**RMS** nel regime di qualità della baseline. Il MinMove iniziale è un riferimento storico, non un tetto. Quindi: niente `neutral_cap` ancorato al valore iniziale.

> ⚠️ **Freno necessario — controllabilità + anti-windup.** L'RMS sopra la mediana è solo **in parte** correggibile dalle leve: ammorbidire cura il *seeing-chasing* (loop che insegue l'atmosfera), NON l'RMS atmosferico in sé. Se il cielo è genuinamente peggiorato, l'RMS resterà sopra la mediana **qualunque** sia il MinMove → un loop puro-RMS spingerebbe MinMove fino a `minmove_max` inseguendo un target irraggiungibile (proprio l'inseguimento che vogliamo evitare, in forma lenta). **Soluzione anti-windup, ancora puro-RMS:** continuare ad alzare MinMove **solo finché l'azione sta effettivamente riducendo l'RMS**. Se dopo K recuperi consecutivi l'RMS non scende (entro una tolleranza), **fermarsi**: quell'RMS è atmosferico, non lever-fixable. Questo dà uno stop "naturale" senza bisogno del jitter. (Lo stop *principiale* basato sul regime — sapere a priori quando ulteriore softening non aiuta — richiede il segnale jitter ed è il design completo, accoppiato a §32: fuori scope qui.)
- **Cooldown:** riusa `minmove_cooldown` (anti-pompaggio). Il recupero NON deve poter oscillare con CASO 3: garantisci che recupero (su) e CASO 3 (giù) non si alternino ad ogni tick — usa la mediana come isteresi (giù solo se `rms < rms_low`, su solo se `rms > mediana`: tra i due, fermo).
- **DECISIONE DI CODE — quante leve.** Valuta sul codice e sui log storici se il recupero verso la prestazione debba applicarsi:
  - **(a) solo MinMove** — conservativo, blast-radius minimo; oppure
  - **(b) MinMove + Aggression coordinate** — raccomandato se codice/replay reggono.
  **Analisi a supporto di (b), da verificare:** l'Aggression ha lo **specchio** dell'asimmetria di MinMove. CASO 3 la alza piano (`aggr_step_up=2`); per scenderla servono CASO 1 (`rms>rms_high`) o CASO 2 (oscillazione), gli **stessi trigger rari** → nella banda morta l'Aggression **resta alta** come MinMove resta al floor. Quindi la correzione naturale è coordinata: in banda morta, quando `rms > mediana`, **MinMove ↑ e Aggression ↓** insieme. È esperienza di campo dell'utente (Aggression che resta elevata una volta su), confermata dalla struttura del codice.
- **Se scegli (b):** il recupero Aggression-DOWN **rispetta** la filosofia esistente (`down=5` rapido / `up=2` lento): aggiunge solo il softening nella banda morta, NON tocca la lentezza di risalita. ⚠️ **Caveat di coordinamento:** muovere entrambe verso soft insieme può ammorbidire troppo in fretta o creare interazione/doppio-conteggio — gestiscilo (es. una leva per tick, o pesi, o priorità), con **anti-windup su entrambe**. Replica i test 1-2 e il replay anche per l'Aggression.
- **Inquadramento (per entrambe le scelte):** il recupero è il **complemento speculare del satisfaction-gate §30**, sulla stessa àncora (mediana baseline): §30 = "se `rms ≤ mediana` non spingere verso la reattività"; recupero = "se `rms > mediana` persistente, spingi verso la morbidezza". Un controllore simmetrico attorno alla baseline.

### Config nuove (`[lever_optimization]` o nuova sezione), default retrocompatibili
```
minmove_recovery_enabled = true     # kill-switch. Vedi nota sul default sotto.
minmove_recovery_factor  = 1.0      # corridoio: recupera finché rms > mediana × questo
recovery_no_progress_k   = 3        # anti-windup: dopo K recuperi senza calo RMS, ferma
# NIENTE neutral_cap: limite superiore solo minmove_max; lo stop è il rientro nel corridoio RMS
```
**Default del kill-switch: `true` — DECISIONE DI ALESSANDRO, non discrezionale.** Motivazione (da riportare in NOTE_CLAUDE): questo NON è una feature sperimentale come il §32, ma la **correzione di un comportamento base** osservato sul campo fin dalla **v2.2**, presente in 2.2/2.3/2.4, confermato dal **codice** e dai **log**, e quantificato (663 opportunità di scendere vs 19 di risalire). Una correzione di un bug strutturale non si nasconde dietro un opt-in. Inoltre, **se il fix è corretto migliora simultaneamente OFF, GUARDIAN e tutte le versioni future**: è una correzione del controller base, non un'aggiunta. Quindi: `enabled = true` di default, **kill-switch sempre presente nel TOML** (rollback immediato al comportamento precedente), **a OFF identico bit-per-bit all'attuale**. Vincolo di rilascio: il default-on entra in campo **solo dopo** il replay obbligatorio sui log storici (sotto) e la validazione beta — non prima.

## 3. REGOLE INDEROGABILI

- **Isolamento:** tocca SOLO la catena CASO in `controller.py` + config + test. NON toccare §31 (`diagnostic_engine.py`), §32, esposizione dinamica, backlash, Guardian/Jitter review.
- **Floor invariato:** `minmove_min` resta `0.15`. Il fix alza MinMove, non abbassa il floor.
- **Aggression:** se Code sceglie (a) MinMove-solo → invariata; se sceglie (b) coordinata → solo softening (DOWN) nella banda morta, preservando `aggr_step_down=5/aggr_step_up=2` (la lentezza di risalita NON si tocca).
- **Retrocompatibilità:** switch OFF ⇒ identico all'attuale; i test esistenti restano verdi.
- **Anti-pompaggio:** cooldown + isteresi sulla mediana, dimostrati nei test.

## 4. TEST ATTESI (obbligatori)

`tests/test_*` (unitari):
1. **Recupero in banda morta:** mediana nota, `rms > mediana` per N frame nella banda morta ⇒ MinMove **sale** di `minmove_step` (rispettando cooldown), **proseguendo oltre il valore iniziale** finché `rms > mediana`, limite solo `minmove_max`.
   1b. **Anti-windup:** se dopo `recovery_no_progress_k` recuperi l'RMS non cala ⇒ il recupero **si ferma** (RMS atmosferico), MinMove non corre fino a `minmove_max`.
2. **Niente pompaggio:** alternanza rms sopra/sotto mediana entro cooldown ⇒ **nessuna** oscillazione su/giù; isteresi rispettata.
3. **CASO 3 invariato:** `rms < rms_low` ⇒ MinMove scende come prima.
4. **CASO 1 invariato:** `rms > rms_high` ⇒ comportamento attuale.
5. **Switch OFF = bit-identico:** con `minmove_recovery_enabled=false`, nessuna differenza dai casi attuali.
6. **Floor:** il recupero non scende mai sotto 0.15 (e non è quello il punto: parte da 0.15 e sale).

**Replay offline (obbligatorio, prima del campo):** script che rigioca `session_20260611_003714.csv` (GUARDIAN) e mostra **quante volte MinMove sarebbe risalito** nei 745 frame di banda morta con il fix attivo, vs zero oggi. Allega il conteggio al report.

## 5. VALIDAZIONE SUL CAMPO + nota di modalità

- **Questo fix agisce in modalità OFF e GUARDIAN** (dove gira la catena CASO). In **JITTER** la catena è sospesa: lì il recupero MinMove dipende dal §31 (ramo NOMINAL monodirezionale, legato a §32) ed è **fuori dallo scope** di questo fix. → Per beneficiarne subito, Alessandro userà **GUARDIAN** (che è anche la modalità raccomandata/distribuibile).
- In campo: avviare in guardian, osservare in dashboard/log che MinMove **risale** quando l'RMS sale nella banda morta e **non resta incollato** a 0.15.

## 6. PROCEDURA REBUILD + DOC (è un'implementazione vera)
- `python build_dist.py` → `Pacchetto_Distribuzione/` + `Adaptive_Agent_PHD2_v<ver>.zip` (ricordare `pip install pyinstaller` se assente nel venv).
- `NOTE_CLAUDE.md`: nuova sezione **§32** (verifica numero) "Recupero MinMove nella banda morta (asimmetria leve §4)". `CONTESTO_PROGETTO.md`: paragrafo di stato.
- **Non** rinumerare/implementare gli altri item (HFD sampling-aware, congelamento): restano su carta.

## 7. CHECKLIST FINALE
- [ ] Ramo recupero MinMove in CASO (controller.py), solo MinMove, ancorato alla mediana, con cooldown+isteresi.
- [ ] Config `minmove_recovery_*` con kill-switch; default deciso e motivato; OFF = bit-identico.
- [ ] Floor 0.15 invariato; scelta leve (a/b) decisa e motivata sul codice/replay; se (b), soften-fast/harden-slow dell'aggression preservato + anti-windup su entrambe.
- [ ] Kill-switch `enabled = true` di default; a OFF bit-identico; rilascio in campo solo dopo replay + beta.
- [ ] 6 test unitari + replay su 003714 (conteggio recuperi).
- [ ] Nessun tocco a §31/§32/esposizione/backlash.
- [ ] Rebuild + ZIP; NOTE_CLAUDE §32 + CONTESTO aggiornati.
- [ ] Report finale: cosa cambiato, risultato replay, come testare in guardian.
