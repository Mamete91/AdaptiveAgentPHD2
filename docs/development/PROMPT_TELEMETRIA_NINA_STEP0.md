# PROMPT per Claude Code — §41: Step 0 telemetria NINA → Agente (ponte di ingresso, lato Agente)

> **Questo è lo Step 0 della roadmap NINA** (`ROADMAP_TELEMETRIA_NINA.md`): il prerequisito che gatea N1–N8. Oggi il flusso plugin→Agente è di **sola lettura** (il plugin fa `GET /about` + `GET /status`); **non esiste alcun canale in ingresso** sull'Agente per ricevere le metriche per-posa di NINA (HFR, conteggio stelle, SNR/fondo, eccentricità). Questo prompt apre quel canale.
> **Perimetro di questo prompt = SOLO il lato Agente Python.** Crea il "tubo" e lo store, lo espone, lo versiona. **Nessun consumatore agisce ancora** sui dati: context-gating (N2), trasparenza (N1), safety (N6), tag (N7), confidence (N8) sono **prompt successivi**, separati. Qui non si tocca il motore §31, non si toccano le leve, non si tocca la baseline.
> **Lato plugin (iscrizione a `IImageSaveMediator.ImageSaved` + inoltro POST) è RIMANDATO** al ripristino del PC principale (plugin congelato). Qui se ne **specifica solo il contratto JSON** (sezione 2E) così il lato-plugin si potrà sviluppare in parallelo senza sorprese.
> **È infrastruttura, non modello matematico** → soglia di validazione bassa: basta non-regressione + il nuovo endpoint testato con un POST simulato. Non serve una sessione di campo per spedirlo (l'Agente senza telemetria si comporta **identico a oggi**).
> **Direttiva:** feed **opzionale e graceful**; endpoint **difensivo** (un payload malformato non deve MAI poter disturbare il loop di guida); nuove chiavi **attive (`true`) nel `config.toml`** (born-operative, ma inerte finché nessuno POSTa).
> **Numerazione doc:** `grep "^## [0-9]" NOTE_CLAUDE.md | tail -1` → atteso §40 → usa **§41**.
> Contesto: `REVISIONE_ARCHITETTURALE_v2.6.md` (§7, §9), `ROADMAP_TELEMETRIA_NINA.md`, `PRINCIPIO_CONVERGENZA_PRESTAZIONE.md` (P1).

## 0. PRE-FLIGHT OBBLIGATORIO (sola lettura — confermare prima di toccare)

1. **`server.py`** — confermare la superficie attuale: `GET /` `/about` `/status` `/history`, `POST /config/dry_run` `/config/ai_find` `/config/diagnostic_mode`, `WS /ws`; middleware CORS `allow_origins=["*"]`; `set_global_state(controller, analyzer, session_logger)`; pattern `BaseModel` per i payload POST. Confermare che **non** esista già un endpoint in ingresso per NINA.
2. **`controller.get_status()`** (~`controller.py:2250`) — confermare la struttura del blocco restituito (chiavi `guiding_state`, `auto_calibration`, `diagnostic_engine`, …). Lo store telemetria NINA verrà esposto **qui dentro** o accanto in `/status` (decisione di design sotto).
3. **`phd2_agent/__about__.py`** — la versione (`2.6`) è single source of truth. **Non** bumpare la versione in questo prompt (è una feature, non una release): la release la farà un prompt git dedicato.
4. **`config.py`** — confermare il pattern dataclass + parsing TOML (`load_config`), per aggiungere una sezione `[nina_telemetry]` coerente con le altre.
5. **`logger.py`** — confermare come il logger di sessione scrive il CSV/JSONL, per decidere se loggare gli arrivi di telemetria (opzionale, vedi 2D).
6. **Decisioni di design da prendere e dichiarare** prima di implementare:
   - nome endpoint: **`POST /nina/telemetry`** (proposto) vs `/ingest/nina`;
   - dove esporre lo store in `/status`: blocco nuovo **`nina`** top-level (proposto, simmetrico a `controller`/`analyzer`) — NON dentro `controller` (è telemetria esterna, non stato del controller);
   - thread-safety: l'Agente ha il loop eventi PHD2 + uvicorn; lo store va protetto (lock leggero o struttura atomica).

## 1. OBIETTIVO TECNICO

Aprire un canale **in ingresso** sull'Agente che riceve le metriche per-posa di NINA via HTTP POST, le conserva in uno **store opzionale in memoria** (ultimo valore + breve storico), e le **espone in `/status`** per dashboard e futuri consumatori. Contratto JSON **versionato**. Zero effetti sul comportamento di guida: senza POST, l'Agente è bit-identico a oggi.

## 2. SPECIFICA FUNZIONALE

### 2A — Endpoint `POST /nina/telemetry` (difensivo)
1. Nuovo modello Pydantic `NinaTelemetryPayload` con i campi del contratto (2E). **Tutti opzionali** tranne `schema_version`: un campo mancante → ignorato, mai un errore 500.
2. Validazione difensiva: tipi/range sanity (es. `star_count >= 0`, `hfr >= 0`); valori fuori-range → scartati con `400`/`422` **senza** toccare lo store. **Mai** sollevare eccezioni che risalgano al loop.
3. Su payload valido: aggiorna lo store (2B), ritorna `200` con `{"accepted": true, "schema_version": N}`.
4. Idempotente e stateless rispetto alla guida: l'endpoint **non** chiama né il controller né il motore né le leve. Solo store.

### 2B — Store telemetria in memoria (`phd2_agent/nina_telemetry.py`, nuovo modulo)
1. Classe `NinaTelemetryStore`: ultimo payload (`last`), timestamp di arrivo, e un piccolo `deque(maxlen=…)` di storico (per future baseline per-campo/trend). Thread-safe (lock).
2. Property `is_fresh` (es. ultimo arrivo < `staleness_seconds`) per distinguere "telemetria assente" da "telemetria stantia".
3. **Nessuna logica derivata qui** (niente TransparencyIndex, niente indici Layer-2): questo è puro Layer-1 (telemetria grezza). Gli indici sono prompt successivi.
4. Istanza creata in `main.py` e passata a `server.set_global_state(...)` (estendere la firma in modo retrocompatibile) **oppure** registrata via un setter dedicato `server.set_nina_store(store)` — scegliere l'opzione meno invasiva e dichiararla.

### 2C — Esposizione in `/status`
1. Aggiungere un blocco top-level **`nina`** alla risposta di `/status`:
   ```json
   "nina": {
     "enabled": true,
     "connected": false,           // is_fresh: true se è arrivata telemetria recente
     "schema_version": 1,
     "last_age_s": null,           // secondi dall'ultimo POST, null se mai
     "metrics": { ... }            // ultimo payload grezzo, {} se assente
   }
   ```
2. Con store assente/disabilitato o nessun POST mai ricevuto: `connected:false`, `metrics:{}`, `last_age_s:null`. La dashboard mostrerà "NINA non connesso" senza errori.

### 2D — Config `[nina_telemetry]`
```toml
[nina_telemetry]
# Step 0 (§41): canale in ingresso per le metriche per-posa di NINA (HFR, conteggio
# stelle, SNR, fondo cielo, eccentricità) inoltrate dal plugin. OPZIONALE e GRACEFUL:
# senza POST l'Agente si comporta identico. Nessun consumatore agisce ancora sui dati
# (context-gating/trasparenza/safety/confidence sono feature successive).
enabled            = true     # ATTIVO (born-operative, ma inerte senza dati in arrivo)
staleness_seconds  = 180.0    # oltre questo l'ultima telemetria è "stantia" (is_fresh=false)
history_frames     = 60       # storico in memoria per future baseline per-campo
log_arrivals       = false    # se true, logga ogni arrivo di telemetria (debug)
```
Kill-switch: `enabled=false` → l'endpoint risponde `200 {"accepted": false, "reason": "disabled"}` e non memorizza; `/status.nina.enabled=false`.

### 2E — CONTRATTO JSON versionato (specifica per il lato plugin, da implementare al ripristino PC)
Il plugin, iscritto a `IImageSaveMediator.ImageSaved` di NINA, POSTerà a ogni sotto-posa salvata:
```json
{
  "schema_version": 1,
  "source": "nina-plugin",
  "ts_unix": 1750000000.0,
  "image": {
    "hfr": 2.13,                 // HFR medio (px) dalla star detection NINA
    "hfr_std": 0.31,
    "star_count": 842,           // stelle rilevate sul light frame
    "eccentricity": 0.42,        // medio (se disponibile nello StarDetectionAnalysis)
    "mean_adu": 1234.5,          // statistiche immagine (proxy SNR/fondo)
    "median_adu": 1180.0,
    "stdev_adu": 210.0,
    "exposure_s": 300.0,
    "filter": "L"
  },
  "context": {                   // per il futuro N2 context-gating (può mancare)
    "activity": "EXPOSING",      // EXPOSING | AUTOFOCUS | MERIDIAN_FLIP | FILTER_CHANGE | SLEW | PLATESOLVE | DITHER | IDLE
    "target": "NGC 7000"
  }
}
```
Regole di contratto (§9 della revisione): **`schema_version` obbligatorio**; campi mancanti tollerati su entrambi i lati; l'Agente non assume la presenza di `context` (arriva con N2). **Le firme esatte di `ImageSavedEventArgs`/`StarDetectionAnalysis` vanno verificate contro l'SDK della NINA installata** quando si farà il lato plugin: dove vive l'eccentricità cambia tra minor version.

### 2F — Lato plugin (NON in questo prompt — documentare come "rimandato")
Annotare in NOTE/CONTESTO che il lato plugin (iscrizione eventi NINA + inoltro POST + eventuale FITS keyword/sidecar per N7) è **rimandato al ripristino del PC principale** (plugin congelato). Il plugin ha già `HttpClient` e il poller (`AgentHealthChecker`): l'aggiunta sarà un secondo client POST, non una riscrittura.

## 3. REGOLE INDEROGABILI
- **Isolato a:** `server.py` (nuovo endpoint + modello + blocco `/status`), nuovo `phd2_agent/nina_telemetry.py`, `config.py` (nuova sezione), `main.py` (creazione store), `[nina_telemetry]` nel `config.toml`. **NON toccare:** `diagnostic_engine.py`, le leve/`controller` decisionale, `analyzer.py`, la baseline RMS, l'esposizione, il **backlash** di PHD2.
- **Opzionale e graceful:** senza POST o con `enabled=false`, comportamento **bit-identico** a oggi. La telemetria può solo *informare*, mai *poter degradare* la guida.
- **Difensivo:** nessuna eccezione dall'endpoint deve mai raggiungere il loop eventi/guida. Payload malformato → scartato, loggato (se `log_arrivals`), guida intatta.
- **Nessun consumatore qui:** lo store NON viene letto da motore/controller/leve in questo prompt. Solo `/status` lo espone.
- Retrocompatibilità totale della firma `set_global_state` / `get_status` (estendere, non rompere; i test esistenti su `/status` devono restare verdi).

## 4. TEST ATTESI (Code DEVE validare la correttezza — nuovo `tests/test_nina_telemetry.py`)
1. **POST valido** → `200 {"accepted":true}`; `/status.nina.metrics` riflette il payload; `connected:true`; `last_age_s` piccolo.
2. **Campi mancanti** (es. solo `schema_version`+`hfr`) → accettato, gli altri campi assenti/`null`, nessun 500.
3. **Payload malformato / tipi errati / valori fuori-range** → `422`/`400`, store **invariato**, nessuna eccezione propagata.
4. **`enabled=false`** → `200 {"accepted":false,"reason":"disabled"}`, store vuoto, `/status.nina.enabled=false`.
5. **Staleness** → dopo `staleness_seconds` senza nuovi POST, `is_fresh=false`, `/status.nina.connected=false` (ma `metrics` conserva l'ultimo).
6. **Graceful assente** → senza alcun POST, `/status` ha `nina.connected=false, metrics:{}`, e tutto il resto della risposta è **identico** al pre-§41 (diff solo per il blocco `nina`).
7. **Isolamento/regressione:** suite esistente verde (atteso ≥180); nessuna modifica osservabile a controller/motore/leve; un GuideStep processato con e senza telemetria produce le **stesse** decisioni.
8. **Thread-safety:** POST concorrenti + letture `/status` in parallelo non corrompono lo store (test con thread).

## 5. VALIDAZIONE SUL CAMPO (leggera, opzionale per questo step)
Non serve una sessione di campo per spedire (è infrastruttura). Sanity manuale: avviare l'Agente, fare un POST con `curl`/script di un payload d'esempio, verificare in dashboard/`/status` che compaia il blocco `nina` popolato e che torni "non connesso" dopo `staleness_seconds`. La validazione di campo vera arriverà col **lato plugin** (al ripristino PC) e coi consumatori (N2…).

## 6. PROCEDURA REBUILD
`python build_dist.py` → ZIP + `Pacchetto_Distribuzione/`. Verificare che il `config.toml` **dentro** il pacchetto abbia `[nina_telemetry] enabled=true` insieme a tutte le chiavi §36→§40 già attive. **Niente bump versione, niente commit/push** in questo prompt (li farà un prompt git/release dedicato, eventualmente accorpando i prossimi step NINA).

## 7. AGGIORNAMENTO DOCUMENTAZIONE
- **`NOTE_CLAUDE.md` §41** — "Step 0 telemetria NINA (lato Agente): `POST /nina/telemetry` + `NinaTelemetryStore` opzionale/graceful + blocco `nina` in `/status`; contratto JSON `schema_version=1`; nessun consumatore (N1–N8 successivi); lato plugin rimandato al ripristino PC. Infrastruttura, non modello."
- **`CONTESTO_PROGETTO.md`** — nota sotto lo stato v2.6: aperto il canale in ingresso NINA→Agente (Step 0), inerte finché il plugin non inoltra.
- **`ROADMAP_TELEMETRIA_NINA.md`** — spuntare Step 0 (lato Agente fatto; lato plugin rimandato).

## 8. CHECKLIST FINALE
- [ ] PRE-FLIGHT confermato con citazioni `file:riga` (superficie `server.py`, struttura `get_status`, pattern config); confermato che nessun endpoint in ingresso esisteva.
- [ ] `POST /nina/telemetry` difensivo: valido→200/store; malformato→422 senza eccezioni; mai disturba il loop.
- [ ] `phd2_agent/nina_telemetry.py`: `NinaTelemetryStore` thread-safe, `last`+storico+`is_fresh`, **nessuna logica derivata**.
- [ ] Blocco `nina` top-level in `/status` (NON dentro `controller`); graceful con store assente.
- [ ] `[nina_telemetry]` nel `config.toml` **attivo**; kill-switch `enabled=false` testato (comportamento identico al pre-§41).
- [ ] Contratto JSON `schema_version=1` documentato (2E); tolleranza campi mancanti su entrambi i lati.
- [ ] **Nessuna modifica** a motore/leve/baseline/esposizione/backlash; decisioni di guida invariate con/senza telemetria.
- [ ] Test 1–8 in `tests/test_nina_telemetry.py`; suite esistente verde.
- [ ] ZIP + Pacchetto_Distribuzione rigenerati con `[nina_telemetry] enabled=true`; nessun bump versione, nessun commit.
- [ ] NOTE §41 + CONTESTO + ROADMAP aggiornati; lato plugin annotato come rimandato.

> **P1 / coerenza con la revisione.** Questo step non migliora l'RMS e non deve: apre l'occhio ortogonale (la forma reale delle stelle nella posa) che servirà a *disambiguare* la causa del degrado e, in prospettiva, a **validare la correttezza del motore §31** (RMS↑+HFR↑ = seeing reale vs RMS↑+HFR piatto = meccanica). È il tubo; l'intelligenza che ci scorre dentro (N2→N1→N8→N3/N4) arriva nei prompt successivi, ciascuno col proprio gate di validazione.
