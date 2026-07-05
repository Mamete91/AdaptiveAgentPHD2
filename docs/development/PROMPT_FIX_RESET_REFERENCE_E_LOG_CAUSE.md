# PROMPT per Claude Code — §39: il riferimento di calma SOPRAVVIVE al dither + logging delle cause di reset

> **Questo è il "passo 2 di 2" del motore operativo.** Il §38 fa *riformare più in fretta* `jitter_ref`/`hfd_ref`, ma la causa profonda è che `reset()` **azzera i riferimenti a ogni dither/settle**, e il dithering avviene ogni pochi minuti → il motore passa la vita a ricostruire un riferimento che gli viene continuamente cancellato. Un dither **non cambia l'atmosfera**: azzerare lì il riferimento di "jitter di calma" è sbagliato (stessa lezione del §36 sull'invalidazione della baseline solo a vero cambio di regime).
> **Due interventi in uno:** (A) **disciplina di reset** — i riferimenti si azzerano SOLO su cambio esposizione / cambio target / cambio pixel-scale, NON su dither/settle; (B) **logging delle cause di reset nel CSV** — oggi i reset NON sono nei log, ed è per questo che il §38 non è validabile su replay. Con le cause loggate, ogni replay futuro diventa fedele.
> **Due fasi:** (1) **FAR QUADRARE** — confermare nel codice i punti di reset e le loro cause, e dimostrare (test/replay) il churn attuale; (2) implementare. Se qualcosa non torna, dillo con dati.
> **AUTORIZZATO A IMPLEMENTARE** dopo la conferma. Isolato a: punti di chiamata `reset()` + `diagnostic_engine.reset()` + logger (nuova colonna CSV). NON toccare: la formazione best-fraction (§38), le condizioni SEEING/OVER/DRIFT (§37), NOMINAL/satisfaction-gate, le leve, la baseline RMS, il backlash. NON cambiare il reset dell'**analyzer** (la finestra RMS DEVE resettarsi al dither: le posizioni saltano).
> **Direttiva:** nuove chiavi **attive (`true`) nel `config.toml`** (born operative); kill-switch per A/B.
> **Numerazione doc:** `grep "^## [0-9]" NOTE_CLAUDE.md | tail -1` → atteso §38 → usa **§39**.
> Contesto: `PRINCIPIO_CONVERGENZA_PRESTAZIONE.md` (P1), memoria del §36 (disciplina di invalidazione: invalidare solo a vero cambio di regime).

## 0. FASE 1 — FAR QUADRARE (sola lettura, confermare prima di toccare)

**Punti di reset da confermare** (Cowork li ha già individuati — verificarli e classificarli):
- `diagnostic_engine.reset()` (~`diagnostic_engine.py:164-167`) azzera `_jitter_ref`, `_hfd_ref` **e le finestre §38**.
- Chiamato da:
  - `main.py:336-338` — **re-start guida** (StartGuiding / AppState→Guiding)
  - `main.py:369-371` — **dopo dither**
  - `main.py:398-400` — **dopo dither** (secondo percorso)
  - `controller.py:1646` — **transizione di modalità** (leve→baseline)
  - `controller.py:1727 / 1748 / 1819 / 1862` — **cambio esposizione** (Path B su/giù)

