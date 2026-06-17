# PROMPT per Claude Code — §40: la baseline si forma anche a SNR basso (stella debole)

> **Compito in due fasi: (1) FAR QUADRARE LA SCOPERTA** (riprodurre il blocco sui log reali + confermare il gate nel codice), **(2) SE confermata, IMPLEMENTARE.** Non fidarti dei numeri: riproducili.
> **AUTORIZZATO A IMPLEMENTARE** dopo la conferma. Isolato a: gate SNR dell'accumulo baseline (`controller.py _update_rms_baseline`) + config. NON toccare: §37/§38/§39 (motore), le condizioni SEEING, le leve, il cap rms_high, l'anti-inversione bande, il reject §33.
> **NON è una regressione del §37/§38/§39** (quelli sono validati sul campo 2026-06-17: jitter_ref 87%, motore che diagnostica). Questo è un bug **preesistente** del gate SNR sulla baseline, emerso ora perché il 71F ha stelle deboli.
> **Direttiva:** chiavi nuove **attive nel `config.toml`** (born operative); kill-switch per A/B.
> **Numerazione doc:** `grep "^## [0-9]" NOTE_CLAUDE.md | tail -1` → atteso §39 → usa **§40**.
> Contesto: `PRINCIPIO_CONVERGENZA_PRESTAZIONE.md` (P1), `ACCERTAMENTO_BASELINE_SEMPRE.md` (§33, di cui questo chiude un buco residuo).

## 0. FASE 1 — FAR QUADRARE (sola lettura)

**Meccanismo da confermare** (`phd2_agent/controller.py` ~L493-497, `_update_rms_baseline`):
```
snr_ok = (snap.snr_avg is not None and snap.snr_avg >= ac.baseline_min_snr   # = 10.0
          and not snap.implosion_detected)
if not snr_ok:
    return        # <-- esce PRIMA di entrambi i percorsi: NOMINAL e fallback §33
```
→ se `snr < baseline_min_snr` non si accumula NULLA (né NOMINAL né il fallback §33). E **`baseline_min_snr = 10.0`** mentre la soglia operativa **`snr_low = 8.0`** (config.toml): una stella **buona per guidare** non è buona per formare la baseline. Quindi il "sempre-forma" del §33 ha un buco: si forma sempre, **tranne** quando SNR < 10.

**Evidenza dai log reali (Cowork, 71F @490mm, `session_20260617_221428`, 738 frame, 29 min) — riprodurre:**
| Metrica | Valore atteso |
|---|---|
| SNR mediano | ~9,2 |
| frame con `snr_avg < 10` (= `baseline_min_snr`) | **100%** |
| `rms_high_active` (unici nella sessione) | **solo 1,20** (fallback, MAI calibrata) |
| `condition == NOMINAL` | ~97% (716/738) — i frame ci sarebbero, è l'SNR a bloccarli |
| `rms_total` su NOMINAL | med ~0,682 (la baseline che SI sarebbe formata) |

**Log reale (disco di Alessandro, NON nel repo):**
`C:\Users\aless\OneDrive\Desktop\IMMAGINI\LOG PER AGENTE ADATTIVO\2026-06-17\logs\session_20260617_221428.csv`
Colonne utili: `snr_avg, rms_total, condition, rms_high_active, rms_low_active, evaluated`.

