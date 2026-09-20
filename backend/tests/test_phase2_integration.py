"""
Phase 2 integration test: the full chain (simulator -> signal_pipeline ->
inference -> controller -> db) wired together exactly as app/main.py will
wire it in Phase 3.

This exists specifically to catch calibration gaps that per-component unit
tests cannot see. It caught a real one during Phase 2 build: StubRiskModel's
original 0.6/0.4 baseline/amplitude weighting had a mathematical ceiling of
0.67, which is below the default risk_alert threshold (0.75) -- meaning SRD
acceptance criterion 8 ("alert fires ... demonstrable via induced test
signal") could never actually be demonstrated against the simulator, no
matter how the demo was run. Unit tests on the controller alone (which drive
the score directly) could not have caught this, because they never exercise
StubRiskModel's actual output range.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.config import settings
from app.controller import Controller
from app.db import Database
from app.inference import load_risk_model
from app.signal_pipeline import SignalPipeline
from app.simulator import Simulator


@pytest.mark.asyncio
async def test_alert_fires_on_sustained_simulated_spike(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    await db.connect()
    session_id = await db.start_session("esp32_primary_01")

    pipeline = SignalPipeline()
    model = load_risk_model("")
    sim = Simulator(seed=42)
    controller = Controller()
    sim.start()

    alerts_fired = 0
    for i in range(40):
        if i == 10:
            sim.spike(duration_s=20)
        w = sim._next_window()
        arr = pipeline.ingest(w)
        score = model.predict(arr) if arr is not None else None
        mode = controller.state.mode
        if score is not None:
            decision = controller.evaluate(
                score=score, battery_pct=w.battery_pct, sqi=w.sqi, timestamp=w.window_start_ts
            )
            mode = decision.mode
            if decision.fire_alert:
                alerts_fired += 1
                await db.insert_alert(session_id, w.window_start_ts, score)
        await db.insert_ecg_window(session_id, w.window_start_ts, w.sqi, score, mode)

    assert alerts_fired >= 1, (
        "a sustained induced spike through the full simulator->model->controller "
        "chain must fire at least one alert -- if this fails, check whether "
        "StubRiskModel's score ceiling still clears settings.risk_alert"
    )

    a_total, _ = await db.alert_counts(session_id)
    assert a_total == alerts_fired

    await db.close()


def test_stub_model_ceiling_clears_risk_alert_threshold():
    """Direct guard on the calibration gap itself: assert the model's
    mathematical maximum score is comfortably above risk_alert, not just that
    one simulator run happened to cross it."""
    model = load_risk_model("")
    # Force baseline to its minimum and feed a very large synthetic amplitude
    # to approximate the model's ceiling.
    model._baseline = 0.05  # type: ignore[attr-defined]
    import numpy as np

    huge_amplitude_window = (np.linspace(-5, 5, 100) * 1.0).reshape(1, 1, -1).astype(np.float32)
    score = model.predict(huge_amplitude_window)
    assert score > settings.risk_alert, (
        f"StubRiskModel ceiling ({score:.3f}) must exceed risk_alert "
        f"({settings.risk_alert}) or the alert path can never be demonstrated"
    )
