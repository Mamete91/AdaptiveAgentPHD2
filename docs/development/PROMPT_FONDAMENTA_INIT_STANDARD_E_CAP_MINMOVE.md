# PROMPT per Claude Code — Fondamenta del motore: (A) Init ai valori standard PHD2 + (B) Cap MinMove adattivo

> **Due principi architetturali del motore (non sperimentazioni), trasversali a Outcome-First/Guardian/NINA.** Da mettere prima di nuove logiche decisionali. Ciclo di vita:
> `Connessione PHD2 → Calibrazione → Inizio guida → (A) INIT ai valori standard PHD2 → Formazione baseline → (B) Cap MinMove adattivo → Agent attivo`
> **A** garantisce uno **stato iniziale noto** (→ log confrontabili tra tutti i beta tester); **B** impedisce al motore di uscire dalla regione ottimale (MinMove che ignora errori ancora correggibili).
> **Due sezioni, kill-switch SEPARATI** (ognuna validabile/reversibile a sé). Metodologia (`METODOLOGIA_VALIDAZIONE_LIVE.md`): operativo, visibile, reversibile. Nuove chiavi attive nel `config.toml`.
> **Numerazione:** `grep "^## [0-9]" NOTE_CLAUDE.md | tail -1` → due § liberi. Verifica.
> Contesto: `controller.py` (avvio guida, calibrazione, Baseline Guardian, `aggr_native_scale` del §ref, baseline §44 bidirezionale, §32 minmove-recovery), `config.py [limits]`, [[phd2-rms-unit-bug]] (§36, lezione scala). Supersede lo schizzo cap `§0` di `PROMPT_DISCRIMINATORE_OSCILLAZIONE_OUTCOME.md`.

## FASE 0 — VERIFICA (sola lettura, riportare)
1. Flusso avvio guida: dove il controller rileva calibrazione, legge/setta le leve, e dove **inizia la formazione della baseline**. Il punto di INIT è **dopo calibrazione, prima della baseline**.
2. **Baseline Guardian** esistente (save/restore/orphan): riusarlo per salvare i valori PHD2 utente all'INIT e ripristinarli allo shutdown pulito.
3. **`aggr_native_scale`** (fix §ref): Hysteresis/Resist Switch espongono aggression in **0.0–1.0** → 70→0.70, 100→1.00. L'INIT deve usare questa conversione. Riportare come si rileva l'**algoritmo di guida** attivo per asse (Hysteresis / Resist Switch / altro).
4. **Baseline §44** (bidirezionale): valore/provider correnti, per costruirci sopra il filtro temporale del cap.

## §A — INIT ai valori standard PHD2 (stato iniziale noto)
All'inizio della guida, **dopo la calibrazione e prima della formazione della baseline**:
1. **Salva** i valori leva correnti dell'utente (via Baseline Guardian) per il ripristino allo shutdown pulito.
2. **Imposta i valori standard** (con `aggr_native_scale`):
   - **RA (Hysteresis):** Aggressiveness **70** (→0.70 native), MinMove **0.20**
   - **DEC (Resist Switch):** Aggressiveness **100** (→1.00 native), MinMove **0.20**
3. **Algoritmo-aware:** applica i default SOLO se l'algoritmo dell'asse è quello atteso (Hysteresis RA / Resist Switch DEC). Se l'utente usa un algoritmo diverso → **NON forzare valori a scala sbagliata**: logga un WARNING e salta l'INIT di quell'asse (fail-safe).
4. **Poi** procede la formazione baseline / osservazione / adattamento, tutti a partire dallo stato noto.
5. **Ripristino:** allo shutdown pulito, ripristina i valori utente salvati (Baseline Guardian). In caso di kill brutale, l'orphan-recovery esistente li recupera.
6. Kill-switch `[control] init_to_phd2_standard=true` (a `false` = eredita come oggi). Logga i valori impostati (per la tracciabilità nei log dei tester).
**Test:** all'avvio le leve diventano 70/0.20 (RA) e 100/0.20 (DEC) in native scale corretta; algoritmo non-standard → skip + warning, nessun valore fuori scala; shutdown pulito → valori utente ripristinati; kill-switch off → eredita come oggi. Suite verde.