**Code in Fase 1:** confermare il gate nel codice; riprodurre i numeri sul CSV (con `baseline_min_snr=10` nessun frame accumula → baseline None; con la soglia a 8 i frame passano e la baseline si formerebbe ~0,68"). **Verdetto: CONFERMATA / PARZIALE / ERRATA** coi numeri.

## 1. OBIETTIVO (Fase 2)
La baseline RMS si forma **anche con stella debole / SNR basso**: (A) una stella che l'Agente accetta per **guidare** (`snr >= snr_low`) deve poter formare la baseline; (B) il fallback "sempre-forma" del §33 **non deve poter restare congelato** da una soglia SNR rigida — su una notte genuinamente fioca deve formarsi comunque dalla frazione a SNR migliore disponibile.

## 2. SPECIFICA
1. **Allineare la soglia:** `baseline_min_snr` deve seguire `snr_low` (oggi 10 vs 8). Portarla a `snr_low` (= 8.0) **e** documentare che deve tracciare `snr_low`, non superarlo. Scriverla **attiva** nel `config.toml`.
2. **Fallback §33 non-congelabile:** il percorso di accumulo del fallback (`_rms_baseline_all_samples`) **non** deve essere bloccato da un hard-cut SNR che fa `return`. Deve accumulare i frame **SNR-validi-o-migliori-disponibili** escludendo solo `implosion`/spazzatura, e l'estimatore best-fraction già pesa la qualità. In pratica: la soglia SNR alta può **preferire** frame migliori, non **bloccare** la formazione. Su una notte a SNR 7 la baseline deve comunque formarsi dai frame meno peggio.
3. **Percorso NOMINAL (notti buone) invariato** salvo l'allineamento soglia: nessuna regressione su stelle luminose.
4. Mantenere: esclusione `implosion`, cap rms_high 1,00", anti-inversione `rms_low ≤ rms_high×0.85`, reject §33 su instabilità/tetto. NON toccarli.

## 3. REGOLE
- Isolato a `_update_rms_baseline` (gate SNR + accumulo fallback) + config. NON toccare §37/§38/§39, leve, cap, reject, anti-inversione.
- Kill-switch **shipped sul nuovo comportamento** (es. `baseline_snr_floor_blocks = false` → la soglia non blocca il fallback; `=true` = vecchio comportamento). Chiavi scritte e attive nel `config.toml`.
- Retrocompatibilità: a kill-switch sul vecchio valore → comportamento identico al pre-§40.

## 4. TEST ATTESI
1. **Riproduzione (Fase 1):** con `baseline_min_snr=10` su frame a SNR 9 → nessun accumulo, baseline None; con la soglia a 8 → accumula e finalizza.
2. **Stella debole forma la baseline:** sequenza con SNR ~9 e condition NOMINAL → baseline si forma (~mediana rms dei NOMINAL).
3. **Notte fioca (SNR 7, sotto snr_low):** il fallback §33 forma comunque la baseline dalla frazione migliore (non resta None).
4. **Nessuna regressione su notte buona:** stella a SNR ~55 → baseline identica a prima.
5. **Garbage escluso:** frame in `implosion` / SNR irrisorio non avvelenano la baseline.
6. **Replay reale** su `session_20260617_221428`: con il fix la baseline si forma (~0,68"), `rms_high_active` si stacca da 1,20; riportare il valore.

## 5. REBUILD + DOC
`python build_dist.py` → ZIP. `NOTE_CLAUDE.md` **§40** ("baseline si forma anche a SNR basso: baseline_min_snr allineata a snr_low + fallback §33 non-congelabile da soglia SNR; chiude il buco low-SNR del §33") + `CONTESTO_PROGETTO.md`. `config.toml` con le chiavi **attive**. Niente commit/push.

## 6. CHECKLIST
- [ ] Fase 1: verdetto CONFERMATA con numeri riprodotti + citazioni `file:riga`.
- [ ] `baseline_min_snr` allineata a `snr_low` (8), scritta attiva nel config.
- [ ] Fallback §33 non più congelabile da hard-cut SNR (forma da best-available, esclude implosion).
- [ ] Percorso NOMINAL/notti buone invariato; cap/anti-inversione/reject intatti.
- [ ] Kill-switch shipped sul nuovo comportamento; vecchio ripristinabile (testato).
- [ ] Test 1-6; replay `221428` mostra baseline ~0,68" (non più 1,20).
- [ ] NOTE §40 + CONTESTO aggiornati; ZIP ribuildato (§32→§40).

> **P1:** senza baseline, satisfaction-gate (§30) e RECOVERY (§32) sono inerti. È la terza volta che "il riferimento deve formarsi sempre" (baseline §33, jitter_ref §38, ora baseline a SNR basso): un riferimento di prestazione non deve poter essere bloccato da una stella un po' debole — al massimo si forma dai frame migliori che ci sono.
