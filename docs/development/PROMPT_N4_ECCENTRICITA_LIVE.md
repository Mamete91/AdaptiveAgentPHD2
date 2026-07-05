# PROMPT per Claude Code — N4: Eccentricità (verifica dell'esito reale) — BLOCCO 2 del filone N1→N8→N4

> **Blocco 2 del filone diagnostico NINA** (`ARCHITETTURA_FILONE_DIAGNOSTICO_NINA.md`). Si consegna **DOPO** che N1/N8 (blocco 1, `PROMPT_N1_N8_FUSIONE_NINA_LIVE.md`) è implementato e validato in diretta — così N4 **riusa l'infrastruttura comune** (baseline per-campo/filtro, persistenza ≥2-3 pose, dead-band, pattern provider→motore, visibilità live) ed è validabile **separatamente**.
> **Ruolo di N4:** l'occhio sull'**esito reale**. PHD2 vede come si muove la stella di guida; N1 il contesto cielo; N8 lo usa nella diagnosi; **N4 misura la forma reale delle stelle sul light frame (eccentricità) → verifica se le decisioni del motore hanno prodotto stelle tonde.** L'RMS è un proxy; l'eccentricità è vicina all'obiettivo vero.
> **In v1 N4 è OSSERVATIVO/di verifica:** misura, mostra, **correla** con le diagnosi del motore. **NON pilota le leve.** (L'uso decisionale e l'eccentricità per-asse RA/DEC = evoluzioni successive.)
> **Metodologia (`METODOLOGIA_VALIDAZIONE_LIVE.md`):** operativo e **visibile in diretta**; reversibile (kill-switch); validazione sul cielo reale.
> **Vincolo versione (decisione architetturale):** il Lenovo è ora **NINA 3.3** → eccentricità/FWHM si possono **sviluppare e testare in locale**. MA gli utenti sono divisi 3.2/3.3 → **il target di build del plugin RESTA l'SDK 3.2** (una DLL per tutti); eccentricità/FWHM si leggono via **reflection** (presenti 3.3 → letti; assenti 3.2 → `null`). **NON cambiare il target a 3.3.**
> **Numerazione:** `grep "^## [0-9]" NOTE_CLAUDE.md | tail -1` → usa il prossimo libero (atteso **§47**). Verifica.
> **Direttiva permanente:** lato NINA consultare il sorgente `daleghent/nina` **al tag di release** + i docs `https://nighttime-imaging.eu/docs/master/site/`.

## FASE 0 — VERIFICA (sola lettura)
1. **API:** confermare su `IStarDetectionAnalysis` (sorgente al tag release 3.3 + DLL installata) la presenza di **`Eccentricity`** (e `FWHM`, arcsec). Sul Lenovo (3.3) ora la **present-path della reflection è testabile in locale**.
2. **Build target:** confermare che il `.csproj` resta su `NINA.Plugin 3.2.0.9001` (compile ref), con NINA 3.3 solo come **runtime di test**. La reflection legge i campi a runtime: su 3.3 li trova, su 3.2 → `null`.
3. **Contratto:** confermare che il contratto §41 ha già i campi `eccentricity` e `fwhm` (nullable) in `NinaImageMetrics` (Agente) → il plugin deve solo **popolarli**.
4. **Riuso:** confermare l'infrastruttura di N1 da riusare (baseline per-campo/filtro, persistenza ≥2-3 pose, dead-band) — N4 non la reinventa.

## §47a — Plugin: leggere e inoltrare l'eccentricità (e FWHM) via reflection  [repo plugin, build 3.2-SDK]
1. Nell'handler `ImageSaved`, leggere `StarDetectionAnalysis.Eccentricity` (e `.FWHM`) via **reflection** (proprietà per nome; se assente → `null`, nessuna eccezione). Popolare i campi `eccentricity`/`fwhm` del payload §41.
2. Graceful e fire-and-forget come il resto del forwarder. Nessun riferimento a compile-time ai membri 3.3-only.
3. Versione plugin bump (es. `1.3.0.0 → 1.4.0.0`); dipendenze NINA/WebView2 invariate; GUID invariati.
**Test:** su NINA 3.3 (Lenovo) il payload porta `eccentricity` valorizzata; simulazione "membro assente" → `null`, nessun crash; build pulita contro 3.2-SDK.

