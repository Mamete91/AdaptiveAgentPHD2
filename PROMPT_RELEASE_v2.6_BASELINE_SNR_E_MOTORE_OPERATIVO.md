# PROMPT per Claude Code — RELEASE v2.6: §40 baseline a SNR basso + bump versione + commit + push

> **PROMPT OPERATIVO COMPLETO — AUTORIZZATO a: implementare §40, bumpare la versione a 2.6, aggiornare la cronistoria, ribuildare ZIP + Pacchetto_Distribuzione, e COMMITTARE + PUSHARE su GitHub.**
> **Niente fase-reproduce:** Alessandro ha già validato in LIVE (forzando PHD2 a guidare su stella a SNR 10 → la baseline si è formata subito). Il meccanismo è confermato sul campo (71F, `session_20260617_221428`: SNR mediano 9,2, 100% frame < 10, `rms_high_active` inchiodato a 1,20 → baseline mai formata per via del gate `baseline_min_snr=10`).
> **Questo commit è la v2.6 ufficiale:** raccoglie §37+§38+§39 (già nel working tree, validati sul campo 2026-06-17) **+ §40** + il bump versione, in un unico commit "release v2.6". Costruisce sopra il commit §36 (`13d2848`).
> **Direttiva inderogabile:** l'Agente parte **operativo in LIVE** — tutte le chiavi attive di default nel `config.toml` packaged.
> Contesto: `PRINCIPIO_CONVERGENZA_PRESTAZIONE.md` (P1), `ACCERTAMENTO_BASELINE_SEMPRE.md` (§33).

## 0. PRE-FLIGHT MINIMO (sola lettura — solo per non rompere nulla)
1. `phd2_agent/controller.py` `_update_rms_baseline` (~L493-497): confermare il gate `if not snr_ok: return` con `snr_ok = snap.snr_avg >= ac.baseline_min_snr` (=10.0), che blocca SIA il percorso NOMINAL SIA il fallback §33.
2. **Individuare TUTTI i punti dove compare la versione "2.5"** da bumpare a "2.6": `build_dist.py` (nome ZIP + eventuale costante), `version_info_template.py`/`version_info.txt`, l'`agent_version` nel context/summary del logger, intestazioni `NOTE_CLAUDE.md`/`CONTESTO_PROGETTO.md`, eventuali `.spec`. Elencarli prima di toccarli.
3. `config.toml`: confermare `snr_low = 8.0` e `baseline_min_snr = 10.0` attuali.

## 1. §40 — IMPLEMENTAZIONE (baseline a SNR basso)
1. **`baseline_min_snr` → 6.0** (= pavimento "Minimum star SNR for AutoFind" di default di PHD2). Scriverlo **attivo** nel `config.toml`. Razionale (commentarlo): 6 = pavimento universale di rilevamento stella di PHD2; ogni utente lo ha → la baseline si forma per tutti. Resta ≤ `snr_low` (8) → coerente. Decoupling voluto: 6 = soglia rilevamento stella, 8 = soglia controllo esposizione.
2. **Fallback §33 NON congelabile da soglia SNR:** il gate `if not snr_ok: return` non deve poter impedire la formazione su una notte genuinamente fioca. Il percorso fallback (`_rms_baseline_all_samples`) deve accumulare i frame escludendo **solo** `implosion` (ed eventualmente un floor anti-garbage tipo SNR≥3, il reject PHD2), e formare dalla **best-fraction**; la soglia SNR alta può **preferire** frame migliori, non **bloccare** del tutto. → su SNR<6 la baseline si forma comunque dai frame meno peggio.
3. **Percorso NOMINAL (notti buone) invariato** salvo l'allineamento soglia. Mantenere intatti: esclusione implosion, cap rms_high 1,00", anti-inversione `rms_low ≤ rms_high×0.85`, reject §33 (instabilità/tetto).
4. Kill-switch coerente con la direttiva born-operative (nuovo comportamento shipped ON; vecchio ripristinabile per A/B).

## 2. BUMP VERSIONE 2.5 → 2.6
Aggiornare a **2.6** tutti i punti elencati in §0.2 (nome ZIP `Adaptive_Agent_PHD2_v2.6.zip`, version_info, agent_version, intestazioni doc). Coerenza totale: nessun "2.5" residuo che indichi la versione corrente.

