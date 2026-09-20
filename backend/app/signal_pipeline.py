"""
signal_pipeline.py -- receives normalized ECG windows, confirms SQI, reshapes
for model input (SRD 4.1). Filtering and SQI *computation* already happened
on-device (SRD 3.1); this module only confirms the flag the firmware already
set and prepares the window for inference.py.

Also owns the in-memory ring buffer backing GET /api/ecg/latest, since raw
samples are deliberately not persisted to SQLite (docs/PLAN.md section 7 item 4).
"""
from __future__ import annotations

import logging
from collections import deque
from typing import Optional

import numpy as np

from app.config import settings
from app.models import EcgWindow

logger = logging.getLogger("glucosentry.pipeline")


class SignalPipeline:
    """Confirms SQI, keeps a short ring buffer of recent windows for
    /api/ecg/latest, and reshapes accepted windows for RiskModel.predict()."""

    def __init__(self, ring_size: int = 20) -> None:
        # Ring buffer holds recent windows (accepted and rejected) so the
        # dashboard's "latest" endpoint and the live waveform have something
        # to show even across a brief WebSocket reconnect.
        self._ring: deque[EcgWindow] = deque(maxlen=ring_size)

    def ingest(self, window: EcgWindow) -> Optional[np.ndarray]:
        """Confirm SQI and return a model-ready array, or None if rejected.

        SRD 3.1 says the firmware already "reject[s]/flag[s] windows below SQI
        threshold -- do not transmit them," so in principle every window that
        arrives here has sqi=1. We still gate on it defensively: the
        simulator can emit sqi=0 windows to exercise this path, and a firmware
        bug should not silently corrupt inference input.
        """
        self._ring.append(window)

        if window.sqi != 1:
            logger.debug("window at %.3f rejected (sqi=%d)", window.window_start_ts, window.sqi)
            return None

        if not window.samples:
            logger.warning("accepted window at %.3f has no samples", window.window_start_ts)
            return None

        return self._reshape(window.samples)

    def _reshape(self, samples: list[int]) -> np.ndarray:
        """(1, 1, N) float32: baseline-removed, then scaled by a FIXED
        reference divisor (config.ecg_normalize_scale) rather than the
        window's own standard deviation.

        Per-window z-score normalization (divide by that window's std) was
        tried first and is deliberately *not* used: it makes the result
        scale-invariant to the window's own amplitude, which erases the exact
        signal an amplitude excursion needs to be visible as (verified against
        simulator.spike() -- with self-normalization the risk score did not
        move at all when the induced signal tripled in amplitude). Baseline
        removal (subtract mean) still happens, since the on-device filtering
        already removes DC drift and this is a cheap defensive no-op.
        """
        arr = np.asarray(samples, dtype=np.float32)
        arr = (arr - arr.mean()) / settings.ecg_normalize_scale
        return arr.reshape(1, 1, -1)

    def latest(self) -> Optional[EcgWindow]:
        """Most recent window regardless of SQI, for GET /api/ecg/latest --
        the dashboard should be able to show *something*, even a flagged
        window, rather than nothing."""
        return self._ring[-1] if self._ring else None
