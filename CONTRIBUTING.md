# Contribuire

Grazie per l'interesse! Questo progetto adatta i parametri di **PHD2** in tempo reale e
si valida **esclusivamente sul campo**, in sessioni reali di autoguida. Il contributo più
prezioso non è necessariamente codice: sono **prove sul campo documentate**.

## Provare l'agente e riportare i risultati

1. Segui l'avvio descritto nel [README](README.md). La prima notte con un setup nuovo gira
   sempre in **DRY_RUN** (`dry_run = true`) per calibrare le soglie sui dati reali prima di
   passare a LIVE.
2. A fine sessione trovi in `logs/` i file `session_*.csv`, `decisions_*.jsonl` e
   `*.summary.json`.
3. Apri una **issue** su GitHub con: setup (telescopio/focale, camera di guida, pixel
   scale), condizioni di seeing/trasparenza, cosa hai osservato e — se possibile — i file
   di log allegati. Anche i risultati "è andato tutto bene" sono utili: confermano la
   validazione.

## Modifiche al codice

- Il **comportamento di guida è validato**: proposte che toccano la legge di controllo
  (motore Outcome-First: §44/§50/§51/§53) vanno accompagnate da **evidenza sul campo**, non
  solo da test verdi. Ogni intervento sulle leve deve restare dietro un kill-switch.
- Le nuove chiavi di `config.toml` nascono operative (attive di default) solo se già
  validate; altrimenti dietro flag `false`.
- Esegui la suite prima di aprire una PR:
  ```
  python -m unittest discover -s tests
  ```
- La cronologia tecnica e la metodologia di validazione sono in
  [`docs/development/`](docs/development/) (`NOTE_CLAUDE.md`,
  `METODOLOGIA_VALIDAZIONE_LIVE.md`).

## Plugin NINA

Il plugin NINA (C#) vive in un **repository separato**; qui è presente solo la sua
integrazione lato agente. Le questioni relative al plugin vanno aperte in quel repo.

## Licenza

Contribuendo, accetti che il tuo contributo sia distribuito sotto licenza
**BSD-3-Clause** (vedi [`LICENSE`](LICENSE)).
