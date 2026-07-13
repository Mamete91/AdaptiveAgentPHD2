"""
test_nina_telemetry.py — §41, Step 0: canale in ingresso telemetria NINA (lato Agente).

Copre i test 1–8 del prompt:
  1. POST valido -> 200 {accepted:true}; /status.nina riflette il payload; connected:true.
  2. Campi mancanti (solo schema_version + hfr) -> accettato, altri null, nessun 500.
  3. Payload malformato / tipi errati / fuori-range -> 422/400, store invariato.
  4. enabled=false (kill-switch) -> 200 {accepted:false,reason:disabled}, store vuoto.
  5. Staleness -> dopo staleness_seconds is_fresh=false, connected=false, metrics conservate.
  6. Graceful assente -> senza POST nina.connected=false, metrics:{}; /status identico
     al pre-§41 a meno del solo blocco `nina`.
  7. Isolamento -> il POST non altera lo stato del controller; un GuideStep dà le
     stesse decisioni con e senza telemetria (lo store non è letto dal motore/leve).
  8. Thread-safety -> POST/aggiornamenti concorrenti + letture parallele non corrompono.

Più: parsing TOML della sezione [nina_telemetry] (retrocompat + kill-switch).

I test endpoint usano il vero FastAPI TestClient sull'app di server.py. Lo store
globale è registrato per-test via server.set_nina_store().
"""
from __future__ import annotations

import threading
import unittest
from unittest.mock import MagicMock

import server
from server import app
from phd2_agent.nina_telemetry import NinaTelemetryStore

# Il TestClient di FastAPI richiede `httpx` (dipendenza solo-test, NON runtime: non
# entra nell'.exe). Se assente, i test a livello HTTP si SKIPpano con grazia; i test
# di store/config/isolamento-decisioni (che non usano HTTP) restano sempre verdi.
try:
    from fastapi.testclient import TestClient
    _HAS_TESTCLIENT = True
except Exception:  # pragma: no cover - dipende dall'ambiente
    TestClient = None  # type: ignore
    _HAS_TESTCLIENT = False

_NEEDS_HTTP = unittest.skipUnless(
    _HAS_TESTCLIENT, "fastapi TestClient non disponibile (manca httpx): test HTTP skippati")

# --- factory controller per i test di isolamento (stile test_lever_optimization_gate) ---
from phd2_agent.analyzer import AnalysisSnapshot, SeeingCondition
from phd2_agent.config import (
    AgentConfig, AxisLimits, ControlConfig, LeverOptimizationConfig,
    NinaTelemetryConfig, SetupConfig, Thresholds, load_config,
)
from phd2_agent.controller import AdaptiveController


_VALID_PAYLOAD = {
    "schema_version": 1,
    "source": "nina-plugin",
    "ts_unix": 1750000000.0,
    "image": {
        "hfr": 2.13,
        "hfr_std": 0.31,
        "star_count": 842,
        "eccentricity": 0.42,
        "mean_adu": 1234.5,
        "median_adu": 1180.0,
        "stdev_adu": 210.0,
        "exposure_s": 300.0,
        "filter": "L",
    },
    "context": {"activity": "EXPOSING", "target": "NGC 7000"},
}


def _client() -> TestClient:
    return TestClient(app)


# ===========================================================================
# 1. POST valido
# ===========================================================================

@_NEEDS_HTTP
class TestValidPost(unittest.TestCase):

    def setUp(self):
        self.store = NinaTelemetryStore(enabled=True, staleness_seconds=180.0)
        server.set_nina_store(self.store)
        server.set_global_state(None, None, None)  # /status senza controller/analyzer
        self.client = _client()

    def tearDown(self):
        server.set_nina_store(None)

    def test_post_accepted_200(self):
        r = self.client.post("/nina/telemetry", json=_VALID_PAYLOAD)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"accepted": True, "schema_version": 1})

    def test_status_reflects_payload(self):
        self.client.post("/nina/telemetry", json=_VALID_PAYLOAD)
        nina = self.client.get("/status").json()["nina"]
        self.assertTrue(nina["enabled"])
        self.assertTrue(nina["connected"])
        self.assertEqual(nina["schema_version"], 1)
        self.assertIsNotNone(nina["last_age_s"])
        self.assertGreaterEqual(nina["last_age_s"], 0.0)
        self.assertLess(nina["last_age_s"], 180.0)
        self.assertEqual(nina["metrics"]["image"]["hfr"], 2.13)
        self.assertEqual(nina["metrics"]["image"]["star_count"], 842)
        self.assertEqual(nina["metrics"]["context"]["activity"], "EXPOSING")

    def test_store_count_increments(self):
        self.assertEqual(self.store.count, 0)
        self.client.post("/nina/telemetry", json=_VALID_PAYLOAD)
        self.client.post("/nina/telemetry", json=_VALID_PAYLOAD)
        self.assertEqual(self.store.count, 2)


