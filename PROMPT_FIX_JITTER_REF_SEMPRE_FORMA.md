# PROMPT per Claude Code — §38: jitter_ref / hfd_ref che si formano SEMPRE (motore finalmente operativo)

> **Compito in due fasi: (1) FAR QUADRARE LA SCOPERTA in autonomia** (riprodurre il comportamento sui log reali + confermare il meccanismo sul codice), **(2) SE confermata, IMPLEMENTARE il fix.** Non fidarti dei numeri qui sotto: riproducili. Se qualcosa non torna, dillo con dati alla mano.
> **AUTORIZZATO A IMPLEMENTARE** dopo la conferma. Isolato alla **formazione delle reference interne del motore** (`diagnostic_engine.py`) + config. NON toccare: le condizioni SEEING/OVERCORRECTION/DRIFT (sono §37), la diagnosi NOMINAL e il satisfaction-gate, §32/§33/§34/§35/§36, le leve, la baseline RMS, il backlash.
> **Direttiva di progetto:** ogni nuova chiave nasce **già attiva (`true`) nel `config.toml`** (born operative); kill-switch per A/B ma shipped sul comportamento nuovo.
> **Numerazione doc:** `grep "^## [0-9]" NOTE_CLAUDE.md | tail -1` → atteso §37 → usa **§38**.
> Contesto: `PRINCIPIO_CONVERGENZA_PRESTAZIONE.md` (P1), `ACCERTAMENTO_BASELINE_SEMPRE.md`/`PROMPT_FIX_BASELINE_SEMPRE.md` (§33, di cui questo è il fratello "un livello più sotto").

## 0. LA SCOPERTA DA FAR QUADRARE (riprodurre, non fidarsi)

**Sintomo:** dopo §34 (freeze=logging) e §37 (HFD fuori dal gate), il motore **continua a non diagnosticare SEEING**. Il motivo non è più l'HFD: è che il **riferimento del jitter (`jitter_ref`) quasi non si forma**, e `classify()` richiede `refs_ready`.

**Meccanismo sospetto (da confermare nel codice):** in `diagnostic_engine.py` le reference EMA si aggiornano SOLO nel ramo NOMINAL stretto:
```
# ~L202-204
if snap.rms_total <= rms_low and snap.condition == SeeingCondition.NOMINAL:
    self._jitter_ref = _ema(self._jitter_ref, snap.jitter_rms, ema_alpha)
    self._hfd_ref    = _ema(self._hfd_ref,    snap.hfd_avg,    ema_alpha)
```
e `refs_ready = (_jitter_ref is not None) and (_hfd_ref is not None)` (~L157-159), usata come gate in `classify()` (~L175) e in `jitter_high` (~L218). Quindi se `rms <= rms_low` capita di rado, le reference non si formano → `refs_ready` falso → niente SEEING. **È lo stesso schema del bug baseline §33, un livello più sotto** (la reference campiona solo una condizione rara).

**Evidenza dai log reali (Cowork, replay su RC8 `session_20260615_211617`, 866 frame valutati).** Riprodurre questi numeri:
| Metrica (sui frame `evaluated==True`) | Valore trovato |
|---|---|
| `jitter_ref > 0` (cioè formata) | **solo 12%** (mediana `jitter_ref` = **0**) |
| `rms_total <= rms_low_active` (condizione che forma le ref) | **~1,5%** |
| `condition == NOMINAL` | ~55% |
| `rms_total > rms_high_active` | ~33% |
| `hfd_avg > hfd_ref*1.25` (hfd_high) | **0%** (HFD cieco, già noto) |
| SEEING (vecchio e nuovo) sui frame con ref pronte | **~0%** |

**Log reale (sul disco di Alessandro, NON nel repo perché `logs/` è in .gitignore):**
`C:\Users\aless\OneDrive\Desktop\IMMAGINI\LOG PER AGENTE ADATTIVO\LOG RC8 CEM70\2026-06-16\logs\session_20260615_211617.csv`
Colonne utili: `rms_total, jitter_rms, jitter_ref, lag1_ra, lag1_dec, rms_high_active, rms_low_active, hfd_avg, hfd_ref, evaluated, diag_state`.

**Cosa deve fare Code in FASE 1:**
1. Confermare il meccanismo nel codice (le righe sopra, il gate `refs_ready`).
2. **Riprodurre i numeri** sul CSV reale (se accessibile dal percorso sopra); altrimenti, se il log non è raggiungibile, dimostrare con un **test sintetico** che con una sequenza realistica in cui `rms` scende sotto `rms_low` solo nell'~1-2% dei frame, `jitter_ref` resta `None` quasi sempre con la logica attuale.
3. Riportare il **verdetto: CONFERMATA / PARZIALE / ERRATA** con i numeri riprodotti.

## 1. OBIETTIVO (Fase 2)
`jitter_ref` (e `hfd_ref`) devono **formarsi presto e in modo robusto** — come la baseline §33 — rappresentando il jitter/HFD della **guida calma**, anche nelle notti in cui `rms` quasi mai scende sotto `rms_low`. Così `refs_ready` diventa vero presto e il motore può finalmente diagnosticare SEEING/jitter (resta "armato e muto" finché la reference non si forma).

