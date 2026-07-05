# PROMPT per Claude Code — Dashboard: aggiungere card "Adaptive MinMove" (§51) + rimuovere card "Oscillation"

> **Due modifiche di dashboard, solo frontend:** (A) AGGIUNGERE la card "Adaptive MinMove" (visibilità live del §51); (B) RIMUOVERE la card "Oscillation" dalla dashboard principale (il progetto è ormai **Outcome-First**: il ramo oscillazioni è disattivato di default → la sua card mostra una logica superata = rumore visivo / effetto "albero di Natale"). Entrambe a rischio nullo sul motore.

> **Motivazione (metodologia live):** il §51 espone già `/status.minmove_cap` ma la **dashboard non lo mostra**. Per la regola "rendere osservabili le nuove logiche in diretta prima di validarle", serve la card grafica: durante le notti si deve vedere in tempo reale **cap corrente, baseline filtrata, quale termine vince (guiding/imaging), MinMove efficace per asse** — senza analizzare i log a posteriori.
> **Quasi tutto frontend + UNA piccola aggiunta backend** (il flag `clamping_active` sul blocco `/status.minmove_cap`, vedi §0-bis): serve per il badge ACTIVE **corretto**. Basso rischio, nessun cambio alla logica leve. **Niente commit/push.**
> Contesto: `controller.py` (i punti dove il §51 applica il `min()` sul MinMove), `dashboard/app.js` + `index.html` + `style.css`. Riusa il pattern delle card esistenti (`auto_calibration`, `diagnostic_engine`, `transparency`).

## FASE 0 (sola lettura)
1. Confermare i **nomi reali dei campi** in `/status.minmove_cap` (li hai creati tu nel §51): cap in arcsec e px, `winning` (guiding/imaging), baseline §44 filtrata, MinMove efficace per asse (RA/DEC). Riportarli.
2. Individuare i punti dove il §51 applica il cap (`min(...)`) sul MinMove **in salita** (CASO1, §32 recovery, GUARDIAN/jitter `_apply_proposal`): lì si può sapere se una richiesta di salita è stata **effettivamente tagliata** dal cap.
3. Individuare come le card esistenti (es. `auto_calibration`) leggono `/status` in `app.js` e si renderizzano in `index.html`/`style.css` → riusare lo stesso schema.
4. Con `minmove_cap_adaptive_enabled=false` o dati assenti il blocco può mancare → la card deve degradare con grazia (mostra "—"/"non attivo", nessun errore JS).

