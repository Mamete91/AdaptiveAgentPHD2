"""
test_e2e.py — Test end-to-end: simulatore → client → analyzer → controller
"""
import time
import threading
import queue as q_module

from simulator.phd2_simulator import PHD2SimulatorServer
from phd2_agent.client import PHD2Client
from phd2_agent.analyzer import StatisticsAnalyzer
from phd2_agent.controller import AdaptiveController
from phd2_agent.config import load_config

cfg = load_config("config.toml")

# ---- Avvia simulatore su porta alternativa ----
sim = PHD2SimulatorServer(host="localhost", port=4401)
t = threading.Thread(target=sim.start, daemon=True)
t.start()
time.sleep(0.6)

# ---- Connetti il client ----
client = PHD2Client("localhost", 4401)
client.connect()
time.sleep(0.3)  # lascia arrivare i messaggi iniziali

# ---- Test RPC ----
state = client.get_app_state()
assert state == "Guiding", f"Stato atteso 'Guiding', ottenuto '{state}'"
print(f"  get_app_state(): {state} ✓")

px_scale = client.get_pixel_scale()
assert 0.5 < px_scale < 5.0, f"Pixel scale out of range: {px_scale}"
print(f"  get_pixel_scale(): {px_scale} arcsec/px ✓")

params = client.probe_algo_params()
assert "ra" in params and "dec" in params, f"Params incompleti: {params}"
print(f"  probe_algo_params(): RA={params['ra']} Dec={params['dec']} ✓")

# ---- Test set_algo_param ----
old_v = params["ra"].get("Aggressiveness", 70.0)
client.set_algo_param("ra", "Aggressiveness", 65.0)
new_v = client.get_algo_param("ra", "Aggressiveness")
assert abs(new_v - 65.0) < 0.01, f"set_algo_param fallito: {new_v}"
print(f"  set_algo_param ra/Aggressiveness: {old_v} → {new_v} ✓")

# ---- Test Analyzer ----
analyzer = StatisticsAnalyzer(window_size=15, rms_high=0.80, rms_low=0.35)
print("\nRaccolta 20 frame GuideStep...")
count = 0
while count < 20:
    try:
        event = client.event_queue.get(timeout=6.0)
        if event.get("Event") == "GuideStep":
            snap = analyzer.ingest_guide_step(event)
            count += 1
            print(
                f"  Frame {count:3d}: "
                f"RMS_RA={snap.rms_ra:.3f}\" "
                f"RMS_Dec={snap.rms_dec:.3f}\" "
                f"SNR={snap.snr_avg:.1f} "
                f"Cond={snap.condition.name}"
            )
    except q_module.Empty:
        print("  Timeout — nessun frame ricevuto")
        break

assert count == 20, f"Ricevuti solo {count} frame"
assert analyzer.is_ready
print(f"\n  Analyzer.is_ready: {analyzer.is_ready} ✓")
print(f"  Ultimo snapshot: RMS_total={snap.rms_total:.3f}\" ✓")

# ---- Test Controller (DRY_RUN) ----
cfg.control.dry_run = True
ctrl = AdaptiveController(client, cfg)
init_ok = ctrl.initialize()
assert init_ok, "Controller initialize() fallito"
print(f"\n  Controller inizializzato ✓ (guiding_state={ctrl.guiding_state.name})")

actions = ctrl.evaluate(snap)
print(f"  Controller.evaluate(): {len(actions)} azioni ✓")

# ---- Chiudi ----
client.disconnect()
print("\n✅ Test end-to-end SUPERATO")