## 2. SPECIFICA
1. **Disaccoppiare la formazione delle reference dal gate stretto `rms<=rms_low AND NOMINAL`.** Scegliere l'approccio più coerente con §33 (Code decide dopo il pre-flight):
   - **(A) best-fraction su finestra mobile** (consigliato, specchio del §33): mantenere una finestra recente di `jitter_rms`/`hfd_avg`; la reference = statistica robusta del *best-fraction* (i frame più calmi). Si forma sempre, robusta ai frame sporchi.
   - **(B) agganciarla alla baseline §33/§34**: formare `jitter_ref`/`hfd_ref` dagli stessi frame che definiscono la baseline RMS (i "migliori" della finestra). Massima coerenza concettuale.
   - **(C) (minimale) allargare il gate** a `condition==NOMINAL` senza `rms<=rms_low`. Più semplice ma reference meno "pulita".
   Preferire A o B (robuste). In ogni caso: warmup breve (~minuti, ordine §33), poi adattamento continuo.
2. **`refs_ready` non deve più dipendere da `hfd_ref`.** Dato che §37 ha reso l'HFD **informativo**, gating la prontezza del motore su `hfd_ref` è un residuo: `refs_ready` deve basarsi **solo su `jitter_ref`**. Continuare comunque a calcolare/loggare `hfd_ref` (informativo, dashboard intatta).
3. **NON cambiare** la diagnosi NOMINAL né il satisfaction-gate (oggi annidati nello stesso ramo): isolare la *formazione reference* lasciando intatta la semantica NOMINAL/satisfaction.
4. Le condizioni SEEING/OVERCORRECTION/DRIFT restano quelle del §37 — non toccarle.

## 3. REGOLE
- Isolato a `diagnostic_engine.py` (formazione reference + `refs_ready`) + config. Nessuna modifica a §37-logica, leve, baseline RMS, satisfaction-gate.
- Kill-switch nel config, **shipped sul nuovo comportamento**: es. `[diagnostic_engine] refs_always_form = true` (true = nuovo; false = vecchia formazione stretta §31, per A/B). Eventuali parametri (finestra/best-fraction) **scritti e attivi** nel `config.toml`.
- Retrocompatibilità: con `refs_always_form = false` comportamento identico al pre-§38.

## 4. TEST ATTESI
1. **Riproduzione scoperta (Fase 1):** con sequenza in cui `rms<=rms_low` ~1-2% → con logica vecchia `jitter_ref` resta `None` quasi sempre; con la nuova si forma entro ~X frame ed è presente sulla grande maggioranza.
2. **`refs_ready` presto:** diventa vero entro pochi minuti (ordine §33), non a metà sessione.
3. **`refs_ready` non dipende più da `hfd_ref`:** con `hfd_ref` ancora None ma `jitter_ref` formata, `refs_ready` è vero.
4. **Payoff §37+§38:** su una sequenza sintetica turbolenta (rms alto + jitter alto, non oscillante) ora **SEEING scatta** (prima non poteva per ref mancante).
5. **Isolamento:** NOMINAL e satisfaction-gate invariati; `refs_always_form=false` riproduce il vecchio comportamento; i test esistenti restano verdi.
6. **Replay reale** su `session_20260615_211617` (se accessibile): `jitter_ref` presente ora sulla grande maggioranza dei frame (vs 12% pre-fix); riportare la nuova %.

## 5. REBUILD + DOC
`python build_dist.py` → ZIP. `NOTE_CLAUDE.md` **§38** ("jitter_ref/hfd_ref sempre-forma (stile §33); refs_ready scollegato da hfd_ref post-§37; motore operativo") + `CONTESTO_PROGETTO.md`. `config.toml` con le nuove chiavi **attive**. Niente commit/push (il commit di §37+§38 lo farà il prompt git dedicato, dopo).

## 6. CHECKLIST
- [ ] Fase 1: verdetto CONFERMATA/PARZIALE/ERRATA con numeri riprodotti (replay reale o test sintetico) + citazioni `file:riga`.
- [ ] `jitter_ref`/`hfd_ref` si formano presto e robusti (best-fraction/baseline-tied); warmup ~minuti.
- [ ] `refs_ready` dipende solo da `jitter_ref` (hfd_ref scollegato, ma ancora calcolato/loggato).
- [ ] NOMINAL + satisfaction-gate invariati; SEEING/OVERCORR/DRIFT (§37) non toccati.
- [ ] Kill-switch `refs_always_form=true` shipped; `=false` = vecchio comportamento.
- [ ] Test 1-6 verdi; replay `211617` ricalcolato (nuova % jitter_ref).
- [ ] NOTE §38 + CONTESTO aggiornati; ZIP ribuildato (contiene §32→§38).

> **P1:** un motore che deve riconoscere il seeing ha bisogno di un *riferimento di calma* che si formi davvero. Finché la reference si forma solo nell'~1,5% dei frame, il motore è armato ma muto. Questo fix è il fratello del §33: "il riferimento si forma sempre, dalla migliore prestazione disponibile nelle condizioni correnti".