## §0-bis — Backend: flag `clamping_active` (per il badge ACTIVE corretto)
**Perché:** ACTIVE ≠ "MinMove == cap". Il MinMove può *coincidere* col cap senza che il controllore stia chiedendo di salire → in quel caso il cap **non** sta limitando nulla. ACTIVE vero = **il controllore ha richiesto un MinMove più alto del cap e il cap l'ha tagliato** (clamping attivo).
- Nei punti del §51 dove si applica `effective = min(requested, cap)`: registrare **se `requested > cap`** (clamping è scattato) su almeno un asse, con breve persistenza (es. ultimi N tick / cooldown, per non far lampeggiare il badge).
- Esporre su `/status.minmove_cap` un flag **`clamping_active`** (bool) — ed eventualmente per-asse. **Nessun cambio alla logica di clamp** (già c'è): si aggiunge solo la registrazione del fatto.
**Test:** richiesta MinMove-up > cap → `clamping_active=true`; MinMove che coincide col cap ma senza richiesta di salita → `clamping_active=false`; nessuna richiesta di salita → false.

## IMPLEMENTAZIONE — card "Adaptive MinMove" (Auto-calibrazione area, accanto alla baseline)
Titolo **"Adaptive MinMove"** (non "Cap": all'utente interessa *come il motore sta gestendo il MinMove ora*, non il cap in sé). Mostrare, aggiornati in tempo reale dal poll `/status`:
- **Badge di stato ACTIVE / IDLE (in alto, colorato) — l'elemento più importante:** guidato dal flag **`clamping_active`** (§0-bis), NON da "MinMove == cap". 🟠 **ACTIVE** (arancione) quando il controllore ha richiesto un MinMove più alto del cap e il cap l'ha **tagliato** (clamping attivo); 🟢 **IDLE** (verde) quando il controllore opera senza limitazioni del cap. Deve dire a colpo d'occhio *"adesso il cap è intervenuto"* **senza far confrontare mentalmente cap vs MinMove**. **Tooltip** (hover): ACTIVE → *"Il MinMove richiesto dal controllore è stato limitato dal cap adattivo"*; IDLE → *"Il controllore sta operando senza limitazioni del cap adattivo"*.
- **Cap corrente:** `cap_arcsec` (e `cap_px` tra parentesi).
- **Baseline filtrata:** il valore §44 filtrato su cui è costruito il cap (così si vede che segue lentamente la notte).
- **Termine vincente:** badge **GUIDING** vs **IMAGING** (quale dei due `min()` sta limitando), colore diverso. **Con tooltip** (hover): GUIDING → *"Il limite è attualmente determinato dalla baseline di guida"*; IMAGING → *"Il limite è determinato dal requisito di imaging del setup"*. Così i beta tester capiscono subito la causa.
- **MinMove efficace RA / DEC:** il dead-band reale per asse in arcsec (per confronto col cap).
- (Opzionale, se semplice) mostrare `k` e `imaging_ceiling` correnti come riferimento.

**Graceful:** `minmove_cap` assente/kill-switch off → card mostra "non attivo"/"—" (badge IDLE grigio), nessun crash.
**(Opzionale, nice-to-have):** un marcatore sul Grafico di Guida quando il cap passa a "attivo" (limita il MinMove). Solo se riusa il meccanismo di marcatori già presente; altrimenti rimandare.

## RIMOZIONE — card "Oscillation" dalla dashboard principale (Outcome-First)
1. Individuare la card/blocco dell'esperimento oscillazioni in `app.js`/`index.html` (il blocco che consuma `/status.oscillation_experiment` — la card "Oscillazione"/"Oscillation experiment"). **NON** confondere con la card `diagnostic_engine` (che resta: è la diagnosi del motore, operativa).
2. **Rimuovere la card dalla vista principale** (HTML + il codice di rendering in `app.js` + eventuale CSS dedicato).
3. **NON toccare il backend:** il campo `/status.oscillation_experiment` **resta** (per log e analisi future; chi vuole lo legge dal JSON grezzo). Nessuna modifica a controller/motore. Non serve una "modalità Developer" ora (YAGNI): rimuovere la sola card visiva è sufficiente e coerente con l'obiettivo "dashboard focalizzata sull'operativo".
4. Verificare che la rimozione non lasci riferimenti pendenti (nessun errore JS se `oscillation_experiment` è ancora nel JSON ma non più renderizzato).

## TEST / VERIFICA
1. Con Agente attivo e `minmove_cap` presente → la card "Adaptive MinMove" mostra badge ACTIVE/IDLE, cap, baseline filtrata, winner, MinMove efficace RA/DEC, aggiornati al poll.
2. **Badge ACTIVE (arancione)** guidato da `clamping_active=true` (richiesta MinMove-up tagliata dal cap); **IDLE (verde)** quando `clamping_active=false` — anche se MinMove coincide col cap senza richiesta di salita. Tooltip ACTIVE/IDLE all'hover.
3. Badge winner GUIDING/IMAGING corretto (vs JSON `/status.minmove_cap`); tooltip visibile all'hover.
4. `minmove_cap_adaptive_enabled=false` / dato assente → "non attivo" (IDLE grigio), nessun errore console.
5. **Card Oscillation NON più presente** nella dashboard; `diagnostic_engine` e le altre card intatte; nessun errore console anche se `/status.oscillation_experiment` è ancora nel JSON.

## PRINCIPIO DI PROGETTO (dashboard) — da rispettare qui e in futuro
**La dashboard mostra ESCLUSIVAMENTE informazioni operative utili durante una sessione di acquisizione. Le logiche sperimentali possono restare disponibili nel backend (`/status`) e nei log, ma NON devono affollare la vista principale.** (È esattamente ciò che si fa qui: via la card Oscillation sperimentale, dentro Adaptive MinMove operativa.) Vista risultante: RMS · Diagnosi · Transparency · Adaptive MinMove · Guardian/Safety · Auto-Calibrazione — ogni card risponde a una domanda operativa precisa.

## CHIUSURA
- `dashboard/` + il solo flag `clamping_active` su `/status.minmove_cap` (§0-bis). Nessun cambio alla logica leve; il campo `/status.oscillation_experiment` resta; nessuna regressione alle altre card.
- **REBUILD:** il flag `clamping_active` (§0-bis) tocca il backend → `python build_dist.py` (rigenera l'exe); allineare la copia `dashboard/` nel pacchetto. Verificare che `/status.minmove_cap.clamping_active` sia nel pacchetto.
- **NOTA cache (importante):** dopo l'update, hard-refresh (Ctrl+Shift+R) o il pannello NINA WebView2 può restare sulla versione cached.
- **DOC:** breve nota in `NOTE_CLAUDE.md` (card "Adaptive MinMove" §51 aggiunta; card Oscillation rimossa dalla dashboard, backend intatto, coerente con Outcome-First) + `VALIDAZIONE_CAMPO_v2.6.md`. Niente commit/push.

## CHECKLIST
- [ ] FASE 0: nomi reali campi `/status.minmove_cap`; punti di clamp §51 individuati; pattern card; graceful.
- [ ] §0-bis: flag `clamping_active` su `/status.minmove_cap` (true solo se richiesta MinMove-up > cap tagliata; persistenza anti-flicker); nessun cambio alla logica di clamp; test.
- [ ] Card "Adaptive MinMove": **badge ACTIVE/IDLE (da `clamping_active`, colorato, con tooltip)**, cap arcsec(+px), baseline filtrata, badge GUIDING/IMAGING **con tooltip**, MinMove efficace RA/DEC; aggiornata live.
- [ ] Graceful (kill-switch off / dato assente → "non attivo"); nessun errore JS.
- [ ] (Opz.) marcatore grafico quando il cap limita.
- [ ] **Card Oscillation rimossa** dalla vista principale; `diagnostic_engine`/altre card intatte; **backend `/status.oscillation_experiment` NON toccato**; nessun errore JS.
- [ ] Copia `dashboard/` del pacchetto allineata (se presente); nota cache; doc; niente commit.

> **Perché conta:** il §51 tocca una leva reale (il MinMove). Renderlo visibile in diretta — cap che sale/scende con la notte, termine che vince, dead-band effettivo — è ciò che ti permette di **validarlo sul cielo** invece che sui log, coerente con tutto l'approccio del progetto.
