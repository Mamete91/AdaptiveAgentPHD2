# CONTESTO PROGETTO PHD2 Adaptive Agent — Stato per nuovo agente AI

## Chi sono
Alessandro, astrofotografo italiano (Borno, BS, montagna). Setup multi-tubo:
- RC8 + ASI2600 + OAG ASI220 Mini (focale 1624mm, lunga focale)
- Tecnosky 115/800 + ASI2600 + OAG (focale 800mm, media)
- Askar 71F + ASI2600 + OAG (focale 490mm, corta)
- Montature: AM5 (focali corte) e CEM70G (focali lunghe + planetario)

## Cos'è questo progetto
PHD2_Adaptive_Agent: un agente Python che si connette al software di guida 
PHD2 (porta TCP 4400 JSON-RPC) e regola dinamicamente i parametri di guida 
in base a seeing, vento e altri eventi. Ha una dashboard web su porta 8080.

Architettura: Python 3.12, FastAPI/uvicorn per dashboard, numpy/scipy per 
analisi statistica + saturation detection. Compilato con PyInstaller in 
eseguibile Windows.

## Storia del progetto
1. Versione 1.0 sviluppata da un amico astrofilo con l'aiuto di Claude
2. Review tecnica della v1.0 ha identificato problemi:
   - Bug runtime: import os mancante in controller.py (crash in LIVE)
   - MinMove dinamico promesso in config ma mai applicato dal codice
   - Baseline Guardian dichiarato ma non implementato
   - Saturation Timer dichiarato ma non implementato
   - Oscillazione DEC ignorata (gestita solo RA)
3. Patch v1.1 applicate (questo pacchetto):
   - Fix bug os
   - MinMove dinamico vero (con cooldown 1.5x)
   - Baseline Guardian completo (save/restore/orphan recovery/shutdown)
   - Saturation detection con timer 300s e CSV log persistente
   - Mitigazione bias centroide su stelle sature
   - Oscillazione DEC ora gestita
   - 3 config separati per i miei setup
4. Patch validate: sintassi OK, test funzionali su FITS sintetici OK,
   test integrazione controller (init/baseline/shutdown/saturation) OK

## Stato attuale — aggiornato al 2026-07-02 (§54 deprecazione modalità JITTER)

### §54 — Modalità JITTER deprecata; GUARDIAN ufficiale (fatto, 2026-07-02)
La modalità di guida **ufficiale è GUARDIAN** (con **OFF** come A/B legittimo). La modalità **JITTER** (motore §31 unica
autorità sulle leve, catena CASO 1/2/3 sospesa) è **deprecata/sperimentale e mai validata**: scavalca tutto il
controllore outcome-first (§44/§50/§51/§53/§32/§30). Era attivabile a un clic dalla dashboard → rischio di finirci per
sbaglio. Interventi: (1) **rimossa dal toggle dashboard** (restano OFF/GUARDIAN; badge graceful "JITTER (deprecato)" se un
config legacy la riporta); (2) **guard-rail backend** — nuovo flag `[diagnostic_engine] allow_experimental_jitter`
(default false): sia `set_diagnostic_mode("jitter")` sia il caricamento config ricadono su GUARDIAN con WARNING quando il
flag è off; solo il flag esplicito la abilita (per una futura validazione deliberata). Il **motore §31 e GUARDIAN restano
invariati**; il ramo jitter è dormiente ma funzionante, solo gated. 270 test verdi. Dettagli: NOTE_CLAUDE §54.

## Stato precedente — aggiornato al 2026-07-02 (§53 recupero simmetrico guidato dall'esito)

### §53 — Recupero simmetrico (banda morta bidirezionale) (fatto, 2026-07-02)
Fix di un **vuoto di progetto** nel control-law, emerso da `session_20260702_215202`: dopo una degradazione, con RMS
tornato poco sopra baseline, **l'aggressività non risaliva mai** in sessione continua (solo un crash→INIT §50 riportava
lo standard). Causa: la banda morta era un **ratchet unidirezionale verso il morbido** — il §32 *alzava* il MinMove (un
secondo softening) e l'aggr risaliva solo nel CASO3 (guida già ottima), mai nella banda morta. Fix: la banda morta
diventa **bidirezionale e guidata dall'esito** — se le leve sono più morbide dello standard §50 e la guida è stabile, il
motore prova a **irrigidire verso lo standard** (aggr SU / MinMove GIÙ), misura l'esito su una finestra e **tiene** se
l'RMS regge/migliora, ammorbidisce (§32, ora fallback) solo se l'esito prova che serviva (seeing vero). Àncora = valori
standard §50; il cap §51 resta il tetto; satisfaction §30 rispettato. Visibile in `/status.recovery` + log. Kill-switch
`symmetric_recovery_enabled` (true, born-operative). 264 test verdi. Chiude il cerchio Outcome-First: si prova a tornare
reattivi e la MISURA (non una classificazione) decide se tenere. Dettagli: NOTE_CLAUDE §53. Da validare sul campo.

## Stato precedente — aggiornato al 2026-06-22 (§50 INIT standard PHD2 + §51 cap MinMove adattivo)

### §50+§51 — Fondamenta del motore (fatto, 2026-06-22)
Due **principi architetturali** del motore (non sperimentazioni), prima di nuove logiche decisionali. Ciclo di vita:
`Connessione → Calibrazione → Inizio guida → (A) INIT standard → Formazione baseline → (B) cap MinMove adattivo → Agent`.
- **§50 INIT ai valori standard PHD2 (A):** all'inizio guida (dopo calibrazione, prima della baseline) le leve partono
  da uno **stato noto** — RA (Hysteresis) 70/0.20, DEC (Resist Switch) 100/0.20 — così ogni adattamento è attribuibile al
  motore e i log dei tester sono confrontabili. Algoritmo-aware (skip+warning se scala diversa, mai valori sbagliati); i
  valori utente salvati/ripristinati dal Baseline Guardian. Kill-switch `[control] init_to_phd2_standard`.
- **§51 cap MinMove adattivo (B):** il MinMove può salire per assorbire il seeing ma **mai oltre** ciò che il setup può
  raggiungere — `cap = min(k × baseline §44 FILTRATA nel tempo, imaging_ceiling)`. `k` universale <1 (rapporto
  scale-indipendente); `imaging_ceiling` per-setup (stub N5) è dove entra la scala di ripresa. EMA su ~18 min (non la
  baseline iniziale, non l'istantaneo). Applicato a tutti i punti che alzano MinMove (CASO1/§32/micro), su /status.
  Kill-switch `[limits] minmove_cap_adaptive_enabled`. Due kill-switch separati, ognuno reversibile a sé.
254 test verdi (242 + 12). NON toccati §24/§31/§32/§41-42/§44. Dettagli: NOTE_CLAUDE §50+§51.

## Stato precedente — aggiornato al 2026-06-21 (§48 N1 unico riconoscitore + §49 N6 safety su nubi)

### §48+§49 — N1 riconoscitore trasparenza (finalizzato) + N6 safety su nubi (fatto, 2026-06-21)
Motivazione di campo: nuvole copiose hanno confuso il modulo SEEING e il Safety Monitor NON ha fermato la ripresa (andava
UNSAFE solo su STAR_LOST di guida). Architettura a livelli: **N1 è l'unico riconoscitore di trasparenza** (Agente,
`nina_indices.py`); **N6 e N8 sono consumatori** dello stesso stato.
- **§48 N1:** finalizzato il contratto per i consumatori — `/status.nina.transparency` ora espone `fresh` (freschezza
  single-source dallo store §43) e `background`, oltre a `index` (continuo, per N8) e `state` CLEAR/HAZE/CLOUD (discreto,
  per N6). Il riconoscitore (baseline per-filtro relativa, TransparencyIndex stelle+fondo NO-HFR con enfasi trend +
  persistenza) è quello del §45. 242 test verdi (Agente).