**Classificazione richiesta a Code** (causa → comportamento atteso):
| Causa | Cambia il regime del jitter? | Azione sui riferimenti |
|---|---|---|
| cambio esposizione | **Sì** (il jitter scala col tempo di posa: 2s media più di 1s) | **AZZERA** (wipe) |
| cambio pixel-scale | Sì | **AZZERA** |
| cambio target / re-start guida post-slew | Sì (campo/altezza/seeing nuovi) | **AZZERA** (default prudente) |
| **dither / settle** | **No** (sposta la stella, non l'atmosfera) | **PRESERVA** (refs + finestre §38) |
| transizione di modalità (leve→baseline) | No | **PRESERVA** (salvo Code rilevi il contrario) |

**Dimostrare il churn attuale (test o replay sintetico):** con reset a cadenza dither (~ogni pochi minuti), oggi `refs_ready` crolla ripetutamente (il legacy reale era 11,8%); preservando i riferimenti sul dither, `refs_ready` resterebbe alto **a qualunque cadenza di dither**. Riportare il **verdetto** con numeri.

## 1. OBIETTIVO (Fase 2)
(A) I riferimenti di calma `jitter_ref`/`hfd_ref` (+ finestre §38) **sopravvivono a dither/settle** e si azzerano solo su cambio esposizione / target / pixel-scale → si formano una volta e **persistono**, eliminando la fragilità "warmup vs cadenza dither" del §38. (B) Ogni reset del motore è **loggato nel CSV con la causa**, così i replay futuri riproducono la realtà e il fix è validabile sui log.

## 2. SPECIFICA
### 2A — Disciplina di reset
1. Passare a `diagnostic_engine.reset()` una **causa** (enum/stringa: `exposure_change` / `pixel_scale_change` / `target_change` / `guiding_restart` / `dither` / `settle` / `mode_transition`).
2. Il reset **azzera i riferimenti** SOLO per le cause che cambiano il regime (`exposure_change`, `pixel_scale_change`, `target_change`, `guiding_restart`). Per `dither`/`settle` (e `mode_transition`) **preserva** `_jitter_ref`/`_hfd_ref` e le finestre §38.
3. **NON modificare `analyzer.reset()`**: la finestra RMS/jitter dell'analyzer continua a resettarsi al dither (le posizioni saltano). Garantire che il transiente post-dither dell'analyzer **non avveleni** la finestra best-fraction del motore (ingerire nel motore solo campioni jitter validi, `jitter_n` sufficiente; il best-fraction è comunque robusto ai picchi).
4. Mappare ciascun punto di chiamata esistente alla causa corretta.

### 2B — Logging delle cause di reset
1. Aggiungere al CSV di sessione una colonna **`reset_cause`** (vuota nei frame senza reset; valorizzata con la causa nel frame in cui avviene il reset del motore). Così un replay che legge il CSV conosce *quando e perché* i riferimenti sono stati azzerati.
2. **`schema_version`** del CSV bumpato (Code conferma il valore corrente, atteso 3 → 4).
3. (Se utile) registrare anche nel log decisioni/eventi un record per reset con la causa.

## 3. REGOLE
- Isolato a: punti di chiamata reset + `diagnostic_engine.reset(cause)` + logger (colonna). NON toccare §38-formazione, §37-condizioni, NOMINAL/satisfaction, leve, baseline RMS, backlash, `analyzer.reset()`.
- Kill-switch **shipped sul nuovo comportamento**: es. `[diagnostic_engine] preserve_refs_on_dither = true` (true = preserva = nuovo; false = vecchio comportamento, azzera sempre). Scritto e attivo nel `config.toml`.
- Retrocompatibilità: con `preserve_refs_on_dither = false` comportamento identico al pre-§39.

## 4. TEST ATTESI (Code DEVE validare la correttezza)
1. **Reset selettivo:** `reset('dither')` PRESERVA `_jitter_ref`/finestre; `reset('exposure_change')` le AZZERA. Idem `settle` (preserva) vs `pixel_scale_change`/`target_change` (azzera).
2. **Persistenza sotto dither ripetuti:** sequenza con dither ogni N frame (N < warmup e N > warmup) → `refs_ready` resta vero (non più churn). Confronto col legacy (`preserve_refs_on_dither=false`) che crolla.
3. **Niente avvelenamento:** dopo un dither il transiente di jitter dell'analyzer non degrada `jitter_ref` (best-fraction stabile).
4. **Logging:** la colonna `reset_cause` è valorizzata col valore giusto sui frame di reset, vuota altrove; `schema_version` bumpato.
5. **Isolamento + regressione:** §37/§38/NOMINAL/satisfaction invariati; `preserve_refs_on_dither=false` riproduce il pre-§39; suite esistente verde.
6. **Replay reale `session_20260615_211617`** (`C:\Users\aless\OneDrive\Desktop\IMMAGINI\LOG PER AGENTE ADATTIVO\LOG RC8 CEM70\2026-06-16\logs\session_20260615_211617.csv`): NOTA onesta — quel CSV è **pre-§39 e NON contiene `reset_cause`**, quindi NON può validare appieno il §39 (i reset reali da dither non sono nei log). Code lo dichiari esplicitamente: la validazione piena del §39 arriva dal **prossimo run di campo** con `reset_cause` loggato. Sul vecchio log si può solo mostrare il churn legacy come baseline di confronto.

## 5. REBUILD + DOC
`python build_dist.py` → ZIP. `NOTE_CLAUDE.md` **§39** ("riferimenti di calma sopravvivono a dither/settle (reset solo a cambio esposizione/target/pixel-scale); logging `reset_cause` nel CSV; schema→4; completa il §38 → motore operativo passo 2/2") + `CONTESTO_PROGETTO.md`. `config.toml` con le nuove chiavi **attive**. Niente commit/push (lo farà il prompt git, che committerà §37+§38+§39 insieme).

## 6. CHECKLIST
- [ ] Fase 1: verdetto CONFERMATA con classificazione delle cause + churn dimostrato + citazioni `file:riga`.
- [ ] `reset(cause)`: riferimenti preservati su dither/settle, azzerati su esposizione/target/pixel-scale; ogni call-site mappato.
- [ ] `analyzer.reset()` invariato; nessun avvelenamento del best-fraction post-dither.
- [ ] Colonna CSV `reset_cause` + `schema_version` bumpato.
- [ ] Kill-switch `preserve_refs_on_dither=true` shipped; `=false` = vecchio comportamento (testato).
- [ ] Test 1-6; suite esistente verde; nota onesta sul limite del replay sul log pre-§39.
- [ ] NOTE §39 + CONTESTO aggiornati; ZIP ribuildato (§32→§39).

> **P1 / coerenza §36:** un riferimento si invalida solo quando cambia davvero il regime che descrive. La baseline RMS si invalida solo al cambio pixel-scale (§36); allo stesso modo il riferimento di calma del jitter deve sopravvivere a un dither (che non tocca l'atmosfera) e azzerarsi solo quando il jitter cambia scala (esposizione) o cambia il cielo (target/pixel-scale). §38 forma in fretta, §39 evita di dover riformare di continuo: insieme rendono il motore davvero operativo.
