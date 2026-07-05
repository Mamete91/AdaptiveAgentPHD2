# PROMPT per Claude Code — Commit + Push della MILESTONE su GitHub (massima accortezza)

> **Obiettivo.** Fissare su GitHub (`origin = https://github.com/Mamete91/AdaptiveAgentPHD2.git`, branch `master`) la milestone attuale dell'Adaptive Agent: motore **Outcome-First** (§44 baseline bidirezionale, §50 INIT, §51 cap adattivo, §53 recupero simmetrico — validato sul campo, percorso felice) + filone NINA (N1 trasparenza, N8 fusione confidence, N6 sicurezza) + i documenti `ARCHITETTURA_MOTORE.md` e `STUDIO_PHD2_DESIGN.md`. Scopo: aprire la validazione dalla community e, in seguito, l'integrazione con NINA.
>
> **NATURA DELL'OPERAZIONE: SOLO GIT.** NON modificare il codice/motore, NON cambiare il comportamento di guida (è validato e va fissato così com'è). Questo prompt è **solo** gestione del repository.
>
> **REGOLE DI SICUREZZA ASSOLUTE (massima accortezza):**
> - **STOP OBBLIGATORIO prima del `git push`** (vedi §6): mostra tutto ad Alessandro e attendi un "vai" esplicito.
> - **MAI `git push --force`**, **MAI riscrivere la history** in questo prompt. Se il remote è divergente in modo inatteso → **fermati e riferisci**, non risolvere con la forza.
> - **MAI committare segreti/credenziali/token.** L'autenticazione GitHub è gestita dall'ambiente di Code: **nessuna credenziale va scritta nel prompt o nei file.**
> - Il **plugin NINA è un repository SEPARATO** (solo la .dll è qui): **non** gestirlo in questo prompt (ha il suo `PROMPT_GIT_NINA_PLUGIN_PUSH.md`).

---

## §0 — PRE-FLIGHT (sola lettura, riverifica indipendente)
1. `git remote -v` → confermare che `origin` sia **esattamente** `https://github.com/Mamete91/AdaptiveAgentPHD2.git`. **Se diverso → STOP.**
2. `git rev-parse --abbrev-ref HEAD` → deve essere `master`.
3. `git fetch origin` poi `git log --oneline origin/master..HEAD` e `git log --oneline HEAD..origin/master`:
   - Atteso: HEAD locale = commit `dda0093` (release v2.6); **tutte le novità sono modifiche di working-tree non committate** (nessuna divergenza di history).
   - **Se `origin/master` è AVANTI rispetto a HEAD** (qualcuno ha pushato) → **STOP e riferisci**; non forzare, non fondere alla cieca.
4. `git status -s` e `git diff --stat` → prendere visione del delta (~743 file). Riportare un riassunto.

## §1 — IGIENE DEL REPOSITORY (la parte più importante)
Prima del commit, togliere dal tracciamento ciò che **non deve** stare in un repo pubblico. **`git rm --cached` NON cancella i file locali**, li smette solo di tracciare.

1. **`phd2-master/`** — è tracciato con **~1279 file** (il 93% del repo): è l'intero sorgente di PHD2 *incluse DLL di runtime Windows* (msvcp140.dll, inpout32.dll, ecc.). Ri-ospitare codice di terzi + binari su un repo pubblico è da evitare (bloat, licensing, confonde i contributor).
   - Azione: `git rm -r --cached phd2-master/` + aggiungere `phd2-master/` a `.gitignore`.
   - Nota: questo lo rimuove dal **nuovo commit in avanti**; resta nella history passata. La pulizia della history (`git filter-repo`/BFG + force-push) è un'operazione **separata, più rischiosa e solo su autorizzazione esplicita di Alessandro** → **NON farla ora**.
2. **`AdaptiveAgentForPHD2.NinaPlugin/AdaptiveAgentForPHD2.NinaPlugin.dll`** — binario compilato tracciato.
   - Raccomandazione: `git rm --cached` la .dll + aggiungere `*.dll` a `.gitignore` (i binari si allegano alle *Release*, non al sorgente). **Decisione ad Alessandro al gate §6** (se vuole spedire la .dll nel repo, si tiene).
3. Riverificare che **nessun altro** binario/artefatto/log sia in stage: `git status` + controllo su `*.zip *.exe *.dll *.pyc dist/ build/ Pacchetto_Distribuzione/ logs/ baseline.json runtime_state.json`. Il `.gitignore` già li esclude: confermare che reggano.

## §2 — SCAN SEGRETI / DATI PERSONALI
Sui file che verranno committati (escluso `phd2-master/`):
1. `grep -rInE 'password|secret|api[_-]?key|token|bearer|C:\\Users\\<utente>|<email-personale>'` sui file di testo tracciati.
2. Il pre-flight non ha trovato segreti in chiaro; **ricontrollare in particolare** `prompts_storici/PROMPT_PLUGIN_NINA_AUTOPAUSE.md` e `..._SAFETY.md` (erano usciti nello scan, probabilmente per la parola "safety"/"token" nel testo — confermare che siano innocui).
3. `config.toml` è tracciato: contiene solo parametri di guida (nessun segreto). Ok pubblico; se preferisci, valuta un `config.example.toml` — **opzionale, non bloccante.**

