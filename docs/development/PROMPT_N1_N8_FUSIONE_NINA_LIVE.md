# PROMPT per Claude Code — N1 (Transparency Index) + N8 (Confidence fusion) — OPERATIVI e VISIBILI in LIVE

> **Metodologia (regola di progetto, `METODOLOGIA_VALIDAZIONE_LIVE.md`):** queste logiche toccano il motore → si rilasciano **direttamente operative** e si validano **in diretta sul cielo**, NON in shadow/log-only. Obbligatorie le 5 condizioni: visibilità real-time, tracciamento dei segnali PHD2+NINA che determinano la decisione, verificabilità a vista, reversibilità immediata (kill-switch), ampiezza GUARDIAN piccola/fail-safe.
> **Nessun lavoro plugin qui:** N1/N8 usano i dati GIÀ in arrivo (§42: `star_count`, `mean/median/stdev_adu`, `filter`). L'eccentricità (N4) è un altro prompt.
> **Riscontro col codice (verificato):** il motore (`diagnostic_engine.py`) ha già un `confidence` che gatea le azioni (`≥ guardian_min_confidence`), ma calcolato **solo da segnali PHD2**; `confidence_calibrated` è **hard-coded False e inutilizzato = il gancio per N8**. Lo store §41/§42 è esposto su `/status` ma **nessun consumatore lo legge**. → N8 = primo consumatore.
> **Numerazione:** `grep "^## [0-9]" NOTE_CLAUDE.md | tail -1` → usa **§45** (N1) e **§46** (N8). Verifica.
> **Sequenza (una modifica-motore per volta):** consigliato consolidare §43/§44 (baseline bidirezionale) in **una** sessione live prima di attivare N8. N1 (solo segnale) si può attivare subito. Vedi nota finale.
> Contesto: `VALIDAZIONE_CAMPO_v2.6.md`, `RIFLESSIONI_ROADMAP_NINA_POST_STEP0.md`, `PRINCIPIO_CONVERGENZA_PRESTAZIONE.md` (P1), architettura 3-layer (Telemetria→Indici→Consumatori).

---

## §45 — N1: Transparency Index  [Agente, Layer-2 + dashboard]

**Obiettivo:** un segnale di trasparenza **ortogonale a PHD2**, dalla camera di ripresa, calcolato in continuo e **visibile in diretta**. PHD2 vede solo la stella di guida e non distingue seeing da velature; NINA vede centinaia di stelle.

