# PROMPT per Claude Code — FIX: la baseline deve formarsi SEMPRE (prerequisito P1)

> **AUTORIZZAZIONE A IMPLEMENTARE**, isolato all'**auto-calibrazione baseline**. NON toccare §31 (motore), §32/RECOVERY, backlash, esposizione, né il **valore del cap `rms_high` (1,00″)**. Contesto già verificato: `ACCERTAMENTO_BASELINE_SEMPRE.md` + `PRINCIPIO_CONVERGENZA_PRESTAZIONE.md` (P1). Log: `LOG RC8 CEM70/logs/session_20260613_004934.csv` (serena) e `..._224829.csv`.
> **Numerazione:** verifica `grep "^## [0-9]" NOTE_CLAUDE.md | tail -1` e usa N+1 (se la §32 è il RECOVERY leve, questa è §33).

## 0. PRE-FLIGHT (sola lettura)

1. `phd2_agent/controller.py` **L468‑540**: `_accumulate`/`_finalize_rms_baseline`. **Confermare il meccanismo:** L473‑475 campiona `rms_total` **solo se `condition == NOMINAL`** (+ snr≥`baseline_min_snr`, no implosion); L477 finalizza a `baseline_window_frames`; L486 mediana; L491‑494 **gate di rifiuto** (`> max(baseline_reject_min_arcsec, baseline_reject_factor×scale)`). Nota: `baseline_provider` (L385‑386) restituisce `None` se `_rms_baseline_rejected`.
2. `phd2_agent/config.py`: `AutoCalibrationConfig` e `Thresholds`. Derivazione di `rms_high` (cap `rms_high_max_arcsec=1,00`) e `rms_low` (`rms_low_factor=0,75`, floor `rms_low_min_arcsec=0,25`).
3. `phd2_agent/analyzer.py`: definizione di `SeeingCondition.NOMINAL` (capire perché a guida degradata non scatta).
4. Usi della baseline a valle: satisfaction-gate §30 e RECOVERY §32 usano la **mediana baseline** → entrambi falliscono se baseline=None.

**Fatto verificato (NON ridiscutere):** notte serena 004934 — RMS mediana **2,05″**, SNR ottimo (min 17,3, **niente nuvole**), ma `condition==NOMINAL` solo **16/3258** → finestra mai riempita → baseline mai finalizzata → `None`. Il **gate di rifiuto non viene nemmeno raggiunto**. Il blocco primario è il **filtro `condition==NOMINAL`**, non il rifiuto.

## 1. OBIETTIVO

La baseline deve **formarsi sempre** (prerequisito P1: senza riferimento il controllore è inerte), riflettendo la **miglior prestazione raggiungibile nelle condizioni correnti**, anche quando la guida è degradata. Senza far diventare l'Agente più lasco (il cap `rms_high` resta).

## 2. SPECIFICA (cosa implementare)

1. **Campionare anche fuori da NOMINAL** (L473‑475): raccogliere i campioni dai frame **SNR-validi, no-implosion, a prescindere da `condition`**. Definire la baseline come **statistica robusta del MEGLIO raggiunto** nella finestra (es. un **percentile basso**, o la mediana del miglior X%), NON la mediana di tutto (che sovrastima la "prestazione raggiungibile"). Scegli e motiva la statistica.
2. **`rms_high` cap invariato** (1,00″): preserva il limite di buona guida. Con baseline alta, `rms_high = min(baseline×1,3, 1,00) = 1,00″`. **NON abbassare il cap.**
3. **VINCOLO CRITICO — niente band inversion:** garantire **sempre `rms_low < rms_high`**. Con baseline 2″, `rms_low = 2×0,75 = 1,5″ > rms_high 1,0″` → bande invertite. **Cappare `rms_low`** (es. `rms_low = min(baseline×0,75, rms_high − margine)`), aggiungendo se serve `rms_low_max_arcsec`. Test esplicito sull'ordinamento.
4. **Refresh tightest-wins (§25) invariato:** la baseline alta si stringe quando il cielo migliora.
5. **Rifiuto → tetto di sanità + stabilità:** alzare la soglia di rifiuto a un livello "guida fondamentalmente rotta" (molto > 1,5″) e/o sostituirla con un **check di varianza** della finestra (rifiuta solo finestre instabili = transitorio/spazzatura, non alte-ma-stabili = notte brutta reale).

## 3. REGOLE INDEROGABILI
- Isolato all'autocal baseline + derivazione soglie. NON toccare motore §31, §32/RECOVERY, esposizione, backlash.
- **Cap `rms_high` 1,00″ invariato.** Mediana/robustezza e tightest-wins preservati.
- **`rms_low < rms_high` sempre** (anti-inversione) — è un bug-fix, attivo sempre.
- Retrocompatibilità: a cielo buono (frame NOMINAL presenti) il comportamento resta come oggi.

## 4. CONFIG / DEFAULT
Proporre un flag (es. `baseline_sample_all_conditions`) con kill-switch. È una correzione P1-prerequisito → propendi per default attivo, ma motiva; a OFF il comportamento è quello attuale (campiona solo NOMINAL). L'anti-inversione `rms_low<rms_high` è **sempre attiva** (correzione di bug).

## 5. TEST ATTESI
1. **Finestra degradata (zero frame NOMINAL):** la baseline **si forma** (statistica robusta del meglio); oggi resterebbe None.
2. **Anti-inversione:** con baseline alta, `rms_low < rms_high` (mai invertite); `rms_high` resta cappato 1,00″.
3. **Guida fondamentalmente rotta (es. baseline 5″):** ancora **rifiutata** (tetto di sanità) o flaggata instabile.
4. **Regressione cielo buono:** con frame NOMINAL, baseline/soglie **identiche** all'attuale.
5. **OFF:** flag spento ⇒ bit-identico all'attuale.

## 6. VALIDAZIONE / REPLAY (obbligatoria prima del campo)
Replay sulla sessione **attendibile `004934`** (cielo sereno; la prima `224829` è ESCLUSA — coperta da nuvole, non rappresentativa): mostrare che con il fix la baseline **si forma** (e con quale valore robusto), che `rms_high` resta **1,00″**, e che `rms_low < rms_high`. Allegare i numeri.

## 7. REBUILD + DOC
`python build_dist.py` → ZIP; NOTE_CLAUDE **§N+1** ("Baseline sempre formata + anti-inversione bande") + CONTESTO. Non toccare gli altri item.

> **Nota onesta (da riportare):** questo fix rende l'Agente **non-inerte** (gli dà un riferimento anche nelle notti brutte), ma **non fa guidare bene l'RC8**: su queste notti la guida è ~2″ RMS con 27% oscillazione anche a cielo sereno → in gran parte taratura montatura/guida (aggressività, PA, bilanciamento, PEC) a monte dell'Agente. È un prerequisito perché RECOVERY/§32 abbiano un'àncora, non una cura del seeing/montatura.
