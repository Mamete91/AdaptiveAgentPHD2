# PROMPT PER CLAUDE CODE — TARATURA FINE: CAP AUTO-CALIBRAZIONE A 1.00" + RANGES AGGRESSIVITÀ/MINMOVE PIÙ AMPI
# Da copiare e incollare integralmente nella conversazione con Claude Code.
# Lavorare nella cartella: PHD2_Assist_PATCHED/

> **NOTA OPERATIVA**: addendum a §22 (auto-scala + soglie adattive + config unico) e §23 (clamp proporzionale +
> gate rifiuto baseline). Questa modifica è **solo a parametri**, NESSUNA modifica architetturale né di logica.
> Due cambi distinti:
>
> 1. **Cap auto-calibrazione**: il tetto assoluto `rms_high_max_arcsec` scende da `3.00` a **`1.00`**. Motivazione:
>    l'analisi dei log reali di Alessandro mostra RMS tipici ben sotto il secondo d'arco su tutti i suoi setup
>    (RC8, Tecnosky 115, Askar 71F). Inoltre il tetto a 1,00" risolve il caso "cercatore-guida con focale diversa
>    dall'imaging" (vedi §23 → discussione architetturale): impedisce che la pixel scale grossolana del cercatore
>    porti l'Agente ad accettare soglie troppo lasche per l'ottica di ripresa. Il tetto a 1" allinea l'Agente al
>    benchmark fisico universalmente riconosciuto di "guida pulita".
>
> 2. **Ranges aggressività e MinMove più ampi e armonizzati su RA/DEC**: i range diventano `35-90` su `aggr` per
>    entrambi gli assi (era RA 40-80 / DEC 35-75) e `0.15-0.85 px` su `minmove` per entrambi (era RA 0.15-0.80 /
>    DEC 0.18-0.85). Motivazione: dare al controller più dinamica nei due estremi — più reattivo in cieli ottimi,
>    più tollerante in cieli scarsi — e armonizzare i due assi per coerenza concettuale.
>
> SCOPE: zero modifiche al codice se non i default delle dataclass in `config.py`. Zero modifiche a §19, §20, §21.
> Le modifiche si propagano automaticamente in tutto il sistema perché il `_finalize_rms_baseline` (§23) e la
> logica del controller (§21 e precedenti) già leggono dai default/TOML.

---

## 0. PRE-FLIGHT OBBLIGATORIO (leggere PRIMA di scrivere codice)

### File Python da consultare

1. `phd2_agent/config.py` — verificare i default attuali di:
   - `AutoCalibrationConfig.rms_high_max_arcsec` (atteso `3.00` post-§23) → diventa `1.00`.
   - La dataclass per i limiti per-asse (probabilmente `LimitsConfig` o `AxisLimitsConfig`, verifica nome esatto):
     campi `aggr_min`, `aggr_max`, `aggr_step_down`, `aggr_step_up`, `minmove_min`, `minmove_max`, `minmove_step`.
     I default attuali sono in `config.py` ma vengono sovrascritti dai valori in `[limits.ra]` e `[limits.dec]` del TOML.

2. `config.toml` — verificare le sezioni:
   - `[auto_calibration]` post-§23: contiene `rms_high_max_arcsec = 3.00`.
   - `[limits.ra]` e `[limits.dec]` post-§22 (config unificato): contengono i ranges attuali.

