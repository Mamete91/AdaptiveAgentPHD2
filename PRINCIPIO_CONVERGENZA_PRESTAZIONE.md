# Principio architetturale fondamentale del progetto

## P1 — Le leve convergono verso la PRESTAZIONE, non verso un valore

**Stato:** principio fondamentale del progetto Adaptive Agent for PHD2. NON è una feature né una scelta specifica della v2.5: è un **criterio architetturale permanente**, da usare come riferimento in ogni evoluzione futura del controller (CASO, Guardian, Jitter e qualunque architettura successiva).
**Origine:** Alessandro Curci, 2026-06-12 — sintesi di mesi di osservazione sul campo (dalla v2.2) e dell'analisi che ha prodotto il RECOVERY della banda morta (§32).

---

## Enunciato (formulazione canonica — Alessandro Curci, 2026-06-12)

**Il controllore deve mantenere la prestazione di guida il più vicino possibile alla baseline corrente. La baseline rappresenta il miglior livello prestazionale osservato dal sistema nelle condizioni operative correnti. Le leve non costituiscono un obiettivo, ma esclusivamente strumenti per convergere verso tale riferimento. Ogni modifica alle leve deve essere confermata da un miglioramento misurabile della prestazione; in assenza di beneficio il controllore deve arrestare o annullare l'azione.**

> MinMove non è un obiettivo. Aggression non è un obiettivo. Exposure non è un obiettivo. Sono strumenti. **L'obiettivo è la prestazione.**

### Note operative del principio

- **"Baseline corrente / miglior prestazione osservata":** nel progetto è la mediana baseline con refresh ciclico *tightest-wins* (§25). Attenzione: tightest-wins conserva il *miglior valore osservato*, che in condizioni genuinamente peggiorate può collocarsi **sotto** la prestazione attualmente raggiungibile → in quel caso vale il corollario 5 (non inseguire il residuo atmosferico irraggiungibile portando le leve ai limiti).
- **"Miglioramento misurabile":** l'RMS è rumoroso, quindi la conferma richiede una **finestra di valutazione**, non un singolo frame. È esattamente ciò che fa l'*outcome tracking* del motore §31 (`outcome_window_frames`) e che l'anti-windup del §32 approssima. **P1 eleva quindi la verifica dell'esito (outcome-tracking) a requisito di base del controllore, non a opzione.**

---

## Corollari

1. **Quando la prestazione migliora**, le leve possono spingere verso maggiore reattività.
2. **Quando la prestazione peggiora**, le leve devono poter recuperare morbidezza.
3. **Ogni modifica alle leve si giudica dal suo effetto sulla prestazione** (RMS vs baseline), mai dal valore assoluto raggiunto dalla leva.
4. **Il loop è chiuso sulla prestazione:** ogni azione sulle leve deve essere seguita dalla verifica che l'RMS si sia mosso verso la baseline. Un'azione che non aiuta va fermata o annullata.
5. **Il target è la prestazione *raggiungibile*, non un RMS assoluto.** L'RMS è solo *in parte* controllabile dalle leve: la componente atmosferica (seeing/vento) non si corregge muovendo le leve. Il loop deve quindi distinguere il residuo *lever-fixable* da quello *atmosferico* e **non inseguire** quest'ultimo (niente corsa delle leve ai limiti per un RMS irraggiungibile). Distinguere le due cose richiede, idealmente, un segnale di regime (jitter/lag-1).
6. **Simmetria:** il meccanismo che spinge verso la reattività (quando la prestazione è al target o sotto) e quello che recupera morbidezza (quando la prestazione peggiora) sono **due metà di un unico controllore**, ancorate allo **stesso riferimento di prestazione** (la mediana baseline). Nessuna delle due metà dovrebbe esistere senza l'altra. *(L'asimmetria storica corretta in §32 era esattamente la mancanza della seconda metà.)*

---

## Indipendenza dall'architettura

Il principio è **indipendente da CASO, Guardian e Jitter**. Questi sono soltanto **modi diversi di perseguire lo stesso obiettivo**:

- **CASO** (v2.3): selettore di direzione a soglie RMS + euristica (RECOVERY + anti-windup). Fallback robusto e semplice.
- **Guardian:** CASO rivisto dal motore diagnostico.
- **Jitter:** selettore di direzione *causale* (la diagnosi §31), più intelligente ma oggi cieco a campionamento grosso (→ §32).

Ogni architettura, presente o futura, va **valutata ed evoluta rispetto a P1**. Una nuova architettura eredita P1 per default.

---

## Come usarlo come criterio di design

Davanti a qualsiasi proposta/revisione di logica delle leve, chiedersi:

- *"Questo movimento di leva è giustificato dal suo effetto **misurato** sulla prestazione, o sta convergendo verso un **numero**?"*
- Una modifica che porta una leva verso un valore fisso **senza** una giustificazione di prestazione **viola P1**.
- I limiti di leva (`min`/`max`, floor, cap) sono **vincoli di sicurezza, non target**. Il target è sempre la prestazione.
- Una leva che resta a lungo a un estremo (molto reattiva o molto morbida) mentre la prestazione si allontana dalla baseline è un **sintomo di violazione di P1** (è esattamente ciò che ha rivelato la banda morta).

---

## Stato di attuazione (riferimento, aggiornabile)

- **Prima attuazione concreta:** §32 RECOVERY (v2.5) — aggiunge la metà "recupero morbidezza" in CASO, con anti-windup (corollari 2-5). In validazione beta (guardian).
- **Attuazione piena in Jitter (futura):** richiede §32 (vista: jitter al posto dell'HFD) + risoluzione del congelamento (INSUFFICIENT) + ramo NOMINAL bidirezionale + uso dell'**outcome tracking** come anti-windup (corollario 4). Vedi `DESIGN_RATIONALE_LEVER_RESPONSIVENESS.md` §5bis.
- **Nord architetturale di lungo periodo:** un unico loop closed-on-performance, con direzione data dalla diagnosi quando confidente e fallback RMS/outcome quando cieca/incerta — pur mantenendo CASO come livello robusto e semplice. P1 è il criterio che giustifica e guida questa convergenza.
