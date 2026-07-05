# Accertamento + fix prioritario — La baseline deve formarsi SEMPRE (prerequisito di P1)

**Stato:** accertamento di campo confermato sui log. Da implementare a breve (Alessandro, 2026-06-12). Legato a **P1** (`PRINCIPIO_CONVERGENZA_PRESTAZIONE.md`).

## L'accertamento

In una notte di seeing brutto con RC8 in montagna, l'RMS di guida è genuinamente alto. La baseline **non si forma** perché un gate di soglia la rifiuta → il controllore resta **senza riferimento** → non può applicare P1 (convergere verso la baseline) proprio quando servirebbe di più.

## Conferma sui dati — sessione ATTENDIBILE 004934 (la prima, 224829, è ESCLUSA: nuvolosa, non fa testo)

Sessione RC8 **004934** (0,508″/px, v2.5, guardian, 3258 frame), **cielo sereno**:
- RMS_total: **mediana 2,05″, media 2,15″, p90 2,89″, max 5,24″**.
- SNR ottimo: **min 17,3, mediana 52** → cielo sereno, **NON** è trasparenza/nuvole.
- `condition==NOMINAL` solo **16/3258** → finestra baseline mai riempita → baseline = `None`.
- 27% dei frame in OSCILLAZIONE → a cielo sereno la guida RC8 è genuinamente ~2″ RMS (mount/loop, non meteo).
- (La sessione 224829 delle 22:48 si è coperta di nuvole in corso → esclusa dalla validazione.)

## Meccanismo esatto (CORRETTO dopo verifica sul codice + log notte serena)

Il blocco primario **NON** è il gate di rifiuto, ma il **filtro di campionamento**: la baseline accumula campioni **solo quando `condition == NOMINAL`** (`controller.py` L473‑475: `snr>=baseline_min_snr AND not implosion AND condition==NOMINAL → append(rms_total)`). Servono `baseline_window_frames=60` campioni NOMINAL per finalizzare (L477).

Conferma sulla notte **serena** 004934 (RC8 0,508″/px, 3258 frame): RMS mediana **2,05″**, SNR ottimo (min 17,3 — **niente nuvole**), ma `condition==NOMINAL` solo **16 frame** → finestra mai riempita → `_finalize_rms_baseline()` mai chiamato → baseline = None. Il **gate di rifiuto §23 (L491‑494, soglia 1,524″ per RC8) non viene nemmeno raggiunto**.

→ Quindi: il gate di rifiuto è **secondario**; il blocco reale è che a guida degradata non esistono 60 frame NOMINAL. (L'ipotesi iniziale "rifiutata perché RMS > soglia" era plausibile ma errata sul meccanismo.)

## Perché è un problema P1

P1: la baseline = *miglior prestazione raggiungibile nelle condizioni correnti*. 1,77″ stasera **era** il meglio raggiungibile → riferimento legittimo, non spazzatura. Senza baseline, satisfaction-gate (§30), RECOVERY (§32) e tutta la logica adattiva **non hanno àncora** → controllore inerte nelle notti brutte. **Una baseline sempre definita è prerequisito di P1.**

## Il fix (corretto: agisce sul campionamento, non sul rifiuto)

1. **Campionare la baseline anche fuori da NOMINAL** (`controller.py` L473‑475): raccogliere i campioni dai frame SNR-validi (no implosion) **a prescindere da `condition`**, così la baseline si forma anche a guida degradata. Definire la baseline come **statistica robusta del MEGLIO raggiunto** (es. un percentile basso / mediana del miglior X% della finestra), NON la mediana di tutto (che sovrastimerebbe) → coerente con "miglior prestazione raggiungibile nelle condizioni correnti".
2. **Tenere il limite di "buona guida" dov'è già: il CAP su `rms_high` (`rms_high_max_arcsec = 1,00″`).** Con baseline alta, `rms_high = min(baseline×1,3 ; cap 1,00) = 1,00″` → l'Agente interviene sopra 1,00″ a prescindere dalla baseline. **Il cap NON si tocca.**
3. **VINCOLO CRITICO — evitare l'inversione delle bande:** se la baseline è alta, `rms_low = baseline×0,75` può superare il `rms_high` cappato (es. baseline 2″ → rms_low 1,5″ > rms_high 1,0″ → bande invertite, logica rotta). Il fix **deve cappare anche `rms_low`** (mantenere `rms_low < rms_high` sempre, es. `rms_low = min(baseline×0,75, rms_high − margine)`).
4. **Affidarsi al refresh tightest-wins (§25):** una baseline alta si stringe da sola quando il cielo migliora.
5. **Mantenere un tetto di sanità + check di stabilità** al posto del rifiuto-su-valore-assoluto troppo basso: alzare la soglia di rifiuto a un livello "guida fondamentalmente rotta" (molto > 1,5″), e/o rifiutare solo se la finestra è **instabile** (varianza alta = transitorio/spazzatura), non se è **alta-ma-stabile** (= notte brutta reale). Conserva lo scopo originale del gate senza buttare via baseline reali.

> **Limite onesto:** questo fix rende l'Agente **non-inerte** (gli dà un riferimento), ma **NON fa guidare bene l'RC8**: su queste notti la guida è ~2″ RMS con 27% di oscillazione anche a cielo sereno → è in gran parte un tema di **taratura montatura/guida** (aggressività, PA, bilanciamento, PEC) a monte dell'Agente. Verificare con il Guiding Assistant di PHD2 in parallelo.

## Cosa NON cambiare

- Il **cap `rms_high` a 1,00″** (limite di buona guida) — resta, è giusto così.
- La **mediana** come stimatore baseline (robusta).
- Il **refresh tightest-wins** (§25).

## Verifica suggerita (replay)

Sul log 224829: confermare che con la baseline ammessa a ~1,77″ il `rms_high` efficace resta **1,00″** (per il cap), e che il controllore avrebbe avuto un riferimento (vs `None` attuale). Test unitario: baseline > soglia di rifiuto attuale → si forma comunque; `rms_high` resta cappato; OFF/regressione invariati.

## Priorità

**Alta.** È un prerequisito perché P1 funzioni nelle notti brutte (le più importanti per un sistema adattivo). Va coordinato con gli altri item (RECOVERY §32 dipende dall'avere una baseline; senza, non ha àncora).