3. `tests/test_auto_calibration.py` — verificare i test §23 che fanno asserzioni sul ceiling 3.00:
   - Test "Cap proporzionale Askar (ceiling)" (era test #2 nel prompt §23): si aspettava `cap_efficace = 3.00`.
     **DEVE essere riscritto** con il nuovo ceiling 1.00 (vedi §2D di questo prompt).
   - Test "Accettazione baseline borderline RC8" (era test #6): la sua asserzione "cap attivo" resta valida con
     il nuovo cap, ma il valore atteso di `cap_efficace` cambia (da 1.02 a 1.00). Verifica e aggiorna.
   - Test "Cap proporzionale RC8" (era test #1): scala 0.51, baseline 0.8 → cap_proporzionale = 1.02,
     `cap_efficace = max(0.70, min(1.00, 1.02)) = 1.00` (era 1.02). Aggiorna l'asserzione.

4. `tests/` — controllare se altri test asseriscono i vecchi default di `LimitsConfig` (aggr_min=40, ecc.).
   Aggiornare per coerenza solo se necessario.

### Conclusioni del pre-flight (già verificate, da confermare)

A. Il clamp `_finalize_rms_baseline` (§23) usa la formula
   `cap_efficace = max(rms_high_min_arcsec, min(rms_high_max_arcsec, rms_high_max_factor * scale))`.
   Cambiare solo il default di `rms_high_max_arcsec` da 3.00 a 1.00 propaga automaticamente: nessun cambio di codice.

B. I ranges aggressività/MinMove vivono in `[limits.ra]` e `[limits.dec]` del config.toml + default in `config.py`.
   Cambiare entrambi (TOML + default Python) garantisce coerenza in tutti i casi.

C. RA e DEC ora condividono lo stesso range (35-90 aggr, 0.15-0.85 minmove) — armonizzazione voluta.

### Nessuna verifica → STOP

Se durante il pre-flight scopri che il nome della dataclass dei limiti è diverso da quello atteso, o che esistono
altri test che asseriscono i vecchi default in modo non banale, **fermati e riportamelo**.

---

## OBIETTIVO TECNICO

Abbassare il tetto assoluto del cap di auto-calibrazione da 3.00 a 1.00 arcsec (allineamento al benchmark fisico
di guida pulita; risolve il caso cercatore-guida) e armonizzare i range di aggressività/MinMove a 35-90 e
0.15-0.85 su entrambi gli assi. Zero modifiche logiche, solo parametri.

---

## REGOLE INDEROGABILI

- **NON toccare** la backlash compensation di PHD2.
- **NON modificare** la logica di `_finalize_rms_baseline` né del controller: solo i parametri di default.
- **NON cambiare** retrocompatibilità del parsing TOML: chiavi assenti → nuovi default.
- **Mantenere** stile esistente (logging in italiano, dataclass, type hints).

### Modalità operativa

Modifica parametri da osservare in LIVE sulla dashboard. `[auto_calibration].enabled` resta `true` (§22).
La sicurezza è garantita dalla logica §22/§23 invariata: cap proporzionale + gate rifiuto baseline + Baseline Guardian.

---

## SPECIFICA FUNZIONALE

### 2A. `config.py` — default `AutoCalibrationConfig.rms_high_max_arcsec`

Modificare solo il default:

```python
@dataclass
class AutoCalibrationConfig:
    # ... campi invariati post-§23 ...
    rms_high_max_arcsec: float = 1.00      # era 3.00 — tetto assoluto del cap (taratura §24)
    # ... altri campi invariati ...
```

### 2B. `config.py` — default dataclass limiti per-asse

Verifica nome esatto (probabilmente `LimitsConfig` o `AxisLimitsConfig`). Modifica i default:

```python
@dataclass
class <NomeDataclassLimiti>:
    aggr_min: int = 35          # era 40
    aggr_max: int = 90          # era 80
    aggr_step_down: int = 5     # invariato
    aggr_step_up: int = 2       # invariato
    minmove_min: float = 0.15   # invariato
    minmove_max: float = 0.85   # era 0.80
    minmove_step: float = 0.05  # invariato
```

I default per RA e DEC ora coincidono (armonizzazione).

### 2C. `config.toml` — sezione `[auto_calibration]`

Aggiornare il valore e il commento:

```toml
[auto_calibration]
# ... campi invariati ...
# Clamp proporzionale del cap su rms_high (§23, taratura aggiornata §24).
# Tetto a 1,00" allineato al benchmark di "guida pulita" universalmente riconosciuto:
# risolve il caso cercatore-guida (focale di guida ≠ imaging) impedendo che la pixel scale
# grossolana del cercatore porti a soglie troppo lasche per l'ottica di ripresa.
rms_high_max_factor           = 2.0
rms_high_min_arcsec           = 0.70
rms_high_max_arcsec           = 1.00     # era 3.00
# ... resto invariato ...
```

### 2D. `config.toml` — sezioni `[limits.ra]` e `[limits.dec]`

Sostituire con i ranges armonizzati:

```toml
[limits.ra]
aggr_min       = 35
aggr_max       = 90
aggr_step_down = 5
aggr_step_up   = 2
minmove_min    = 0.15
minmove_max    = 0.85
minmove_step   = 0.05

[limits.dec]
aggr_min       = 35
aggr_max       = 90
aggr_step_down = 5
aggr_step_up   = 2
minmove_min    = 0.15
minmove_max    = 0.85
minmove_step   = 0.05
```

I due blocchi sono ora identici.

---

## TEST ATTESI

### Aggiornamento test esistenti §23

In `tests/test_auto_calibration.py`:

1. **Test "Cap proporzionale RC8"** (era test 1 di §23):
   - Scala 0.51, baseline 0.8 → `cap_proporzionale = 1.02`,
     `cap_efficace = max(0.70, min(1.00, 1.02)) = 1.00` (era 1.02).
   - `derived_high = 1.5 × 0.8 = 1.20`, `new_high = min(1.20, 1.00) = 1.00` → cap_active = True (era True con 1.02).
   - Asserzione: `rms_high == 1.00` (era 1.02).

2. **Test "Cap proporzionale Askar (ceiling)"** (era test 2 di §23):
   - Scala 1.58, baseline 1.4 → `cap_proporzionale = 3.16`, `cap_efficace = max(0.70, min(1.00, 3.16)) = 1.00`
     (era 3.00).
   - `derived_high = 1.5 × 1.4 = 2.10`, `new_high = min(2.10, 1.00) = 1.00` → `_rms_high_cap_active = True`
     (era False con ceiling 3.00).
   - Asserzione: `rms_high == 1.00`, `_rms_high_cap_active == True` (cambio significativo rispetto a §23).

3. **Test "Accettazione baseline borderline RC8"** (era test 6 di §23): aggiorna il valore di cap atteso da 1.02 a 1.00.

### Nuovo test §24

4. **Test "Cap globale a 1.00 sui tre setup"**: verifica che con la stessa baseline 0.8 su scale diverse, il cap
   risulti sempre 1.00 (era 1.02 / 2.06 / 3.00 nei tre casi):
   - Scala 0.51 (RC8): `cap_efficace = 1.00`.
   - Scala 1.03 (Tecnosky 115): `cap_efficace = 1.00`.
   - Scala 1.58 (Askar 71F): `cap_efficace = 1.00`.
   - Caso ipotetico cercatore 1.93"/px: `cap_efficace = 1.00` (era 3.00).

5. **Test "Cap proporzionale prevale a scala estremamente fine"**: verifica che a scala 0.30"/px,
   `cap_proporzionale = 0.60`, `cap_efficace = max(0.70, min(1.00, 0.60)) = 0.70` (pavimento attivo).
   Il cap globale 1.00 NON si applica perché la formula proporzionale già taglia più stretto.

### Test ranges aggressività/MinMove

6. Se esistono test che istanziano `LimitsConfig()` (o nome equivalente) senza argomenti e poi verificano i campi,
   aggiornarli ai nuovi default: `aggr_min == 35`, `aggr_max == 90`, `minmove_min == 0.15`, `minmove_max == 0.85`.

### Sanity simulator

```bash
python main.py --simulator --dry-run --config config.toml
```

Verifica:
- Nessun errore all'avvio.
- Il log iniziale del controller mostra i nuovi ranges (`aggr_min=35, aggr_max=90` per entrambi gli assi).
- `/status` espone `auto_calibration.rms_high_cap_arcsec = 1.0` (o valore proporzionale se scala finissima).

---

## VALIDAZIONE SUL CAMPO

### Cosa cambia rispetto a §22+§23 stato attuale

- Sui tuoi setup attuali (RMS reali tipici 0,4-0,8"), il cap a 1,00" **non si attiva mai in nottate buone**:
  baseline derivata `rms_high` resta sotto 1,00". Comportamento osservato identico a oggi.
- **Si attiva** in nottate degradate (baseline > 0,67"), pinnando `rms_high` a 1,00" — è esattamente lì che vuoi
  l'Agente in modalità più severa.
- Sui ranges: aggressività e MinMove avranno più "respiro" sia in alto sia in basso. Su un cielo eccezionale
  l'Agente può spingere aggr fino a 90; in caso di vento può scendere a 35 (era 40 RA, 35 DEC).

### Cosa osservare sulla dashboard

- Card "Auto-calibrazione": il valore "Cap rms_high" mostrerà 1,00" sui tuoi tre setup (era 1,02 / 2,06 / 3,00).
- Badge "CAP ATTIVO" (ambra): probabilmente non comparirà nelle tue nottate buone. Se compare, segnala una serata
  in cui la baseline misurata avrebbe superato il limite di "guida pulita" — informazione utile in sé.
- Card controller: i ranges di aggressività e MinMove ora vanno da 35 a 90 e 0.15 a 0.85 su entrambi gli assi.

---

## PROCEDURA REBUILD

1. `python -m pytest tests/ -v` → tutti i test passano (esistenti aggiornati + nuovi §24).
2. `python build_dist.py`.
3. Copiare in `Pacchetto_Distribuzione/`: `config.toml`, `Sblocca_Firewall_8080.bat`.
4. Verifica residui: solo `Avvia.bat` + `Sblocca_Firewall_8080.bat`, un solo `config.toml`.
5. Ricreare `PHD2_Agent_Distribuzione.zip`.

---

## AGGIORNAMENTO DOCUMENTAZIONE

### `CONTESTO_PROGETTO.md`

Aggiornare la data e aggiungere, prima di "Cosa NON è stato ancora fatto":

```markdown
### Taratura fine: cap a 1.00" + ranges aggr/MinMove armonizzati (§24) — IMPLEMENTATA (YYYY-MM-DD)
Refinement parametrico di §22/§23. Tetto assoluto del cap auto-calibrazione abbassato da 3.00 a 1.00
arcsec dopo analisi log che mostrano RMS reali sotto il secondo d'arco su tutti i setup di sviluppo;
la scelta allinea l'Agente al benchmark fisico di "guida pulita" e risolve il caso cercatore-guida con
focale diversa dall'imaging (la pixel scale grossolana del cercatore non porta più a soglie troppo lasche
per l'ottica di ripresa). Ranges aggressività e MinMove armonizzati a 35-90 e 0.15-0.85 px su entrambi gli
assi RA e DEC, per dare al controller più dinamica nei due estremi. Zero modifiche logiche, solo parametri.
Dettaglio in NOTE_CLAUDE.md §24.
```

In "Cosa NON è stato ancora fatto":
```
- Validazione sul campo di §24: confermare in 2-3 sessioni reali che il cap a 1.00" non si attivi nelle
  nottate normali su RC8 e che si attivi correttamente in caso di vento o seeing scarso.
```

### `NOTE_CLAUDE.md`

Verificare ultima sezione con `grep "^## [0-9]" NOTE_CLAUDE.md | tail -1` (atteso §23). Aggiungere in coda:

```markdown
## 24. Taratura fine: cap a 1.00" + ranges aggr/MinMove armonizzati (YYYY-MM-DD)

### Motivazione
La §23 aveva fissato il tetto assoluto del cap auto-calibrazione a 3.00 arcsec come safety per scale
grossolane. L'analisi dei log reali su RC8/Tecnosky 115/Askar 71F mostra però che gli RMS tipici stanno
ben sotto 1", quindi 3.00" come tetto è eccessivo e non offre la protezione che dovrebbe nei casi limite
(es. cercatore-guida con focale 400mm in parallelo a imaging 1000mm, dove la pixel scale di guida 1,93"/px
porterebbe il cap proporzionale §23 a 3.86", troncato dal ceiling a 3.00" — comunque troppo permissivo
per stelle imaging puntiformi). Abbassare il tetto a 1,00" allinea l'Agente al benchmark fisico
universalmente riconosciuto di "guida pulita" e copre anche il caso cercatore.

Sui ranges: i precedenti `[limits.ra]` (40-80 aggr, 0.15-0.80 minmove) e `[limits.dec]` (35-75 aggr,
0.18-0.85 minmove) erano leggermente disomogenei tra i due assi. L'armonizzazione a 35-90 / 0.15-0.85
su entrambi dà più dinamica al controller (più reattivo in cieli ottimi, più tollerante in cieli scarsi)
e coerenza concettuale RA/DEC.

### Architettura
Zero modifiche logiche. Solo cambio di valore di default:
- `AutoCalibrationConfig.rms_high_max_arcsec`: 3.00 → 1.00.
- `[limits.ra]` e `[limits.dec]`: ranges armonizzati a 35-90 (aggr) e 0.15-0.85 (minmove).
- Default delle dataclass aggiornati in `config.py` per coerenza.

### Effetto sui setup
| Setup | pixel scale | cap §23 (era) | cap §24 (ora) |
|---|---|---|---|
| RC8 | 0,51 | 1,02" | 1,00" |
| Tecnosky 115 | 1,03 | 2,06" | 1,00" |
| Askar 71F | 1,58 | 3,00" (ceiling) | 1,00" |
| Cercatore 400mm + ASI120 (1,93) | 1,93 | 3,00" (ceiling) | 1,00" |

### File modificati
- `phd2_agent/config.py`: default `rms_high_max_arcsec` 3.00 → 1.00; default `LimitsConfig` ranges aggiornati.
- `config.toml`: `[auto_calibration]` aggiornato; `[limits.ra]` e `[limits.dec]` armonizzati.
- `tests/test_auto_calibration.py`: 3 test §23 aggiornati con nuovo cap, +1 nuovo test "cap globale sui tre setup".

### Limiti dell'approccio
1. Il cap a 1,00" è ancora "globale assoluto", non personalizzato per la specifica ottica di ripresa.
   Per i guide-scope users esiste ancora un margine di imprecisione (es. cercatore 200mm + imaging 3000mm
   vorrebbe cap ancora più stretto). Soluzione futura: introdurre un campo opzionale
   `imaging_pixel_scale_arcsec` in `[setup]` che, quando valorizzato, sostituisce la pixel scale di guida
   nella formula del cap. Non implementato in §24.

### Validazione raccomandata
1. Sessione RC8 in seeing normale: cap NON attivo, badge non compare.
2. Sessione RC8 in seeing scarso/vento: cap attivo, badge "CAP ATTIVO" visibile.
3. Verifica sui log dei ranges effettivi che il controller può raggiungere (aggr 35-90, minmove 0.15-0.85).
```

### `README.md`

Aggiornare una riga in caratteristiche se elenca i ranges o il cap. Non strettamente necessario.

---

## CHECKLIST FINALE PRIMA DI COMMIT

- [ ] Pre-flight: confermato nome esatto dataclass limiti per-asse in config.py.
- [ ] `AutoCalibrationConfig.rms_high_max_arcsec` default cambiato da 3.00 a 1.00.
- [ ] `LimitsConfig` (o nome equivalente) default: aggr 35-90, minmove 0.15-0.85.
- [ ] `config.toml` [auto_calibration]: `rms_high_max_arcsec = 1.00`, commento aggiornato.
- [ ] `config.toml` [limits.ra] e [limits.dec]: ranges armonizzati 35-90 / 0.15-0.85.
- [ ] Test §23 aggiornati: cap RC8 da 1.02 a 1.00; cap Askar da 3.00 a 1.00; baseline borderline RC8 da 1.02 a 1.00.
- [ ] Nuovo test §24: cap globale 1.00 verificato sui tre setup + caso cercatore.
- [ ] Nuovo test §24: cap proporzionale prevale a scala 0.30 (pavimento 0.70 attivo).
- [ ] `python -m pytest tests/ -v`: tutti verdi.
- [ ] `python main.py --simulator --dry-run --config config.toml`: nessun errore, ranges nuovi nel log.
- [ ] `python build_dist.py` ok; `config.toml` copiato in Pacchetto_Distribuzione/; ZIP rigenerato.
- [ ] `CONTESTO_PROGETTO.md` aggiornato + `NOTE_CLAUDE.md` §24 aggiunta.
- [ ] Nessuna modifica a backlash, esposizione dinamica (§19), escalation gate (§21), config unico (§22),
      clamp proporzionale §23 oltre allo stretto necessario per i nuovi default.

---

## DOMANDE DA FARMI PRIMA DI PROCEDERE (se servono)

Se trovi:
- Nome diverso della dataclass dei limiti per-asse.
- Test che asseriscono valori specifici dei vecchi default in modo che non si possa solo aggiornare il numero.
- Configurazioni TOML legacy ancora presenti da qualche parte con i vecchi ranges.

→ **Fermati e chiedi**, non improvvisare.

Se tutto è chiaro: procedi step-by-step, mostrami i diff prima di applicarli, poi i test, poi rebuild e docs,
quindi un singolo commit `feat: taratura fine cap 1.00 + ranges aggr/MinMove armonizzati (NOTE_CLAUDE §24)`
includendo anche questo `PROMPT_TARATURA_FINE.md` come specifica di design (stessa convenzione di §22 e §23).

Grazie.
