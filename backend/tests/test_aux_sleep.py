"""The deep-sleeping foot module: check-in decisions (controller.py), the
node_info packet and missing-node logic (aux_gateway.py), and queued manual
requests (POST /api/foot/request)."""
from __future__ import annotations

import struct
import time

import pytest
from fastapi.testclient import TestClient

from app.aux_gateway import AuxGateway, parse_node_info
from app.config import settings
from app.controller import foot_checkin_should_read, foot_sleep_seconds

NOW = 1_000_000.0


def test_reads_when_due():
    assert foot_checkin_should_read(now=NOW, scheduled_time=NOW - 1, battery_pct=80, manual_requested=False, busy=False)


def test_skips_when_not_due():
    assert not foot_checkin_should_read(now=NOW, scheduled_time=NOW + 60, battery_pct=80, manual_requested=False, busy=False)


def test_manual_request_reads_even_when_not_due():
    assert foot_checkin_should_read(now=NOW, scheduled_time=NOW + 3600, battery_pct=80, manual_requested=True, busy=False)


def test_low_battery_defers_a_due_check():
    assert not foot_checkin_should_read(
        now=NOW, scheduled_time=NOW - 1, battery_pct=settings.battery_aux_min - 1, manual_requested=False, busy=False
    )


def test_never_reads_while_busy():
    assert not foot_checkin_should_read(now=NOW, scheduled_time=NOW - 1, battery_pct=None, manual_requested=True, busy=True)


def test_sleeps_until_next_check_within_bounds():
    assert foot_sleep_seconds(now=NOW, scheduled_time=NOW + 12) == 12
    assert foot_sleep_seconds(now=NOW, scheduled_time=NOW + 1) == settings.aux_min_sleep_s
    assert foot_sleep_seconds(now=NOW, scheduled_time=NOW + 86400) == settings.aux_max_sleep_s
    # Due but deferred (e.g. low battery): back off rather than return in seconds.
    assert foot_sleep_seconds(now=NOW, scheduled_time=NOW - 5) == settings.aux_max_sleep_s


def test_parse_node_info():
    info = parse_node_info(struct.pack("<BII", 2, 17, 30))
    assert info.wake_reason == "button" and info.boot_count == 17 and info.last_sleep_s == 30
    with pytest.raises(ValueError):
        parse_node_info(b"\x01")


def test_node_missing_until_seen_then_asleep_then_overdue():
    gw = AuxGateway()
    assert gw.missing and gw.status()["state"] == "missing"
    gw.node_state, gw.next_wake_ts = "asleep", time.time() + 20
    assert not gw.missing and gw.status()["state"] == "asleep"
    gw.next_wake_ts = time.time() - settings.aux_missing_grace_s - 1
    assert gw.missing


class SleepingNode:
    """Stand-in for AuxGateway between check-ins."""
    rendezvous = True
    eta_s = 1
    connected = False
    missing = False
    next_wake_ts = None

    def status(self):
        return {"state": "asleep", "next_wake_ts": self.next_wake_ts, "last_seen_ts": None,
                "wake_reason": "timer", "boot_count": 3, "checkins": 3}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "gs_source", "none")
    monkeypatch.setattr(settings, "gs_aux_source", "simulator")
    monkeypatch.setattr(settings, "gs_db_path", str(tmp_path / "test.db"))
    monkeypatch.setattr(settings, "gs_model_selection_path", str(tmp_path / "selection.txt"))
    from app.main import app

    with TestClient(app) as c:
        yield c, app


def test_manual_request_is_queued_for_a_sleeping_node(client):
    c, app = client
    node = SleepingNode()
    node.next_wake_ts = time.time() + 20
    app.state.gs.aux_gateway = node
    r = c.post("/api/foot/request")
    assert r.status_code == 202
    assert r.json()["eta_s"] >= 20
    status = c.get("/api/status").json()
    assert status["aux_state"] == "asleep" and status["aux_check_queued"] is True


def test_manual_request_refused_for_a_missing_node(client):
    c, app = client
    node = SleepingNode()
    node.missing = True
    app.state.gs.aux_gateway = node
    assert c.post("/api/foot/request").status_code == 503