# ===========================================================================
# 2. Campi mancanti tollerati
# ===========================================================================

@_NEEDS_HTTP
class TestMissingFields(unittest.TestCase):

    def setUp(self):
        self.store = NinaTelemetryStore(enabled=True)
        server.set_nina_store(self.store)
        server.set_global_state(None, None, None)
        self.client = _client()

    def tearDown(self):
        server.set_nina_store(None)

    def test_only_schema_and_hfr_accepted(self):
        r = self.client.post("/nina/telemetry",
                             json={"schema_version": 1, "image": {"hfr": 2.5}})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["accepted"])
        nina = self.client.get("/status").json()["nina"]
        img = nina["metrics"]["image"]
        self.assertEqual(img["hfr"], 2.5)
        # gli altri campi assenti -> null, nessun 500
        self.assertIsNone(img["star_count"])
        self.assertIsNone(img["eccentricity"])
        self.assertIsNone(nina["metrics"]["context"])

    def test_bare_schema_version_accepted(self):
        r = self.client.post("/nina/telemetry", json={"schema_version": 1})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["accepted"])
        nina = self.client.get("/status").json()["nina"]
        self.assertIsNone(nina["metrics"]["image"])


# ===========================================================================
# 3. Payload malformato / fuori-range -> 422, store invariato
# ===========================================================================

@_NEEDS_HTTP
class TestMalformedRejected(unittest.TestCase):

    def setUp(self):
        self.store = NinaTelemetryStore(enabled=True)
        server.set_nina_store(self.store)
        server.set_global_state(None, None, None)
        self.client = _client()

    def tearDown(self):
        server.set_nina_store(None)

    def test_missing_schema_version_422(self):
        r = self.client.post("/nina/telemetry", json={"image": {"hfr": 2.0}})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.store.count, 0)
        self.assertIsNone(self.store.last_age_s)

    def test_wrong_type_422(self):
        r = self.client.post("/nina/telemetry",
                             json={"schema_version": 1, "image": {"hfr": "tanto"}})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.store.count, 0)

    def test_negative_hfr_out_of_range_422(self):
        r = self.client.post("/nina/telemetry",
                             json={"schema_version": 1, "image": {"hfr": -1.0}})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.store.count, 0)

    def test_negative_star_count_422(self):
        r = self.client.post("/nina/telemetry",
                             json={"schema_version": 1, "image": {"star_count": -5}})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.store.count, 0)

    def test_store_unchanged_after_rejected(self):
        # un payload valido prima, poi uno malformato: lo store conserva il valido
        self.client.post("/nina/telemetry", json=_VALID_PAYLOAD)
        self.assertEqual(self.store.count, 1)
        r = self.client.post("/nina/telemetry",
                             json={"schema_version": 1, "image": {"hfr": -9}})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.store.count, 1)  # invariato
        nina = self.client.get("/status").json()["nina"]
        self.assertEqual(nina["metrics"]["image"]["hfr"], 2.13)  # ancora il valido


# ===========================================================================
# 4. Kill-switch enabled=false
# ===========================================================================