- **§49 N6 (plugin C# v1.4):** il **Safety Monitor** ora dichiara UNSAFE anche sulle **nubi** — `SafetyDecisionEngine`
  legge `nina.transparency` dal `/status` (già interrogato; JSON puro → gira su NINA 3.2 e 3.3) e va UNSAFE quando lo
  stato resta CLOUD per N poll consecutivi (isteresi asimmetrica: lento verso unsafe, più rapido verso safe), **accanto**
  a STAR_LOST (non lo sostituisce). **FAIL-SAFE:** senza telemetria fresca (`fresh=false`) la condizione nubi è neutra →
  resta solo STAR_LOST. Confine invariato (NINA decide pausa/park). Kill-switch `CloudSafetyEnabled`. Build 3.2 pulita
  (0/0). N6 ferma le nubi PRIMA di perdere la stella di guida → non spreca light. Prossimo consumatore di N1 = N8 (già
  fatto in §46, useerà l'`index` continuo). Dettagli: NOTE_CLAUDE §48+§49, `ARCHITETTURA_FILONE_DIAGNOSTICO_NINA.md`.

## Stato precedente — aggiornato al 2026-06-21 (§47 esperimento outcome-first: ramo oscillazioni disattivo)

### §47 — Esperimento OUTCOME-FIRST (fatto, 2026-06-21)
Direzione architetturale (Alessandro): il motore reagisce al **risultato** (RMS/outcome), non pre-classifica le cause.
**Esperimento reversibile**: DISATTIVATO (kill-switch `[diagnostic_engine] oscillation_branch_enabled=false`, NON
cancellato) il ramo oscillazioni — sia la proposta del motore su OVERCORRECTION/lag-1 (ora stato solo informativo,
`proposal=None`) sia il **CASO2 v2.3** "oscillazione=trend→↓aggr". Tesi: una vera oscillazione patologica si manifesta
comunque come peggioramento RMS/outcome; SEEING-softening, §32, Guardian, §44 restano gli attori. **Strumentazione di
attribuzione** (per capire chi guida davvero la spirale): ogni azione porta `softening_source` + `minmove_arcsec`;
contatore shadow `osc_would_fire`(+degraded); `/status.oscillation_experiment` + badge/breakdown in dashboard. Da
validare in diretta (3–4 sessioni) prima di rimuovere strutturalmente. NON toccati: §44/Guardian/SEEING-softening/§32/
outcome/NINA. Nessun cap MinMove, discriminatore oscillazione parcheggiato. 239 test verdi (232 + 7). Dettagli:
NOTE_CLAUDE §47 + `VALIDAZIONE_CAMPO_v2.6.md`.

## Stato precedente — aggiornato al 2026-06-19 (N1 Transparency Index §45 + N8 confidence fusion §46)

### §45+§46 — NINA inizia a "vedere il cielo": trasparenza + fusione confidence (fatto, 2026-06-19)
Primi consumatori della telemetria NINA (§41/§42), architettura 3-layer.
- **§45 N1 — Transparency Index** (`phd2_agent/nina_indices.py`, Layer-2): segnale di trasparenza del cielo ORTOGONALE a
  PHD2, dal conteggio stelle + fondo della camera di ripresa. Riferimento SEMPRE RELATIVO al campo+filtro (rolling-high
  su finestra mobile), MAI assoluto: campo povero ma stabile → CLEAR; calo % rapido (velature/nubi) → HAZE/CLOUD. Niente
  HFR. Esposto in `/status.nina.transparency` + card dashboard "Trasparenza (NINA)" + colonne CSV. Kill-switch
  `[nina_indices] enabled`.
- **§46 N8 — confidence fusion** (`diagnostic_engine.py`): la trasparenza in calo **modula** (abbassa) la confidence del
  motore SOLO sulla diagnosi **SEEING** (mai OVERCORRECTION/DRIFT/meccanica), con **penalità proporzionale** al calo %
  (dead-band sul rumore → ramp fino a 40 punti), confermata su ≥2 pose. Effetto solo "astieniti" (NINA non aumenta mai
  aggressività; tocca solo la soglia di confidence, non l'ampiezza). Visibile live: evidence esplicita + badge confidence
  decomposto (`58% (PHD2 76 − NINA 18)`) + marcatore sul grafico. Kill-switch `[diagnostic_engine] confidence_use_nina`.
  Graceful: senza telemetria fresca = confidence PHD2-only (pre-§46).
Born-operative, da validare in diretta sul cielo (metodologia live: visibile, tracciato, reversibile, GUARDIAN-piccolo,
fail-safe). 232 test verdi (213 + 19). Dettagli: NOTE_CLAUDE §45+§46 + `VALIDAZIONE_CAMPO_v2.6.md`.

## Stato precedente — aggiornato al 2026-06-19 (rifiniture §43/§44 post-validazione di campo)

### §43+§44 — rifiniture v2.6 dopo la validazione di campo (fatto, 2026-06-19)
Validato sul campo (Minixz100/NINA 3.3, 71F, 2026-06-18): telemetria NINA reale, `jitter_ref` dinamico, GUARDIAN che fa
la prima micro su SEEING reale. Tre interventi:
- **§43a — freschezza telemetria adattiva:** `/status.nina` non va più in falso "disconnesso" tra una posa e l'altra.
  Finestra = `max(staleness_seconds, staleness_exposure_factor × exposure_s)` (chiave `staleness_exposure_factor=1.5`).
- **§43b — cap aggressività 90→100** (RA+DEC, solo config; `minmove_max` invariato 0.85).
- **§44 — baseline a rinnovo CONTINUO e BIDIREZIONALE** (il cuore): risolve il softening spurio visto nei log `223204`,
  dove la baseline "tightest-wins" del §25 non poteva salire col peggiorare del seeing → `rms_high` inchiodato a 0.704 →
  RMS legittimi letti come SEEING. Ora la baseline si aggiorna in continuo su finestra mobile e può **salire** (seeing
  peggiore) o stringersi (migliore), seguendo la scala reale della notte. **Il CAP §24 resta** come tetto di sicurezza
  (la baseline lo raggiunge ma non lo supera); §23/anti-inversione backstop intatti. Kill-switch
  `baseline_track_bidirectional` (default true; false = legacy §25). 213 test verdi. Dettagli: NOTE_CLAUDE §43+§44.

## Stato precedente — aggiornato al 2026-06-18 (Step 0 telemetria NINA — COMPLETO: Agente §41 + plugin §42)

### §42 — Step 0 telemetria NINA (lato PLUGIN): inoltro metriche per-posa → Agente — Plugin v1.3 (fatto, 2026-06-18)
Chiusa la seconda metà dello Step 0: il **plugin NINA** (repo separato `AdaptiveAgentForPHD2.NinaPlugin/`, GitHub
`Mamete91/AdaptiveAgentPHD2-NinaPlugin`) ora **inoltra** le metriche per-posa all'Agente. Nuovo `AgentTelemetryForwarder`
iscritto a `IImageSaveMediator.ImageSaved`; a ogni light salvata fa `POST <DashboardUrl>/nina/telemetry` (contratto §41
`schema_version=1`, solo `image{}`: HFR, HFR std, conteggio stelle, statistiche ADU mean/median/stdev, durata, filtro).
**Opzionale e graceful**: handler non-throwing, POST fire-and-forget (timeout 3 s, nessun retry, swallow totale) →
Agente offline = no-op, NINA mai disturbata. Toggle `ForwardTelemetryToAgent` (default ON, kill-switch lato plugin).
Plugin bumpato a **v1.3.0.0**; build Release **0 errori/0 warning** contro l'SDK NINA **3.2.0.9001**; GUID e dipendenze
NINA/WebView2 invariati. **Lezione verify-before-implement**: la tabella API fornita era dal ramo `develop`, ma il
compilatore ha rivelato che `FWHM`/`Eccentricity` **non** esistono su `IStarDetectionAnalysis` in 3.2.0.9001 (aggiunti in
build successive) → **omessi** (non inventati); il contratto §41 ha già il campo `fwhm` (FASE 0.B) forward-ready per
quando la NINA installata li esporrà. Congelamento plugin **rimosso** (Alessandro): sviluppo/build/validazione sul PC
corrente (installato .NET 8 SDK 8.0.422). Validazione di contratto: il payload del forwarder è accettato dall'endpoint
§41 e compare in `/status.nina` (HFR/star_count/ADU; fwhm/eccentricity → null). Test NINA-in-the-loop = manuali (build
pulita ✓; Agente vivo→connected, Agente spento→graceful, toggle off = da spuntare in campo). Niente bump Agente (solo
`fwhm` aggiunto a `NinaImageMetrics`). Dettagli: NOTE_CLAUDE §42 + README plugin (sez. v1.3).

### §41 — Step 0 telemetria NINA (lato Agente): canale in ingresso aperto — Agente v2.6 (fatto, 2026-06-18)
Aperto il canale in INGRESSO NINA→Agente, **inerte finché il plugin non inoltra**. Prima il flusso plugin→Agente era di
sola lettura (`GET /about` + `/status`); ora c'è **`POST /nina/telemetry`** (endpoint difensivo, pydantic
`NinaTelemetryPayload`, contratto JSON `schema_version=1`: HFR, conteggio stelle, SNR/fondo, eccentricità, contesto),
uno store opzionale e thread-safe **`NinaTelemetryStore`** (Layer-1 grezzo, ultimo valore + storico + `is_fresh`, nessuna
logica derivata) e un blocco top-level **`nina`** in `/status` (`enabled/connected/schema_version/last_age_s/metrics`).
**Opzionale e graceful**: senza POST l'Agente è bit-identico a oggi; payload malformato → 422 senza mai disturbare il loop
di guida. **Nessun consumatore agisce ancora** sui dati (context-gating N2, trasparenza N1, safety N6, tag N7, confidence
N8 = prompt successivi). Config `[nina_telemetry] enabled=true` born-operative (kill-switch `enabled=false`). **Lato
plugin RIMANDATO** al ripristino del PC principale (plugin congelato): il contratto JSON è già fissato per svilupparlo in
parallelo. È infrastruttura (non modello): non migliora l'RMS, apre l'occhio ortogonale (forma reale delle stelle nella
posa) per disambiguare seeing vs meccanica e validare il motore §31. Niente bump versione (release in prompt git dedicato).
203 test verdi (180 + 23). Dettagli: NOTE_CLAUDE §41 + `ROADMAP_TELEMETRIA_NINA.md` (Step 0).

### RELEASE v2.6 (2026-06-17) — milestone §37→§40
Prima versione ufficiale sopra la 2.5. Il motore di diagnosi del seeing passa da **dormiente a operativo** (parte
attivo in GUARDIAN) e misura in arcsec. Raccoglie: **§37** (HFD informativo, fuori dal gate SEEING), **§38**
(`jitter_ref`/`hfd_ref` sempre-forma via best-fraction), **§39** (i riferimenti sopravvivono al dither/settle; logging
`reset_cause`; schema CSV 3→4), **§40** (baseline anche a SNR basso), su base **§36** (RMS px→arcsec, già in v2.5).
Tutte le feature default-ON (born operative). Validato sul campo (71F @490, 2026-06-17: jitter_ref 12%→87%, motore che
diagnostica, baseline che si forma). Versione bumpata 2.5→2.6 in `__about__.py`. Dettagli: NOTE_CLAUDE §40 + nota release.

### §40 — la baseline si forma anche a SNR basso — Agente v2.6 (fatto, 2026-06-17)
Il gate `_update_rms_baseline` con `baseline_min_snr=10` bloccava sia NOMINAL sia il fallback §33 → su notti a SNR
basso la baseline non si formava (campo 71F `221428`: SNR mediano 9,2, 100% < 10, `rms_high_active` inchiodato a 1,20).
Fix isolato al gate: `baseline_min_snr` 10→**6** (= floor "Minimum star SNR for AutoFind" di PHD2); il **fallback §33
non è più congelabile** dalla soglia SNR — accumula i frame sopra un floor anti-garbage (`baseline_fallback_min_snr=3`,
= reject PHD2) e forma dal best-fraction, così la baseline si forma anche su notti fioche dai frame meno peggio. NOMINAL/
cap 1,00"/anti-inversione/reject §33 intatti; esclusione implosion mantenuta. Kill-switch
`baseline_fallback_ignores_snr_gate=true` shipped (false = gate stretto §33). Replay `221428`: baseline da None →
**0,58"**, `rms_high_active` da 1,20 → **0,752"**. 180 test verdi (5 nuovi). Terza chiusura del principio "il
riferimento si forma sempre" (dopo baseline §33 e jitter_ref §38). Dettagli: NOTE_CLAUDE §40.

### §39 — il riferimento di calma SOPRAVVIVE al dither + logging reset_cause — Agente v2.5 (fatto, 2026-06-16)
Passo 2/2 del motore operativo (dopo §38). Causa profonda: `diagnostic_engine.reset()` azzerava `jitter_ref`/`hfd_ref`
+ finestre §38 a OGNI dither/settle (ogni pochi minuti) → il motore riformava all'infinito un riferimento che gli
veniva cancellato. Ma un dither sposta la stella, non l'atmosfera (stessa lezione del §36: invalidare solo a vero
cambio di regime). Fix in due parti, isolato ai call-site di reset + `reset(cause)` + logger: **(A)** `reset(cause)`
preserva refs+finestre su `dither`/`settle`/`mode_transition` e le azzera solo su `exposure_change`/`pixel_scale_change`/
`target_change`/`guiding_restart` (il jitter scala col tempo di posa / cambia il cielo); `analyzer.reset()` NON toccato
(la finestra RMS deve resettarsi al dither). **(B)** nuova colonna CSV `reset_cause` (causa loggata sul frame del reset),
`schema_version` 3→**4**, così i replay futuri sono fedeli. Kill-switch `[diagnostic_engine] preserve_refs_on_dither=true`
shipped (false = azzera sempre §31). Demo: `refs_ready` resta **97,7% a qualunque cadenza di dither** (legacy crolla a
0% con dither frequenti). 175 test verdi (7 nuovi). Limite onesto: il log RC8 `211617` è pre-§39 (senza `reset_cause`),
validazione piena dal prossimo run di campo. Coerente con P1/§36. Dettagli: NOTE_CLAUDE §39.

### §38 — jitter_ref/hfd_ref che si formano SEMPRE (motore operativo) — Agente v2.5 (fatto, 2026-06-16)
Fratello del §33 "un livello più sotto". Dopo §34/§37 il motore continuava a non diagnosticare SEEING perché le
reference EMA (`jitter_ref`/`hfd_ref`) si formavano solo nel ramo stretto `rms<=rms_low AND NOMINAL` (e venivano
azzerate a ogni reset): replay reale RC8 `211617` → `jitter_ref` formata solo **11,8%** dei frame, **SEEING=0** in
assoluto (scoperta riprodotta e CONFERMATA). Fix isolato a `diagnostic_engine.py`: le reference si formano col
**best-fraction su finestra mobile** (i frame più calmi), come la baseline §33 — sempre e presto, anche nelle notti
turbolente. `refs_ready` ora dipende **solo da `jitter_ref`** (post-§37 l'HFD è informativo); `hfd_ref` resta
calcolato/loggato. NOMINAL/satisfaction-gate e le condizioni SEEING/OVER/DRIFT (§37) **invariati**. Kill-switch
`[diagnostic_engine] refs_always_form=true` shipped (false = formazione §31 per A/B); parametri attivi
`refs_window_frames=120`, `refs_best_fraction=0.25`, `refs_warmup_frames=15`. Replay §38: `refs_ready` **11,8%→95,4%**,
**52 SEEING** (prima 0); alla cadenza di reset realistica ~60-83% vs ~11% legacy (5-7×). 168 test verdi (7 nuovi).
Coerente con P1: il riferimento di calma ora si forma davvero. Dettagli: NOTE_CLAUDE §38.

### §37 — HFD declassato a SOLO INFORMATIVO: fuori dal gate SEEING — Agente v2.5 (fatto, 2026-06-16)
Verificato sul campo (tutti i setup/notti): sulla camera di guida l'HFD resta piatto (`hfd_avg/hfd_ref ≈ 1.0`), quindi
`hfd_high` non scattava mai e il gate AND `rms>rms_high AND jitter_high AND hfd_high` **azzerava SEEING** anche con
guida turbolenta (conferma RC8 2026-06-16: SEEING=0 a 0.83"). Fix isolato a `diagnostic_engine.py`: SEEING ridefinito
sulla sola **firma dinamica** `rms_total>rms_high AND jitter_high AND not oscillation` (specifico, distinto da
OVERCORRECTION=oscillazione e da DRIFT=trend); HFD tolto da OGNI decisione (anche `not hfd_high` da OVER/DRIFT) ma
**ancora calcolato/loggato** (`hfd`/`hfd_ref` nelle metrics → CSV + card dashboard intatti). Guardian resta review-only
(nessuna micro spuria: verificato in test). Kill-switch `[diagnostic_engine] hfd_gates_seeing=false` **shipped sul
nuovo comportamento** (true = gate §31 legacy per A/B). 161 test verdi (7 nuovi). Via **semplice** scelta da Alessandro
al posto del weighting sampling-aware (`PROPOSTA_§32_HFD_SAMPLING_AWARE.md`): non si pretende dall'HFD della guida un
seeing che non può misurare (il segnale vero arriverà dalla camera di ripresa, roadmap NINA). Replay RC8 `211617` da
eseguire su Minix100 (log fuori repo). Coerente con P1. Dettagli: NOTE_CLAUDE §37.

### §36 — FIX unità: RMS misurato in PIXEL ma trattato come ARCSEC — Agente v2.5 (fatto, 2026-06-15)
Bug confermato su codice (PHD2 + Agente): le distanze di guida di PHD2 (`RADistanceRaw/DECDistanceRaw`) sono in PIXEL,
l'Agente le leggeva come arcsec senza convertirle, ma le soglie/cap/reject sono in arcsec → misura(px) vs soglie(arcsec),
miscalibrazione di un fattore pixel-scale (RC8 sovrastima ×~2, Askar/Mirko sottostimano). Fix isolato: `ingest_guide_step`
converte `ra_raw/dec_raw` **× pixel-scale viva** all'ingest (una volta); rms/peak/jitter/trend ereditano arcsec e
combaciano con le soglie (nessuna ritaratura). HFD invariato (ha già la sua conversione); aggressività/soglie/cap NON
toccati. Kill-switch `[analyzer] convert_distance_to_arcsec=true` (shipped ON; OFF = px buggato per A/B). `schema_version`
2→3. Replay RC8 000212: RMS mediano **1.79 px → 0.91" reale**, baseline da **rifiutata→accettata**. 154 test verdi
(9 nuovi). Prerequisito di tutto (baseline/cap/RECOVERY/diagnosi): misura e soglie ora nella stessa unità. Dettagli:
NOTE_CLAUDE §36.

## Stato precedente — aggiornato al 2026-06-15 (Cadenza/baseline §34 + Riselezione Path B §35 — Agente v2.5)

### §34 — Cadenza loop / baseline reale / pulizia logging INSUFFICIENT — Agente v2.5 (fatto, 2026-06-15)
Accertamento CONFERMATO sul codice: `evaluate()` (classify + baseline) gira solo sul tick `interval_seconds` (10s,
~1 frame su 5), ma il CSV logga ogni guide-frame → le righe fuori-tick escono coi default dello snapshot
(`exposure_ms=0`, `diag_state=INSUFFICIENT`), e il contatore baseline avanza per tick → ~30 min invece di ~6.
Fix: nuovo `controller.ingest_frame` chiamato per OGNI guide-frame (kill-switch `[control] per_frame_baseline=true`):
accumula la baseline sui frame reali (fallback §33 in ~8 min) e popola exposure_ms + ultimo diag_state valido sulle
righe fuori-tick; `evaluate()` marca `evaluated=True` (nuova colonna CSV, `schema_version` 1→2). `classify`/leve NON
toccati (restano per-tick). Replay `session_20260615_000212`: INSUFFICIENT 81%→**15% sui frame valutati**, baseline
~37→**~8 min**. Dettagli: NOTE_CLAUDE §34.

### §35 — Riselezione stella all'aumento esposizione (Path B) — Agente v2.5 (fatto, 2026-06-15)
Quando Path B alza l'esposizione e la stella SATURA al nuovo tempo (picco flat-top → centroide in bias), prima il
recupero arrivava solo dopo il timer 300s. Ora, dopo un breve settle, su immagine fresca si verifica la saturazione e
— **solo se satura** — si riseleziona la migliore stella NON satura (`find_best_star(prefer_unsaturated=True)` +
`set_lock_position`), con anti-flapping (cooldown) e solo in guida valida. Kill-switch
`[exposure_dynamic] restar_on_pathb_saturation=true` (shipped ON; a OFF = solo timer 300s). NON tocca §31/§32/§33/leve.
145 test verdi (15 nuovi: `test_per_frame_baseline.py`, `test_pathb_restar.py`). Dettagli: NOTE_CLAUDE §35.

### §33 — La baseline deve formarsi SEMPRE (prerequisito di P1) — Agente v2.5 (fatto, 2026-06-13)
Sulle notti di seeing brutto (RC8/CEM70) la baseline auto-calibrata non si formava: campionava solo da frame
`condition==NOMINAL` e a guida degradata non se ne accumulano 60 → baseline `None` → satisfaction-gate (§30),
RECOVERY (§32) e tutta la logica P1 senza àncora (controllore inerte proprio quando serve). Fix sul campionamento
(non sul rifiuto): percorso NOMINAL invariato (notti buone bit-identiche) + **fallback** che, se i 60 frame NOMINAL
non arrivano entro `baseline_fallback_frames`, forma la baseline dalla finestra "tutti i frame" con stimatore
**mediana del miglior X%** (la miglior prestazione raggiungibile = P1). Il **CAP su rms_high (1,00″) NON si tocca**;
aggiunto **cap anti-inversione su rms_low** (rms_low < rms_high sempre); rifiuto fallback su **instabilità/tetto**
invece che su valore assoluto basso. Kill-switch `[auto_calibration] baseline_always_form` (default true; a OFF =
identico). Replay su log serena 004934: oggi baseline=None → col fix **1,452″** (rms_high resta 1,00″, rms_low 0,85″).
130 test verdi (12 nuovi in `test_baseline_formation.py`). **Niente rebuild**: si folde nel prossimo build v2.5 →
**lo ZIP v2.5 col solo §32 è ora stale** (il prossimo conterrà §32+§33). Limite onesto: dà un riferimento ma non
fa guidare bene l'RC8 (taratura montatura a monte). Dettagli: NOTE_CLAUDE §33.

### §32 — Recupero MinMove nella banda morta (asimmetria leve) — Agente v2.5 (fatto, 2026-06-12)
Corretta l'asimmetria storica delle leve v2.2/2.3/2.4: MinMove scendeva su `rms<rms_low` (frequente) ma risaliva
solo su `rms>rms_high` (raro), restando congelato al floor 0,15 nella **banda morta** (`rms_low<rms<rms_high`).
Aggiunto un ramo di recupero alla catena CASO (motore OFF + GUARDIAN; sospeso in JITTER): se `rms > mediana
baseline` persiste nella banda morta, MinMove **risale** di un gradino verso la morbidezza (oltre il valore
iniziale, fino a `minmove_max`; floor 0,15 invariato), con isteresi sulla mediana (no pompaggio) e anti-windup
puro-RMS (si ferma se il softening non riduce l'RMS). Complemento speculare del satisfaction gate §30.
Solo MinMove (l'Aggression coordinata è il loop a due leve jitter-aware, fuori scope). Kill-switch
`[lever_optimization] minmove_recovery_enabled` **default true** (a OFF = identico v2.4). Replay su log
2026-06-11 GUARDIAN: **14 risalite col fix vs 0 oggi** nei 745 frame di banda morta. 118 test verdi
(13 nuovi in `test_minmove_recovery.py`). Dettagli: NOTE_CLAUDE §32, `DESIGN_RATIONALE_LEVER_RESPONSIVENESS.md`.
Rilascio in campo solo dopo validazione beta. Altri item v2.5 (HFD sampling-aware, congelamento INSUFFICIENT)
restano **su carta**.

## Stato precedente — aggiornato al 2026-06-08 (Seeing Diagnostic Engine §31 — Agente v2.4)

### Ambiente installato sul PC Windows (fatto)
- Python 3.12.10 installato via winget
- Dipendenze pip installate: fastapi 0.136.1, uvicorn 0.46.0, numpy 2.4.4,
  scipy 1.17.1, websockets 16.0, pydantic 2.13.3 e relative dipendenze
- PyInstaller 6.20.0 installato

### Modifica a build_dist.py (fatto)
- build_dist.py è stato modificato per usare PHD2_Agent.spec per la build
  dell'agente principale (invece degli argomenti inline che mancavano scipy).
  Il .spec include già tutti gli hidden imports corretti per scipy e numpy.

### Build completata (fatto)
- Eseguita con: python build_dist.py
- Output generato in: Pacchetto_Distribuzione/
  - PHD2_Agent.exe (11.5 MB, più _internal/ ~100 MB di dipendenze)
  - Diagnostica_Connessione.exe (48.4 MB, onefile)
  - config.toml (default)
  - config_rc8.toml, config_tecnosky115.toml, config_askar71f.toml (copiati a mano)
  - dashboard/, phd2_log/, LEGGIMI_PER_AVVIARE.txt
- ZIP finale: PHD2_Agent_Distribuzione.zip (100.9 MB) — pronto per distribuzione

### Test simulatore (fatto)
- Eseguito python main.py --simulator --dry-run (2 run sequenziali)
- Verificato: nessun ModuleNotFoundError, connessione simulatore OK,
  controller inizializzato, Baseline Guardian salva baseline.json
- Verificato: orphan recovery funziona (run 2 rileva baseline orfana dal run 1)
- Il controller ha emesso decisioni DRY_RUN corrette:
  [TEST] RA Aggressiveness: 70.0 -> 72.0 (guida stabile, aumento graduale)

### Double initialize() — RISOLTO (2026-04-30)
Aggiunto `mark_uninitialized()` in `controller.py`. Handler `GuidingStopped`
chiama `controller.mark_uninitialized()`. Handler `StartGuiding` controlla
`if not controller.is_initialized()` prima di chiamare `initialize()`.

### Dithering/Settling — IMPLEMENTATO (2026-05-01)
Flag `is_settling` in `_event_loop`. Gestione eventi `SettleBegin`/`SettleDone`
(primario) e `AppState: Settling/Guiding` (backup). I GuideStep durante
il settling vengono scartati. `analyzer.reset()` alla fine del settling.

### BUG CRITICO SCALA aggression — TROVATO E RISOLTO IN CAMPO (2026-05-01)
PHD2 Hysteresis e Resist Switch espongono `aggression` in scala 0.0–1.0
(non 0–100 come tutti gli altri). Il controller leggeva 0.7, sommava
step_up=3, tentava di inviare 4 → RPC Error "could not set param".
Fix: `aggr_native_scale` in `AxisState`, conversione bidirezionale in
`_setup_axis` (lettura) e `_apply` (invio). Baseline v2 include la scala.
Vedere NOTE_CLAUDE.md sezione 13 per dettaglio completo.

### Sezione [phd2_log] e PHD2LogConfig — AGGIUNTO (2026-04-30)
Tutti i config_*.toml ora hanno [phd2_log]. `config.py` ha `PHD2LogConfig`
dataclass e relativo parsing in `load_config()`.

### Avvio rapido .bat — CREATI (2026-04-30)
`Avvia_Askar71F.bat`, `Avvia_Tecnosky115.bat`, `Avvia_RC8.bat` in
`Pacchetto_Distribuzione/`. Usare doppio click per avviare.

### Confronto GA-Agent + correzione pixel scale OAG (2026-05-01)
Prodotto `doc/CONFRONTO_GA_AGENT.md` (23 KB): analisi comparativa tra
PHD2 Guiding Assistant e l'agente adattivo, con formula SmartDefaultMinMove
verificata sul sorgente C++ PHD2. Identificati i sensori guida corretti:
- OAG Askar 71F: **ASI120MM Mini** (sensore AR0130CS, pixel 3.75 µm, 1280×960)
- OAG RC8 + Tecnosky 115: **ASI220MM Mini** (sensore SC2210, pixel 4.0 µm, 1920×1080)
Corretta pixel scale in `config_askar71f.toml`: era calcolata con 4.0 µm (sbagliato),
corretta a `1.58"/px` nativo, `1.97"/px` ridotto. Tabella SmartDefault ricalcolata
con pixel size corretti; SmartDefault RC8 nativo = 0.46 px (non 0.67 come con 2.33 µm).

### Estensione minmove_max (2026-05-01)
Tutti e tre i config (root + Pacchetto_Distribuzione) aggiornati:
- `[limits.ra]  minmove_max`: 0.55 → **0.80** (tutti i setup)
- `[limits.dec] minmove_max`: 0.55 → **0.85** (tutti i setup)
Motivazione: valore precedente troppo restrittivo; range esteso per consentire
al controller piena libertà di riduzione in condizioni di guida degradata.

### Filosofia operativa: solo sessioni reali (2026-05-01)
Decisione di non simulare artificialmente condizioni di guida (es. dati FITS
sintetici) per test di logica. Il test funzionale su simulatore è sufficiente
per verificare syntax/init. La validazione della logica adattiva avviene
esclusivamente su sessioni reali con cielo aperto, analizzando i log `decisions_*.jsonl`.

### Prima sessione LIVE Askar 71F (2026-05-01)
Prima sessione con `dry_run = false` e algoritmo Hysteresis RA / Resist Switch DEC.
Risultati guida nella fase stabile: RMS 0.11–0.20" RA, 0.13–0.43" DEC — ottimo
per la focale di 490 mm con AM5.

**Evento critico alle 00:12:45**: crash USB ASI120MM Mini. SDK ASI restituisce
`EXP_FAILED giving up` → PHD2 entra in StarLost loop → controller chiama
`find_star()` ogni ~10s senza backoff per ~6 minuti (130+ chiamate). I pochi
frame corrotti pervenuti mostravano RMS 17.86" RA / 12.17" DEC — fisicamente
impossibili alla scala di 1.58"/px — ma il controller li elaborava normalmente.
Sessione terminata manualmente.

### Mitigazione crash USB ASI120MM Mini (2026-05-01)
Due azioni intraprese:
1. **Hardware**: acquistato cavo Lindy Anthra Line USB-A/USB-C 0.5 m per
   sostituire il cavo USB problematico della camera guida.
2. **Architetturale**: PHD2 non espone via JSON-RPC alcun endpoint per reset/
   reinizializzazione camera. Il recovery automatico via software non è
   implementabile; la gestione si limita a stop/restart guiding.

### Soglie rms_low/rms_high da ricalibrare (dopo sessioni reali)
I valori attuali nei config sono stime a priori, non calibrati su seeing reale
di Borno. Dopo 2-3 sessioni con il profilo corretto applicare la formula:
- `rms_high = 1.5 × RMS_medio_tipico_della_notte`
- `rms_low  = 0.7 × RMS_medio_tipico_della_notte`
Leggere `mean_rms_total_arcsec` da `logs/session_*.summary.json`.

### Esposizione dinamica RMS-based — IMPLEMENTATA (2026-05-09)
Aggiunta sezione `[exposure_dynamic]` ai config con macchina a stati
`ExposureState` (NOMINAL / BOOSTED_FOR_SNR / BOOSTED_FOR_SEEING). Il path
RMS-based si attiva su DEGRADED_SEEING + spike + HFD + peak/rms ratio,
con esclusioni tassative di OSCILLATING e LOW_SNR (delegato al path A
preesistente). Cambio esposizione → `analyzer.reset()` obbligatorio.
Baseline Guardian aggiornato a v3 con persistenza dello stato esposizione.
`config_rc8.toml` ha `dry_run = false` e `enabled = true` per validazione LIVE
diretta sul grafico dashboard. (Dopo §21 anche gli altri due setup hanno
`dry_run = false` e `enabled = true`.)
Vedere NOTE_CLAUDE.md sezione 19 per dettaglio completo.

### Refactor [setup] e supporto Riduttore Focale — IMPLEMENTATO (2026-05-09)
Spostata `guide_pixel_scale_arcsec` da `[exposure_dynamic]` a una nuova sezione
`[setup]` estesa con campi `_native`, `_reduced` e flag `reducer_active`.
La pixel scale effettiva è esposta come property calcolata `cfg.setup.guide_pixel_scale_arcsec`,
letta da tutte le feature future (oggi dall'esposizione dinamica path B).

Corretti i valori di pixel scale ridotta per i tre setup:
- Askar 71F: 1.58"/px nativo, 2.11"/px ridotto (riduttore 0.75x)
- Tecnosky 115: 1.03"/px nativo, 1.29"/px ridotto (riduttore 0.80x)
- RC8: 0.51"/px nativo, 0.68"/px ridotto (riduttore 0.75x)

Aggiunti flag CLI `--with-reducer` e `--no-reducer` in `main.py` come override
del valore TOML. Creati 3 nuovi `.bat` (`Avvia_<setup>_Ridotto.bat`) per
attivare la modalità riduttore con doppio click, senza editing del TOML.
`config_rc8.toml` configurato per validazione LIVE: `dry_run = false`,
`[exposure_dynamic].enabled = true`.
Vedere NOTE_CLAUDE.md sezione 20 per dettaglio completo.

### Dashboard §21: Pannello Stato Esposizione & Escalation Gate — IMPLEMENTATO (2026-05-12)
Estesa la dashboard con un nuovo pannello `mid-row-2` tra il grafico e il log:
- **Exposure card**: badge stato (NOMINAL / BOOSTED_FOR_SNR / BOOSTED_FOR_SEEING),
  esposizione corrente / base in ms, steps sopra base, cooldown bar con countdown.
- **Escalation Gate card**: badge abilitato, status RA/DEC (SATURATE / OK),
  nota contestuale sul gate aperto/chiuso.
- **Chart.js 4th dataset**: scatter triangoli (giallo = UP, verde = DOWN) sovrapposti
  al grafico RMS per marcare ogni cambio esposizione in tempo reale.
- `get_status()` esteso: blocco `escalation_gate` (enabled + ra + dec bool) e
  `cooldown_residuo_s` / `cooldown_total_s` nell'exposure block.
- Tutti e 3 i config_*.toml ora: `dry_run = false`, `[exposure_dynamic].enabled = true`.
- `build_dist.py` aggiornato per copiare tutti i 6 `.bat` (inclusi `_Ridotto`).
Vedere NOTE_CLAUDE.md sezione 21 per dettaglio completo.

### FIX difensive find_star backoff + RMS implosion detector (2026-05-03)
Due fix implementati a seguito della prima sessione LIVE:

**FIX 1 — find_star backoff** (`controller.py`, `_evaluate_star_lost`):
Tre tier progressivi per fallimenti consecutivi di `find_star()` in LIVE:
- Normale (< 5 fallimenti): tentativo ogni `find_star_delay` secondi
- Slow (5–9 fallimenti): tentativo ogni 30 s
- Suspended (≥ 10 fallimenti): nessuna chiamata, log WARNING ogni 60 s con
  indicazione "verificare connessione USB camera"
I contatori si azzerano su successo o su `initialize()` (nuovo `StartGuiding`).

**FIX 2 — RMS implosion detector** (`analyzer.py`, `StatisticsAnalyzer._compute`):
Reference EMA del `rms_total` (α=0.1, aggiornata solo su frame validi: sotto
soglia E SNR ≥ snr_low). Se `rms_total ≥ 8 × reference`: log CRITICAL, analisi
sospesa per 60 s (`implosion_suspended=True`), condizione forzata a NOMINAL
(controller non agisce), contatori consecutivi non aggiornati (evita CRITICAL
spurio al ritorno). Reset di reference e sospensione in `reset()`.

### Auto-configurazione + config unico — IMPLEMENTATA (2026-05-27)
L'agente legge la pixel scale di guida da PHD2 (`get_pixel_scale`, fallback TOML) e deriva le soglie RMS da una
baseline misurata sul campo (config efficace in memoria, TOML mai riscritto). MinMove e aggressività restano
scale-independent. La configurazione è collassata in un solo `config.toml` + un solo `Avvia.bat`: valori unificati
(max_exposure 4000ms, snr_low 8.0, spike_min 0.25, hfd_min 4.0"); i 3 TOML per-setup e i 6 .bat sono stati eliminati.
La scelta del telescopio avviene selezionando il profilo in PHD2. Dettaglio in NOTE_CLAUDE.md §22.

### Clamp proporzionale + gate rifiuto baseline (§23) — IMPLEMENTATA (2026-05-28)
Rifinitura della §22: il clamp di sicurezza sulle soglie RMS adattive non è più fisso (0,50"-2,50") ma
proporzionale alla pixel scale rilevata (cap = 2.0 × pixel_scale, con pavimento 0,70" e tetto 3,00"
come safety per scale estreme). Aggiunto un gate di rifiuto della baseline misurata quando la mediana
supera 3.0 × pixel_scale (con pavimento 1,50"): in tal caso la calibrazione non viene applicata, l'Agente
mantiene le soglie iniziali del TOML, la dashboard segnala "BASELINE RIFIUTATA". Aggiunto floor su rms_low
a 0,25". Setup di riferimento per la scelta dei parametri: RC8 (cap 1,02"; rifiuto >1,53"). Dettaglio in
NOTE_CLAUDE.md §23.

### Branding progetto + identità autore (§26) — IMPLEMENTATA (2026-05-30)
Introdotto il modulo `phd2_agent/__about__.py` come single source of truth per
nome progetto, autore, versione, copyright e canale di contatto (gruppo
Telegram della community, unico canale di feedback — nessuna email). Il banner
d'avvio in console, l'endpoint `/about` della dashboard, il footer della
dashboard (con link Telegram cliccabile), i metadata dell'`.exe` Windows
(VSVersionInfo via PyInstaller), la copertina e i metadata del manuale PDF,
l'header di `config.toml` e di `Avvia.bat`, e il nome del file ZIP di
distribuzione leggono tutti da questo modulo. Copyright semplificato a
`Copyright © 2026 Alessandro Curci`. Bumpare la versione richiede ora l'edit di
un solo file. Nessuna modifica logica all'Agente: tutte le feature §1-§25
invariate. Pacchetto pronto per il primo rilascio pubblico v2.2 nel gruppo
Telegram di astrofotografia. Dettaglio in NOTE_CLAUDE.md §26.

### Refresh ciclico baseline (tightest-wins) + rms_high_factor 1.3 (§25) — IMPLEMENTATA (2026-05-30)
Refinement architetturale di §22 dopo osservazioni sul campo della prima sessione reale (Askar 71F): la baseline
misurata all'inizio della sessione si "congelava" anche se le condizioni meteo cambiavano (caso osservato: baseline
0,571" con cielo già velato → soglie troppo larghe per il resto della notte). La §25 introduce un refresh periodico
(default ogni 30 min) della baseline: la nuova mediana sostituisce la corrente SOLO se più stretta ("tightest-wins").
L'Agente non concede mai reattività al peggioramento del cielo, ma si adatta automaticamente quando il cielo migliora.
Durante il refresh le soglie correnti restano attive (non si va mai "senza soglie"). Inoltre `rms_high_factor`
abbassato da 1.5 a 1.3 dopo verifica numerica: protegge meglio le focali lunghe (su RC8 0,51"/px riduce le soglie
DEGRADED da 0,82-0,90" a 0,72-0,78") senza danneggiare le corte. Dettaglio in NOTE_CLAUDE.md §25.

### Taratura fine: cap a 1.00" + ranges aggr/MinMove armonizzati (§24) — IMPLEMENTATA (2026-05-29)
Refinement parametrico di §22/§23. Tetto assoluto del cap auto-calibrazione abbassato da 3.00 a 1.00
arcsec dopo analisi log che mostrano RMS reali sotto il secondo d'arco su tutti i setup di sviluppo;
la scelta allinea l'Agente al benchmark fisico di "guida pulita" e risolve il caso cercatore-guida con
focale diversa dall'imaging (la pixel scale grossolana del cercatore non porta più a soglie troppo lasche
per l'ottica di ripresa). Ranges aggressività e MinMove armonizzati a 35-90 e 0.15-0.85 px su entrambi gli
assi RA e DEC, per dare al controller più dinamica nei due estremi. Zero modifiche logiche, solo parametri.
Dettaglio in NOTE_CLAUDE.md §24.

### Plugin NINA opzionale per dashboard embedded (§27) — IMPLEMENTATO (2026-06-02)
Creato un plugin C# separato per NINA 3.3 — **Adaptive Agent for PHD2 — Dashboard** v1.0.0.0 — che aggiunge a NINA
un pannello dockable contenente la dashboard `http://localhost:8080` caricata via WebView2 direttamente nell'interfaccia
NINA. Il plugin è opzionale: la dashboard web tramite browser resta il canale primario (obbligatorio per accesso da
tablet/secondo monitor/PC remoto). Il plugin è una pura shell WebView2, non interagisce con PHD2 né con il codice Python
dell'Agente: il lifecycle dei due processi è completamente separato. GUID univoco stabile del plugin:
`6F2E9C19-4F66-4F69-B7D3-E21D5AD7458B` (NON cambiare mai nei rilasci futuri). DLL installata in
`%LOCALAPPDATA%\NINA\Plugins\3.0.0\AdaptiveAgentForPHD2.NinaPlugin\`. Progetto repo separato in
`C:\Users\aless\Documents\N.I.N.A\AdaptiveAgentForPHD2.NinaPlugin\`, build pulita 0 errori 0 warning. Dettaglio in
NOTE_CLAUDE.md §27.

### Satisfaction gate sulla mediana baseline (§30) — IMPLEMENTATA (2026-06-06) — Agente v2.3
Nel ramo "guida ottima" (CASO 3 di `_evaluate_axis`) la spinta monotòna di Aggressività
verso aggr_max e MinMove verso minmove_min è ora filtrata da un satisfaction gate
stateless: quando l'RMS dell'asse è già <= mediana baseline × target_factor (default
1.0), il ramo di ottimizzazione viene sospeso per quel tick. Le leve restano sul
valore corrente finché la guida resta in regime ottimo a quel livello di RMS o
sotto. Se l'RMS risale sopra la soglia, il gate si disattiva automaticamente e il
CASO 3 procede come da v2.2. L'asimmetria è intenzionale: il gate NON modifica
CASO 1 (degradato), CASO 2 (oscillazione), escalation gate §19, esposizione dinamica
§19. Quando il seeing peggiora, le leve continuano ad ammorbidirsi fino
all'eventuale attivazione del path B esposizione. Nuova sezione `[lever_optimization]`
in `config.toml` (enabled=true, target_factor=1.0). Bump versione Agente v2.2 → v2.3.

### Seeing Diagnostic Engine (jitter + lag-1) — modalità JITTER e GUARDIAN (§31) — IMPLEMENTATA (2026-06-08) — Agente v2.4
Nuovo modulo `phd2_agent/diagnostic_engine.py`. L'analyzer calcola jitter RMS frame-to-frame e
autocorrelazione lag-1 (RA/DEC). Il motore combina RMS+HFD+jitter+lag1+trend per classificare il
regime (SEEING / OVERCORRECTION / DRIFT / NOMINAL), con soglie relative a reference EMA (azzerate al
cambio esposizione). Due modalità (la vecchia "shadow" è stata eliminata): `jitter` (motore unica
autorità su Aggr/MinMove, CASO 1/2/3 sospesi — ricerca, logging azione→esito pre/post in
`experimental_*.jsonl`) e `guardian` (la v2.3 pilota; il motore conferma/attenua/blocca le sue mosse
e fa micro-correzioni proprie ad ampiezza ridotta — `guardian_action_factor` — solo quando la v2.3 è
ferma sull'asse; fail-safe; distribuibile). `enabled=false` di default = comportamento identico alla
v2.3. DRIFT non genera azioni; NOMINAL ottimizza solo sopra mediana baseline (§30). Il motore non
tocca mai esposizione (§19)/backlash; non accede a `self.client`. Dashboard: switcher OFF/GUARDIAN/
JITTER (OFF sempre, attivazione gated da `allow_dashboard_mode_switch` + conferma). Vedi NOTE_CLAUDE.md §31.

## Cosa NON è stato ancora fatto

- Validazione §31: jitter su RC8+CEM70G/Askar+AM5 (esiti negli episodi DRIFT/OVERCORRECTION);
  guardian su flotta (review sensati, micro-correzioni nei buchi, fail-safe). Tarare le soglie e
  i fattori guardian. Decidere in v2.5 se guardian diventa default flotta (enabled=true).


- Validazione LIVE del satisfaction gate §30 su Alessandro (2-3 sessioni reali con
  baseline finalizzata, almeno una con RMS sotto mediana per verificare gate attivo).
- Raccolta feedback beta tester gruppo Telegram: pattern di gate attivo nelle loro
  sessioni, eventuale necessità di tarare target_factor sui loro setup.

- Validazione LIVE dell'auto-configurazione: sessioni reali su almeno 2 profili PHD2 diversi (es. RC8 e Askar
  ridotto), verificando che pixel scale e soglie cambino da sole. Tarare poi rms_high_factor in base ai log.

- Validazione sul campo di §24: confermare in 2-3 sessioni reali che il cap a 1.00" non si attivi nelle
  nottate normali su RC8 e che si attivi correttamente in caso di vento o seeing scarso.

- Validazione sul campo di §25 in 2-3 sessioni reali, idealmente almeno una con cielo che migliora durante
  la nottata: verificare che il refresh applicato sia visibile sulla dashboard e che le soglie si stringano.

- Distribuzione pubblica v2.2 nel gruppo Telegram di astrofotografia (~1000 utenti): raccolta feedback nel
  gruppo Telegram della community (https://t.me/+eewRNpvElSs5OWY8), triage delle segnalazioni, eventuali
  patch v2.2.x.

- Validazione sul campo di §23 su RC8: verificare in 2-3 sessioni con seeing variabile che il cap proporzionale
  si attivi quando previsto e che il gate di rifiuto non si attivi nelle serate normali. Tarare eventualmente
  rms_high_max_factor o baseline_reject_factor sui log.

- Test graceful shutdown (Ctrl+C interattivo) su PHD2 reale: verificare che
  all'uscita compaiano "Shutdown controller - restore baseline..." e
  "Baseline file rimosso (shutdown pulito)".

- Test Baseline Guardian con kill brutale + restart (Task Manager) su PHD2
  reale: verificare messaggio "Trovata baseline.json orfana" e restore.

- Test Saturation Timer (con saturation_timeout_s = 30 temporaneo).

- Sessioni DRY_RUN aggiuntive (Tecnosky 115 e RC8) per taratura soglie:
    rms_low  = 0.7 × RMS_medio_tipico
    rms_high = 1.5 × RMS_medio_tipico

- Seconda sessione LIVE Askar 71F con nuovo cavo Lindy: verificare assenza
  crash USB e validare comportamento FIX 1 / FIX 2 nei log.

- Passaggio a LIVE Tecnosky 115 e RC8 (dopo validazione Askar 71F completa).

- Validazione LIVE dell'esposizione dinamica RMS-based su tutti i setup:
  almeno 2 sessioni reali per setup. Ora tutti i config_*.toml hanno `dry_run = false`
  e `[exposure_dynamic].enabled = true`. Osservare sulla dashboard:
  - pannello "Esposizione Dinamica": cambio stato e countdown cooldown
  - pannello "Escalation Gate": quando RA/DEC mostrano SATURATE
  - triangoli gialli (UP) e verdi (DOWN) sul grafico RMS
  Tarare `spike_min`, `hfd_min_arcsec`, `cooldown_s` in base alla frequenza
  dei trigger osservata nei `decisions_*.jsonl`.

## Workflow operativo per il nuovo agente AI

Se riprendi da questa conversazione:
1. L'ambiente è già pronto (Python 3.12, pip, PyInstaller tutto installato)
2. Il pacchetto compilato è in Pacchetto_Distribuzione/ e come ZIP (101 MB)
3. I prossimi task sono sessioni LIVE su campo (tutti i config già LIVE)
4. NON modificare la logica del codice senza prima discutere con Alessandro
5. NON cambiare dry_run = false nei config senza esplicita autorizzazione
6. MAI toccare la backlash compensation di PHD2
7. OGNI modifica a un .py richiede rebuild + copia file extra (vedi sotto)

## Come avviare per setup specifico
```
Doppio click su Avvia_Askar71F.bat      (490mm, AM5)
Doppio click su Avvia_Tecnosky115.bat   (800mm, AM5/CEM70G)
Doppio click su Avvia_RC8.bat           (1624mm, CEM70G)
```
Oppure da PowerShell:
```powershell
cd Pacchetto_Distribuzione
.\PHD2_Agent.exe --config config_askar71f.toml
```

## Procedura post-modifica sorgente (IMPORTANTE)
build_dist.py ricrea Pacchetto_Distribuzione da zero — dopo ogni rebuild:
1. `python build_dist.py`
2. Copiare `config_rc8.toml`, `config_tecnosky115.toml`, `config_askar71f.toml`
3. Copiare `Avvia_*.bat` e `Sblocca_Firewall_8080.bat`
4. Ripristinare `LEGGIMI_PER_AVVIARE.txt` (build_dist.py lo sovrascrive con uno stub)
5. Ricreare ZIP con `[System.IO.Compression.ZipFile]::CreateFromDirectory(...)`

## Politica di sicurezza
- L'agente in LIVE può modificare parametri di guida del telescopio.
  Testare SEMPRE in DRY_RUN prima di passare a LIVE.
- Ordine consigliato per il passaggio a LIVE:
  Askar 71F → Tecnosky 115 → RC8 (dal più tollerante al più critico).
- Il config.toml di default ha dry_run = true, NON cambiarlo.
- Mai toccare la backlash compensation di PHD2.

## Riferimento tecnico
Il pacchetto è stato preparato in conversazione con Claude (Anthropic) sulla
chat web claude.ai. Quella conversazione contiene il dettaglio tecnico
completo delle patch. Se servono chiarimenti su scelte di design specifiche,
Alessandro può recuperarle da quella chat.
