# PROMPT per Claude Code — FIX CRITICO: l'RMS è misurato in PIXEL ma trattato come ARCSEC

> **Bug di unità confermato sul codice (Agente + sorgente PHD2).** L'Agente legge le distanze di guida da PHD2 (che sono in **pixel**) e le tratta/etichetta come **arcsec**, poi le confronta con soglie progettate in **arcsec**. Lo scarto è esattamente il fattore pixel-scale → miscalibrazione, **in direzioni opposte** sui diversi setup (RC8 sovrastima, Askar/Mirko sottostimano).
> **AUTORIZZATO A IMPLEMENTARE** dopo il pre-flight §0 (conferma puntuale: non deve esistere una conversione compensativa altrove). Isolato alla **conversione px→arcsec della misura**. NON ritoccare le soglie/cap (sono già in arcsec → diventano corrette da sole), NON toccare lo scaling dell'aggressività, §31/§32/§33-logica, leve, backlash.
> **Direttiva di progetto:** eventuali nuove chiavi nascono **già attive (`true`) nel `config.toml`** (born operative).
> **Numerazione doc:** `grep "^## [0-9]" NOTE_CLAUDE.md | tail -1` → usa **N+1**.

## 0. PRE-FLIGHT (sola lettura — confermare, poi implementare)

**Prova lato PHD2 (già verificata, citazioni):**
- `phd2-master/phd2-master/src/event_server.cpp:2883-2884` → `RADistanceRaw = step.mountOffset.X`, `DECDistanceRaw = step.mountOffset.Y`. `mountOffset` è in **pixel**.
- `statswindow.cpp:168` → `arcsecs(double px, double sampling){ ... px * sampling ... }` — PHD2 tiene le statistiche RMS in **pixel** e converte in arcsec **solo per il display** (× pixel scale). `graph.cpp:293` → `enable_arcsecs = GetCameraPixelScale() != 1.0` (arcsec è conversione opt-in di visualizzazione).

**Prova lato Agente (già verificata, citazioni):**
- `phd2_agent/analyzer.py:140-141` → `ra_raw=float(event["RADistanceRaw"])`, `dec_raw=float(event["DECDistanceRaw"])`: legge i **pixel** dentro campi commentati "arcsec" (`analyzer.py:43-44,58`). `rms_ra/dec/total` (`analyzer.py:192-194`) risultano in **pixel**. L'Analyzer NON ha la pixel-scale (`__init__` L114) e NON applica conversione.
- Le soglie invece sono in **arcsec** e moltiplicano per `scale = cfg.setup.guide_pixel_scale_arcsec`: reject baseline `max(1.50, 3.0*scale)` (`controller.py:554`), cap rms_high `clamp(2.0*scale, 0.70, 1.00)` (`controller.py:611` + `rms_high_max_arcsec=1.00`), `baseline_fallback_reject_arcsec=4.0`. → **misura (px) confrontata con soglie (arcsec)**. Il fatto che le soglie moltiplichino per `scale` dimostra che il design assumeva la misura in arcsec: manca solo la conversione della misura.

**DA CONFERMARE prima di scrivere:**
1. Che NON esista, da `main.py:277` (`analyzer.ingest_guide_step(event)`) fino al `_compute()`, alcuna moltiplicazione per la scala già applicata alla misura (per evitare doppia conversione). Verificare anche `ingest_star_lost` e qualunque altro punto che legga `RADistanceRaw/DECDistanceRaw/dx/dy/AvgDist`.
2. Che lo scaling dell'aggressività (`controller.py:363,783` `current_aggr*scale` / `/scale`) sia un concetto **diverso** (mapping del parametro aggressività di PHD2), da **NON** toccare.
3. Che `cfg.setup.guide_pixel_scale_arcsec` sia disponibile e **vivo** al momento dell'ingest (property: override da `get_pixel_scale` PHD2 → reduced/native TOML; ritorna scala efficace anche dopo cambio riduttore).

## 1. OBIETTIVO
Convertire le distanze di guida grezze da **pixel → arcsec** al momento dell'ingest, moltiplicando per la pixel-scale efficace **viva**. Così `rms_ra/dec/total`, picchi, `jitter_rms`, trend diventano **arcsec reali** e combaciano con le soglie già progettate in arcsec → niente ritaratura delle soglie.

