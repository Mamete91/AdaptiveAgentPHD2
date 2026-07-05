# Changelog

Tutte le milestone rilevanti del progetto. La cronologia tecnica dettagliata,
sezione per sezione (§), vive in [`docs/development/NOTE_CLAUDE.md`](docs/development/NOTE_CLAUDE.md).

Il progetto segue una filosofia di **validazione esclusivamente sul campo**: ogni
funzione del motore nasce dietro un kill-switch e viene promossa solo dopo sessioni
reali di autoguida.

---

## [2.7] — Milestone "Outcome-First" + filone NINA

Consolidamento del motore adattivo attorno al principio **Outcome-First**: le leve di
PHD2 (`Aggressiveness`, `MinMove`) si muovono solo quando l'esito misurato lo
giustifica, con àncora ai valori standard di PHD2 e ripristino garantito.

### Motore adattivo
- **§44 — Baseline RMS bidirezionale continua.** La baseline di riferimento si aggiorna
  in modo continuo e bidirezionale (finestra rolling best-fraction, comportamento
  EMA-like), mantenendo il cap di sicurezza.
- **§50 — INIT ai valori standard PHD2.** All'avvio le leve partono dai valori standard
  di PHD2 (RA Hysteresis 70 / 0.20, DEC ResistSwitch 100 / 0.20), con skip e warning
  se l'algoritmo attivo non li espone (algorithm-aware).
- **§51 — Cap MinMove adattivo.** Il tetto del MinMove è `min(k · baseline_filtrata,
  ceiling_imaging) / pixel_scale`, con `k` universale < 1 e kill-switch dedicati.
- **§53 — Recupero simmetrico guidato dall'esito.** Quando le leve sono ammorbidite e
  la guida è stabile, il motore le irrigidisce verso lo standard §50 e misura l'esito:
  mantiene l'irrigidimento se l'RMS regge/migliora, ammorbidisce (§32) solo se l'esito
  dimostra seeing reale. Àncora = standard §50. Validato sul campo (percorso felice).
- **§54 — Deprecazione modalità JITTER.** GUARDIAN è la modalità ufficiale, OFF resta un
  A/B legittimo. JITTER (che scavalca il controllore validato) è rimossa dal toggle
  della dashboard e gated dietro il flag `allow_experimental_jitter` (default `false`):
  la richiesta di jitter ricade su GUARDIAN con warning. Il ramo jitter resta nel codice,
  dormiente e raggiungibile solo con flag esplicito.

### Filone NINA (telemetria e sicurezza)
- **N1 — Transparency Index.** Riconoscitore unico di trasparenza del cielo
  (`phd2_agent/nina_indices.py`, Layer-2) che espone indice continuo, stato discreto e
  freshness.
- **N8 — Fusione confidence.** Penalità proporzionale sulla sola diagnosi SEEING, con
  dead-band, persistenza e kill-switch.
- **N6 — Sicurezza cloud (plugin NINA).** Condizione CLOUD nel `SafetyDecisionEngine` del
  plugin, accanto a STAR_LOST, con isteresi asimmetrica e fail-safe.

### Documentazione e igiene del repository
- Nuovi documenti ufficiali: **`ARCHITETTURA_MOTORE.md`** (com'è fatto il motore) e
  **`STUDIO_PHD2_DESIGN.md`** (perché quelle scelte).
- Aggiunta licenza **BSD-3-Clause** (coerente con l'ecosistema PHD2).
- Sorgente di terzi `phd2-master/` e binari (`*.dll`) rimossi dal tracciamento (restano
  nelle Release, non nel sorgente).
- Documenti di sviluppo raccolti in **`docs/development/`** per una root pulita,
  mantenendo la tracciabilità completa del percorso.

## [2.6] — Motore diagnostico operativo

- Motore diagnostico operativo, RMS espresso in arcsec, baseline robusta con rigetto
  delle baseline non rappresentative. Release di riferimento `dda0093`.
