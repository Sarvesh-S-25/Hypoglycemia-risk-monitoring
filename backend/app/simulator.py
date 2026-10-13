"""
simulator.py -- synthetic hardware source. Produces the exact same EcgWindow
shape ble_gateway.py will produce from real hardware (docs/API_CONTRACT.md
section 2.3), so signal_pipeline/controller/db/api cannot tell them apart
(docs/PLAN.md section 1 decision 1). This is what lets the frontend and
backend be built, demonstrated and tested before firmware exists (SRD build
step 6).

Runs as an asyncio task started from app/main.py's lifespan when
GS_SOURCE=simulator (or GS_SOURCE=auto and no BLE device was found).
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

import numpy as np

from app.models import EcgWindow

logger = logging.getLogger("glucosentry.simulator")

WINDOW_SECONDS = 1.0  # one window "arrives" per second in sim time, matching
# the ~1 msg/s cadence documented in docs/API_CONTRACT.md section 4 notes
# (real windows are 30-60s of ECG, decimated and delivered less often; the
# simulator ticks faster so a demo doesn't require waiting minutes to see
# movement, which is a deliberate, documented departure from realism).


class Simulator:
    """Generates a synthetic ECG stream: a normal sinus-like waveform most of
    the time, occasional SQI dropouts (simulating motion artifact), slow
    battery drain, and an on-demand spike() for demonstrating the sustained-
    risk alert path per SRD acceptance criterion 8: "demonstrable via induced
    test signal, not real hypoglycemia."
    """

    def __init__(self, device_id: str = "esp32_primary_01", sample_rate_hz: int = 100, seed: Optional[int] = None) -> None:
        self.device_id = device_id
        self.sample_rate_hz = sample_rate_hz
        self._rng = np.random.default_rng(seed)
        self._battery_pct = 100.0
        self._running = False
        self._spike_until: float = 0.0
        self._t = 0.0  # running phase accumulator for the synthetic waveform
        self._sample_index = 0  # continuous across windows, so the beat clock never restarts

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    def spike(self, duration_s: float = 20.0) -> None:
        """Drive synthetic risk upward for duration_s so the controller's
        Verify-mode sustained-risk confirmation, and then the alert, can be
        exercised on demand (POST /api/sim/spike, dev-only per config.gs_enable_sim)."""
        self._spike_until = time.time() + duration_s
        logger.info("simulator: spike triggered for %.1fs", duration_s)

    @property
    def running(self) -> bool:
        return self._running

    @property
    def battery_pct(self) -> int:
        return int(round(self._battery_pct))

    def _drain_battery(self) -> None:
        # ~100% -> 0% over roughly 2 hours of continuous Normal-mode sim time,
        # just fast enough to see the number move in a demo without being
        # silly. Real battery-life measurement (SRD 6) happens on hardware.
        self._battery_pct = max(0.0, self._battery_pct - 0.014)

    def _next_window(self) -> EcgWindow:
        self._drain_battery()
        n = self.sample_rate_hz  # one second of samples per window tick

        spiking = time.time() < self._spike_until

        # Synthetic "QRS-ish" waveform: a base sinus rhythm plus periodic sharp
        # peaks. Not a physiological model -- it exists only to give the
        # canvas waveform and the stub risk model something plausible to react to.
        t = np.arange(n) / self.sample_rate_hz + self._t
        heart_rate_hz = 1.2  # ~72 bpm
        base = 0.15 * np.sin(2 * np.pi * heart_rate_hz * t)
        qrs = np.zeros(n)
        beat_period = self.sample_rate_hz / heart_rate_hz
        # The phase must come from the global sample index: computing it from
        # `i` restarted the rhythm every window, inserting an extra beat at
        # each boundary (72 bpm intended, a refractory-filtered 60 bpm and a
        # visibly doubled beat once per second in practice). Found by
        # tests/test_heart_rate.py.
        for i in range(n):
            phase = (self._sample_index + i) % beat_period
            if phase < 3:
                qrs[i] = 1.0 * np.exp(-((phase - 1) ** 2) / 0.5)

        amplitude = 3.0 if spiking else 1.0
        noise = self._rng.normal(0, 0.05, n)
        waveform = amplitude * (base + qrs) + noise
        samples = (waveform * 1000).astype(np.int16).tolist()  # scale to int16 range, mirrors ADC counts

        self._t += n / self.sample_rate_hz
        self._sample_index += n

        # Occasional SQI dropout to exercise the reject path (~3% of windows),
        # simulating motion artifact per SRD 3.1's MPU6050-based gating.
        sqi = 0 if self._rng.random() < 0.03 else 1

        return EcgWindow(
            device_id=self.device_id,
            window_start_ts=time.time(),
            sample_rate_hz=self.sample_rate_hz,
            sqi=sqi,
            samples=samples,
            battery_pct=self.battery_pct,
        )

    async def run(self, on_window) -> None:
        """Long-running task: emits one window per WINDOW_SECONDS while
        running. on_window is an async callback taking an EcgWindow."""
        self.start()
        logger.info("simulator started (device_id=%s)", self.device_id)
        try:
            while True:
                if self._running:
                    window = self._next_window()
                    await on_window(window)
                await asyncio.sleep(WINDOW_SECONDS)
        except asyncio.CancelledError:
            logger.info("simulator task cancelled")
            raise
