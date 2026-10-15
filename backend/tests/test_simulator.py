"""The simulator's scenarios and the simulated foot module (app/simulator.py),
plus the /api/sim/* controls."""
from __future__ import annotations

import asyncio

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.aux_gateway import AuxUnavailable
from app.config import settings
from app.simulator import SimulatedFootModule, Simulator


def windows(sim: Simulator, n: int):
    return [sim._next_window() for _ in range(n)]


def test_normal_ecg_has_ecg_shape_and_scale():
    sim = Simulator(seed=1)
    sim.random_artifacts = False
    ws = windows(sim, 10)
    assert all(w.sqi == 1 and not w.leads_off for w in ws)
    x = np.concatenate([w.samples for w in ws])
    # R peaks ~1 mV -> ~1200 counts, S/Q dip below baseline, i.e. not a sine.
    assert 900 < x.max() < 1700
    assert x.min() < -150


def test_motion_scenario_is_rejected_with_high_motion():
    sim = Simulator(seed=2)
    sim.set_scenario("motion", 5)
    ws = windows(sim, 3)
    assert all(w.sqi == 0 and not w.leads_off for w in ws)
    assert all(w.motion_ms2 > settings.serial_motion_sqi_threshold_ms2 for w in ws)


def test_leads_off_scenario_is_flat_and_flagged():
    sim = Simulator(seed=3)
    sim.set_scenario("leads_off", 5)
    w = sim._next_window()
    assert w.leads_off and w.sqi == 0
    assert np.ptp(w.samples) < 50


def test_hypo_pattern_raises_heart_rate():
    sim = Simulator(seed=4)
    sim.set_scenario("hypo", 0.3)  # progress is time-based; let it complete
    import time
    time.sleep(0.25)
    assert sim.state()["heart_rate_bpm"] > sim.base_hr_bpm + 20


def test_scenario_expires_back_to_normal():
    sim = Simulator(seed=5)
    sim.set_scenario("spike", 0.01)
    import time
    time.sleep(0.02)
    assert sim.scenario == "normal"


def test_unknown_scenario_rejected():
    with pytest.raises(ValueError):
        Simulator().set_scenario("bogus")


@pytest.mark.parametrize("mode,valid,elevated", [("normal", True, False), ("elevated", True, True), ("invalid", False, None)])
def test_simulated_foot_module_modes(monkeypatch, mode, valid, elevated):
    monkeypatch.setattr(settings, "foot_check_eta_s", 0)
    foot = SimulatedFootModule(seed=1)
    foot.set_mode(mode)
    r = asyncio.run(foot.read())
    assert r.valid is valid
    if valid:
        assert (abs(r.delta) > settings.foot_check_elevated_threshold_c) is elevated


def test_simulated_foot_module_offline_raises():
    foot = SimulatedFootModule()
    foot.set_mode("offline")
    assert not foot.connected
    with pytest.raises(AuxUnavailable):
        asyncio.run(foot.read())


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "gs_source", "simulator")
    monkeypatch.setattr(settings, "gs_aux_source", "simulator")
    monkeypatch.setattr(settings, "gs_enable_sim", True)
    monkeypatch.setattr(settings, "gs_db_path", str(tmp_path / "test.db"))
    monkeypatch.setattr(settings, "gs_model_selection_path", str(tmp_path / "selection.txt"))
    from app.main import app

    with TestClient(app) as c:
        yield c


def test_sim_api_round_trip(client):
    s = client.post("/api/sim/scenario", json={"name": "motion", "duration_s": 30}).json()
    assert s["ecg"]["scenario"] == "motion"
    s = client.post("/api/sim/settings", json={"heart_rate_bpm": 95, "battery_pct": 12}).json()
    assert s["ecg"]["base_heart_rate_bpm"] == 95 and s["ecg"]["battery_pct"] == 12
    s = client.post("/api/sim/foot", json={"mode": "offline"}).json()
    assert s["foot"]["connected"] is False
    assert client.get("/api/status").json()["aux_connected"] is False
    assert client.post("/api/foot/request").status_code == 503
    assert client.post("/api/sim/scenario", json={"name": "bogus"}).status_code == 400
    assert client.get("/api/diagnostics").json()["simulator"]["ecg"]["scenario"] == "motion"
