"""
ble_gateway.py -- the real primary node over BLE (docs/API_CONTRACT.md
section 2.1, Phase 7). Produces the same normalized EcgWindow as the simulator
and the serial source, so signal_pipeline/controller/db/api cannot tell them
apart (docs/PLAN.md section 1 decision 1).

Unlike the serial source, the firmware does the decimation and SQI on-device
(SRD 3.1); this module only parses packets and pairs them into windows.

It also closes the loop the other way: it listens on the event bus and writes
`controller_cmd` when the controller's mode changes and `alert_cmd` when an
alert fires, so the device actually hears what the backend decided.

Runs as an asyncio task from app/main.py's lifespan when GS_SOURCE=ble, or
GS_SOURCE=auto once a device has been found.
"""
from __future__ import annotations

import asyncio
import logging
import struct
import time
from typing import Awaitable, Callable, NamedTuple, Optional

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

from app.config import settings
from app.events import bus
from app.models import VALID_MODES, EcgWindow

logger = logging.getLogger("glucosentry.ble")

BATTERY_UNKNOWN = 255  # firmware value for "not measured" (API_CONTRACT 2.1)
WINDOW_SECONDS = 1.0   # firmware sends one window per second
STATUS_LEN = 5         # battery, mode, leads_off, motion(u16)


class DeviceStatus(NamedTuple):
    battery_pct: Optional[int]
    mode: str
    leads_off: bool
    motion_ms2: float


def parse_ecg_data(data: bytes) -> tuple[float, list[int]]:
    """`double` device uptime, then little-endian int16 samples."""
    if len(data) < 8 or (len(data) - 8) % 2:
        raise ValueError(f"malformed ecg_data packet ({len(data)} bytes)")
    (device_ts,) = struct.unpack_from("<d", data, 0)
    n = (len(data) - 8) // 2
    return device_ts, list(struct.unpack_from(f"<{n}h", data, 8))


def parse_device_status(data: bytes) -> DeviceStatus:
    if len(data) < STATUS_LEN:
        raise ValueError(f"malformed device_status packet ({len(data)} bytes)")
    battery, mode, leads_off, motion = struct.unpack_from("<BBBH", data, 0)
    return DeviceStatus(
        battery_pct=None if battery == BATTERY_UNKNOWN else min(battery, 100),
        mode=VALID_MODES[mode] if mode < len(VALID_MODES) else "Normal",
        leads_off=bool(leads_off),
        motion_ms2=motion / 100.0,
    )


def build_window(
    device_id: str, sqi: int, samples: list[int], status: DeviceStatus, window_start_ts: float
) -> EcgWindow:
    return EcgWindow(
        device_id=device_id,
        window_start_ts=window_start_ts,
        sample_rate_hz=settings.ecg_sample_rate_hz,
        # A leads-off window is never accepted, whatever the flag says.
        sqi=0 if status.leads_off else sqi,
        samples=samples,
        battery_pct=status.battery_pct,
        leads_off=status.leads_off,
        motion_ms2=status.motion_ms2,
    )


async def find_device(timeout: float) -> Optional[BLEDevice]:
    """Scan for a node advertising the primary service UUID."""
    service = settings.ble_primary_service_uuid.lower()

    def match(_device, adv) -> bool:
        return service in (u.lower() for u in adv.service_uuids)

    try:
        return await BleakScanner.find_device_by_filter(match, timeout=timeout)
    except (BleakError, OSError) as e:
        # No adapter, adapter off, or BlueZ not running: same outcome as "not found".
        logger.warning("ble: scan failed: %s", e)
        return None


