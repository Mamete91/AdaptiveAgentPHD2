# PROMPT per Claude Code — Deprecare la modalità JITTER: rimuoverla dal toggle dashboard + guard-rail backend

> **OBIETTIVO.** La modalità di guida ufficiale è **GUARDIAN** (con **OFF** come A/B legittimo). La modalità **JITTER** (motore §31 unica autorità sulle leve, catena CASO 1/2/3 **sospesa**) è **deprecata/sperimentale e mai validata sul campo**: scavalca tutto il controllore outcome-first validato (§44 baseline bidirezionale, §50 INIT, §51 cap, **§53 recupero simmetrico**, §32, satisfaction-gate §30). Oggi è attivabile **a un clic dalla dashboard** (toggle OFF/GUARDIAN/JITTER) → rischio concreto che io o un beta-tester ci finisca per sbaglio. Va resa **non attivabile per errore**.
>
> **Cosa NON è in discussione:** il **motore diagnostico §31** e la modalità **GUARDIAN** (supervisione: conferma/attenua/blocca + micro-correzioni) restano. Si deprecano **solo la MODALITÀ jitter** (engine-owns-levers) e la sua esposizione in dashboard. **Non cancellare** il codice jitter: resta dormiente, raggiungibile solo con flag esplicito per un'eventuale validazione deliberata futura.
>
> **Coerente col principio dashboard già adottato** (rimozione card Oscillation, "PRINCIPIO DI PROGETTO (dashboard)" del prompt §51): la vista principale mostra **solo logica operativa e validata**.

## FASE 0 — PRE-FLIGHT (sola lettura)
1. `dashboard/app.js` — lo switcher costruito iterando **`['off','guardian','jitter']`** (≈L755 render e ≈L863 handler di click) + il ramo `confirm()` specifico jitter (≈L868-869) + il badge modalità (≈L672-673).
2. `dashboard/index.html` — i bottoni del toggle "Modalità" (≈L381-387): `diag-btn-guardian`, **`diag-btn-jitter`** (`data-mode="jitter"`).
3. `dashboard/style.css` — `.diag-mode-badge.mode-jitter` (≈L845) e lo switcher (≈L907).
4. `server.py` — endpoint **`POST /config/diagnostic_mode`** → `set_diagnostic_mode(payload)`, `DiagModePayload.mode` ("off"|"jitter"|"guardian"), gate `allow_dashboard_mode_switch`.
5. `phd2_agent/controller.py` — `set_diagnostic_mode(...)`, `_engine_owns_levers()` (=enabled & mode=="jitter" → CASO sospesi), `_guardian_active()`.
6. `phd2_agent/config.py` — `DiagnosticEngineConfig.mode` + la validazione (≈L596-599: valore ignoto → fallback `guardian` con WARNING). Qui va aggiunto il flag `allow_experimental_jitter`.

## §1 — Frontend: rimuovere JITTER dal toggle (lasciare OFF / GUARDIAN)
- In `app.js`: cambiare le due liste **`['off','guardian','jitter']` → `['off','guardian']`** (render switcher + handler). Rimuovere il ramo `confirm()` specifico di jitter (≈L868-869). Lasciare il `confirm()` di GUARDIAN.
- In `index.html`: rimuovere il bottone **`diag-btn-jitter`** (`data-mode="jitter"`). Lasciare OFF e GUARDIAN.
- **Graceful:** se per qualunque motivo il backend riportasse ancora `mode="jitter"` (config legacy), il badge non deve rompersi: mostrarlo come **"JITTER (deprecato)"** o mapparlo visivamente a uno stato neutro, **senza** ricreare il bottone. Nessun errore JS. Il CSS `mode-jitter` può restare (innocuo).