## §3 — LICENSE, README, documenti pubblici
1. **Manca un file `LICENSE`.** Per un repo pubblico verso community/upstream va aggiunto. **Alessandro sceglie la licenza** (per l'ecosistema PHD2/NINA una permissiva tipo BSD-3-Clause o MIT è coerente; PHD2 è BSD-3). Aggiungere il file scelto. *(Se Alessandro non decide ora, segnalarlo come TODO nel gate, non inventare una licenza d'ufficio.)*
2. **README.md**: aggiornarlo perché punti ai nuovi documenti — `ARCHITETTURA_MOTORE.md` ("com'è fatto") e `STUDIO_PHD2_DESIGN.md` ("perché quelle scelte") — e indichi stato/versione attuali.
3. Verificare che i nuovi doc siano inclusi: `ARCHITETTURA_MOTORE.md`, `STUDIO_PHD2_DESIGN.md` (erano UNTRACKED).
4. *(Decisione, non bloccante)* nel repo ci sono già ~36 doc interni (`PROMPT_*.md`, `NOTE_CLAUDE.md`, `prompts_storici/`). Si possono **tenere** (trasparenza del percorso) o riordinare in `docs/internal/`. Scelta di Alessandro; **non** rimuoverli senza sua indicazione.

## §4 — VERSIONE E NOTE DELLA MILESTONE
1. Versione: confermare/aggiornare `phd2_agent/__about__.py` (attuale v2.6 → numero della milestone a scelta di Alessandro, es. v2.6.x).
2. Aggiornare `CONTESTO_PROGETTO.md` e `NOTE_CLAUDE.md` (e `RELEASE_NOTES` se in uso) con la sintesi della milestone: §44 baseline bidirezionale · §50 INIT standard · §51 cap MinMove adattivo · §53 recupero simmetrico Outcome-First (validato percorso felice) · N1/N8/N6 · doc `ARCHITETTURA_MOTORE`/`STUDIO_PHD2_DESIGN` · deprecazione JITTER pianificata (§54, non ancora in questo stato).

## §5 — COMMIT
1. Mettere in stage l'insieme rivisto (dopo §1–§4).
2. **Un commit di release chiaro.** Messaggio proposto (adattabile):
   `release: milestone Outcome-First (§44/§50/§51/§53) + filone NINA N1/N6/N8 + doc architettura & studio PHD2; pulizia repo (untrack phd2-master/binari)`
3. **Non** pushare ancora.

## §6 — ⛔ STOP OBBLIGATORIO: GATE DI CONFERMA (prima del push)
Presentare ad Alessandro e **attendere un "vai" esplicito**:
- `git diff --stat --cached` (lista file finale del commit);
- le modifiche a `.gitignore` e le rimozioni (`phd2-master/`, eventuale `.dll`);
- il messaggio di commit, il remote (`Mamete91/AdaptiveAgentPHD2`) e il branch (`master`);
- l'esito degli scan §2 (nessun segreto) e le decisioni aperte (LICENSE, .dll, doc interni).
**Nessun `git push` prima di questa conferma esplicita. Mai `--force`.**

## §7 — PUSH + TAG + POST (solo dopo il "vai")
1. `git push origin master`.
2. Creare un **tag annotato** della milestone (es. `git tag -a v2.6-outcome-first -m "Milestone Outcome-First + filone NINA"`) e `git push origin <tag>`.
3. Verifica su GitHub: file presenti; `phd2-master/` **non** più nel nuovo albero; README che rende e rimanda ai doc; nessun binario/segreto.
4. **Promemoria:** il **plugin NINA** (repo separato, SDK 3.2) si pusha con il suo prompt dedicato, **non** qui.

## CHECKLIST FINALE
- [ ] §0 remote = Mamete91/AdaptiveAgentPHD2, branch master, nessuna divergenza (altrimenti STOP).
- [ ] §1 `phd2-master/` untracked + gitignored; .dll decisa; nessun binario/log/artefatto in stage.
- [ ] §2 scan segreti pulito (inclusi i 2 file storici); config.toml senza segreti.
- [ ] §3 LICENSE aggiunta (scelta Alessandro); README aggiornato ai nuovi doc; `ARCHITETTURA_MOTORE`/`STUDIO_PHD2_DESIGN` inclusi.
- [ ] §4 versione + CONTESTO/NOTE_CLAUDE aggiornati alla milestone.
- [ ] §5 un commit di release con messaggio chiaro; **nessun push prima del gate**.
- [ ] §6 gate di conferma mostrato e "vai" ricevuto.
- [ ] §7 push + tag + verifica su GitHub; nessun force-push; plugin lasciato al suo repo.

> **Perché tanta cura:** è un push pubblico e sostanzialmente irreversibile, ed è la prima impressione che PHD2/NINA e la community avranno del progetto. Meglio una milestone pulita (senza codice di terzi, senza binari, con licenza e doc) che una veloce. Il comportamento di guida validato non si tocca: qui si sistema solo *come* il progetto si presenta.
