# Changelog

All notable project milestones. The detailed technical history, section by section (§),
lives in [`docs/development/NOTE_CLAUDE.md`](docs/development/NOTE_CLAUDE.md) (in Italian).

The project follows a **field-validation-first** philosophy: every engine feature is born
behind a kill-switch and promoted only after real autoguiding sessions.

---

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
