"""
serial_gateway.py -- real ESP32 over its USB cable (docs/API_CONTRACT.md
section 2.4). An interim hardware source until the BLE firmware and
ble_gateway exist (Phase 7): it produces the same normalized EcgWindow as the
simulator, so signal_pipeline/controller/db/api cannot tell them apart
(docs/PLAN.md section 1 decision 1).

The firmware streams raw 250 Hz samples rather than filtered, decimated
windows, so the decimation and the MPU-based SQI gating that SRD 3.1 places
on-device happen here instead. When the BLE firmware takes that work back on
the device, this module is the only thing that needs to go.

Runs as an asyncio task started from app/main.py's lifespan when
GS_SOURCE=serial. Blocking serial reads run in a worker thread, one call per
window, so the event loop is never held up by the port.
"""
from __future__ import annotations

import asyncio
import glob
import logging
import time
from typing import Awaitable, Callable, NamedTuple, Optional

import numpy as np
import serial

from app.config import settings
from app.models import EcgWindow

logger = logging.getLogger("glucosentry.serial")

# Consecutive empty 1 s reads before an open port is treated as dead -- covers
# a board that stopped streaming (crashed, or held in reset) without the OS
# removing the device node.
STALL_READS = 3

WINDOW_SECONDS = 1.0  # same cadence as the simulator (~1 ws frame/s, API_CONTRACT section 4)


class Sample(NamedTuple):
    ecg_mv: float
    leads_off: bool
    ax: float
    ay: float
    az: float


def parse_line(line: bytes) -> Optional[Sample]:
    """One firmware line -> Sample, or None for boot messages / partial lines."""
    parts = line.strip().split(b",")
    if len(parts) != 5:
        return None
    try:
        ecg, lo, ax, ay, az = (float(p) for p in parts)
    except ValueError:
        return None
    return Sample(ecg, lo != 0, ax, ay, az)


def build_window(samples: list[Sample], device_id: str, window_start_ts: float) -> EcgWindow:
    """One window of raw device-rate samples -> the normalized EcgWindow.

    Decimation: a 3-tap moving average first (first null at 83 Hz, well above
    ECG content but enough to stop the 250 -> 100 Hz resample aliasing
    high-frequency noise down into the band), then linear interpolation onto
    the 100 Hz grid. The ratio is 2.5, so plain every-Nth-sample picking
    isn't possible.
    """
    device_rate = settings.serial_device_rate_hz
    out_rate = settings.ecg_sample_rate_hz

    ecg_mv = np.array([s.ecg_mv for s in samples], dtype=np.float64)
    counts = ecg_mv / settings.serial_mv_per_lsb
    smoothed = np.convolve(counts, np.ones(3) / 3, mode="same")

    duration_s = len(samples) / device_rate
    t_in = np.arange(len(samples)) / device_rate
    t_out = np.arange(int(round(duration_s * out_rate))) / out_rate
    decimated = np.interp(t_out, t_in, smoothed)
    decimated = np.clip(np.round(decimated), -32768, 32767).astype(np.int16)

    leads_off = any(s.leads_off for s in samples)
    accel_mag = np.array([np.sqrt(s.ax ** 2 + s.ay ** 2 + s.az ** 2) for s in samples])
    motion_ms2 = float(np.std(accel_mag))
    moving = motion_ms2 > settings.serial_motion_sqi_threshold_ms2

    return EcgWindow(
        device_id=device_id,
        window_start_ts=window_start_ts,
        sample_rate_hz=out_rate,
        sqi=0 if (leads_off or moving) else 1,
        samples=decimated.tolist(),
        battery_pct=None,  # bus-powered over USB; no battery gauge to read
        leads_off=leads_off,
        motion_ms2=round(motion_ms2, 3),
    )


def find_port() -> Optional[str]:
    """ESP32 dev boards enumerate as ttyACM (native USB / CH343) or ttyUSB
    (CP210x / CH340). First match wins; set GS_SERIAL_PORT to disambiguate."""
    if settings.gs_serial_port:
        return settings.gs_serial_port
    for pattern in ("/dev/ttyACM*", "/dev/ttyUSB*"):
        ports = sorted(glob.glob(pattern))
        if ports:
            return ports[0]
    return None


class SerialGateway:
    """Reads the firmware's line stream and emits one EcgWindow per second of
    samples. Reconnects forever: unplugging the board flips the dashboard to
    disconnected rather than killing the backend."""

    def __init__(self, device_id: str = "esp32_primary_01") -> None:
        self.device_id = device_id
        self.port: Optional[str] = None

    def _read_window(self, ser: serial.Serial) -> list[Sample]:
        """Blocking: collect one window's worth of samples. Runs in a worker thread."""
        n = int(settings.serial_device_rate_hz * WINDOW_SECONDS)
        samples: list[Sample] = []
        empty_reads = 0
        while len(samples) < n:
            line = ser.readline()
            if not line:
                empty_reads += 1
                if empty_reads >= STALL_READS:
                    raise serial.SerialException(f"no data from {ser.port} for {STALL_READS}s")
                continue
            empty_reads = 0
            sample = parse_line(line)
            if sample is not None:
                samples.append(sample)
        return samples

    async def run(
        self,
        on_window: Callable[[EcgWindow], Awaitable[None]],
        on_link_change: Callable[[bool], Awaitable[None]],
    ) -> None:
        """Long-running task. on_window gets each EcgWindow; on_link_change
        gets True/False as the port opens or is lost."""
        try:
            while True:
                self.port = find_port()
                if self.port is None:
                    logger.info("serial: no ESP32 port found, retrying in %.0fs", settings.serial_reconnect_s)
                    await asyncio.sleep(settings.serial_reconnect_s)
                    continue

                try:
                    ser = await asyncio.to_thread(serial.Serial, self.port, settings.gs_serial_baud, timeout=1)
                except serial.SerialException as e:
                    logger.warning("serial: cannot open %s: %s", self.port, e)
                    await asyncio.sleep(settings.serial_reconnect_s)
                    continue

                logger.info("serial: connected to %s at %d baud", self.port, settings.gs_serial_baud)
                try:
                    first = True
                    while True:
                        samples = await asyncio.to_thread(self._read_window, ser)
                        if first:
                            await on_link_change(True)
                            first = False
                        # Stamp with arrival time minus the window length: the
                        # firmware has no wall clock, and USB latency (~ms) is
                        # far below the 1 s window resolution.
                        await on_window(build_window(samples, self.device_id, time.time() - WINDOW_SECONDS))
                except serial.SerialException as e:
                    logger.warning("serial: link to %s lost: %s", self.port, e)
                finally:
                    ser.close()
                await on_link_change(False)
                await asyncio.sleep(settings.serial_reconnect_s)
        except asyncio.CancelledError:
            logger.info("serial gateway task cancelled")
            raise
