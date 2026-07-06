# Contributing

Thank you for your interest! This project tunes **PHD2** guiding parameters in real time and is validated **primarily in real astrophotography sessions**. The most valuable contribution is not necessarily code: it is **documented field testing**.

## Field-testing the Agent

1. Follow the quick start in the [README](README.md). The first night on a new setup always runs in **DRY_RUN** (`dry_run = true`), so the Agent logs its decisions without sending anything to PHD2.
2. After the session you will find in `logs/`: a per-frame CSV, a per-decision JSONL and a session summary JSON.
3. Open a **GitHub issue** with: your setup (telescope/focal length, guide camera, pixel scale), the seeing/transparency conditions, what you observed, and — if possible — the log files. "Everything worked" reports are useful too: they confirm validation.

## Code contributions

- The guiding behavior is **field-validated**: changes to the control law (the Outcome-First controller) must come with **field evidence**, not only green tests. Every engine intervention must stay behind a kill-switch.
- New `config.toml` keys ship enabled by default only if already validated; otherwise behind a flag defaulting to `false`.
- Run the test suite before opening a PR:
  ```
  python -m unittest discover -s tests
  ```
- The technical changelog and the validation methodology live in [`docs/development/`](docs/development/) (in Italian).

## N.I.N.A. plugin

The companion N.I.N.A. plugin lives in a **separate repository**: [AdaptiveAgentPHD2-NinaPlugin](https://github.com/Mamete91/AdaptiveAgentPHD2-NinaPlugin). Plugin issues belong there.

## License

By contributing, you agree that your contribution is distributed under the **BSD-3-Clause** license (see [`LICENSE`](LICENSE)).
