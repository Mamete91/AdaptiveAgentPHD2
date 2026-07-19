# Changelog

All notable project milestones. The detailed technical history, section by section (§),
lives in [`docs/development/NOTE_CLAUDE.md`](docs/development/NOTE_CLAUDE.md) (in Italian).

The project follows a **field-validation-first** philosophy: every engine feature is born
behind a kill-switch and promoted only after real autoguiding sessions.

---

## [2.8.1] — Hotfix: event-loop crash from §57 wiring (first field bug of 2.8)

First real-sky validation night (2026-07-19) caught a wiring regression:
`recovery_hint_tracker` was referenced inside `_event_loop` as a `main()` local
(`NameError` on the first evaluated frame); the exception reached the outer handler
whose `finally` disconnected from PHD2 — a connect/crash cycle every ~20-35 s (178
times in 65 minutes). Effects, proven from the session CSV: recovery hint never fed,
`controller.evaluate` never reached (GUARDIAN inert), RMS baseline starved (~1 sample
per cycle). The recovery probes themselves worked (probe #1 refreshed N1 to index 1.00).

- **Fix:** the tracker is now a proper `_event_loop` parameter, and the per-frame
  update is wrapped defensively — a passive observer can never take down the guiding
  loop (first error logged, then silenced).
- **Regression tests that execute the real `_event_loop`** (full frame path, crashing
  observer, missing tracker): the "green suite but broken loop" gap is closed for good.
- **Engine cycle observability:** new `engine` block on `/status` (`eval_count`,
  `last_eval_ts`, `actions_total`, `last_action`) and a three-state "Engine cycle" row
  on the dashboard — *collecting data* / *active, evaluating with no intervention
  needed* / *last intervention at hh:mm:ss* — so a healthy-but-quiet engine is
  distinguishable from a stalled one during field validation.

Test suite: **301 tests**. Patch-level versioning introduced (major.minor.patch).

## [2.8] — Recovery & lifecycle infrastructure (engine core frozen)

Infrastructure-only milestone: the adaptive guiding engine validated in the field is
**untouched**. Everything below concerns observability, cloud recovery, process lifecycle
and the companion N.I.N.A. plugin (v1.5.0.0 → v1.7.0.0).

### Safety & observability
- **§55 — Telemetry freshness on `/status`.** `age_s` and `window_s` (adaptive freshness
  window) exposed under `nina.transparency` + a FRESH/STALE badge on the dashboard.
  Companion plugin v1.5.0.0 fixes three fail-dangerous Safety Monitor bugs found in the
  field (index-based leaky cloud persistence, stale telemetry → unsafe, Agent loss →
  unsafe — the monitor never "fails toward safe" anymore).
- **§56 — No more re-init on guiding restarts.** Orphan-recovery check, baseline save and
  §50 lever INIT run only on the **first** initialization of the process; subsequent
  reconnects re-attach without resetting the levers (kill-switch
  `[control] full_reinit_on_restart`). Agent log persisted to `logs/agent.log`
  (rotating), PHD2 version logged on connect.

### Cloud recovery (S1/S2)
- **§57 — Recovery hint.** `phd2_agent/recovery_hint.py`: a time-based leaky accumulator
  on guide-star SNR that raises `/status.recovery_hint` when, under a CLOUD/HAZE context,
  the SNR stays above a threshold anchored to its clear-sky reference (EMA) — the "sky
  may be recovering" signal (S2) consumed by the plugin's **Recovery probe** sequencer
  instruction. Probe outcomes are observed back (`observe_probe`) with S1/S2 attribution.
  Config: `[recovery_hint]`, `[recovery_probe]` — all kill-switchable.

### Process lifecycle
- **§58 — Graceful remote shutdown.** `POST /shutdown` triggers the same path as the
  signal handlers (stop event → controller shutdown → **baseline restore**), responding
  200 before shutting down; idempotent. The N.I.N.A. plugin (v1.7.0.0) owns the Agent
  lifecycle: auto-launch on N.I.N.A. start and graceful stop on close.
- **§58-bis — Background agent.** The packaged `PHD2_Agent.exe` runs **without a console
  window** (GUI subsystem); `Avvia.bat` starts it detached, `Arresta.bat` requests a
  graceful shutdown via `POST /shutdown`, `Mostra_Log.bat` tails `logs/agent.log` live.
- **§59 — Termination contract.** Accepting `/shutdown` arms a **daemon self-kill
  watchdog** (25 s): if the graceful path stalls, the process force-exits and the §56
  orphan recovery restores the baseline at the next start. The 200 response is therefore
  a real contract — N.I.N.A. can close instantly, delegating to the Agent.

Test suite: **297 tests** (from 270). Companion plugin: 35 tests, UI fully localized
(English/Italiano, live-switchable) as of v1.7.0.0.

## [2.7] — "Outcome-First" milestone + N.I.N.A. integration line

Consolidation of the adaptive guiding engine around the **Outcome-First** principle: the
PHD2 levers (`Aggressiveness`, `MinMove`) move only when the measured outcome justifies
it, anchored to PHD2's standard values, with guaranteed restore.

### Adaptive guiding engine
- **§44 — Continuous bidirectional RMS baseline.** The reference baseline updates
  continuously and in both directions (best-fraction rolling window, EMA-like behavior),
  while keeping the safety cap.
- **§50 — Initialization to PHD2 standard values.** At startup the levers start from
  PHD2's standard values (RA Hysteresis 70 / 0.20, DEC ResistSwitch 100 / 0.20), with
  skip-and-warn when the active algorithm does not expose them (algorithm-aware).
- **§51 — Adaptive MinMove cap.** The MinMove ceiling is `min(k · filtered_baseline,
  imaging_ceiling) / pixel_scale`, with a universal `k` < 1 and dedicated kill-switches.
- **§53 — Symmetric outcome-guided recovery.** When the levers have been softened and
  guiding is stable, the engine stiffens them back toward the §50 standard and measures
  the outcome: it keeps the stiffening if RMS holds/improves, and softens (§32) only when
  the outcome proves real seeing degradation. Anchor = §50 standard. Field-validated
  (happy path).
- **§54 — JITTER mode deprecated.** GUARDIAN is the official mode; OFF remains a
  legitimate A/B baseline. JITTER (which bypasses the validated controller) is removed
  from the dashboard toggle and gated behind the `allow_experimental_jitter` flag
  (default `false`): requesting jitter falls back to GUARDIAN with a warning. The jitter
  code path remains in the codebase, dormant, reachable only via the explicit flag.

### N.I.N.A. integration line (telemetry and safety)
- **N1 — Transparency Index.** A single sky-transparency recognizer
  (`phd2_agent/nina_indices.py`, layer 2) exposing a continuous index, a discrete state
  and freshness.
- **N8 — Confidence fusion.** Proportional penalty on the SEEING diagnosis only, with
  dead-band, persistence and kill-switch.
- **N6 — Cloud safety (N.I.N.A. plugin).** CLOUD condition in the plugin's
  `SafetyDecisionEngine`, alongside STAR_LOST, with asymmetric hysteresis and fail-safe.

### Documentation and repository hygiene
- New reference documents: **`ARCHITETTURA_MOTORE.md`** (system architecture, bilingual)
  and **`STUDIO_PHD2_DESIGN.md`** (PHD2 design study, Italian).
- **BSD-3-Clause** license added (consistent with the PHD2 ecosystem).
- Third-party sources (`phd2-master/`) and binaries (`*.dll`) removed from tracking
  (binaries belong in Releases, not in the source tree).
- Development documents collected under **`docs/development/`** for a clean root while
  keeping full traceability of the project's evolution.

## [2.6] — Diagnostic engine operational

- Diagnostic engine operational, RMS expressed in arcsec, robust baseline with rejection
  of non-representative baselines. Reference release `dda0093`.
