"""
Serial source tests (docs/API_CONTRACT.md section 2.4): firmware line parsing,
250 -> 100 Hz window building, SQI gating, and the nullable-battery rules that
the USB source introduced. No hardware needed -- the gateway's parsing and
window building are pure functions over the firmware's line format.
"""
from __future__ import annotations

import numpy as np

from app.config import settings
from app.controller import Controller, should_fire_foot_check
from app.serial_gateway import Sample, build_window, parse_line
from app.signal_pipeline import SignalPipeline


def _still_samples(n: int = 250, ecg_mv: float = 1650.0, leads_off: bool = False) -> list[Sample]:
    """Board lying flat and motionless: gravity on Z only."""
    return [Sample(ecg_mv, leads_off, 0.0, 0.0, 9.81) for _ in range(n)]


def test_parse_line_accepts_firmware_format():
    s = parse_line(b"1652.4,0,1.02,0.41,9.73\n")
    assert s == Sample(1652.4, False, 1.02, 0.41, 9.73)
    assert parse_line(b"0.0,1,1.02,0.41,9.73\r\n").leads_off is True


def test_parse_line_ignores_boot_messages_and_partial_lines():
    assert parse_line(b"Scanning I2C bus...\n") is None
    assert parse_line(b"MPU6500 (0x68): OK\n") is None
    assert parse_line(b"Streaming: ecg_mV,leads_off,ax,ay,az\n") is None
    assert parse_line(b"52.4,0,1.02\n") is None
    assert parse_line(b"") is None


def test_window_is_decimated_to_100hz_int16_counts():
    w = build_window(_still_samples(ecg_mv=1650.0), "esp32_primary_01", 1000.0)
    assert w.sample_rate_hz == settings.ecg_sample_rate_hz == 100
    assert len(w.samples) == 100
    # 1650 mV / 0.125 mV per LSB = 13200 ADC counts, the ADS1115's own units.
    # The 3-tap smoother's zero-padded edges dip the very first/last points.
    assert all(v == 13200 for v in w.samples[1:-1])
    assert all(isinstance(v, int) for v in w.samples)


def test_decimation_preserves_a_heartbeat_shaped_peak():
    """An R-peak must survive 250 -> 100 Hz, or the model sees a flat line."""
    samples = _still_samples()
    t = np.arange(250) / 250
    peak = 1650 + 800 * np.exp(-((t - 0.5) / 0.012) ** 2)
    samples = [s._replace(ecg_mv=float(v)) for s, v in zip(samples, peak)]
    w = build_window(samples, "esp32_primary_01", 1000.0)
    arr = np.array(w.samples)
    assert 45 <= int(np.argmax(arr)) <= 55  # peak stays near the middle
    assert arr.max() - np.median(arr) > 0.5 * (800 / settings.serial_mv_per_lsb)


def test_still_window_with_leads_on_is_accepted():
    w = build_window(_still_samples(), "esp32_primary_01", 1000.0)
    assert w.sqi == 1
    assert w.leads_off is False
    assert w.battery_pct is None  # USB bus-powered: unmeasured, not faked


def test_leads_off_anywhere_in_window_rejects_it():
    samples = _still_samples()
    samples[120] = samples[120]._replace(leads_off=True)
    w = build_window(samples, "esp32_primary_01", 1000.0)
    assert w.sqi == 0
    assert w.leads_off is True


def test_motion_rejects_window():
    rng = np.random.default_rng(1)
    samples = [
        Sample(1650.0, False, *(rng.normal(0, 6, 3) + [0, 0, 9.81]))
        for _ in range(250)
    ]
    w = build_window(samples, "esp32_primary_01", 1000.0)
    assert w.sqi == 0
    assert w.leads_off is False


def test_pipeline_scores_a_serial_window():
    w = build_window(_still_samples(), "esp32_primary_01", 1000.0)
    arr = SignalPipeline().ingest(w)
    assert arr is not None and arr.shape == (1, 1, 100)


def test_unknown_battery_never_forces_eco():
    c = Controller()
    for i in range(settings.sqi_stable_window + 1):
        decision = c.evaluate(score=0.1, battery_pct=None, sqi=1, timestamp=float(i))
    assert decision.mode == "Normal"


def test_unknown_battery_does_not_block_foot_check():
    assert should_fire_foot_check(scheduled_time=10.0, battery_pct=None, now=20.0) is True
    assert should_fire_foot_check(scheduled_time=10.0, battery_pct=5, now=20.0) is False
