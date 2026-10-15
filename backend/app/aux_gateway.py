"""
aux_gateway.py -- the real auxiliary (foot-check) node over BLE
(docs/API_CONTRACT.md section 2.2).

Holds a connection to the node whenever it is in range, so `aux_connected`
in the status frame reflects reality, and performs the wake -> bilateral
reading exchange on request: write `wake`, then wait for one
`foot_temp_result` notification.

Runs as an asyncio task from app/main.py's lifespan when GS_AUX_SOURCE=ble,
alongside whichever primary source GS_SOURCE selects. The scheduler decides
*when* to call `read()`; this module only knows *how* (AGENTS.md: clinical-
adjacent logic stays in controller.py).
"""
from __future__ import annotations

import asyncio
import logging
import struct
from typing import Awaitable, Callable, NamedTuple, Optional

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

from app.config import settings

logger = logging.getLogger("glucosentry.aux")

RESULT_FORMAT = "<fffB"  # t_left, t_right, delta (deg C), valid
RESULT_LEN = struct.calcsize(RESULT_FORMAT)


class FootReading(NamedTuple):
    t_left: float
    t_right: float
    delta: float
    valid: bool


class AuxUnavailable(Exception):
    """No foot module connected, or it did not answer a wake in time."""


def parse_foot_result(data: bytes) -> FootReading:
    if len(data) < RESULT_LEN:
        raise ValueError(f"malformed foot_temp_result packet ({len(data)} bytes)")
    t_left, t_right, delta, valid = struct.unpack_from(RESULT_FORMAT, data, 0)
    return FootReading(round(t_left, 2), round(t_right, 2), round(delta, 2), bool(valid))


async def find_aux_device(timeout: float) -> Optional[BLEDevice]:
    service = settings.ble_aux_service_uuid.lower()

    def match(_device, adv) -> bool:
        return service in (u.lower() for u in adv.service_uuids)

    try:
        return await BleakScanner.find_device_by_filter(match, timeout=timeout)
    except (BleakError, OSError) as e:
        logger.warning("aux: scan failed: %s", e)
        return None


class AuxGateway:
    eta_s = settings.aux_eta_s  # what POST /api/foot/request tells the UI to expect

    def __init__(self) -> None:
        self._client: Optional[BleakClient] = None
        self._pending: Optional[asyncio.Future[FootReading]] = None
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    async def run(self, on_link_change: Callable[[bool], Awaitable[None]]) -> None:
        """Long-running task: find, connect, hold the link, reconnect forever."""
        try:
            while True:
                device = await find_aux_device(settings.gs_ble_scan_timeout_s)
                if device is None:
                    logger.info("aux: no foot module found, rescanning")
                    await asyncio.sleep(settings.serial_reconnect_s)
                    continue
                try:
                    await self._session(device, on_link_change)
                except (BleakError, OSError, asyncio.TimeoutError) as e:
                    logger.warning("aux: link to %s lost: %s", device.address, e)
                self._client = None
                await on_link_change(False)
                await asyncio.sleep(settings.serial_reconnect_s)
        except asyncio.CancelledError:
            logger.info("aux gateway task cancelled")
            raise

    async def _session(self, device: BLEDevice, on_link_change) -> None:
        disconnected = asyncio.Event()
        async with BleakClient(device, disconnected_callback=lambda _c: disconnected.set()) as client:
            logger.info("aux: connected to %s (%s)", device.name, device.address)
            await client.start_notify(settings.ble_char_foot_temp_result, self._on_result)
            self._client = client
            await on_link_change(True)
            await disconnected.wait()

    def _on_result(self, _char, data: bytearray) -> None:
        try:
            reading = parse_foot_result(bytes(data))
        except ValueError as e:
            logger.warning("aux: %s", e)
            return
        if self._pending is not None and not self._pending.done():
            self._pending.set_result(reading)

    async def read(self) -> FootReading:
        """Wake the node and return its bilateral reading.
        Raises AuxUnavailable if it isn't connected or doesn't answer."""
        async with self._lock:
            client = self._client
            if client is None or not client.is_connected:
                raise AuxUnavailable("foot module not connected")
            self._pending = asyncio.get_running_loop().create_future()
            try:
                await client.write_gatt_char(settings.ble_char_aux_wake, b"\x01", response=True)
                return await asyncio.wait_for(self._pending, timeout=settings.aux_result_timeout_s)
            except asyncio.TimeoutError:
                raise AuxUnavailable(f"no result within {settings.aux_result_timeout_s:.0f}s")
            except BleakError as e:
                raise AuxUnavailable(f"wake write failed: {e}")
            finally:
                self._pending = None
