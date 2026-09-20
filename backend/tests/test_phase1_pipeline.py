"""
Phase 1 regression tests: simulator -> signal_pipeline -> inference -> db.

Guards specifically against the normalization bug found during Phase 1 build:
per-window z-score normalization is scale-invariant to the window's own
amplitude, which silently erases the signal an induced spike (or a real
amplitude anomaly) needs to be visible as. See signal_pipeline.py's docstring
on _reshape for the full explanation.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.db import Database
from app.inference import StubRiskModel, load_risk_model
from app.signal_pipeline import SignalPipeline
from app.simulator import Simulator


def test_stub_model_selected_when_no_path():
    model = load_risk_model("")
    assert isinstance(model, StubRiskModel)


def test_spike_raises_risk_score_above_baseline():
    """The core regression guard: an induced spike must be clearly
    distinguishable from baseline, or the SRD acceptance criterion "vibration
    alert fires only after sustained-risk confirmation, demonstrable via
    induced test signal" has nothing to demonstrate with."""
    pipeline = SignalPipeline()
    model = load_risk_model("")
    sim = Simulator(seed=7)
    sim.start()

    normal_scores = []
    for _ in range(10):
        w = sim._next_window()
        arr = pipeline.ingest(w)
        if arr is not None:
            normal_scores.append(model.predict(arr))

    sim.spike(duration_s=10)
    spike_scores = []
    for _ in range(10):
        w = sim._next_window()
        arr = pipeline.ingest(w)
        if arr is not None:
            spike_scores.append(model.predict(arr))

    assert max(spike_scores) > max(normal_scores) + 0.1, (
        f"spike did not clearly raise risk: normal max={max(normal_scores):.3f}, "
        f"spike max={max(spike_scores):.3f}"
    )


def test_sqi_rejected_window_returns_none():
    pipeline = SignalPipeline()
    from app.models import EcgWindow

    rejected = EcgWindow(
        device_id="test",
        window_start_ts=0.0,
        sample_rate_hz=100,
        sqi=0,
        samples=[1, 2, 3],
        battery_pct=80,
    )
    assert pipeline.ingest(rejected) is None
    # but it's still visible via latest() so the dashboard can show *something*
    assert pipeline.latest() is rejected


@pytest.mark.asyncio
async def test_end_to_end_persists_and_excludes_rejected_from_history(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    await db.connect()
    session_id = await db.start_session("esp32_primary_01")

    pipeline = SignalPipeline()
    model = load_risk_model("")
    sim = Simulator(seed=42)
    sim.start()

    rejected_count = 0
    for _ in range(20):
        w = sim._next_window()
        arr = pipeline.ingest(w)
        score = model.predict(arr) if arr is not None else None
        if score is None:
            rejected_count += 1
        await db.insert_ecg_window(session_id, w.window_start_ts, w.sqi, score, "Normal")

    total, rejected_in_db = await db.window_counts(session_id)
    assert total == 20
    assert rejected_in_db == rejected_count

    history = await db.risk_history(session_id, 0)
    # rejected windows have risk_score IS NULL and must not appear in history
    assert len(history) == total - rejected_in_db

    await db.close()
