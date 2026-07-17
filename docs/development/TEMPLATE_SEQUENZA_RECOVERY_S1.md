# §57 — Template di sequenza: RECOVERY AUTO-STARTING da UNSAFE-nubi (rev. §57-bis)

> **Cosa risolve.** Quando N6 va UNSAFE per nubi, il `Wait Until Safe` di NINA è un puro
> loop di attesa (poll `IsSafe` ogni 5 s, **nessuna posa**): senza light salvati N1 resta
> congelato e N6 non può mai tornare SAFE (deadlock provato il 12/7: indice fermo a 0.115
> per 28 minuti). Questo template scatta una **posa-sonda** a cadenza (S1, fail-safe) —
> anticipabile dall'**hint SNR-guida** (S2) — così N1 riceve dati freschi e il drain §55
> riporta SAFE **da solo**. La verità resta la camera di imaging: nessun componente
> dichiara SAFE senza un light reale.

> **Revisione §57-bis (13/7).** La prova sulla GUI reale ha mostrato che i container del
> `Trigger On Unsafe` **rifiutano le istruzioni di categoria Camera** (Take Exposure &
> co.) pur accettando le istruzioni del nostro plugin. Il template v1 (gate + TakeExposure
> esterno) non era quindi montabile. La **RecoveryProbe** è ora **autocontenuta**: attende
> il gate e scatta internamente la sonda, replicando il light interrotto.

Richiede: **NINA 3.3** (il `Trigger On Unsafe` è core dalla 3.3) + plugin Adaptive Agent
**v1.6.0.0** (istruzione "*Recovery probe (Adaptive Agent)*"). Niente Sequencer Powerups.

---

## 1. Struttura del template

Nel target/area imaging della Advanced Sequence, aggiungi il trigger — **una sola
istruzione, direttamente nel Before, senza container né condizioni** (rev. §57-ter):

```
Trigger On Unsafe
│
├── Before Waiting For Safety:            ← eseguito all'UNSAFE
│   └── Recovery probe (Adaptive Agent)   ← TUTTO QUI: è l'INTERO ciclo di recovery
│         Probe timeout (min):    12      ← cadenza fail-safe S1
│         Min interval (min):     5       ← floor assoluto tra sonde
│         Fallback exposure (s):  60      ← usata SOLO se nessun light visto in sessione
│
├── (attesa interna Wait Until Safe — passa subito: l'istruzione ritorna solo a SAFE)
│
└── After Waiting For Safety:             ← eseguito UNA volta al ritorno SAFE
      (per ora vuoto; qui andrà il park su unsafe prolungato: unpark, autofocus…)
```

**Cosa fa la Recovery probe, da sola (ciclo completo interno):** finché il Safety Monitor
riporta UNSAFE ripete: attesa gate (timeout S1 **oppure** `recovery_hint.active` S2, mai
prima del min-interval) → **una** posa LIGHT **replica dell'ultimo light salvato**
(esposizione/gain/offset/binning; filtro già in posizione, nessun comando alla ruota) →
pipeline standard → `ImageSaved` → forwarder → N1 fresco → drain §55. Lo stato del monitor
viene riletto ogni 5 s: **appena torna SAFE l'istruzione esce da sola** (anche a metà
attesa) e la sequenza riprende. L'annullamento della sequenza interrompe tutto.

## 2. Parametri consigliati (allineati a `config.toml [recovery_probe]`)

| Parametro | Valore | Perché |
|---|---|---|
| Probe timeout | **12 min** | Fail-safe: al massimo ~5 sonde/ora sotto nube fitta. Col drain §55 (~1 min dopo la sonda buona) il rientro tipico è ≤ 13 min dal sereno |
| Min interval | **5 min** | Paletto 3: un hint "ballerino" non martella l'otturatore |
| Fallback exposure | **60 s** | Usata SOLO se NINA è stata riavviata e nessun LIGHT è ancora stato salvato: in ogni altro caso la sonda **replica automaticamente il light interrotto** (obbligatorio per N1: il confronto `star_count` vs `base_stars` non normalizza per esposizione) |
| Guiding | *(gestito da sé)* | La sonda è una CaptureImage non guidata: in nube fitta la stella guida sparisce (13/7: guida mai ripartita dalle 03:20) e la sonda parte comunque |

## 3. Perché è fatto così (motivazioni tecniche)

- **Il ciclo vive DENTRO l'istruzione (§57-ter)** — la GUI del trigger rifiuta anche
  container/condizioni (`Loop While Unsafe` incluso: seconda evidenza sperimentale, vedi
  §4.3), quindi la ripetizione è interna: l'istruzione rilegge lo stato del Safety Monitor
  ogni 5 s (`ISafetyMonitorMediator.GetInfo()`, **sola lettura** — lo stesso meccanismo del
  `Wait Until Safe` core) ed esce da sola appena torna SAFE, anche a metà attesa. Leggere
  lo stato per fermarsi è consumo, non giudizio: il SAFE lo decide sempre e solo N6.
