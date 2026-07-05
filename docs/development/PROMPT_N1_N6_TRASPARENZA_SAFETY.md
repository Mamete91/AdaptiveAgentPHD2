# PROMPT per Claude Code — N1 (riconoscitore trasparenza) + N6 (safety su nubi) — architettura a livelli

> **Motivazione di campo (2026-06-21):** nuvole copiose hanno confuso il modulo SEEING (degrado da nubi letto come seeing) e il **Safety Monitor NON ha fermato la ripresa**, perché oggi va UNSAFE solo su `STAR_LOST` di guida (5 min), non sulle nubi. Il **conteggio stelle dei light NINA** cambiava molto da posa a posa = firma delle nubi. Quel segnale **arriva già** all'Agente (§42) ma nessuno lo consuma. → costruiamo il consumatore-sicurezza (N6) sopra il riconoscitore (N1).
>
> **Architettura a livelli (confermata):** **N1 è l'UNICO modulo che riconosce la trasparenza** (Layer-2, nell'Agente); **N6 e N8 sono semplici consumatori** dello stato di N1. Questo prompt implementa **N1 + N6**. N8 (confidence del motore) sarà un secondo consumatore dello STESSO N1, in un prompt successivo — **N1 si definisce UNA volta, qui.** (Supersede la parte N1 del precedente `PROMPT_N1_N8_FUSIONE_NINA_LIVE.md`.)
>
> **Tre vincoli reali del progetto (da rispettare):**
> 1. **Cross-processo:** N1 gira nell'**Agente** (Python) ed espone su `/status.nina.transparency`; N6 vive nel **plugin** (C#) e lo legge tramite il **polling di `/status` che già fa** (`AgentHealthChecker`, oggi legge `guiding_state`).
> 2. **Un solo riconoscitore, decisione/isteresi PER-CONSUMATORE:** N1 espone **sia l'indice continuo** (per N8, penalità proporzionale) **sia lo stato discreto** CLEAR/HAZE/CLOUD (per N6/dashboard). L'**isteresi di sicurezza** (quanto deve durare una nube per fermare la sequenza) sta in **N6**, non in N1.
> 3. **N6 FAIL-SAFE:** se la trasparenza manca/è stantia (Agente spento, niente telemetria) → N6 **non ha opinione** sulle nubi: NON forza UNSAFE né blocca; resta lo `STAR_LOST` di guida come backstop. Agire solo su segnale CLOUD **positivo e fresco**.
>
> **Metodologia (`METODOLOGIA_VALIDAZIONE_LIVE.md`):** operativo, **visibile**, reversibile (kill-switch). **Direttiva NINA:** sorgente al tag release + docs ufficiali.
> **Numerazione:** `grep "^## [0-9]" NOTE_CLAUDE.md | tail -1` → usa due § liberi (uno N1, uno N6). Verifica.
> Contesto: §41/§42 (`nina_telemetry.py`, `/status.nina`), plugin `AgentHealthChecker.cs` + `SafetyDecisionEngine.cs` + `AdaptiveAgentSafetyMonitor.cs`, `ARCHITETTURA_FILONE_DIAGNOSTICO_NINA.md`, P1.

## FASE 0 — VERIFICA (sola lettura, riportare)
1. **Agente:** `nina_telemetry.py` store (`image.star_count`, `median_adu`, `mean_adu`, `filter`, `exposure_s`, `is_fresh`), e come `/status` monta il blocco `nina`. Confermare che star_count/ADU arrivano (visto in campo).
2. **Plugin:** `AgentHealthChecker.ProbeStatusAsync` legge oggi solo `controller.guiding_state`; `AgentStatusSnapshot` record; `SafetyDecisionEngine.Evaluate` (STAR_LOST consolidato). Riportare file:riga. Il plugin builda contro **SDK 3.2** (leggere `/status` è JSON puro, **version-agnostic** → N6 gira su 3.2 e 3.3).
3. **NINA doc/API:** confermare la semantica `ISafetyMonitor.IsSafe`/`Connected` (già usata da `AdaptiveAgentSafetyMonitor`). Doc: la sequenza deve avere "Wait Until Safe" **dentro il loop** per protezione continua (nota utente, non codice).

## §A — N1: riconoscitore di trasparenza (Agente, `nina_indices.py`, Layer-2 — store §42 intatto)
1. **Baseline per-target E per-filtro, RELATIVA (mai soglie assolute):** riferimento "cielo più limpido recente" per QUESTO campo+filtro (rolling-high/best-fraction del `star_count`; il `filter` è nel payload; il target non c'è finché non arriva N2 → rilevare il cambio target da un salto di regime del `star_count` e ri-formare). Nota onesta: robusta appieno con N2.
2. **TransparencyIndex (CONTINUO, 0..1):** blend relativo di **conteggio stelle + fondo cielo** (NIENTE HFR), con **enfasi sul TREND** (calo % rapido su 2-3 pose = nube; livello basso ma stabile = campo povero, NON è nube). **Persistenza ≥2-3 pose + dead-band** (una singola posa anomala non conta).
3. **Stato DISCRETO** CLEAR / HAZE / CLOUD derivato dall'indice (soglie config). *(L'isteresi di sicurezza vera è in N6.)*
4. **Espone su `/status.nina.transparency`**: `{ index (continuo), state, star_count, base_stars, background, filter, fresh }` — **sia continuo sia discreto**.
5. **Dashboard:** card "Trasparenza (NINA)" live (indice + stato). Log (`transparency_index`, `transparency_state`).
6. Config `[nina_indices] enabled=true` + soglie `clear_above`/`cloud_below` + isteresi indice + finestra pose. Kill-switch. Graceful: niente telemetria → `transparency=null`, resto invariato.
7. **N1 è il solo riconoscitore:** N8 (futuro) userà `index` continuo; N6 (sotto) usa `state`. Nessun'altra parte ricalcola le nubi.
**Test:** calo % rapido stesso campo/filtro → CLOUD; livello basso ma stabile → CLEAR (anti-soglia-assoluta); singola posa anomala → ignorata (persistenza); cambio filtro/target → riforma; graceful. Suite verde.