**Calcolo (nuovo modulo `phd2_agent/nina_indices.py`, Layer-2 — NON sporcare lo store Layer-1):**
1. Input dallo store §42: `star_count`, `median_adu` (fondo cielo), `mean_adu`/`stdev_adu`, `filter`.
2. **Baseline SEMPRE RELATIVA al campo+filtro CORRENTE — MAI soglie assolute** (critica di GPT, condivisa). Il `star_count` assoluto non dice nulla: campo ricco (NGC 7000 ~150 stelle) vs campo povero (NGC 5907 ~60) non sono confrontabili. Quindi: riferimento "cielo più limpido recente **per QUESTO target e QUESTO filtro**" (rolling-high/best-fraction su finestra mobile). Il `filter` è nel payload; il **target** oggi non lo è (`context` arriva con N2) → finché manca, rilevare il cambio target da un **salto di regime** del `star_count` e ri-formare il riferimento. **Nota onesta:** la baseline trasparenza diventa davvero robusta con N2 (target esplicito); in v1 è per-filtro + adattiva al regime. Nessun numero assoluto entra in alcuna decisione.
3. **TransparencyIndex = misura RELATIVA + privilegia il TREND** (ragionamento da astrofilo: le nubi/velature si vedono come **calo % improvviso** del conteggio stelle su pochi frame; un campo povero è un livello **basso ma stabile**). Quindi l'indice pesa soprattutto il **rapporto vs riferimento del campo** e la sua **derivata** (caduta rapida = trasparenza), non il valore assoluto. Forma: `TI = clamp( (star_count/base_stars_campo) × (base_bkg/bkg), 0..1 )` con enfasi sulla variazione relativa recente. **NIENTE HFR** (domini separati). Fondo cielo che sale = segnale di supporto (occhio: sale anche con Luna/IL/quota → secondario; il conteggio stelle resta il primario).
4. **Stato** con isteresi: `CLEAR` (>~0.8) / `HAZE` (~0.5–0.8) / `CLOUD` (<~0.5) — soglie nel config, da tarare in campo.
5. Cadenza per-posa (aggiorna all'arrivo di ogni payload NINA); tra le pose mantiene l'ultimo. Graceful: nessuna telemetria → TI non disponibile (None), tutto il resto invariato.

**Visibilità (obbligatoria):**
- `/status`: blocco `nina.transparency` = `{index, state, base_stars, star_count, bkg, filter}`.
- **Dashboard:** nuova card "Trasparenza (NINA)" accanto a "Condizioni" — indice + stato CLEAR/HAZE/CLOUD + (stelle: corrente/base). Aggiornata in tempo reale.
- Logging: colonne `transparency_index`, `transparency_state` nel CSV di sessione (schema_version+1).

**Config `[nina_indices]`:** `enabled=true` (operativo); soglie `clear_above=0.8`, `cloud_below=0.5`, isteresi, `baseline_window_subs`. Kill-switch `enabled=false`.

**Test:** **calo % relativo rapido** del star_count vs riferimento del campo (es. −50% in pochi frame, stesso filtro/target) → TI scende → HAZE/CLOUD; livello **basso ma stabile** (campo povero) → resta CLEAR (NON deve scattare: è il test anti-soglia-assoluta); cambio filtro/target → riferimento si ri-forma; nessuna telemetria → graceful. Suite verde.

---

## §46 — N8: Confidence fusion nel motore  [diagnostic_engine.py — OPERATIVO + VISIBILE + reversibile · PENALITÀ PROPORZIONALE all'evidenza]

**Obiettivo:** dare al motore il secondo occhio per la disambiguazione **SEEING vs trasparenza**. NINA **non comanda le leve**: **modula** la fiducia del motore nella diagnosi di SEEING con una **penalità proporzionale alla forza del calo di trasparenza** (trascurabile sul rumore, decisa su un crollo reale), **tarabile** sul campo.

**Logica — MODULAZIONE GRADUALE e PROPORZIONALE all'evidenza (NON freeze binario, ma nemmeno penalità sempre debole):**
1. Il motore riceve il TransparencyIndex via provider. NINA fresca → `confidence_calibrated = True`.
2. **Modulazione SOLO sulla diagnosi SEEING** (ragionamento fisico: la trasparenza confonde solo il SEEING — entrambi atmosferici, entrambi alzano l'RMS. **OVERCORRECTION** (oscillazione, lag-1), **DRIFT** (deriva/trend) e qualunque firma **meccanica/backlash** NON sono confondibili con le nubi → NINA **non li tocca mai**). Quando il motore diagnostica SEEING e la trasparenza è in calo: `confidence_finale = confidence_phd2 − penalità(deficit_trasparenza)`.
3. **La penalità è PROPORZIONALE alla forza del segnale osservato** (richiesta di Alessandro, condivisa) — funzione monotòna del **calo % vs il riferimento del campo** (N1), con **dead-band per il rumore** e crescita progressiva:
   - perdita **lieve** (es. 150→140, ~−7%, dentro la fluttuazione) → penalità **trascurabile** (dead-band: non reagire al rumore frame-to-frame);
   - perdita **moderata** (es. 150→110, ~−27%) → penalità **significativa**;
   - perdita **forte** (es. 150→80, ~−47%) → penalità **forte** (è successo qualcosa di reale sul cielo: velature/nube/foschia/condensa).
   Curva e pendenza **tarabili** (`nina_confidence_curve`/`weight`), così il peso di NINA cresce **coerentemente con l'evidenza**. La fiducia **non va a zero per un velo lieve**, ma **scende decisamente per un crollo netto**. NINA **non aumenta mai** aggressività né confidence; nel dubbio → no-op.
4. **PERSISTENZA su ≥2-3 sotto-pose consecutive (richiesta Alessandro, importante):** una penalità significativa scatta **solo se il calo di trasparenza è confermato su almeno 2-3 pose consecutive**. Una **singola posa anomala** (satellite, raffica, bordo nube transitorio in un angolo del frame, frame con meno stelle rilevate per un istante) **NON** deve generare penalità. Il segnale che guida N8 è il **trend**, non il singolo frame. (Con pose 120–300 s, 2-3 pose = la scala temporale giusta per una vera variazione di trasparenza, che dura minuti.)
5. **CHIARIMENTO IMPLEMENTATIVO — cosa tocca N8 (risposta esplicita):** la penalità abbassa **SOLO `confidence`**; `confidence` è una **SOGLIA** (`≥ guardian_min_confidence`) → l'effetto è **binario al gate** (agisci / astieniti), **NON scala l'ampiezza** di Aggressività/MinMove (governata da `guardian_action_factor`, che NINA NON tocca). Impatto sulle leve in v1 = *"a volte una micro-correzione in meno"*, mai correzioni più grandi o più piccole. L'accoppiamento confidence→ampiezza è un'eventuale evoluzione futura (N8 v2), **NON in v1**.
6. **Perché è comunque sicuro anche con penalità forte:** l'unico effetto è far **astenere** il motore dall'ammorbidire le leve sul SEEING (direzione sicura: non si "cura" una nube con MinMove, e con un crollo netto PHD2 perderà presto la stella comunque). L'ampiezza di qualunque azione resta GUARDIAN-piccola/fail-safe.
7. **Graceful:** telemetria assente/stantia → `confidence_calibrated=False`, confidence PHD2-only = oggi.

**Perché NON il freeze binario (scenario GPT) ma nemmeno troppo debole (precisazione Alessandro):** velo sottile (−7%) con RMS che sale per seeing vero → penalità piccola → il motore agisce; crollo netto (−40/50%) → penalità forte → il motore si astiene (è una nube). La penalità **segue la fisica osservata**, non una soglia fissa né un cap arbitrario piccolo.

**Visibilità (il cuore della validazione live — obbligatoria), numeri SEMPRE RELATIVI:**
- `evidence` con la modulazione esplicita. Es.: `✓ RMS sopra soglia · ✓ jitter sopra riferimento → SEEING (confidence PHD2 80) · ◦ trasparenza in calo (−18% vs riferimento campo) → confidence 80→68`. (mai numeri assoluti di stelle)
- **Dashboard** ("Seeing Diagnostic Engine"): **decomposizione del confidence** = parte PHD2 + contributo NINA + stato trasparenza che ha pesato.
- **Grafico di guida:** marcatore quando NINA ha **modulato** una decisione.
- Logging: `confidence_phd2`, `nina_penalty`, `confidence_final`, `transparency_index` sul frame della decisione.

**Config `[diagnostic_engine]`:** `confidence_use_nina = true` (born-operative); **curva penalità tarabile** (`nina_confidence_*`: dead-band sul rumore + pendenza progressiva proporzionale al calo %); `false` = confidence PHD2-only (pre-N8).

**Test (Code DEVE validare):**
1. **Penalità proporzionale (richiesta Alessandro):** calo lieve (~−7%, dentro la dead-band) → penalità **trascurabile**; moderato (~−27%) → **significativa**; forte (~−47%) → **forte**. Monotòna e tarabile.
2. **Seeing vero + velo lieve (scenario GPT):** RMS↑+jitter↑ + calo lieve → confidence scende **di poco** → il motore **PUÒ ancora agire** (niente soppressione erronea).
3. **Crollo trasparenza + SEEING:** penalità forte → confidence sotto soglia → il motore si **astiene** (probabile nube).
4. **OVERCORRECTION/DRIFT/meccanica:** confidence **NON** modulata da NINA — verificato.
5. **Graceful / reversibile:** nessuna telemetria o `confidence_use_nina=false` → identico al pre-§46.
6. **Fail-safe:** NINA non aumenta mai aggressività; effetto solo in direzione "astieniti". Suite verde.

---

## REGOLE / CHIUSURA
- **NON toccare:** backlash, baseline §33/§40/§44, cap §24, telemetria §41/§42 (Layer-1), gate rifiuto §23.
- Born-operative + 5 condizioni metodologia: visibile in tempo reale, segnali tracciati, reversibile (kill-switch), GUARDIAN-piccolo, fail-safe.
- **REBUILD obbligatorio** (per validare in campo): `python build_dist.py` → verifica che il `config.toml` nel pacchetto abbia `[nina_indices] enabled=true` e `[diagnostic_engine] confidence_use_nina=true`; ZIP rigenerato; data exe fresca. (Lezione: l'ultima volta il pacchetto non era stato ricostruito.)
- **DOC:** `NOTE_CLAUDE.md` §45 (N1) + §46 (N8) + `CONTESTO_PROGETTO.md`; `VALIDAZIONE_CAMPO_v2.6.md` (predisporre la sessione di validazione live). **Niente commit/push.**

## CHECKLIST
- [ ] §45 N1: `nina_indices.py` (Layer-2, store intatto); baseline trasparenza per-filtro; TI = stelle+fondo (NO HFR); stato CLEAR/HAZE/CLOUD con isteresi; `/status.nina.transparency` + **card dashboard live** + log; graceful; kill-switch; test verdi.
- [ ] §46 N8: confidence fusa con TI tramite **penalità PROPORZIONALE al calo % (dead-band→lieve→forte)**, **solo sulla diagnosi SEEING** (mai DRIFT/OVERCORRECTION/meccanica), effetto solo "astieniti" (mai più aggressività); `confidence_calibrated=True` con NINA fresca; **evidence + decomposizione confidence + marcatore grafico** in live; graceful PHD2-only senza NINA; kill-switch `confidence_use_nina`; fail-safe; test verdi.
- [ ] REBUILD pacchetto + config nel pacchetto con le nuove chiavi attive; ZIP fresco.
- [ ] Nessuna regressione §24/§31/§33/§40/§41/§42/§43/§44; doc §45+§46; niente commit.

> **P1 + metodologia live:** PHD2 sa come si muove la stella; NINA sa come vengono le immagini. N8 è "non inseguire con le leve un degrado che potrebbe non essere lever-fixable (nubi)". In v1 lo fa **con mano leggera**: quando arrivano le velature e le stelle calano, il motore ti mostra — dashboard + grafico — che la confidence nel SEEING **scende dolcemente** (es. 80→68), con il contributo NINA esplicito. Tu **osservi sul campo quanto pesa davvero la trasparenza** prima di decidere se rafforzare l'effetto. Niente hard-freeze finché i dati reali non lo giustificano.
