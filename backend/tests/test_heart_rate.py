"""
Heart-rate display value (docs/API_CONTRACT.md section 3, `heart_rate_bpm`):
correct on known rhythms, null until enough clean signal, and reset -- not
stale -- after any rejected window.
"""
from __future__ import annotations

import numpy as np

from app.config import settings
from app.heart_rate import HeartRateEstimator, estimate_bpm
from app.models import EcgWindow
from app.simulator import Simulator

FS = 100


def _ecg(bpm: float, seconds: float, fs: int = FS) -> np.ndarray:
    t = np.arange(int(seconds * fs)) / fs
    x = 50 * np.sin(2 * np.pi * 0.25 * t)  # baseline wander
    for beat in np.arange(0.3, seconds, 60.0 / bpm):
        x += 1500 * np.exp(-((t - beat) / 0.015) ** 2)
    return x + np.random.default_rng(0).normal(0, 20, t.size)


def _window(samples, sqi: int = 1) -> EcgWindow:
    return EcgWindow(
        device_id="test", window_start_ts=0.0, sample_rate_hz=FS, sqi=sqi,
        samples=[int(v) for v in samples], battery_pct=None,
    )


def test_estimates_known_rates():
    for bpm in (50, 72, 120):
        est = estimate_bpm(_ecg(bpm, 8), FS)
        assert est is not None and abs(est - bpm) < 2, (bpm, est)


def test_flat_or_noise_is_null():
    assert estimate_bpm(np.zeros(800), FS) is None
    assert estimate_bpm(np.random.default_rng(1).normal(0, 5, 800), FS) is None
    assert estimate_bpm(_ecg(72, 1), FS) is None  # too short


def test_estimator_null_until_window_filled_then_reports():
    hr = HeartRateEstimator()
    x = _ecg(72, settings.hr_window_s)
    chunks = np.split(x, int(settings.hr_window_s))
    for c in chunks[:-1]:
        assert hr.update(_window(c)) is None
    assert abs(hr.update(_window(chunks[-1])) - 72) < 2


def test_rejected_window_resets_instead_of_going_stale():
    hr = HeartRateEstimator()
    for c in np.split(_ecg(72, settings.hr_window_s), int(settings.hr_window_s)):
        hr.update(_window(c))
    assert hr.bpm is not None
    assert hr.update(_window(np.zeros(FS), sqi=0)) is None
    assert hr.bpm is None
    # One clean window after the gap is not enough to report again.
    assert hr.update(_window(_ecg(72, 1))) is None


def test_simulator_reads_about_72_bpm():
    """The simulator's base rate is 72 bpm (with ~4% respiratory variation)."""
    sim = Simulator(seed=3)
    sim.random_artifacts = False  # artifact windows really are corrupted now
    sim.start()
    hr = HeartRateEstimator()
    readings = []
    for _ in range(30):
        w = sim._next_window()
        if (bpm := hr.update(w)) is not None:
            readings.append(bpm)
    assert readings and all(abs(r - 72) < 3 for r in readings), readings