## 2. SPECIFICA
1. **Punto di conversione:** in `ingest_guide_step` (e `ingest_star_lost` se legge distanze), moltiplicare `ra_raw` e `dec_raw` per la **scala efficace viva**. L'Analyzer deve poter leggere la scala corrente a ogni frame (non fissata all'`__init__`, perché l'override PHD2 può arrivare dopo l'init e la scala può cambiare col riduttore). Soluzione consigliata: passare la scala per-chiamata da `main.py:277` (es. `analyzer.ingest_guide_step(event, pixel_scale=cfg.setup.guide_pixel_scale_arcsec)`) **oppure** dare all'Analyzer un riferimento a `cfg.setup` e leggere la property. Scegliere la via che NON congela la scala all'init.
2. **Conversione unica, niente doppioni:** convertire SOLO la misura grezza (`ra_raw`, `dec_raw`). Tutto il derivato (rms, peak, jitter, trend) eredita arcsec automaticamente. NON convertire una seconda volta a valle.
3. **Scala = 1.0 / assente:** se `guide_pixel_scale_arcsec == 1.0` (caso PHD2 indistinguibile o nessun profilo) la conversione è identità → comportamento invariato, nessun rischio.
4. **Etichette/commenti:** aggiornare i commenti "arcsec" dell'Analyzer perché ora siano **veri** (oggi sono fuorvianti). Le stringhe di log con `"` (arcsec) diventano corrette.
5. **NON toccare le soglie/cap/reject:** sono già in arcsec → con la misura ora in arcsec diventano corrette e coerenti su tutti i setup. Nessuna ritaratura.

## 3. REGOLE INDEROGABILI
- Isolato alla conversione px→arcsec della **misura**. NON toccare: scaling aggressività, §31/§32/§33-logica, leve, backlash, cap/reject/floor.
- Eventuale kill-switch (es. `[analyzer] convert_distance_to_arcsec`) **shipped ON** nel `config.toml`; ma il default e lo shipped sono **CONVERTITO**. (Un fix di correttezza non deve girare col bug.)
- **Schema log:** la conversione cambia le unità dei valori loggati → **bump `schema_version`** e annotare in NOTE, così i replay sanno distinguere log pre/post-fix.
- Retrocompatibilità logica: le soglie restano numericamente identiche nel TOML (sono già arcsec); cambia la **misura**, che ora è corretta.

## 4. IMPATTO ATTESO (dichiararlo in NOTE, è una correzione che sposta i numeri)
- `arcsec = px × scale`. RC8 (0.51"/px): l'RMS visualizzato passa da ~2 a **~1,0"** (guida in realtà buona). Askar (1,58) e Mirko (1,76): gli RMS **salgono** (px < arcsec). 
- Si attende la **fine dei rifiuti baseline "spuri" su RC8** (il gate reject 1,53" confrontava 2,0 px): verificare su replay.

## 5. TEST ATTESI
1. **Unit:** ingest di un GuideStep con `RADistanceRaw=2.0, DECDistanceRaw=0.0` e scala 0.51 → `rms`/`ra_raw` in arcsec = 1,02 (non 2,0). Con scala 1,58 → 3,16. Con scala 1,0 → invariato.
2. **Niente doppia conversione:** un solo `× scale` nel percorso misura.
3. **Scala viva:** se `pixel_scale_override` cambia a runtime, l'ingest successivo usa la nuova scala.
4. **Soglie coerenti:** su RC8 una baseline reale ~1,0" NON viene più rifiutata dal gate (`max(1.50, 3.0*0.51)=1.53"`).
5. **Regressione:** i 145 test esistenti restano verdi (aggiornare quelli che assumevano la misura in px, se presenti).

## 6. VALIDAZIONE SUL CAMPO / REPLAY
- Replay su `session_20260615_000212` (RC8): l'RMS mediano reale ≈ 1,0" (= 2,0 px × 0,51); confermare che baseline e cap ora siano sensati. In campo: la dashboard RC8 deve mostrare ~1" non ~2".

## 7. REBUILD + DOC
`python build_dist.py` → ZIP. `NOTE_CLAUDE.md` **§N+1** ("FIX unità: RMS px→arcsec all'ingest; impatto per-setup; bump schema_version") + `CONTESTO_PROGETTO.md`. Nuove eventuali chiavi **attive nel config.toml**. Niente commit/push.

## 8. CHECKLIST FINALE
- [ ] Pre-flight §0 confermato: nessuna conversione compensativa preesistente; aggressività non toccata.
- [ ] Conversione px→arcsec applicata UNA volta su `ra_raw/dec_raw`, con scala **viva** (non fissata all'init).
- [ ] Soglie/cap/reject NON modificate (diventano corrette da sole).
- [ ] `schema_version` bumpato; commenti/etichette "arcsec" ora veri.
- [ ] Test unit (scala 0.51 / 1.58 / 1.0) + niente doppia conversione + 145 esistenti verdi.
- [ ] Replay `000212`: RMS reale ~1,0" su RC8, baseline non più rifiutata.
- [ ] NOTE §N+1 + CONTESTO aggiornati con l'impatto per-setup; ZIP generato.

> **P1:** un controllore che converge alla prestazione deve **misurare la prestazione nella giusta unità**. Con la misura in pixel e le soglie in arcsec, l'Agente inseguiva un riferimento sbagliato e diverso su ogni setup. Questo fix riallinea misura e soglie — è prerequisito di tutto il resto (baseline, cap, RECOVERY, diagnosi).
