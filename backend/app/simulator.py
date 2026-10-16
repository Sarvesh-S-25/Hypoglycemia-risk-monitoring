"""
simulator.py -- synthetic hardware. Produces the exact same EcgWindow shape the
BLE and serial gateways produce (docs/API_CONTRACT.md section 2.3), so
signal_pipeline/controller/db/api cannot tell them apart (docs/PLAN.md
section 1 decision 1), plus a simulated foot module with the same interface
as app/aux_gateway.AuxGateway.

The ECG is built beat by beat from Gaussian P, Q, R, S and T waves (the
ECGSYN idea, McSharry et al. 2003, without the ODE), with respiratory heart-
rate variability, baseline wander, a little 50 Hz mains and white noise,
scaled to ADS1115 counts. It is a test signal, not a physiological model.

Scenarios reproduce what the real hardware does, so every path can be
demonstrated without a person wearing electrodes (POST /api/sim/scenario):

  normal     clean sinus rhythm
  motion     EMG noise and baseline jumps, accelerometer over the SQI limit
  leads_off  flat output with the AD8232 leads-off flag set
  hypo       a TEST PATTERN ramping in the ECG changes reported during
             hypoglycaemia (tachycardia, QT prolongation, T-wave flattening,
             mild ST depression). Not validated physiology, and whether a
             given model reacts to it is a property of that model.
  spike      triples the amplitude: the induced test signal for the alert
             path with the heuristic stub (SRD acceptance criterion 8)

Runs as an asyncio task from app/main.py's lifespan when GS_SOURCE=simulator
(or auto with no BLE node found).
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np

from app.aux_gateway import AuxUnavailable, FootReading
from app.config import settings
from app.models import EcgWindow

logger = logging.getLogger("glucosentry.simulator")

WINDOW_SECONDS = 1.0  # one window per second, the same cadence as the hardware

SCENARIOS = ("normal", "motion", "leads_off", "hypo", "spike")
DEFAULT_DURATION_S = {"motion": 15.0, "leads_off": 15.0, "hypo": 180.0, "spike": 20.0}

COUNTS_PER_MV = 1200.0  # AD8232 gain into the ADS1115, roughly as on the bench


@dataclass
class _Wave:
    amp_mv: float
    center_s: float  # relative to the R peak
    width_s: float


# A lead-II-like beat at 60 bpm; P/Q/S/T timings scale with the RR interval
# below, the way they shorten at higher rates.
_BEAT = {
    "P": _Wave(0.15, -0.20, 0.025),
    "Q": _Wave(-0.10, -0.035, 0.010),
    "R": _Wave(1.00, 0.0, 0.012),
    "S": _Wave(-0.25, 0.035, 0.010),
    "T": _Wave(0.30, 0.30, 0.055),
}


class Simulator:
    """Synthetic ECG node. Call _next_window() once per second (run() does)."""

    def __init__(self, device_id: str = "esp32_primary_01", sample_rate_hz: int = 100, seed: Optional[int] = None) -> None:
        self.device_id = device_id
        self.sample_rate_hz = sample_rate_hz
        self._rng = np.random.default_rng(seed)
        self._battery_pct = 100.0
        self._running = False
        self._sample_index = 0  # continuous across windows: the beat clock never restarts

        self.base_hr_bpm = 72.0
        self.random_artifacts = True  # ~3% of windows hit by a short motion artifact
        self._scenario = "normal"
        self._scenario_started = 0.0
        self._scenario_until: Optional[float] = None

        self._beats: list[float] = []  # R-peak times (s, simulation clock) still affecting output
        self._next_beat_s = 0.3

    # --- control ----------------------------------------------------------

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    def set_scenario(self, name: str, duration_s: Optional[float] = None) -> None:
        if name not in SCENARIOS:
            raise ValueError(f"scenario must be one of {SCENARIOS}")
        self._scenario = name
        self._scenario_started = time.time()
        if name == "normal":
            self._scenario_until = None
        else:
            self._scenario_until = self._scenario_started + (duration_s or DEFAULT_DURATION_S[name])
        logger.info("simulator: scenario %s for %s", name, "ever" if self._scenario_until is None else f"{duration_s or DEFAULT_DURATION_S[name]:.0f}s")

    def spike(self, duration_s: float = 20.0) -> None:
        """Kept for POST /api/sim/spike and the tests that drive the alert path."""
        self.set_scenario("spike", duration_s)

    def set_battery(self, pct: float) -> None:
        self._battery_pct = float(np.clip(pct, 0, 100))

    @property
    def battery_pct(self) -> int:
        return int(round(self._battery_pct))

    @property
    def scenario(self) -> str:
        if self._scenario_until is not None and time.time() >= self._scenario_until:
            self._scenario = "normal"
            self._scenario_until = None
        return self._scenario

    def state(self) -> dict:
        scenario = self.scenario
        remaining = None if self._scenario_until is None else max(0.0, self._scenario_until - time.time())
        return {
            "running": self._running,
            "scenario": scenario,
            "scenario_remaining_s": None if remaining is None else round(remaining, 1),
            "hypo_progress": round(self._hypo_progress(), 2) if scenario == "hypo" else None,
            "heart_rate_bpm": round(self._current_hr(), 1),
            "base_heart_rate_bpm": self.base_hr_bpm,
            "battery_pct": self.battery_pct,
            "random_artifacts": self.random_artifacts,
        }

    # --- signal -----------------------------------------------------------

    def _hypo_progress(self) -> float:
        """0 -> 1 over the first two thirds of the hypo scenario, then held."""
        if self.scenario != "hypo" or self._scenario_until is None:
            return 0.0
        span = (self._scenario_until - self._scenario_started) * 2 / 3
        return float(np.clip((time.time() - self._scenario_started) / span, 0.0, 1.0))

    def _current_hr(self) -> float:
        return self.base_hr_bpm + 25.0 * self._hypo_progress()  # sympathetic tachycardia in the test pattern

    def _schedule_beats(self, until_s: float) -> None:
        hr = self._current_hr()
        while self._next_beat_s < until_s + 1.0:
            self._beats.append(self._next_beat_s)
            rr = 60.0 / hr
            # Respiratory sinus arrhythmia (0.25 Hz) plus a little randomness.
            rr *= 1 + 0.04 * np.sin(2 * np.pi * 0.25 * self._next_beat_s) + self._rng.normal(0, 0.01)
            self._next_beat_s += rr

    def _ecg_mv(self, t: np.ndarray) -> np.ndarray:
        p = self._hypo_progress()
        hr = self._current_hr()
        rr_scale = np.sqrt(60.0 / hr)  # Bazett-style shortening with rate
        qt_stretch = 1.0 + 0.15 * p   # QT prolongation
        t_amp = 1.0 - 0.6 * p         # T-wave flattening
        st_shift = -0.05 * p          # mild ST depression (mV)

        out = np.zeros_like(t)
        for r in self._beats:
            if r < t[0] - 1.0 or r > t[-1] + 1.0:
                continue
            for name, w in _BEAT.items():
                center = w.center_s * (rr_scale if name in ("P", "T") else 1.0)
                amp = w.amp_mv
                if name == "T":
                    center *= qt_stretch
                    amp *= t_amp
                out += amp * np.exp(-((t - r - center) ** 2) / (2 * w.width_s ** 2))
            # ST segment: between S and T.
            st = (t > r + 0.05) & (t < r + 0.22 * rr_scale * qt_stretch)
            out[st] += st_shift
        self._beats = [r for r in self._beats if r > t[-1] - 1.0]
        return out

    def _next_window(self) -> EcgWindow:
        self._battery_pct = max(0.0, self._battery_pct - 0.014)  # ~2 h from full, visible in a demo
        n = self.sample_rate_hz
        t = (self._sample_index + np.arange(n)) / self.sample_rate_hz
        self._sample_index += n
        self._schedule_beats(t[-1])

        scenario = self.scenario
        ecg = self._ecg_mv(t)
        ecg += 0.05 * np.sin(2 * np.pi * 0.3 * t)          # breathing baseline wander
        ecg += 0.02 * np.sin(2 * np.pi * 50.0 * t + 0.7)    # mains pickup
        ecg += self._rng.normal(0, 0.012, n)                 # amplifier noise

        leads_off = False
        artifact = scenario == "motion" or (
            self.random_artifacts and scenario == "normal" and self._rng.random() < 0.03
        )
        if scenario == "leads_off":
            leads_off = True
            ecg = self._rng.normal(0, 0.002, n)  # rails to a near-flat output
        elif artifact:
            # Electrode movement: EMG burst plus a baseline step.
            ecg += self._rng.normal(0, 0.25, n) + self._rng.uniform(-0.8, 0.8)
        if scenario == "spike":
            ecg *= 3.0

        motion = self._rng.uniform(2.0, 4.0) if artifact else self._rng.uniform(0.02, 0.08)
        sqi = 0 if (leads_off or artifact) else 1

        samples = np.clip(np.round(ecg * COUNTS_PER_MV), -32768, 32767).astype(np.int16).tolist()
        return EcgWindow(
            device_id=self.device_id,
            window_start_ts=time.time(),
            sample_rate_hz=self.sample_rate_hz,
            sqi=sqi,
            samples=samples,
            battery_pct=self.battery_pct,
            leads_off=leads_off,
            motion_ms2=round(float(motion), 3),
        )

    async def run(self, on_window) -> None:
        """Long-running task: one window per WINDOW_SECONDS while running."""
        self.start()
        logger.info("simulator started (device_id=%s)", self.device_id)
        try:
            while True:
                if self._running:
                    await on_window(self._next_window())
                await asyncio.sleep(WINDOW_SECONDS)
        except asyncio.CancelledError:
            logger.info("simulator task cancelled")
            raise


FOOT_MODES = ("random", "normal", "elevated", "invalid", "offline")


class SimulatedFootModule:
    """Stands in for app/aux_gateway.AuxGateway when GS_AUX_SOURCE=simulator:
    same `connected` / `read()` interface, so main.run_foot_check and the
    scheduler run the identical path for simulated and real checks.

    `mode` forces the next results so each scheduler branch (P5) and each
    validity rule (P6) can be demonstrated on demand. "random" is mostly
    normal with occasional elevated and invalid results."""

    eta_s = settings.foot_check_eta_s
    rendezvous = False  # always reachable: read() runs whenever it's asked

    def __init__(self, seed: Optional[int] = None) -> None:
        self.mode = "random"
        self._rng = random.Random(seed)

    @property
    def connected(self) -> bool:
        return self.mode != "offline"

    def set_mode(self, mode: str) -> None:
        if mode not in FOOT_MODES:
            raise ValueError(f"mode must be one of {FOOT_MODES}")
        self.mode = mode
        logger.info("simulated foot module: mode %s", mode)

    def state(self) -> dict:
        return {"mode": self.mode, "connected": self.connected}

    def status(self) -> dict:
        """Same shape as AuxGateway.status(); this one never sleeps."""
        return {
            "state": "awake" if self.connected else "missing",
            "next_wake_ts": None,
            "last_seen_ts": None,
            "wake_reason": None,
            "boot_count": None,
            "checkins": 0,
        }

    async def read(self) -> FootReading:
        if not self.connected:
            raise AuxUnavailable("simulated foot module offline")
        await asyncio.sleep(settings.foot_check_eta_s)

        mode = self.mode
        if mode == "random":
            roll = self._rng.random()
            mode = "invalid" if roll < 0.10 else "elevated" if roll < 0.25 else "normal"
        if mode == "invalid":
            return FootReading(0.0, 0.0, 0.0, False)

        t_left = round(self._rng.uniform(29.5, 32.5), 2)
        offset = self._rng.uniform(2.4, 3.5) if mode == "elevated" else self._rng.uniform(0.1, 1.5)
        t_right = round(t_left + offset * self._rng.choice((1, -1)), 2)
        return FootReading(t_left, t_right, round(t_left - t_right, 2), True)
