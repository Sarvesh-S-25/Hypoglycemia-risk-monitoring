"""
aux_gateway.py -- the real auxiliary (foot-check) node over BLE
(docs/API_CONTRACT.md section 2.2).

The node deep-sleeps between check-ins. Each time it wakes (on its own RTC
timer, or its button), this gateway connects, lets app/main.py decide whether
a reading is due (write `wake`, wait for one `foot_temp_result`), and then
writes `sleep` with how long to sleep until the next check-in.

Runs as an asyncio task from app/main.py's lifespan when GS_AUX_SOURCE=ble,
alongside whichever primary source GS_SOURCE selects. The scheduler decides
*when* to call `read()`; this module only knows *how* (AGENTS.md: clinical-
adjacent logic stays in controller.py).
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


WAKE_REASONS = {0: "power_on", 1: "timer", 2: "button"}
NODE_INFO_FORMAT = "<BII"  # wake_reason, boot_count, last_sleep_s
NODE_INFO_LEN = struct.calcsize(NODE_INFO_FORMAT)


class NodeInfo(NamedTuple):
    wake_reason: str
    boot_count: int
    last_sleep_s: int


def parse_node_info(data: bytes) -> NodeInfo:
    if len(data) < NODE_INFO_LEN:
        raise ValueError(f"malformed node_info packet ({len(data)} bytes)")
    reason, boot_count, last_sleep = struct.unpack_from(NODE_INFO_FORMAT, data, 0)
    return NodeInfo(WAKE_REASONS.get(reason, "unknown"), boot_count, last_sleep)


class AuxGateway:
    """Meets the deep-sleeping foot module each time it checks in.

    The node's radio is off in deep sleep, so it cannot be woken on demand.
    Instead it wakes on its own timer (or its button), advertises briefly,
    and this gateway connects. `on_checkin` (app/main.py) then decides
    whether a reading is due, and returns how long the node should sleep
    before checking in again; that is written to the `sleep` characteristic,
    which sends the node back into deep sleep.
    """

    eta_s = settings.aux_eta_s
    rendezvous = True  # checks happen when the node checks in, not on demand

    def __init__(self) -> None:
        self._client: Optional[BleakClient] = None
        self._pending: Optional[asyncio.Future[FootReading]] = None
        self._lock = asyncio.Lock()
        self.node_state = "unknown"  # unknown | awake | asleep
        self.next_wake_ts: Optional[float] = None
        self.last_seen_ts: Optional[float] = None
        self.wake_reason: Optional[str] = None
        self.boot_count: Optional[int] = None
        self.checkins = 0

    @property
    def connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    @property
    def missing(self) -> bool:
        """Not awake, and not asleep on a schedule we know about (never seen,
        or overdue for its check-in)."""
        if self.connected:
            return False
        if self.node_state == "asleep" and self.next_wake_ts is not None:
            return time.time() > self.next_wake_ts + settings.aux_missing_grace_s
        return True

    def status(self) -> dict:
        state = "awake" if self.connected else "missing" if self.missing else "asleep"
        return {
            "state": state,
            "next_wake_ts": self.next_wake_ts if state == "asleep" else None,
            "last_seen_ts": self.last_seen_ts,
            "wake_reason": self.wake_reason,
            "boot_count": self.boot_count,
            "checkins": self.checkins,
        }

    async def run(
        self,
        on_link_change: Callable[[bool], Awaitable[None]],
        on_checkin: Callable[["AuxGateway"], Awaitable[float]],
    ) -> None:
        """Long-running task: wait for each check-in, forever."""
        try:
            while True:
                device = await find_aux_device(settings.gs_ble_scan_timeout_s)
                if device is None:
                    await asyncio.sleep(1.0)  # a failed scan can return instantly
                    continue
                try:
                    await self._session(device, on_link_change, on_checkin)
                except (BleakError, OSError, asyncio.TimeoutError) as e:
                    logger.warning("aux: check-in with %s failed: %s", device.address, e)
                self._client = None
                await on_link_change(False)
        except asyncio.CancelledError:
            logger.info("aux gateway task cancelled")
            raise

    async def _session(self, device: BLEDevice, on_link_change, on_checkin) -> None:
        async with BleakClient(device) as client:
            await client.start_notify(settings.ble_char_foot_temp_result, self._on_result)
            try:
                info = parse_node_info(bytes(await client.read_gatt_char(settings.ble_char_aux_node_info)))
                self.wake_reason, self.boot_count = info.wake_reason, info.boot_count
            except (ValueError, BleakError) as e:
                logger.warning("aux: node_info unreadable: %s", e)
                self.wake_reason = None
            self._client = client
            self.node_state = "awake"
            self.last_seen_ts = time.time()
            self.checkins += 1
            logger.info("aux: foot module checked in (%s, boot %s)", self.wake_reason, self.boot_count)
            await on_link_change(True)

            sleep_s = settings.aux_max_sleep_s
            try:
                sleep_s = await on_checkin(self)
            finally:
                # Always send it back to sleep, even if the check-in logic failed.
                await client.write_gatt_char(
                    settings.ble_char_aux_sleep, struct.pack("<I", int(round(sleep_s))), response=True
                )
                self.node_state = "asleep"
                self.next_wake_ts = time.time() + sleep_s
                self._client = None
                logger.info("aux: foot module sent to sleep for %.0fs", sleep_s)

    def _on_result(self, _char, data: bytearray) -> None:
        try:
            reading = parse_foot_result(bytes(data))
        except ValueError as e:
            logger.warning("aux: %s", e)
            return
        if self._pending is not None and not self._pending.done():
            self._pending.set_result(reading)

    async def read(self) -> FootReading:
        """Wake the sensors on a checked-in node and return its reading.
        Raises AuxUnavailable if it isn't awake or doesn't answer."""
        async with self._lock:
            client = self._client
            if client is None or not client.is_connected:
                raise AuxUnavailable("foot module not awake")
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