## §B — N6: Safety su nubi (plugin C#, estende il Safety Monitor esistente)
1. **`AgentHealthChecker.ProbeStatusAsync`:** oltre a `guiding_state`, leggere `nina.transparency` (`state`, `index`, `fresh`) dal `/status` che già interroga. Estendere `AgentStatusSnapshot` con questi campi (tolleranti: assenti → null/`fresh=false`).
2. **`SafetyDecisionEngine`:** aggiungere una condizione di trasparenza **accanto** a STAR_LOST (non sostituirla):
   - **UNSAFE** quando `state == CLOUD` **persiste per N poll consecutivi** (isteresi di sicurezza, tarabile — es. N tale da coprire ~2-3 pose). Asimmetrica: **lento** verso UNSAFE.
   - **RECOVERY (SAFE)** quando `state ∈ {CLEAR, HAZE}` per M poll consecutivi (M tarabile). Prudente ma più rapido del go-unsafe.
   - Una **velatura breve (HAZE transitorio)** NON deve mandare UNSAFE; un **CLOUD persistente** sì.
3. **FAIL-SAFE (critico):** se `fresh==false` o `transparency` assente (Agente giù / telemetria stantia) → la condizione nubi è **neutra**: NON forza UNSAFE, NON forza SAFE. Resta attiva solo la logica STAR_LOST (backstop di guida). Agire su nubi **solo** con segnale CLOUD positivo e fresco.
4. **Confine invariato:** il Safety Monitor riporta UNSAFE/SAFE; **NINA** decide (pausa/park). Notifiche/log come le esistenti (STAR_LOST), distinguendo la causa (`STAR_LOST` vs `CLOUD`).
5. Settings plugin: toggle "Safety su nubi (NINA)" (default ON) + soglie persistenza N/M. Kill-switch. Version bump plugin.
6. **Cross-version:** nessuna dipendenza da API NINA 3.3 (si legge JSON) → gira su 3.2 e 3.3. Build 3.2-SDK.
**Test:** CLOUD persistente N poll → UNSAFE (causa `CLOUD`); HAZE breve → NON UNSAFE; ritorno CLEAR M poll → SAFE; **STAR_LOST continua a funzionare**; **fail-safe:** `fresh=false` → nessun UNSAFE spurio, STAR_LOST resta backstop; kill-switch off → solo STAR_LOST (legacy). Build pulita.

## VISIBILITÀ (metodologia live)
- Dashboard: stato trasparenza (da N1) + stato Safety Monitor con **causa** (STAR_LOST / CLOUD / nessuna). Marcatore/log quando N6 transita.
- Così in campo vedi in diretta: nubi in arrivo → N1 passa a CLOUD → (dopo l'isteresi) N6 → UNSAFE → NINA mette in pausa. Verificabile a vista, come da metodologia.

## CHIUSURA
- **NON toccare:** motore/leve §31, baseline §44, telemetria §41/§42 (Layer-1), la logica STAR_LOST esistente (si affianca, non si sostituisce), backlash.
- **REBUILD:** Agente (`build_dist.py`, config con `[nina_indices]` attivo) + **plugin** (`dotnet build -c Release`, DLL nuova) su Lenovo (3.3) e per il campo Minixz100. Verifica config nel pacchetto. Niente commit/push.
- **DOC:** `NOTE_CLAUDE.md` (§ N1 + § N6) + `CONTESTO_PROGETTO.md` + README plugin (nuova capability + **nota utente: "Wait Until Safe" va dentro il loop di ripresa per protezione continua**) + `VALIDAZIONE_CAMPO_v2.6.md` + `ARCHITETTURA_FILONE_DIAGNOSTICO_NINA.md` (N1 fatto, N6 fatto, N8 = prossimo consumatore).

## CHECKLIST
- [ ] FASE 0: store §42 + montaggio `/status.nina`; `AgentHealthChecker`/`SafetyDecisionEngine`/`AgentStatusSnapshot` (file:riga); build 3.2-SDK confermato.
- [ ] §A N1: baseline per-target/filtro RELATIVA; TransparencyIndex continuo (stelle+fondo, NO HFR, enfasi TREND, persistenza ≥2-3); stato CLEAR/HAZE/CLOUD; `/status.nina.transparency` continuo+discreto; card dashboard; graceful; kill-switch; **unico riconoscitore**.
- [ ] §B N6: `/status` legge `nina.transparency`; `SafetyDecisionEngine` + condizione CLOUD **accanto** a STAR_LOST; isteresi asimmetrica N/M; **FAIL-SAFE** su `fresh=false`; confine (NINA pausa, plugin segnala); causa distinta; settings+kill-switch; version bump; build 3.2 pulita.
- [ ] Visibilità live (stato trasparenza + causa safety); rebuild Agente+plugin; nessuna regressione §31/§41/§42/STAR_LOST; doc; niente commit.

> **P1 + architettura:** un solo occhio riconosce le nubi (N1), più consumatori lo usano ciascuno a modo suo (N6 ferma la ripresa, N8 — poi — pesa la diagnosi). N6 ferma le nubi **prima** di perdere la stella di guida → non spreca light. E se il segnale manca, N6 tace e lascia la guida come rete: una sicurezza che degrada in modo sicuro.