@_NEEDS_HTTP
class TestKillSwitch(unittest.TestCase):

    def setUp(self):
        self.store = NinaTelemetryStore(enabled=False)
        server.set_nina_store(self.store)
        server.set_global_state(None, None, None)
        self.client = _client()

    def tearDown(self):
        server.set_nina_store(None)

    def test_disabled_returns_accepted_false(self):
        r = self.client.post("/nina/telemetry", json=_VALID_PAYLOAD)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"accepted": False, "reason": "disabled"})

    def test_disabled_store_stays_empty(self):
        self.client.post("/nina/telemetry", json=_VALID_PAYLOAD)
        self.assertEqual(self.store.count, 0)

    def test_status_enabled_false(self):
        self.client.post("/nina/telemetry", json=_VALID_PAYLOAD)
        nina = self.client.get("/status").json()["nina"]
        self.assertFalse(nina["enabled"])
        self.assertFalse(nina["connected"])
        self.assertEqual(nina["metrics"], {})
        self.assertIsNone(nina["last_age_s"])


# ===========================================================================
# 5. Staleness
# ===========================================================================

class TestStaleness(unittest.TestCase):

    def test_fresh_then_stale(self):
        store = NinaTelemetryStore(enabled=True, staleness_seconds=120.0)
        store.update(dict(_VALID_PAYLOAD), 1)
        self.assertTrue(store.is_fresh)
        blk = store.status_block()
        self.assertTrue(blk["connected"])
        # forza la staleness senza dormire: arretra il timestamp di arrivo
        store._last_monotonic -= 1000.0
        self.assertFalse(store.is_fresh)
        blk = store.status_block()
        self.assertFalse(blk["connected"])
        # ma le metriche restano: conserva l'ultimo
        self.assertEqual(blk["metrics"]["image"]["hfr"], 2.13)
        self.assertGreater(blk["last_age_s"], 120.0)

    @_NEEDS_HTTP
    def test_status_endpoint_reports_stale(self):
        store = NinaTelemetryStore(enabled=True, staleness_seconds=60.0)
        server.set_nina_store(store)
        server.set_global_state(None, None, None)
        try:
            client = _client()
            client.post("/nina/telemetry", json=_VALID_PAYLOAD)
            store._last_monotonic -= 5000.0  # invecchia
            nina = client.get("/status").json()["nina"]
            self.assertTrue(nina["enabled"])
            self.assertFalse(nina["connected"])
            self.assertEqual(nina["metrics"]["image"]["hfr"], 2.13)
        finally:
            server.set_nina_store(None)


# ===========================================================================
# 6. Graceful assente — diff solo per il blocco `nina`
# ===========================================================================

@_NEEDS_HTTP
class TestGracefulAbsent(unittest.TestCase):

    def tearDown(self):
        server.set_nina_store(None)

    def test_no_store_registered(self):
        server.set_nina_store(None)
        server.set_global_state(None, None, None)
        nina = _client().get("/status").json()["nina"]
        self.assertFalse(nina["enabled"])
        self.assertFalse(nina["connected"])
        self.assertEqual(nina["metrics"], {})
        self.assertIsNone(nina["last_age_s"])

    def test_no_post_ever(self):
        server.set_nina_store(NinaTelemetryStore(enabled=True))
        server.set_global_state(None, None, None)
        nina = _client().get("/status").json()["nina"]
        self.assertTrue(nina["enabled"])      # abilitato ma nessun dato
        self.assertFalse(nina["connected"])
        self.assertEqual(nina["metrics"], {})
        self.assertIsNone(nina["last_age_s"])

    def test_status_shape_diff_only_nina(self):
        # Lo /status post-§41 deve avere solo la chiave `nina` in più rispetto
        # alla forma pre-§41 {timestamp, controller, analyzer}.
        server.set_nina_store(NinaTelemetryStore(enabled=True))
        server.set_global_state(None, None, None)
        body = _client().get("/status").json()
        self.assertEqual(set(body.keys()), {"timestamp", "controller", "analyzer", "nina"})
        body.pop("nina")
        self.assertEqual(set(body.keys()), {"timestamp", "controller", "analyzer"})


# ===========================================================================
# 7. Isolamento: il POST non tocca il controller; decisioni invariate
# ===========================================================================

