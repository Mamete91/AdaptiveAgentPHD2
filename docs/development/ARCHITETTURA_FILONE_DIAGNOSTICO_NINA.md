# Architettura del filone diagnostico NINA — N1 → N8 → N4 (un'unica catena, implementazioni separate)

**Data:** 2026-06-19. Recepisce l'intuizione di Alessandro: N1/N8/N4 non sono feature indipendenti, ma **una sola catena logica** che va **progettata coerente fin dall'inizio**, pur con **implementazioni e test separati** (niente blocco monolitico difficile da validare).

## La catena (input → decisione → verifica)
```
PHD2 (stella di guida: come si MUOVE)
        │
   N1  CONTESTO atmosferico        → trasparenza (stelle/fondo)         [Layer-2 indice]
        │
   N8  DECISIONE                   → il motore USA il contesto:          [Layer-3 consumatore]
        │                            modula la confidence SEEING (nubi vs seeing)
        │
   N4  VERIFICA dell'esito reale   → eccentricità = forma reale delle    [Layer-3 consumatore/outer-loop]
                                      stelle sul light frame
```
- **N1 = l'occhio sul cielo** (contesto): che trasparenza c'è.
- **N8 = l'uso del contesto** nella diagnosi: distingue degrado da nubi (non lever-fixable) da degrado da seeing/meccanica.
- **N4 = l'occhio sul risultato** (esito): le stelle finali sono tonde o allungate? Chiude il cerchio.

**Perché N4 completa il filone (non è una feature a sé):** l'RMS di guida è un **proxy**; l'obiettivo reale è **stelle tonde nella posa**. N4 (eccentricità) misura l'obiettivo reale → **verifica se le decisioni del motore (RMS + contesto N8) hanno davvero prodotto buone stelle**. È l'anello esterno di conferma della correttezza del motore (il "debito di correttezza" della revisione architetturale).

## Principio di progettazione: "una catena, tre blocchi separati"
- **Architettura condivisa, progettata ora** (questo documento + i provider/baseline comuni): N1/N8/N4 devono dialogare. Riuso comune: la **baseline per-campo/per-filtro**, la **persistenza ≥2-3 pose**, il **dead-band sul rumore**, il pattern **provider→motore**, e la **visibilità live** (evidence + grafico).
- **Implementazioni e test SEPARATI** (blocchi distinti): ogni blocco si valida **in diretta sul cielo** su una domanda diversa:
  - N1/N8 → "il motore attribuisce il degrado a nubi vs seeing correttamente?"
  - N4 → "l'eccentricità segnala elongazioni/problemi di guida che l'RMS non vede?"
  → bundle in un unico prompt = validazione confusa. Separati = validazione live pulita (regola "una modifica-motore per volta").

## Ruoli e impatto sulle leve (onesto)
- **N1/N8 v1:** impatto leve **minimo** (gate sulla confidence SEEING → "a volte una micro in meno"). Valore = **consapevolezza**, non rivoluzione della guida.
- **N4 v1:** ruolo **osservativo/di verifica** — misura l'eccentricità vs il riferimento del rig, la mostra, la **correla** con le diagnosi del motore. **NON pilota le leve** in v1. L'eccentricità per-asse (RA/DEC, richiede mappatura angolo camera) e l'eventuale uso decisionale = evoluzioni successive.
- Il **nucleo che controlla la guida** resta Guardian + Jitter + baseline bidirezionale. Questo filone NINA è il **secondo livello: consapevolezza della qualità del cielo e delle immagini.**

## Vincolo di versione NINA 3.2/3.3 (decisione architetturale)
Il Lenovo è ora su **NINA 3.3** → **rimosso l'ostacolo a SVILUPPARE/TESTARE N4** (eccentricità/FWHM esistono e si possono esercitare in locale). **MA il vincolo di distribuzione resta:** gli utenti sono divisi 3.2/3.3.
→ **Il target di build del plugin resta l'SDK 3.2** (lowest common denominator: una sola DLL gira su 3.2 e 3.3). Eccentricità/FWHM si leggono via **reflection** (presenti su 3.3 → letti; assenti su 3.2 → `null`). Il contratto §41 ha già i campi `eccentricity`/`fwhm` (nullable). **Beneficio concreto del Lenovo→3.3:** ora la **present-path** della reflection si testa direttamente sul PC di sviluppo (prima solo sul campo, Minixz100). **NON cambiare il target a 3.3** (romperebbe gli utenti 3.2).

## Sequenza operativa
1. **Blocco 1 — N1+N8** (`PROMPT_N1_N8_FUSIONE_NINA_LIVE.md`): solo Agente+dashboard, nessun lavoro plugin. → implementa, rebuild, **valida in diretta** una sessione.
2. **Blocco 2 — N4** (`PROMPT_N4_ECCENTRICITA_LIVE.md`): plugin (reflection eccentricità/FWHM) + Agente (indice qualità stelle, osservativo) + dashboard. Riusa la baseline/persistenza di N1. → si consegna **dopo** che N1/N8 è dentro (così riusa l'infrastruttura comune e si valida separatamente).

## Stato di avanzamento (aggiornato 2026-06-21)
- ✅ **N1 — riconoscitore trasparenza** (§45, finalizzato §48): unico modulo Layer-2 (`nina_indices.py`), espone `index` continuo + `state` discreto + `fresh` su `/status.nina.transparency`. **È l'unico che riconosce le nubi.**
- ✅ **N8 — confidence fusion** (§46): primo consumatore di N1; usa l'`index` continuo per la penalità proporzionale sulla diagnosi SEEING (solo SEEING; graceful; kill-switch).
- ✅ **N6 — safety su nubi** (§49): secondo consumatore di N1 (nel **plugin**, `SafetyDecisionEngine`); usa lo `state` discreto → UNSAFE su CLOUD persistente (isteresi propria, fail-safe su `fresh=false`). Ferma la ripresa **prima** di STAR_LOST. *(N6 non era nel diagramma della catena N1→N8→N4: è un consumatore di sicurezza parallelo, stesso N1.)*
- ⏳ **N4 — eccentricità/verifica esito** (`PROMPT_N4_ECCENTRICITA_LIVE.md`): **prossimo**. Terzo consumatore; osservativo in v1. Riusa baseline/persistenza/visibilità di N1.

**Principio confermato dal campo:** N1 definito **una volta**; N6/N8 (e poi N4) consumano lo stesso stato, ciascuno con la propria isteresi/decisione. Nessuna duplicazione del riconoscitore nubi.
