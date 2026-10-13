"""
AppState -- the single object holding every long-lived piece the API layer
needs (db, pipeline, model, controller, current session, live device
snapshot). Created once in app/main.py's lifespan and attached to
`app.state.gs`; routes and the WebSocket handler read it from `request.app`.

Kept as one plain object rather than scattering module-level globals so
tests can construct a fresh one per test without import-order headaches.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from app.controller import Controller
from app.heart_rate import HeartRateEstimator
from app.db import Database
from app.inference import RiskModel
from app.models import EcgWindow
from app.signal_pipeline import SignalPipeline
from app.simulator import Simulator


@dataclass
class AppState:
    db: Database
    pipeline: SignalPipeline
    model: RiskModel
    controller: Controller
    session_id: int
    simulator: Optional[Simulator] = None
    source: str = "simulator"  # "ble" | "serial" | "simulator" | "none"

    # Live snapshot, updated by the source-consuming task, read by GET
    # /api/status and the WebSocket's "hello"/"status" frames.
    last_window: Optional[EcgWindow] = None
    last_risk_score: Optional[float] = None
    last_risk_ts: Optional[float] = None
    last_alerting: bool = False
    device_connected: bool = False
    aux_connected: bool = False

    heart_rate: HeartRateEstimator = field(default_factory=HeartRateEstimator)

    # Foot-check scheduling/demo state.
    foot_check_busy: bool = False
    next_foot_check_scheduled: Optional[float] = None

    # WebSocket status-frame throttling (docs/API_CONTRACT.md section 4:
    # "at most once per second, and only when something actually changed").
    _last_status_snapshot: Optional[dict] = field(default=None, repr=False)
    _last_status_push_ts: float = field(default=0.0, repr=False)

    def status_dict(self) -> dict:
        from app.config import settings

        motion = self.last_window.motion_ms2 if self.last_window else None
        return {
            "connected": self.device_connected,
            "source": self.source if self.device_connected else "none",
            "device_id": self.last_window.device_id if self.last_window else None,
            "battery_pct": self.last_window.battery_pct if self.last_window else None,
            "mode": self.controller.state.mode,
            # Real AD8232 state from the serial source; always False from the
            # simulator, which doesn't model it.
            "leads_off": self.last_window.leads_off if self.last_window else False,
            "sqi": self.last_window.sqi if self.last_window else 0,
            "last_packet_ts": self.last_window.window_start_ts if self.last_window else None,
            "aux_connected": self.aux_connected,
            "session_id": self.session_id,
            "model": self.model.name,
            "heart_rate_bpm": self.heart_rate.bpm,
            "motion_ms2": motion,
            "moving": None if motion is None else motion > settings.serial_motion_sqi_threshold_ms2,
        }

    def status_changed(self) -> bool:
        """Throttle gate for the WebSocket's `status` frame: fire at most
        once per second, and only if the snapshot actually differs."""
        now = time.time()
        from app.config import settings

        if now - self._last_status_push_ts < settings.status_push_min_interval_s:
            return False
        snapshot = self.status_dict()
        if snapshot == self._last_status_snapshot:
            return False
        self._last_status_snapshot = snapshot
        self._last_status_push_ts = now
        return True