class BleGateway:
    """Connects, subscribes, emits one EcgWindow per firmware window, writes
    commands back. Reconnects forever, like the serial source."""

    def __init__(self, device_id: str = "esp32_primary_01") -> None:
        self.device_id = device_id
        self._sqi = 1
        self._ecg: Optional[tuple[float, list[int]]] = None
        self._last_device_ts: Optional[float] = None
        self._sent_mode: Optional[str] = None
        self._warned_short = False
        self._device_mode: Optional[str] = None

    async def run(
        self,
        on_window: Callable[[EcgWindow], Awaitable[None]],
        on_link_change: Callable[[bool], Awaitable[None]],
        device: Optional[BLEDevice] = None,
    ) -> None:
        try:
            while True:
                if device is None:
                    device = await find_device(settings.gs_ble_scan_timeout_s)
                    if device is None:
                        logger.info("ble: no GlucoSentry node found, rescanning")
                        continue
                try:
                    await self._session(device, on_window, on_link_change)
                except (BleakError, OSError, asyncio.TimeoutError) as e:
                    logger.warning("ble: link to %s lost: %s", device.address, e)
                await on_link_change(False)
                device = None  # rescan: the address can change across firmware resets
                await asyncio.sleep(settings.serial_reconnect_s)
        except asyncio.CancelledError:
            logger.info("ble gateway task cancelled")
            raise

    async def _session(self, device: BLEDevice, on_window, on_link_change) -> None:
        disconnected = asyncio.Event()
        queue: asyncio.Queue[tuple[str, bytes]] = asyncio.Queue(maxsize=64)

        def push(kind: str):
            def handler(_char, data: bytearray) -> None:
                try:
                    queue.put_nowait((kind, bytes(data)))
                except asyncio.QueueFull:
                    pass  # live data: drop rather than block the BLE callback
            return handler

        async with BleakClient(device, disconnected_callback=lambda _c: disconnected.set()) as client:
            # Not logging client.mtu_size: on BlueZ it reads a placeholder 23
            # until queried, even though BlueZ has already negotiated a larger
            # MTU. A too-small MTU shows up as short ecg_data packets instead,
            # which _ingest checks.
            logger.info("ble: connected to %s (%s)", device.name, device.address)
            self._warned_short = False
            await client.start_notify(settings.ble_char_sqi_flag, push("sqi"))
            await client.start_notify(settings.ble_char_ecg_data, push("ecg"))
            await client.start_notify(settings.ble_char_device_status, push("status"))
            await on_link_change(True)
            self._sent_mode = None

            commands = asyncio.create_task(self._forward_commands(client))
            try:
                while not disconnected.is_set():
                    try:
                        kind, data = await asyncio.wait_for(queue.get(), timeout=settings.ble_stall_timeout_s)
                    except asyncio.TimeoutError:
                        raise BleakError(f"no notifications for {settings.ble_stall_timeout_s:.0f}s")
                    window = self._ingest(kind, data)
                    if window is not None:
                        await on_window(window)
            finally:
                commands.cancel()

    def _ingest(self, kind: str, data: bytes) -> Optional[EcgWindow]:
        """Pair sqi_flag + ecg_data + device_status (sent in that order) into
        one window. Returns the window when its status packet arrives."""
        try:
            if kind == "sqi":
                self._sqi = 1 if data and data[0] else 0
            elif kind == "ecg":
                self._ecg = parse_ecg_data(data)
                expected = int(settings.ecg_sample_rate_hz * WINDOW_SECONDS)
                if len(self._ecg[1]) != expected and not self._warned_short:
                    # Almost always an ATT MTU below the 211 the contract requires.
                    logger.warning(
                        "ble: ecg_data carried %d samples, expected %d -- check the negotiated MTU",
                        len(self._ecg[1]), expected,
                    )
                    self._warned_short = True
            elif kind == "status" and self._ecg is not None:
                status = parse_device_status(data)
                if status.mode != self._device_mode:
                    # The firmware echoes the last controller_cmd it received.
                    logger.info("ble: device reports mode %s", status.mode)
                    self._device_mode = status.mode
                device_ts, samples = self._ecg
                self._ecg = None
                if self._last_device_ts is not None and device_ts - self._last_device_ts > 1.5 * WINDOW_SECONDS:
                    logger.info("ble: %.1fs gap in device windows", device_ts - self._last_device_ts)
                self._last_device_ts = device_ts
                # Host arrival time, as for the serial source: the device has no wall clock.
                return build_window(self.device_id, self._sqi, samples, status, time.time() - WINDOW_SECONDS)
        except ValueError as e:
            logger.warning("ble: %s", e)
        return None

    async def _forward_commands(self, client: BleakClient) -> None:
        """Mode changes -> controller_cmd, alerts -> alert_cmd."""
        q = bus.subscribe()
        try:
            while True:
                frame = await q.get()
                try:
                    # status frames too, not just risk_update: those only exist for
                    # accepted windows, so with leads off a manual mode change
                    # would otherwise never reach the device.
                    if frame.type in ("risk_update", "status"):
                        mode = frame.data.get("mode")
                        if mode in VALID_MODES and mode != self._sent_mode:
                            await client.write_gatt_char(
                                settings.ble_char_controller_cmd, bytes([VALID_MODES.index(mode)]), response=False
                            )
                            self._sent_mode = mode
                    elif frame.type == "alert":
                        await client.write_gatt_char(settings.ble_char_alert_cmd, b"\x01", response=False)
                        logger.info("ble: alert_cmd written")
                except BleakError as e:
                    logger.warning("ble: command write failed: %s", e)
        finally:
            bus.unsubscribe(q)
