"""
BLE gateway tests (docs/API_CONTRACT.md section 2.1): packet parsing in the
exact byte layout the firmware sends, sqi/ecg/status pairing into windows,
and the command path back to the device. No radio needed -- the gateway's
packet handling is separate from the bleak connection.
"""
from __future__ import annotations

import asyncio
import struct

import pytest

from app.ble_gateway import BleGateway, DeviceStatus, parse_device_status, parse_ecg_data
from app.config import settings
from app.events import bus


def _ecg_packet(device_ts: float = 12.5, samples=None) -> bytes:
    samples = samples if samples is not None else list(range(-50, 50))
    return struct.pack("<d", device_ts) + struct.pack(f"<{len(samples)}h", *samples)


def _status_packet(battery=255, mode=1, leads_off=0, motion_centi=4) -> bytes:
    return struct.pack("<BBBH", battery, mode, leads_off, motion_centi)


def test_parse_ecg_data_layout():
    ts, samples = parse_ecg_data(_ecg_packet(12.5, [1, -2, 32767, -32768]))
    assert ts == 12.5
    assert samples == [1, -2, 32767, -32768]


def test_parse_ecg_data_full_window_is_208_bytes():
    pkt = _ecg_packet(samples=[0] * settings.ecg_sample_rate_hz)
    assert len(pkt) == 208  # the MTU requirement in the contract is derived from this
    assert len(parse_ecg_data(pkt)[1]) == 100


@pytest.mark.parametrize("bad", [b"", b"\x00" * 7, b"\x00" * 9])
def test_parse_ecg_data_rejects_malformed(bad):
    with pytest.raises(ValueError):
        parse_ecg_data(bad)


def test_parse_device_status():
    assert parse_device_status(_status_packet(255, 2, 1, 350)) == DeviceStatus(None, "Watch", True, 3.5)
    assert parse_device_status(_status_packet(78, 0, 0, 4)).battery_pct == 78
    with pytest.raises(ValueError):
        parse_device_status(b"\x01\x02")


def test_ingest_pairs_packets_into_one_window_on_status():
    gw = BleGateway()
    assert gw._ingest("sqi", b"\x01") is None
    assert gw._ingest("ecg", _ecg_packet()) is None
    w = gw._ingest("status", _status_packet())
    assert w is not None
    assert w.sqi == 1 and w.sample_rate_hz == 100 and len(w.samples) == 100
    assert w.battery_pct is None and w.leads_off is False and w.motion_ms2 == 0.04


def test_status_without_ecg_emits_nothing():
    gw = BleGateway()
    assert gw._ingest("status", _status_packet()) is None


def test_leads_off_window_is_never_accepted():
    gw = BleGateway()
    gw._ingest("sqi", b"\x01")  # even if firmware claimed accept
    gw._ingest("ecg", _ecg_packet())
    w = gw._ingest("status", _status_packet(leads_off=1))
    assert w.sqi == 0 and w.leads_off is True


def test_malformed_packet_is_dropped_not_raised():
    gw = BleGateway()
    assert gw._ingest("ecg", b"\x00\x01\x02") is None
    assert gw._ingest("status", _status_packet()) is None


class FakeClient:
    def __init__(self):
        self.writes: list[tuple[str, bytes]] = []

    async def write_gatt_char(self, uuid, data, response=False):
        self.writes.append((uuid, bytes(data)))


async def test_mode_changes_and_alerts_are_written_to_device():
    gw = BleGateway()
    client = FakeClient()
    task = asyncio.create_task(gw._forward_commands(client))
    await asyncio.sleep(0)  # let it subscribe

    bus.publish("risk_update", {"score": 0.6, "mode": "Watch", "timestamp": 1.0})
    bus.publish("risk_update", {"score": 0.6, "mode": "Watch", "timestamp": 2.0})  # unchanged: no write
    bus.publish("alert", {"id": 1, "level": "high", "score": 0.9, "timestamp": 3.0, "message": "x"})
    for _ in range(5):
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert client.writes == [
        (settings.ble_char_controller_cmd, bytes([2])),
        (settings.ble_char_alert_cmd, b"\x01"),
    ]


async def test_manual_mode_change_reaches_device_via_status_frame():
    """With leads off there are no risk_update frames, only status frames --
    a manual override must still be written to the device."""
    gw = BleGateway()
    client = FakeClient()
    task = asyncio.create_task(gw._forward_commands(client))
    await asyncio.sleep(0)
    bus.publish("status", {"mode": "Verify", "connected": True})
    for _ in range(3):
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert client.writes == [(settings.ble_char_controller_cmd, bytes([3]))]


async def test_failed_scans_pause_and_log_once(monkeypatch, caplog):
    """A scan that fails returns at once (e.g. BlueZ "Operation already in
    progress"). The gateway must pause between attempts instead of spinning,
    and report the outage once rather than on every attempt."""
    import logging

    import app.ble_gateway as ble

    calls = 0

    async def failing_scan(timeout):
        nonlocal calls
        calls += 1
        return None

    async def unused(*_):
        raise AssertionError("no device was found, so nothing should be called")

    monkeypatch.setattr(ble, "find_device", failing_scan)
    monkeypatch.setattr(settings, "ble_rescan_pause_s", 0.05)
    caplog.set_level(logging.INFO, logger="glucosentry.ble")

    task = asyncio.create_task(BleGateway().run(unused, unused))
    await asyncio.sleep(0.3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert 2 <= calls <= 8  # ~6 at a 0.05 s pause; without the pause, thousands
    assert sum("no GlucoSentry node found" in r.message for r in caplog.records) == 1
