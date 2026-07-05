"""
test_jitter_deprecation.py — §54: la modalità JITTER è deprecata/gated.
GUARDIAN è la modalità ufficiale; OFF resta A/B. Senza allow_experimental_jitter la
richiesta di jitter (dashboard o config legacy) ricade su GUARDIAN con WARNING; il ramo
jitter resta funzionante solo con il flag esplicito.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from phd2_agent.config import (
    AgentConfig, ControlConfig, DiagnosticEngineConfig, load_config,
)
from phd2_agent.controller import AdaptiveController


def _ctrl(allow_switch=True, allow_jitter=False, mode="guardian", enabled=True) -> AdaptiveController:
    cfg = AgentConfig()
    cfg.control = ControlConfig(dry_run=True, cooldown_seconds=0.0)
    cfg.diagnostic_engine = DiagnosticEngineConfig(
        enabled=enabled, mode=mode, allow_dashboard_mode_switch=allow_switch,
        allow_experimental_jitter=allow_jitter, warmup_frames_after_switch=0)
    ctrl = AdaptiveController(client=MagicMock(), config=cfg)
    ctrl._initialized = True
    if enabled:
        ctrl.diagnostic_engine = ctrl._make_diagnostic_engine()
    return ctrl


class TestSetModeGuardRail(unittest.TestCase):
    def test_jitter_coerced_to_guardian_when_flag_off(self):
        ctrl = _ctrl(allow_switch=True, allow_jitter=False, mode="guardian")
        with self.assertLogs("phd2_agent.controller", level="WARNING") as cm:
            r = ctrl.set_diagnostic_mode("jitter")
        self.assertEqual(r["mode"], "guardian")                 # ritorna la modalità EFFETTIVA
        self.assertEqual(ctrl.cfg.diagnostic_engine.mode, "guardian")
        self.assertFalse(ctrl._engine_owns_levers())            # jitter NON attiva
        self.assertTrue(ctrl._guardian_active())
        self.assertTrue(any("JITTER" in m and "GUARDIAN" in m for m in cm.output))

    def test_jitter_honored_with_flag_on(self):
        ctrl = _ctrl(allow_switch=True, allow_jitter=True, mode="guardian")
        r = ctrl.set_diagnostic_mode("jitter")
        self.assertEqual(r["mode"], "jitter")                   # percorso deliberato
        self.assertTrue(ctrl._engine_owns_levers())             # ramo jitter funzionante
        self.assertFalse(ctrl._guardian_active())

    def test_off_and_guardian_unchanged(self):
        ctrl = _ctrl(allow_switch=True, allow_jitter=False, mode="guardian")
        self.assertEqual(ctrl.set_diagnostic_mode("off")["mode"], "off")
        self.assertFalse(ctrl.cfg.diagnostic_engine.enabled)
        self.assertEqual(ctrl.set_diagnostic_mode("guardian")["mode"], "guardian")
        self.assertTrue(ctrl._guardian_active())


class TestConfigLoadGuardRail(unittest.TestCase):
    def _load(self, toml: str):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.toml"
            p.write_text(toml, encoding="utf-8")
            return load_config(p)

    def test_legacy_jitter_config_falls_back_to_guardian(self):
        cfg = self._load('[diagnostic_engine]\nenabled = true\nmode = "jitter"\n')
        self.assertEqual(cfg.diagnostic_engine.mode, "guardian")     # gated -> guardian
        self.assertFalse(cfg.diagnostic_engine.allow_experimental_jitter)

    def test_jitter_config_honored_with_flag(self):
        cfg = self._load('[diagnostic_engine]\nenabled = true\nmode = "jitter"\n'
                         'allow_experimental_jitter = true\n')
        self.assertEqual(cfg.diagnostic_engine.mode, "jitter")
        self.assertTrue(cfg.diagnostic_engine.allow_experimental_jitter)

    def test_default_config_is_guardian_no_jitter(self):
        cfg = self._load('[diagnostic_engine]\nmode = "guardian"\n')
        self.assertEqual(cfg.diagnostic_engine.mode, "guardian")
        self.assertFalse(cfg.diagnostic_engine.allow_experimental_jitter)


if __name__ == "__main__":
    unittest.main()