## §B — CAP MINMOVE ADATTIVO (riferimento = baseline §44 FILTRATA nel tempo)
**Riferimento (deciso insieme):** NON la baseline iniziale (fotografa solo l'avvio → troppo restrittiva o troppo permissiva quando le condizioni cambiano), NON il valore istantaneo (rincorre il seeing). **Sì la baseline §44 FILTRATA temporalmente** (EMA/rolling su **~decine di minuti**, costante di tempo config): rappresenta la capacità reale media del setup in quella notte e segue lentamente l'evoluzione senza inseguire le fluttuazioni.

**Formula:** `minmove_cap_arcsec = min( k × baseline_§44_filtrata , minmove_imaging_ceiling_arcsec )`, poi `cap_px = cap_arcsec / pixel_scale`.
- **`k` UNIVERSALE < 1** (default **~0.8**): è un **rapporto** (dead-band ÷ RMS raggiungibile) → **scale-indipendente per costruzione** → uguale per tutti i setup. k<1 tiene il dead-band una frazione dell'RMS raggiungibile (non fabbrica RMS, niente feedback cap↔baseline).
- **`minmove_imaging_ceiling_arcsec` = requisito di imaging (stub di N5), setup-dependent:** quanto errore è tollerabile prima di essere visibile nell'immagine finale (dipende da scala di **ripresa** + durata posa; RC8 0,5"/px più stringente di un rifrattore corto 2"/px). **In v1: valore per-setup nel config** (default generoso). In futuro derivato da scala imaging + durata posa (N5 completo). È il secondo tetto: **la dipendenza dalla scala entra QUI, non in k.**
- **Filtro temporale:** `baseline_filter_tau_minutes` (default ~15–20). Fallback: finché la baseline filtrata non è pronta → cap px legacy / default.
- Applicare su **entrambi gli assi** e a **TUTTI** i punti che alzano il MinMove (§32 recovery + micro GUARDIAN).
- **Esporre su `/status`/log:** MinMove efficace in arcsec, il cap corrente in arcsec, e quale dei due termini sta vincendo (guiding vs imaging).
- Kill-switch `[limits] minmove_cap_adaptive_enabled=true`.
**Test:** baseline filtrata 0,5" → cap 0,4" (k 0,8) → MinMove ≤0,4" (mai 1,3"); baseline sale lentamente in nottata (seeing peggiore) → il cap sale con essa (k<1 → resta sotto l'RMS); baseline scende → il cap si stringe; `minmove_imaging_ceiling` più basso della baseline×k (setup esigente) → vince il tetto imaging; valore istantaneo NON usato (solo filtrato); fallback se baseline non pronta; §32/GUARDIAN rispettano il cap; kill-switch off → legacy. Suite verde.

## CHIUSURA
- **NON toccare:** backlash, esposizione, motore diagnostico §31, telemetria §41/§42, baseline §44 (la si LEGGE filtrata, non la si modifica), cap rms_high §24.
- **REBUILD** (`build_dist.py`, config con le nuove chiavi attive: `init_to_phd2_standard`, `minmove_cap_adaptive_enabled`, `minmove_cap_baseline_factor`(k), `minmove_imaging_ceiling_arcsec`, `baseline_filter_tau_minutes`); verifica config nel pacchetto; niente commit/push.
- **DOC:** `NOTE_CLAUDE.md` (§ A INIT + § B cap) + `CONTESTO_PROGETTO.md` + `VALIDAZIONE_CAMPO_v2.6.md`.

## CHECKLIST
- [ ] FASE 0: punto di INIT (post-calibrazione/pre-baseline); Baseline Guardian save/restore; `aggr_native_scale`; rilevazione algoritmo per-asse; baseline §44 provider.
- [ ] §A INIT: salva valori utente; imposta 70/0.20 (RA Hyst→0.70), 100/0.20 (DEC RS→1.00) con conversione scala; algoritmo-aware (skip+warning se diverso); ripristino allo shutdown; kill-switch; logga i valori.
- [ ] §B CAP: `min(k×baseline_§44_filtrata, imaging_ceiling)` → px; **k universale <1**; **imaging_ceiling per-setup (stub N5)**; filtro temporale ~15–20 min; su RA+DEC e tutti i punti che alzano MinMove; effettivo+cap+termine-vincente su /status; fallback; kill-switch.
- [ ] Test A e B; entrambi reversibili; rebuild; nessuna regressione §24/§31/§32/§44/§41-42; doc; niente commit.

> **P1:** (A) un controllore adattivo parte da uno stato noto — così ogni adattamento è attribuibile al motore, non alla configurazione ereditata, e i log dei tester diventano confrontabili. (B) il MinMove può salire per assorbire il seeing, ma mai oltre ciò che il setup può davvero raggiungere (k×baseline filtrata) né oltre ciò che l'immagine tollera (requisito imaging/N5): adattivo ma dentro la regione fisicamente sensata. Due pilastri, non due leve.