def _iso_config() -> AgentConfig:
    cfg = AgentConfig()
    cfg.control = ControlConfig(dry_run=True, cooldown_seconds=30.0)
    cfg.thresholds = Thresholds(rms_high=1.20, rms_low=0.60, snr_low=10.0,
                                spike_ratio_high=0.30, consecutive_frames=5)
    cfg.ra = AxisLimits(aggr_min=35, aggr_max=90, aggr_step_down=5, aggr_step_up=2,
                        minmove_min=0.15, minmove_max=0.85, minmove_step=0.05)
    cfg.dec = AxisLimits(aggr_min=35, aggr_max=90, aggr_step_down=5, aggr_step_up=2,
                         minmove_min=0.15, minmove_max=0.85, minmove_step=0.05)
    cfg.setup = SetupConfig(profile_name="test", guide_pixel_scale_arcsec_native=0.51)
    cfg.lever_optimization = LeverOptimizationConfig(enabled=True, target_factor=1.0)
    return cfg


def _iso_controller() -> AdaptiveController:
    ctrl = AdaptiveController(client=MagicMock(), config=_iso_config())
    ctrl._initialized = True
    for ax in (ctrl._ra, ctrl._dec):
        ax.aggr_param = "Aggressiveness"
        ax.minmove_param = "MinMove"
        ax.current_aggr = 70.0
        ax.current_minmove = 0.40
        ax.last_action_time = 0.0
        ax.last_minmove_action_time = 0.0
    ctrl._rms_baseline_value = 0.5
    ctrl._rms_baseline_rejected = False
    return ctrl


def _degraded_snap() -> AnalysisSnapshot:
    s = AnalysisSnapshot()
    s.condition = SeeingCondition.DEGRADED_SEEING
    s.frame_count = 30
    return s


class TestIsolation(unittest.TestCase):

    def tearDown(self):
        server.set_nina_store(None)

    @_NEEDS_HTTP
    def test_post_does_not_change_controller_status(self):
        ctrl = _iso_controller()
        store = NinaTelemetryStore(enabled=True)
        server.set_nina_store(store)
        server.set_global_state(ctrl, None, None)
        client = _client()
        ctrl_before = client.get("/status").json()["controller"]
        client.post("/nina/telemetry", json=_VALID_PAYLOAD)
        client.post("/nina/telemetry", json=_VALID_PAYLOAD)
        ctrl_after = client.get("/status").json()["controller"]
        self.assertEqual(ctrl_before, ctrl_after)

    def test_guide_decision_identical_with_and_without_telemetry(self):
        # Stesso asse, stesso rms degradato, due controller identici: uno con
        # telemetria nello store globale, uno senza. Le decisioni devono coincidere
        # (lo store non è letto dal motore/leve in §41).
        def decide():
            ctrl = _iso_controller()
            return ctrl._evaluate_axis(
                ctrl._ra, ctrl.cfg.ra, 1.5, 6, 0,
                SeeingCondition.DEGRADED_SEEING, _degraded_snap(),
            )

        server.set_nina_store(None)
        baseline = [(a.axis, a.param, a.old_value, a.new_value) for a in decide()]

        store = NinaTelemetryStore(enabled=True)
        server.set_nina_store(store)
        store.update(dict(_VALID_PAYLOAD), 1)
        with_tlm = [(a.axis, a.param, a.old_value, a.new_value) for a in decide()]

        self.assertEqual(baseline, with_tlm)
        self.assertGreater(len(baseline), 0)  # CASO 1 ha agito (test significativo)


# ===========================================================================
# 8. Thread-safety
# ===========================================================================

class TestThreadSafety(unittest.TestCase):

    def test_concurrent_updates_and_reads(self):
        store = NinaTelemetryStore(enabled=True, staleness_seconds=180.0, history_frames=50)
        n_writers, n_per_writer = 8, 50
        n_readers = 4
        errors: list = []
        stop = threading.Event()

        def writer(wid):
            try:
                for i in range(n_per_writer):
                    p = dict(_VALID_PAYLOAD)
                    p["image"] = dict(_VALID_PAYLOAD["image"], star_count=wid * 1000 + i)
                    store.update(p, 1)
            except Exception as e:  # pragma: no cover
                errors.append(e)

        def reader():
            try:
                while not stop.is_set():
                    blk = store.status_block()
                    assert "metrics" in blk
                    _ = store.is_fresh
                    _ = store.history_snapshot()
            except Exception as e:  # pragma: no cover
                errors.append(e)

        readers = [threading.Thread(target=reader) for _ in range(n_readers)]
        writers = [threading.Thread(target=writer, args=(w,)) for w in range(n_writers)]
        for t in readers:
            t.start()
        for t in writers:
            t.start()
        for t in writers:
            t.join()
        stop.set()
        for t in readers:
            t.join()

        self.assertEqual(errors, [], f"Eccezioni nei thread: {errors}")
        self.assertEqual(store.count, n_writers * n_per_writer)
        blk = store.status_block()
        self.assertIn("image", blk["metrics"])
        self.assertIsInstance(blk["metrics"]["image"]["star_count"], int)
        self.assertTrue(blk["connected"])