- **La sonda vive DENTRO un'istruzione eseguita dal sequencer** — è lo stesso meccanismo
  del `Take Exposure` core (che internamente usa gli stessi mediator). Il principio
  "l'imaging resta al sequencer" è rispettato: nessuna cattura autonoma, si scatta solo
  quando il sequencer esegue l'istruzione. (Il divieto assoluto di `IImagingMediator` del
  Gate v1 nasceva contro le catture da monitor/timer, fuori dal flusso di sequenza.)
- **Replica del light interrotto** — il plugin memorizza i parametri di ogni LIGHT salvato
  (`LastLightMemory`, alimentata da `ImageSaved`): la sonda è un sub equivalente, quindi
  il deficit di N1 è confrontabile e, se il cielo è tornato, il frame è **utilizzabile**.
- **L'hint non ha autorità** (paletto 1) — la SNR guida è un proxy contaminato
  (seeing/fuoco/magnitudine): può solo ANTICIPARE la sonda entro i limiti. SAFE arriva
  esclusivamente da: sonda reale → N1 fresco → drain §55 → N6.
- **Criterio a TEMPO REALE (§57-bis)** — l'accumulatore dell'hint è in **secondi**
  (`sustained_seconds=60`), non in campioni: il comportamento è identico con guide-frame
  da 0.5 s o da 4 s, fisicamente coerente con l'evoluzione del cielo.

## 4. Limitazioni e comportamenti del Sequencer scoperti in ricognizione

1. **`Wait Until Safe` core non ospita istruzioni** (verificato sul sorgente: puro poll
   5 s) — per questo serve il loop nel *Before*, non si può "arricchire" l'attesa interna.
2. **I container del `Trigger On Unsafe` rifiutano le istruzioni di categoria Camera**
   (verificato sulla GUI reale, NINA 3.3.0.1048): il sorgente del trigger non mostra
   restrizioni — il filtro è nel layer GUI/drop (probabile protezione contro esposizioni
   doppie nei trigger). Le istruzioni del plugin (categoria propria) sono accettate:
   da qui la sonda autocontenuta.
3. **I container del trigger rifiutano ANCHE container e condizioni di ciclo**
   (`Loop While Unsafe` incluso — seconda evidenza sperimentale sulla GUI, 14/7):
   l'istruzione esiste nella libreria ma il drag&drop nel *Before* viene rifiutato,
   esattamente come per le istruzioni Camera. Per questo il ciclo è INTERNO alla
   Recovery probe (§57-ter): il *Before* gira una volta, ma l'istruzione non ritorna
   finché il monitor non è SAFE (o la sequenza viene annullata). Se torna unsafe
   durante l'*After*, il trigger riparte da capo: corretto per noi.
4. **`Trigger On Unsafe` è solo 3.3+** — su NINA 3.2 la stessa logica si costruisce con
   blocchi alternati in container normali (`Loop While Safe [imaging]` → `Loop While
   Unsafe [recovery]`), dove le istruzioni Camera SONO ammesse: lì funziona anche il
   pattern gate + `Take Exposure` esterno.
5. **Warning rossi (!) su Parcheggia/Trova Home nel container**: il `Validate()` del
   trigger aggrega i problemi dei figli (tipicamente "montatura non connessa" al momento
   della validazione). Da ispezionare quando faremo il §58.
6. **La Recovery probe mostra un warning se la camera non è connessa** (validazione
   propria): è normale in fase di editing della sequenza a equipment scollegato.

## 5. Cosa osserverai (telemetria di validazione, paletto 8)

- **Dashboard → card "Recovery (§57)"**: stato hint live (IN OSSERVAZIONE / CIELO IN
  RECUPERO?), SNR/riferimento, accumulatore in secondi, **ultima sonda** (S1/S2 → esito N1).
- **`logs/agent.log`**: `[recovery_hint] ACTIVE — …` / `[recovery_probe] sonda osservata:
  trigger=timeout_S1|hint_S2 -> index=… state=…`.
- **Log NINA**: `RecoveryProbe: gate OPEN — recovery hint active (S2) … -> probing 300s
  LIGHT (replica of last light: gain=100 offset=50 bin=1x1 filter=L)`.
- A fine notte: confronta i `gate OPEN` (NINA) coi record sonda (agente) → di quanto S2
  ha anticipato S1 e con quale esito → taratura di `[recovery_hint]`.

## 6. Prova a banco (pannello Gemini)

1. Sequenza attiva col template → chiudi il pannello → N1 scende → N6 UNSAFE →
   la sequenza entra nel trigger; il loop sonda parte.
2. Lascia chiuso > 12 min: verifica le sonde S1 a cadenza (log + card), con parametri
   replicati dall'ultimo sub.
3. Riapri il pannello: la SNR guida risale → hint ACTIVE (~60 s sostenuti) → sonda
   anticipata S2 → indice risale → drain §55 → SAFE → il loop esce e la sequenza riprende.
   Cronometra: atteso ≤ ~2-3 min dal ritorno del sereno (vs 12 min max del solo S1).