## 3. CRONISTORIA (procedura standard)
- `NOTE_CLAUDE.md`: nuova sezione **§40** ("baseline si forma anche a SNR basso: baseline_min_snr 10→6 = floor AutoFind PHD2 + fallback §33 non-congelabile; chiude il buco low-SNR") **e** una nota di **release v2.6** che riassume il milestone §37→§40 ("motore diagnostico da dormiente a operativo + RMS in arcsec + baseline robusta").
- `CONTESTO_PROGETTO.md`: aggiornare intestazione "Stato attuale" a **v2.6** con il riassunto del milestone.

## 4. REBUILD (born-operative)
1. `python build_dist.py` → genera `Adaptive_Agent_PHD2_v2.6.zip` + `Pacchetto_Distribuzione/`.
2. **Verificare che il `config.toml` DENTRO il pacchetto** abbia TUTTE le chiavi attive (LIVE): `convert_distance_to_arcsec=true` (§36), `hfd_gates_seeing=false` (§37), `refs_always_form=true` (§38), `preserve_refs_on_dither=true` (§39), `baseline_min_snr=6.0` + la chiave §40 (§40), oltre a `[diagnostic_engine] enabled=true, mode="guardian"`. L'Agente deve partire operativo senza che l'utente tocchi nulla.

## 5. COMMIT + PUSH (v2.6 ufficiale)
1. **Stage pulito:** `git add -A` (`.venv/` già ignorato); `git restore --staged phd2-master/` (rumore fine-riga). Verificare che NON entrino `phd2-master/`, `.venv/`, `*.zip`, `build/`, `dist/`, `Pacchetto_Distribuzione/`.
2. **Gate di sicurezza:** `git diff --cached --name-only | sort` → solo file Agente (phd2_agent/, config.toml, main.py, build_dist.py, version_info_template.py, tests/, i .md).
3. **Commit:**
   ```
   release: Adaptive Agent v2.6 — motore diagnostico operativo + RMS in arcsec + baseline robusta

   Prima versione ufficiale sopra la 2.5. Il motore di diagnosi del seeing passa da dormiente a operativo.
   - §37 HFD declassato a informativo (fuori dal gate SEEING)
   - §38 jitter_ref/hfd_ref sempre-forma (best-fraction su finestra mobile)
   - §39 riferimenti sopravvivono al dither/settle; logging reset_cause; schema CSV 3->4
   - §40 baseline si forma anche a SNR basso: baseline_min_snr 10->6 (= floor AutoFind PHD2) + fallback non-congelabile
   - (su base §36: RMS px->arcsec, gia in v2.5)
   - Tutte le feature default-ON nel config.toml (born operative)
   - Validato sul campo: 71F @490mm 2026-06-17 (jitter_ref 12%->87%, motore che diagnostica, baseline ora si forma)
   ```
4. **Push:** `git push origin master`. Credenziali HTTPS = quelle salvate.

## 6. TEST + VERIFICA
- Test: §40 — stella a SNR 9 forma la baseline; notte SNR 7 (sotto floor) forma comunque dal fallback; notte buona (SNR 55) invariata; garbage/implosion esclusi. Suite esistente verde (atteso ≥175 + nuovi).
- Replay reale `session_20260617_221428`: con il fix la baseline si forma (~0,68"), `rms_high_active` si stacca da 1,20 — riportare il valore.
- Post-push: `git log --oneline -2` mostra il commit v2.6 sopra `13d2848`; `HEAD == origin/master`; ZIP `v2.6` e Pacchetto_Distribuzione rigenerati con config LIVE.

## 7. CHECKLIST FINALE
- [ ] §40: `baseline_min_snr=6` attivo; fallback §33 non-congelabile (best-fraction, esclude implosion); NOMINAL/cap/anti-inversione/reject intatti.
- [ ] Versione bumpata a **2.6** ovunque (ZIP, version_info, agent_version, doc); nessun "2.5" residuo.
- [ ] `config.toml` packaged con TUTTE le chiavi §36→§40 attive (born operative).
- [ ] NOTE_CLAUDE §40 + nota release v2.6 + CONTESTO aggiornati.
- [ ] ZIP `Adaptive_Agent_PHD2_v2.6.zip` + Pacchetto_Distribuzione rigenerati.
- [ ] Stage pulito (no .venv/phd2-master/zip); commit v2.6; push su `origin/master` riuscito.
- [ ] Replay `221428`: baseline ~0,68" (non più 1,20).

> **P1:** è la terza volta che "il riferimento deve formarsi sempre" (baseline §33, jitter_ref §38, baseline a SNR basso §40). Con la v2.6 il principio è chiuso: nessun riferimento di prestazione può essere bloccato — né da assenza di frame NOMINAL, né da reset frequenti, né da una stella debole. Il motore parte operativo e misura nella giusta unità.