## §2 — Backend: guard-rail (difesa in profondità, oltre alla UI)
Anche senza il bottone, l'endpoint/API e i config legacy potrebbero veicolare `jitter` → va intercettato:
- Nuovo flag `DiagnosticEngineConfig.allow_experimental_jitter: bool = False` (config.toml, default **false**, con commento: "sblocca la modalità jitter DEPRECATA/sperimentale, mai validata; scavalca CASO/§44/§50/§51/§53").
- **`set_diagnostic_mode("jitter")` e la validazione config:** se `mode=="jitter"` e **NOT** `allow_experimental_jitter` → forzare **`guardian`** con **WARNING prominente** nel log (es. "modalità JITTER deprecata e non validata — scavalca §44/§50/§51/§53; ignorata, uso GUARDIAN. Per esercitarla deliberatamente impostare allow_experimental_jitter=true"). L'endpoint deve **ritornare la modalità EFFETTIVA** (guardian) così la UI riflette la realtà.
- Se `allow_experimental_jitter=true` → jitter viene onorata (percorso deliberato per una futura validazione live dedicata). **Il ramo/codice jitter resta invariato e funzionante**, solo gated.
- **Non toccare** la logica di `_engine_owns_levers()`/CASO/§53: si aggiunge solo il gate a monte sulla selezione della modalità.

## §3 — TEST (`tests/test_jitter_deprecation.py`)
1. `set_diagnostic_mode("jitter")` con `allow_experimental_jitter=false` → modalità effettiva = `guardian`, WARNING loggato, valore di ritorno = guardian.
2. `allow_experimental_jitter=true` + `mode="jitter"` → jitter onorata (`_engine_owns_levers()` True) — il percorso deliberato resta funzionante.
3. `mode="off"` e `mode="guardian"` invariati (nessuna regressione).
4. Config con `mode="jitter"` e flag assente/false → caricamento con fallback guardian + warning (nessun crash).
5. Nessuna regressione ai test esistenti di guardian/§53/§44/§50/§51.

## §4 — DOC + CHIUSURA
- **NOTE_CLAUDE.md**: verifica `grep "^## [0-9]" NOTE_CLAUDE.md | tail -1` (atteso §53) → nuova sezione **§54 "Deprecazione modalità JITTER: rimossa dal toggle dashboard + guard-rail backend (allow_experimental_jitter); GUARDIAN modalità ufficiale, OFF A/B legittimo"**. Motivare: jitter scavalca il controllore validato, mai validata, era a un clic.
- **CONTESTO_PROGETTO.md**: registrare che la modalità ufficiale è GUARDIAN; JITTER deprecata/sperimentale dietro flag.
- **REBUILD:** il flag/guard tocca il backend → `python build_dist.py`; allineare la copia `dashboard/` nel pacchetto; verificare che `allow_experimental_jitter` sia nel `config.toml` del pacchetto. Nota cache WebView (Ctrl+Shift+R).
- **Niente commit/push.**

## CHECKLIST
- [ ] FASE 0: switcher app.js (L≈755/863), bottone index.html `diag-btn-jitter`, endpoint `/config/diagnostic_mode`, `set_diagnostic_mode`, validazione config + punto d'inserimento del flag — individuati.
- [ ] §1 frontend: liste `['off','guardian']`, bottone jitter rimosso, confirm jitter rimosso, badge graceful su mode legacy, nessun errore JS.
- [ ] §2 backend: flag `allow_experimental_jitter` (default false); jitter→guardian+WARNING quando flag off; ritorno modalità effettiva; jitter onorata solo con flag on; codice jitter NON cancellato.
- [ ] §3 test `test_jitter_deprecation.py` (5 casi) verdi; nessuna regressione guardian/§53/§44/§50/§51.
- [ ] §4 REBUILD + flag nel pacchetto + dashboard allineata + nota cache; NOTE_CLAUDE §54 (numerazione verificata) + CONTESTO; niente commit.

> **Perché conta:** JITTER a un clic è l'unico modo per cui, per sbaglio, tutta la macchina outcome-first (fino a §53) verrebbe sospesa in favore di un motore mai validato. Toglierla dalla vista e metterla dietro un flag esplicito protegge te e i beta-tester, senza perdere la possibilità di esercitarla in futuro in modo deliberato e controllato.