## §47b — Agente: indice Qualità Stelle (eccentricità) — osservativo  [Agente + dashboard]
1. **EccentricityQuality** (Layer-2, in `nina_indices.py` accanto al TransparencyIndex): eccentricità vs **riferimento del rig per-filtro** (recente-migliore = eccentricità minima raggiungibile da questo rig/ottica, che ha un suo "pavimento" da tilt/aberrazioni). Segnale = **elevazione sopra il pavimento del rig** (stelle più allungate del solito). Backstop assoluto: eccentricità molto alta (es. >0.6–0.7) = comunque sospetta. **Persistenza ≥2-3 pose + dead-band** (riuso N1): una singola posa allungata (raffica, satellite) non conta.
2. **Ruolo = verifica/correlazione, NON azione leve.** Esposto su `/status.nina.star_quality` + **card dashboard** ("Qualità stelle / eccentricità") + log (`eccentricity`, `ecc_quality`, `ecc_ref`).
3. **Chiudere il cerchio (la parte di valore):** correlare in live l'eccentricità con la diagnosi del motore e mostrarlo nell'evidence/grafico:
   - RMS↑ **+ eccentricità↑** → il degrado ha **davvero** rovinato le stelle (diagnosi confermata dall'esito reale).
   - eccentricità↑ **con RMS nella norma** → elongazione che la guida-RMS non vede (deriva lenta/PE/flessione) → segnale che il proxy RMS si perde.
   - RMS↑ **+ eccentricità nella norma** → il degrado **non** ha rovinato le stelle (es. mosso recuperato) → conferma che non serviva agire.
   Questi tre casi vanno **visibili a schermo**, è il senso di N4 v1: vedere se la diagnosi del motore corrisponde all'esito reale sul sensore.
4. **NON modifica le leve** in v1 (nessun input al confidence/azioni). Kill-switch `[nina_indices] star_quality_enabled=true`.
**Test:** eccentricità elevata e persistente vs pavimento rig → stato "stelle allungate" + correlazione mostrata; singola posa anomala → ignorata (persistenza); nessun effetto su leve/decisioni del motore (verificato); graceful senza il campo. Suite verde.

## REGOLE / CHIUSURA
- **NON toccare:** leve/decisioni del motore (N4 v1 è osservativo), backlash, baseline §33/§40/§44, cap §24, telemetria §41/§42, N1/N8.
- Plugin **buildato contro 3.2-SDK** + reflection (universale 3.2/3.3); **niente** riferimenti compile-time 3.3-only.
- **REBUILD** Agente (`build_dist.py`, config nel pacchetto con `star_quality_enabled=true`) + **rebuild plugin** (`dotnet build -c Release`, DLL v1.4) → su Minixz100 e Lenovo. Niente commit/push.
- **DOC:** `NOTE_CLAUDE.md` §47 + `CONTESTO_PROGETTO.md` + `ARCHITETTURA_FILONE_DIAGNOSTICO_NINA.md` (spuntare blocco 2) + `VALIDAZIONE_CAMPO_v2.6.md`.

## CHECKLIST
- [ ] FASE 0: `Eccentricity`/`FWHM` confermati su 3.3 (release+DLL); build target **resta 3.2-SDK**; contratto già pronto; infrastruttura N1 da riusare individuata.
- [ ] §47a plugin: reflection legge `Eccentricity`/`FWHM` (graceful→null), popola payload; build 3.2-SDK pulita; v1.4; deps/GUID invariati.
- [ ] §47b Agente: `EccentricityQuality` vs pavimento rig per-filtro, persistenza ≥2-3 + dead-band; **card dashboard** + correlazione con la diagnosi (3 casi visibili); log; **nessun effetto leve**; kill-switch; graceful.
- [ ] Rebuild Agente + plugin; config attive; nessuna regressione N1/N8/§41-§46; doc §47; niente commit.

> **P1:** N4 misura l'obiettivo vero (stelle tonde nella posa), non il proxy (RMS). In v1 non comanda nulla: **mostra se il motore ha capito giusto**, chiudendo il cerchio iniziato da N1 (contesto) e N8 (decisione). Quando l'eccentricità confermerà o smentirà in diretta le diagnosi del motore, avremo per la prima volta il riscontro tra "come si muoveva la guida" e "come sono venute le stelle".
