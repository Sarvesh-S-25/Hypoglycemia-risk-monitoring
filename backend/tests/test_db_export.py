"""
Regression tests for Database.export_rows, guarding two real bugs found while
building it: a range-JOIN row-multiplication bug, and a SQLite ORDER BY
correlation limitation. See db.py's export_rows docstring for the full story.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.db import Database


@pytest.fixture
async def db(tmp_path: Path):
    """Always closed, even when a test fails: aiosqlite runs each connection
    on a non-daemon thread, so a connection left open keeps the pytest
    process alive forever after every test has already passed."""
    database = Database(tmp_path / "test.db")
    await database.connect()
    try:
        yield database
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_export_has_exactly_one_row_per_window_even_with_multiple_status_rows(db: Database):
    """The core regression guard: device_status rows inserted once per
    window (dense, ~1 Hz) must not multiply the exported ecg_windows rows.
    The original range-based JOIN (`ABS(diff) < 5.0`) turned 4 windows into
    16 export rows because every window matched several nearby status rows."""
    session_id = await db.start_session("test-device")

    n_windows = 6
    for i in range(n_windows):
        ts = 1000.0 + i * 1.0  # 1 Hz, same cadence as the real pipeline
        await db.insert_ecg_window(session_id, ts, sqi=1, risk_score=0.2, mode="Normal")
        # Every window gets its own status row -- this density is exactly
        # what triggered the original bug.
        await db.insert_device_status(session_id, ts, battery_pct=90, mode="Normal", leads_off=False)

    rows = await db.export_rows(session_id)
    assert len(rows) == n_windows, (
        f"expected exactly {n_windows} export rows (one per window), got {len(rows)} "
        "-- if this fails, the device_status join is multiplying rows again"
    )
    for r in rows:
        assert r["battery_pct"] == 90


@pytest.mark.asyncio
async def test_export_attaches_nearest_alert_and_foot_check_within_window(db: Database):
    session_id = await db.start_session("test-device")

    await db.insert_ecg_window(session_id, 1000.0, sqi=1, risk_score=0.9, mode="Verify")
    await db.insert_alert(session_id, 1000.3, risk_score=0.9)  # within the 1.0s attach window

    await db.insert_ecg_window(session_id, 2000.0, sqi=1, risk_score=0.1, mode="Normal")
    await db.insert_foot_check(
        session_id, 2000.1, t_left=30.0, t_right=31.0, delta_t=1.0, valid=True,
        next_check_scheduled=2000.0 + 86400.0, action="scheduled_24h",
    )

    await db.insert_ecg_window(session_id, 3000.0, sqi=1, risk_score=0.1, mode="Normal")
    # An alert far away in time must NOT attach to the unrelated window.
    await db.insert_alert(session_id, 3050.0, risk_score=0.9)

    rows = await db.export_rows(session_id)
    assert len(rows) == 3

    by_ts = {round(r["timestamp"]): r for r in rows}
    assert by_ts[1000]["alert_id"] is not None
    assert by_ts[2000]["foot_delta_t"] == 1.0
    assert by_ts[3000]["alert_id"] is None, "an alert 50s away must not attach to this window"


@pytest.mark.asyncio
async def test_export_empty_session_returns_no_rows(db: Database):
    session_id = await db.start_session("test-device")
    rows = await db.export_rows(session_id)
    assert rows == []