# ===========================================================================
# Parsing TOML [nina_telemetry]
# ===========================================================================

class TestConfigParsing(unittest.TestCase):

    def test_missing_section_defaults_born_operative(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.toml"
            p.write_text("[thresholds]\nrms_high = 1.2\n", encoding="utf-8")
            cfg = load_config(p)
        self.assertIsInstance(cfg.nina_telemetry, NinaTelemetryConfig)
        self.assertTrue(cfg.nina_telemetry.enabled)            # born-operative
        self.assertEqual(cfg.nina_telemetry.staleness_seconds, 180.0)
        self.assertEqual(cfg.nina_telemetry.history_frames, 60)
        self.assertFalse(cfg.nina_telemetry.log_arrivals)

    def test_section_parsed(self):
        import tempfile
        from pathlib import Path
        toml = ("[nina_telemetry]\nenabled = false\nstaleness_seconds = 90.0\n"
                "history_frames = 30\nlog_arrivals = true\n")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.toml"
            p.write_text(toml, encoding="utf-8")
            cfg = load_config(p)
        self.assertFalse(cfg.nina_telemetry.enabled)
        self.assertEqual(cfg.nina_telemetry.staleness_seconds, 90.0)
        self.assertEqual(cfg.nina_telemetry.history_frames, 30)
        self.assertTrue(cfg.nina_telemetry.log_arrivals)

    def test_staleness_exposure_factor_default_and_parsed(self):
        import tempfile
        from pathlib import Path
        # §43a — assente -> default 1.5
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.toml"
            p.write_text("[nina_telemetry]\nenabled = true\n", encoding="utf-8")
            cfg = load_config(p)
        self.assertEqual(cfg.nina_telemetry.staleness_exposure_factor, 1.5)
        # presente -> parsato
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.toml"
            p.write_text("[nina_telemetry]\nstaleness_exposure_factor = 2.0\n", encoding="utf-8")
            cfg = load_config(p)
        self.assertEqual(cfg.nina_telemetry.staleness_exposure_factor, 2.0)


# ===========================================================================
# §43a — Finestra di freschezza ADATTIVA alla posa
# ===========================================================================

class TestAdaptiveFreshness(unittest.TestCase):

    def test_window_extends_with_exposure(self):
        # exposure_s=300, factor 1.5 -> finestra effettiva 450 (> staleness 180).
        store = NinaTelemetryStore(enabled=True, staleness_seconds=180.0,
                                   staleness_exposure_factor=1.5)
        store.update(dict(_VALID_PAYLOAD), 1)   # _VALID_PAYLOAD.image.exposure_s = 300.0
        self.assertAlmostEqual(store.status_block()["effective_staleness_s"], 450.0, places=1)
        # age 300: oltre il vecchio staleness 180 ma sotto 450 -> ANCORA connesso (era il bug)
        store._last_monotonic -= 300.0
        self.assertTrue(store.is_fresh)
        self.assertTrue(store.status_block()["connected"])
        # age 500: oltre 450 -> stantio
        store._last_monotonic -= 200.0
        self.assertFalse(store.is_fresh)
        self.assertFalse(store.status_block()["connected"])

    def test_floor_when_no_exposure(self):
        # Senza exposure_s la finestra resta il pavimento staleness_seconds (graceful).
        store = NinaTelemetryStore(enabled=True, staleness_seconds=180.0,
                                   staleness_exposure_factor=1.5)
        store.update({"schema_version": 1, "image": {"hfr": 2.0}}, 1)
        self.assertAlmostEqual(store.status_block()["effective_staleness_s"], 180.0, places=1)
        store._last_monotonic -= 200.0   # age 200 > 180
        self.assertFalse(store.is_fresh)

    def test_factor_zero_disables_adaptivity(self):
        store = NinaTelemetryStore(enabled=True, staleness_seconds=180.0,
                                   staleness_exposure_factor=0.0)
        store.update(dict(_VALID_PAYLOAD), 1)   # exposure 300 ma factor 0
        self.assertAlmostEqual(store.status_block()["effective_staleness_s"], 180.0, places=1)


# ===========================================================================
# §43b — Cap aggressività 100 nel config.toml di shipping
# ===========================================================================

class TestAggrMaxShippedConfig(unittest.TestCase):

    def test_aggr_max_100_minmove_unchanged(self):
        from pathlib import Path
        cfg = load_config(Path(__file__).resolve().parent.parent / "config.toml")
        self.assertEqual(cfg.ra.aggr_max, 100)
        self.assertEqual(cfg.dec.aggr_max, 100)
        # MinMove NON è una % -> resta 0.85 su entrambi gli assi
        self.assertAlmostEqual(cfg.ra.minmove_max, 0.85)
        self.assertAlmostEqual(cfg.dec.minmove_max, 0.85)


@_NEEDS_HTTP
class TestTransparencyFreshContract(unittest.TestCase):
    """§48 — /status.nina.transparency espone `fresh` (single-source dallo store §43)
    e `background`, contratto per il consumatore N6 (plugin)."""

    def tearDown(self):
        server.set_nina_store(None)
        server.set_transparency_tracker(None)

    def _client(self, staleness=180.0):
        from phd2_agent.nina_indices import TransparencyTracker
        store = NinaTelemetryStore(enabled=True, staleness_seconds=staleness)
        tracker = TransparencyTracker(enabled=True, baseline_window_subs=6)
        server.set_nina_store(store)
        server.set_transparency_tracker(tracker)
        server.set_global_state(None, None, None)
        return _client(), store

    def test_fresh_true_after_recent_post(self):
        c, store = self._client()
        for _ in range(6):
            c.post("/nina/telemetry", json={"schema_version": 1,
                    "image": {"star_count": 150, "median_adu": 900, "filter": "L", "exposure_s": 300}})
        t = c.get("/status").json()["nina"]["transparency"]
        self.assertTrue(t["fresh"])
        self.assertEqual(t["state"], "CLEAR")
        self.assertIsNotNone(t["index"])       # continuo
        self.assertIn("background", t)          # alias contratto N6
        # §55 (fix N6) — età telemetria + finestra adattiva esposte accanto a fresh:
        # il plugin le logga a ogni tick (osservabilità: "stantio" provato, non dedotto).
        self.assertIsNotNone(t["age_s"])
        self.assertLess(t["age_s"], 60.0)
        self.assertAlmostEqual(t["window_s"], 450.0)   # max(180, 1.5×300s)

    def test_fresh_false_when_stale(self):
        c, store = self._client()
        c.post("/nina/telemetry", json={"schema_version": 1,
                "image": {"star_count": 150, "median_adu": 900, "filter": "L", "exposure_s": 300}})
        store._last_monotonic -= 10000.0        # forza staleness
        t = c.get("/status").json()["nina"]["transparency"]
        self.assertFalse(t["fresh"])            # N6 -> il plugin escala (fix §55), non ignora
        # §55 — l'età rende lo stantio auto-evidente: >> finestra adattiva.
        self.assertGreater(t["age_s"], t["window_s"])

    def test_fresh_false_when_no_tracker(self):
        server.set_nina_store(None)
        server.set_transparency_tracker(None)
        server.set_global_state(None, None, None)
        t = _client().get("/status").json()["nina"]["transparency"]
        self.assertFalse(t["fresh"])
        self.assertIsNone(t["age_s"])           # §55 — mai ricevuto: età assente, non 0
        self.assertIsNone(t["window_s"])


if __name__ == "__main__":
    unittest.main()
