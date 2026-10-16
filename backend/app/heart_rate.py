"""
heart_rate.py -- R-peak heart-rate estimate over the last few seconds of
accepted ECG (docs/API_CONTRACT.md section 3, `heart_rate_bpm`).

Deliberately simple: a moving-average baseline removal, an adaptive
threshold at a fraction of the window's peak, and a refractory period. It is
a display value for the dashboard, not an input to the risk model or the
controller, so it is kept out of signal_pipeline/inference entirely.

Any rejected window clears the buffer: a rate computed across a leads-off gap
or a motion burst would be confidently wrong, and AGENTS.md prefers an honest
null to a stale number.
"""
from __future__ import annotations

from collections import deque
from typing import Optional

import numpy as np

from app.config import settings
from app.models import EcgWindow


def estimate_bpm(samples: np.ndarray, sample_rate_hz: int) -> Optional[float]:
    """Median R-R interval of `samples` as beats per minute, or None if no
    plausible rhythm is found."""
    fs = sample_rate_hz
    if len(samples) < fs * 2:
        return None

    k = max(1, int(fs * settings.hr_baseline_s))
    detrended = samples - np.convolve(samples, np.ones(k) / k, mode="same")
    # Edges of a "same" convolution are biased by zero padding; ignore them.
    detrended[:k] = 0
    detrended[-k:] = 0
    peak = float(np.max(detrended))
    mad = float(np.median(np.abs(detrended - np.median(detrended))))
    # Without distinct R-peaks (flat line, pure noise, a disconnected lead
    # floating) the threshold would happily pick noise maxima as "beats".
    if peak <= 0 or peak < settings.hr_min_peak_to_mad * mad:
        return None
    threshold = settings.hr_peak_fraction * peak

    refractory = int(fs * 60.0 / settings.hr_max_bpm)
    peaks: list[int] = []
    i = 1
    while i < len(detrended) - 1:
        v = detrended[i]
        if v > threshold and v >= detrended[i - 1] and v >= detrended[i + 1]:
            peaks.append(i)
            i += refractory
        else:
            i += 1
    if len(peaks) < 3:
        return None

    bpm = 60.0 * fs / float(np.median(np.diff(peaks)))
    if not settings.hr_min_bpm <= bpm <= settings.hr_max_bpm:
        return None
    return round(bpm, 1)


class HeartRateEstimator:
    """Feed every window (accepted or not) to `update()`; read `bpm`."""

    def __init__(self) -> None:
        self._windows: deque[list[int]] = deque()
        self._sample_rate_hz: Optional[int] = None
        self.bpm: Optional[float] = None

    def update(self, window: EcgWindow) -> Optional[float]:
        if window.sqi != 1 or window.sample_rate_hz != self._sample_rate_hz:
            self._windows.clear()
            self._sample_rate_hz = window.sample_rate_hz
            if window.sqi != 1:
                self.bpm = None
                return None

        self._windows.append(window.samples)
        max_windows = max(1, round(settings.hr_window_s * window.sample_rate_hz / max(1, len(window.samples))))
        while len(self._windows) > max_windows:
            self._windows.popleft()

        if len(self._windows) < max_windows:
            # Still filling after a reset; bpm is already None from the reject.
            return self.bpm

        samples = np.concatenate([np.asarray(w, dtype=np.float64) for w in self._windows])
        self.bpm = estimate_bpm(samples, window.sample_rate_hz)
        return self.bpm
