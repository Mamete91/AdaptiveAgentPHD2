"""
test_reinit_orphan.py — §56: fix re-init "self-orphan" + leve preservate tra ripartenze.

Il bug (notte 2026-07-12): ogni ripartenza guida (autofocus/filtro/ricentraggio) rifaceva
l'init PIENO — orphan-recovery sulla baseline scritta da NOI (falso WARNING "orfana") +
restore ai valori utente + INIT §50 ai valori standard → la convergenza costruita nella
corsa precedente veniva scartata due volte. Fix: init pesante solo al PRIMO init del
processo (`_process_initialized`); ri-init di sessione = ri-aggancio leggero.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from phd2_agent.config import AgentConfig, ControlConfig
from phd2_agent.controller import AdaptiveController


def _make_client(aggr: float = 0.70, minmove: float = 0.20) -> MagicMock:
    """Client PHD2 finto: probe_algo_params riflette lo STATO CORRENTE di PHD2
    (mutabile dal test per simulare la convergenza costruita dall'agente)."""
    client = MagicMock()
    client.state = {"ra": {"aggression": aggr, "minMove": minmove},
                    "dec": {"aggression": aggr, "minMove": minmove}}
    client.probe_algo_params.side_effect = lambda: {
        "ra": dict(client.state["ra"]), "dec": dict(client.state["dec"])}
    client.get_exposure_durations.return_value = [1000, 2000, 4000]
    client.get_exposure.return_value = 2000
    client.get_pixel_scale.return_value = 0.5
    return client


def _make_controller(tmpdir: str, full_reinit: bool = False,
                     client: MagicMock | None = None) -> AdaptiveController:
    cfg = AgentConfig()
    cfg.control = ControlConfig(dry_run=True, cooldown_seconds=0.0,
                                full_reinit_on_restart=full_reinit)
    ctrl = AdaptiveController(client=client or _make_client(), config=cfg)
    ctrl.baseline_path = Path(tmpdir) / "baseline.json"
    return ctrl


def _write_baseline(path: Path, setup_id: str, age_hours: float = 0.5,
                    aggr: float = 65.0, version: int = 3) -> None:
    path.write_text(json.dumps({
        "version": version,
        "saved_at": time.time() - age_hours * 3600,
        "setup_id": setup_id,
        "ra": {"aggr_param": "aggression", "current_aggr": aggr,
               "aggr_native_scale": 0.01, "minmove_param": "minMove",
               "current_minmove": 0.25},
        "dec": {"aggr_param": "aggression", "current_aggr": aggr,
                "aggr_native_scale": 0.01, "minmove_param": "minMove",
                "current_minmove": 0.25},
        "base_exposure_ms": 2000,
        "current_exposure_ms": 2000,
        "exposure_state": "NOMINAL",
        "exposure_steps_above_base": 0,
    }))


class TestFirstInitOrphan(unittest.TestCase):
    """1. Primo init del processo con orphan REALE -> recovery + §50 eseguiti."""

    def test_orphan_recovery_and_std_init_on_first_init(self):
        with tempfile.TemporaryDirectory() as d:
            ctrl = _make_controller(d)
            _write_baseline(ctrl.baseline_path, ctrl._baseline_setup_id)
            with patch.object(ctrl, "restore_baseline",
                              wraps=ctrl.restore_baseline) as restore, \
                 patch.object(ctrl, "_init_to_phd2_standard",
                              wraps=ctrl._init_to_phd2_standard) as std:
                self.assertTrue(ctrl.initialize())
            restore.assert_called_once_with(source="orphan_recovery")
            std.assert_called_once()
            self.assertTrue(ctrl._process_initialized)


class TestSessionReinit(unittest.TestCase):
    """2. Ri-init di sessione (il bug): niente orphan/save/§50, leve preservate."""

    def test_session_reinit_is_light_and_preserves_levers(self):
        with tempfile.TemporaryDirectory() as d:
            client = _make_client(aggr=0.70)
            ctrl = _make_controller(d, client=client)
            self.assertTrue(ctrl.initialize())          # primo init (pieno)

            # La corsa di guida converge: l'agente ha portato PHD2 a aggr 0.62.
            client.state["ra"]["aggression"] = 0.62
            client.state["dec"]["aggression"] = 0.62

            ctrl.mark_uninitialized()                    # GuidingStopped (autofocus)
            with patch.object(ctrl, "_check_orphan_baseline") as orphan, \
                 patch.object(ctrl, "save_baseline") as save, \
                 patch.object(ctrl, "_init_to_phd2_standard") as std, \
                 self.assertNoLogs("phd2_agent.controller", level="WARNING"):
                self.assertTrue(ctrl.initialize())       # StartGuiding -> ri-init
            orphan.assert_not_called()
            save.assert_not_called()
            std.assert_not_called()
            # Leve = stato REALE di PHD2 (convergenza preservata), non 70 standard.
            self.assertAlmostEqual(ctrl._ra.current_aggr, 62.0)
            self.assertAlmostEqual(ctrl._dec.current_aggr, 62.0)


class TestCrashRecovery(unittest.TestCase):
    """3. Crash simulato -> NUOVO processo: la recovery vera resta garantita."""

    def test_new_process_recovers_previous_baseline(self):
        with tempfile.TemporaryDirectory() as d:
            ctrl_a = _make_controller(d)
            self.assertTrue(ctrl_a.initialize())
            self.assertTrue(ctrl_a.baseline_path.exists())   # scritta dal processo A
            # ... crash del processo A: nessuno shutdown, il file resta ...

            ctrl_b = _make_controller(d)                     # nuovo processo (flag False)
            with patch.object(ctrl_b, "restore_baseline",
                              wraps=ctrl_b.restore_baseline) as restore:
                self.assertTrue(ctrl_b.initialize())
            restore.assert_called_once_with(source="orphan_recovery")


class TestKillSwitch(unittest.TestCase):
    """4. Kill-switch ON: ogni initialize() rifà l'init pieno (legacy identico)."""

    def test_full_reinit_on_restart_restores_legacy(self):
        with tempfile.TemporaryDirectory() as d:
            ctrl = _make_controller(d, full_reinit=True)
            self.assertTrue(ctrl.initialize())
            ctrl.mark_uninitialized()
            with patch.object(ctrl, "_check_orphan_baseline",
                              wraps=ctrl._check_orphan_baseline) as orphan, \
                 patch.object(ctrl, "save_baseline",
                              wraps=ctrl.save_baseline) as save, \
                 patch.object(ctrl, "_init_to_phd2_standard",
                              wraps=ctrl._init_to_phd2_standard) as std:
                self.assertTrue(ctrl.initialize())
            orphan.assert_called_once()
            save.assert_called_once()
            std.assert_called_once()


class TestRestoreGuards(unittest.TestCase):
    """5. Guard esistenti del restore invariati (setup diverso / età > 24h)."""

    def test_setup_mismatch_skips_restore(self):
        with tempfile.TemporaryDirectory() as d:
            ctrl = _make_controller(d)
            _write_baseline(ctrl.baseline_path, setup_id="ALTRO_SETUP")
            self.assertFalse(ctrl.restore_baseline(source="orphan_recovery"))

    def test_old_baseline_skips_restore(self):
        with tempfile.TemporaryDirectory() as d:
            ctrl = _make_controller(d)
            _write_baseline(ctrl.baseline_path, ctrl._baseline_setup_id, age_hours=25.0)
            self.assertFalse(ctrl.restore_baseline(source="orphan_recovery"))


class TestReinitializeFullBootstrap(unittest.TestCase):
    """reinitialize() = re-bootstrap COMPLETO esplicito (resetta anche il flag processo)."""

    def test_reinitialize_forces_full_init(self):
        with tempfile.TemporaryDirectory() as d:
            ctrl = _make_controller(d)
            self.assertTrue(ctrl.initialize())
            with patch.object(ctrl, "save_baseline", wraps=ctrl.save_baseline) as save, \
                 patch.object(ctrl, "_init_to_phd2_standard",
                              wraps=ctrl._init_to_phd2_standard) as std:
                ctrl.reinitialize()
            save.assert_called_once()
            std.assert_called_once()


class TestFileLogging(unittest.TestCase):
    """6. (§B) setup_logging crea logs/agent.log e vi scrive (smoke test)."""

    def test_setup_logging_windowed_no_stderr(self):
        """§58 — build windowed (PyInstaller console=False): sys.stderr è None →
        nessun StreamHandler (niente crash), il file handler resta il canale primario."""
        import main as agent_main
        root = logging.getLogger()
        saved_handlers = root.handlers[:]
        saved_stderr = agent_main.sys.stderr
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as d:
            try:
                os.chdir(d)
                root.handlers = []
                agent_main.sys.stderr = None          # come nella build windowed
                agent_main.setup_logging("INFO")
                kinds = [type(h).__name__ for h in logging.getLogger().handlers]
                self.assertNotIn("StreamHandler", kinds)
                self.assertIn("RotatingFileHandler", kinds)
            finally:
                agent_main.sys.stderr = saved_stderr
                for h in root.handlers[:]:
                    if isinstance(h, logging.FileHandler):
                        h.close()
                os.chdir(cwd)
                root.handlers = saved_handlers

    def test_setup_logging_writes_agent_log(self):
        import main as agent_main
        root = logging.getLogger()
        saved_handlers = root.handlers[:]
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as d:
            try:
                os.chdir(d)
                root.handlers = []          # basicConfig è no-op se già configurato
                agent_main.setup_logging("INFO")
                logging.getLogger("phd2_agent.test").info("smoke §56")
                for h in logging.getLogger().handlers:
                    h.flush()
                log_file = Path(d) / "logs" / "agent.log"
                self.assertTrue(log_file.exists())
                self.assertIn("smoke §56", log_file.read_text(encoding="utf-8"))
            finally:
                for h in root.handlers[:]:
                    if isinstance(h, logging.FileHandler):
                        h.close()           # rilascia agent.log (Windows: serve per rmdir)
                os.chdir(cwd)
                root.handlers = saved_handlers


if __name__ == "__main__":
    unittest.main()
