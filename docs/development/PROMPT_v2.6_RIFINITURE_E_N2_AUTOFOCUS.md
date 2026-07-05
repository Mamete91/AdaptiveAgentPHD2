# PROMPT per Claude Code — rifiniture v2.6: freschezza telemetria + aggressività 100 + baseline continua/bidirezionale (CAP mantenuto)

> **Campo (Minixz100 / NINA 3.3, 71F): TUTTO FUNZIONA.** Telemetria NINA reale su `/status.nina` (HFR 1.91, star 122, ADU, filtro; `eccentricity:null` come previsto su DLL 3.2). `jitter_ref` dinamico. GUARDIAN ha fatto la prima micro su SEEING reale. §38/§39 validati su 3.3.
>
> **Scoperta dai log (sessione `223204`) — è la motivazione di C:** l'ammorbidimento leve (aggr 70→68, MinMove 0.2→0.22) è avvenuto con **cap NON attivo** (`rms_high`=0.704, baseline 0.541, `rms_high_cap_active:false`). Causa reale: con seeing in peggioramento la **baseline non è potuta salire** (regola "tightest-wins" del §25 + formazione una-tantum) → `rms_high` inchiodato a 0.704 → RMS legittimi per quel seeing letti come SEEING → softening. **Il driver è la baseline che non traccia il peggioramento, NON il cap.**
>
> **Decisione (Alessandro + Cowork, 2026-06-19):** il **CAP resta** (la sua rimozione era un'ipotesi scartata: nei dati non era lui il problema, e fa da tetto di sicurezza). La fix che conta è rendere la **baseline a rinnovo CONTINUO e BIDIREZIONALE** (può **salire** col peggiorare del seeing, stringersi col migliorare). Dall'idea iniziale resta solo il **rinnovo ciclico senza soste**.
> **Numerazione:** `grep "^## [0-9]" NOTE_CLAUDE.md | tail -1` → atteso §42 → **§43** (A+B), **§44** (C). Verifica.
> **Direttiva permanente:** lato NINA consultare il sorgente GitHub **al tag di release** + i docs ufficiali `https://nighttime-imaging.eu/docs/master/site/`.
> Contesto: `VALIDAZIONE_CAMPO_v2.6.md`, `PRINCIPIO_CONVERGENZA_PRESTAZIONE.md` (P1), `ACCERTAMENTO_BASELINE_SEMPRE.md`.

---

## A (§43a) — Finestra di freschezza telemetria ADATTIVA alla posa  [Agente]
**Problema (dato reale):** `/status.nina.connected:false`, `last_age_s:197.9`, pose **300 s** ma `staleness_seconds=180` → falso "disconnesso" per ~120 s di ogni posa.
**Fix in `phd2_agent/nina_telemetry.py` + config:**
1. Finestra adattiva: `effective_window = max(staleness_seconds, staleness_exposure_factor × last_exposure_s)` (`last_exposure_s` = `image.exposure_s` dell'ultimo payload). Applicare a `is_fresh` e `status_block()`.
2. Graceful: senza `exposure_s` → solo `staleness_seconds`.
3. `[nina_telemetry] staleness_exposure_factor = 1.5` (attiva); `staleness_seconds=180` resta pavimento; parsing in `load_config`.
**Test:** `exposure_s=300` → fresco fino a ~450 s; senza `exposure_s` → 180; suite verde.

## B (§43b) — Cap aggressività 90 → 100  [solo config]
1. `[limits.ra]` e `[limits.dec]`: `aggr_max` 90 → **100**. È un tetto (CASO3/satisfaction-gate/OVERCORRECTION governano il valore reale).
2. **NON toccare `minmove_max`** — resta **0.85** (MinMove è una distanza px/arcsec, non %; 100 disattiverebbe la guida).
**Test:** aggressività può salire a 100; MinMove cap invariato; suite verde.

## C (§44) — Baseline a rinnovo CONTINUO e BIDIREZIONALE (CAP mantenuto)  [Agente — cuore della fix]

Obiettivo: le soglie devono seguire la **scala reale della notte**. Se il seeing peggiora `rms_high` deve **salire** (così un RMS alto-ma-stabile per quella notte è NOMINAL, non SEEING → niente softening spurio); se migliora deve stringersi.

**C1 — Rinnovo continuo (no attesa).** Sostituire l'attesa `refresh_interval_seconds=1800` con un aggiornamento **continuo** della baseline a ogni ciclo di valutazione, su **finestra mobile** (riusa lo stimatore best-fraction §33/§38; `baseline_window_frames` come ampiezza). Niente pause tra una valutazione e l'altra. Importante: aggiornamento **liscio** (best-fraction su finestra, non scatti per singolo frame) per non far "ballare" le soglie.

**C2 — Bidirezionale (il punto chiave).** **Rimuovere il vincolo "tightest-wins"** (`refresh_only_if_tighter`): la baseline aggiornata **sostituisce** la corrente sia se più stretta sia se **più larga**, così traccia il peggioramento. ⚠️ È questo che realizza l'obiettivo: tenere tightest-wins + continuo inchioderebbe la baseline ancora più bassa e **peggiorerebbe** il softening (è il meccanismo trovato nei log). Kill-switch `[auto_calibration] baseline_track_bidirectional` (default **true** = nuovo; `false` ripristina tightest-wins per A/B).

**C3 — CAP MANTENUTO.** **NON rimuovere** il cap §24: `rms_high_active = min(rms_high_factor × baseline_median, cap)` resta. Il cap continua a fare da **tetto di sicurezza** contro soglie troppo larghe (complacency / setup rotto / caso cercatore-guida). **Interazione voluta:** con baseline bidirezionale, `rms_high` segue le condizioni **fino al tetto del cap** (≈1,00″ sul 71F) — copre il caso comune osservato (223204, dove il cap non mordeva); sopra quel tetto il cap resta come backstop assoluto. Le due cose si completano.

**Backstop mantenuti (NON toccare):** gate di **rifiuto baseline §23** (`reject se baseline > max(1.50, 3.0×pixel_scale)`), **anti-inversione** `rms_low ≤ rms_high×0.85`, formazione baseline §33/§40, esclusione implosion.

**Test (Code DEVE validare):**
1. **Peggioramento sotto il cap:** RMS che cresce con baseline che resta < ~0,77″ → la baseline **sale** in continuo → `rms_high` sale (es. 0.70→0.85) → RMS alti-ma-stabili NON più classificati SEEING (niente softening spurio). Confronto col vecchio (tightest-wins): baseline inchiodata → SEEING spurio (riproduce 223204).
2. **Miglioramento:** RMS cala → baseline si **stringe** → soglie più severe.
3. **Cap ancora efficace:** baseline_median 0,90″ → `rms_high_factor×baseline`=1,17 ma **cap lo limita a 1,00** (`rms_high_cap_active:true`) — il cap fa il suo lavoro come oggi. Baseline assurda (oltre §23) → rifiutata; anti-inversione attiva.
4. **Kill-switch:** `baseline_track_bidirectional=false` → comportamento pre-§44 (tightest-wins). Suite verde.

---

## REGOLE / CHIUSURA
- **NON toccare:** backlash, logica leve/motore §31, telemetria §41/§42, formazione baseline §33/§40, **cap §24**, gate rifiuto §23, anti-inversione.
- Born-operative: chiavi nuove attive nel `config.toml` (A,B attive; `baseline_track_bidirectional=true`; cap invariato).
- **DOC:** `NOTE_CLAUDE.md` §43 (freschezza + aggr 100) e §44 (baseline continua/bidirezionale; citare l'evidenza log: tightest-wins era il driver, non il cap; cap mantenuto come tetto; §23/anti-inversione backstop) + `CONTESTO_PROGETTO.md`.
- **REBUILD DEL PACCHETTO (obbligatorio per la validazione di campo):** dopo le modifiche ai sorgenti:
  1. `python build_dist.py` → rigenera `Pacchetto_Distribuzione/` + `Adaptive_Agent_PHD2_v2.6.zip`.
  2. **Verifica che il `config.toml` DENTRO il pacchetto** abbia le chiavi nuove **attive**: `aggr_max=100` (RA+DEC), `baseline_track_bidirectional=true`, `staleness_exposure_factor=1.5`, oltre a tutte le §36–§42 (`convert_distance_to_arcsec=true`, `hfd_gates_seeing=false`, `refs_always_form=true`, `preserve_refs_on_dither=true`, `baseline_min_snr=6.0`, `[nina_telemetry] enabled=true`). NON deve restare `aggr_max=90`.
  3. Ripristina `LEGGIMI_PER_AVVIARE.txt` se `build_dist.py` lo sovrascrive con lo stub; verifica `Avvia.bat` + `Sblocca_Firewall_8080.bat` presenti.
  4. Conferma data/ora fresca di `PHD2_Agent.exe` e che lo ZIP sia rigenerato.
- **Niente commit/push** (prompt git dedicato).

## CHECKLIST
- [ ] A: freschezza adattiva (`max(staleness_seconds, 1.5×exposure_s)`); `staleness_exposure_factor` nel TOML+parsing; graceful; test verdi.
- [ ] B: `aggr_max` 90→100 (RA+DEC); `minmove_max` invariato 0.85; test verdi.
- [ ] C1: baseline aggiornata in continuo (no attesa 1800 s), su finestra mobile, liscia.
- [ ] C2: bidirezionale (tightest-wins rimosso; baseline può salire); kill-switch `baseline_track_bidirectional` (default true).
- [ ] C3: **cap §24 MANTENUTO** (`min(..., cap)` intatto); gate rifiuto §23 + anti-inversione intatti.
- [ ] Test 1–4 (peggioramento sotto cap→baseline sale→no SEEING spurio; miglioramento→stringe; cap ancora efficace sopra soglia; kill-switch).
- [ ] Nessuna regressione §24/§31/§33/§40/§41/§42; doc §43+§44; niente commit.

---

## N2 (context-gating autofocus) — PARCHEGGIATO
Doc ufficiale NINA (*AF Disable Guiding*): "For OAG or belt focuser users, it may be better to have this option set to On." Con quel flag **ON** (config di Alessandro) la guida si ferma durante l'autofocus → l'Agente si ferma da solo → N2 ridondante. Fallback a bassa priorità per chi tiene il flag OFF.

> **P1:** la baseline bidirezionale è "convergere verso la prestazione raggiungibile **date le condizioni di adesso**", non combattere il seeing contro una scala vecchia. Il cap resta come tetto assoluto di buon senso; la distinzione fine "seeing (non fixabile) vs setup (fixabile)" resta il lavoro di N3/N8 (telemetria NINA).
