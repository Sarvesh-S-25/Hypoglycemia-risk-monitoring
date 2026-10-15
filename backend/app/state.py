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
from typing import Optional, Union

from app.aux_gateway import AuxGateway
from app.controller import Controller
from app.heart_rate import HeartRateEstimator
from app.db import Database
from app.inference import RiskModel
from app.models import EcgWindow
from app.signal_pipeline import SignalPipeline
from app.simulator import SimulatedFootModule, Simulator


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
    # The real AuxGateway (GS_AUX_SOURCE=ble) or a SimulatedFootModule; both
    # expose connected / eta_s / read(). None only in tests that build state by hand.
    aux_gateway: Optional[Union[AuxGateway, SimulatedFootModule]] = None

    heart_rate: HeartRateEstimator = field(default_factory=HeartRateEstimator)

    # Foot-check scheduling/demo state.
    foot_check_busy: bool = False
    next_foot_check_scheduled: Optional[float] = None
    last_foot_check: Optional[dict] = None  # the last foot_check_result payload

    # Session counters for the engineering view (GET /api/diagnostics).
    windows_total: int = 0
    windows_accepted: int = 0
    rejected_leads_off: int = 0
    rejected_motion: int = 0
    last_inference_ms: Optional[float] = None

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
            "aux_source": settings.gs_aux_source,
            "session_id": self.session_id,
            "model": self.model.name,
            "heart_rate_bpm": self.heart_rate.bpm,
            "motion_ms2": motion,
            "moving": None if motion is None else motion > settings.serial_motion_sqi_threshold_ms2,
            "risk_ready_in_s": self.risk_ready_in_s(),
        }

    def risk_ready_in_s(self) -> Optional[float]:
        """Seconds of clean signal still needed before the model can score:
        0 when scoring, None when it can't even start (no clean signal)."""
        ctx = self.model.context()
        if self.last_window is None or self.last_window.sqi != 1:
            return None
        return round(max(0.0, ctx["needed_s"] - ctx["buffered_s"]), 1)

    def diagnostics_dict(self) -> dict:
        """Everything the backend is using to make its decisions, for the
        engineering view (docs/API_CONTRACT.md GET /api/diagnostics)."""
        import numpy as np
        from app.config import settings

        w = self.last_window
        last_window = None
        if w is not None and w.samples:
            arr = np.asarray(w.samples, dtype=np.float64)
            last_window = {
                "n_samples": int(arr.size),
                "min": int(arr.min()),
                "max": int(arr.max()),
                "ptp": int(np.ptp(arr)),
                "mean": round(float(arr.mean()), 1),
            }

        c = self.controller.state
        cooldown_remaining = None
        if c.last_alert_ts is not None:
            cooldown_remaining = max(0.0, settings.alert_cooldown_s - (time.time() - c.last_alert_ts))

        return {
            "timestamp": time.time(),
            "link": {
                "source": self.source,
                "connected": self.device_connected,
                "last_packet_ts": w.window_start_ts if w else None,
                "battery_pct": w.battery_pct if w else None,
                "aux_source": settings.gs_aux_source,
                "aux_connected": self.aux_connected,
            },
            "pipeline": {
                "sample_rate_hz": settings.ecg_sample_rate_hz,
                "windows_total": self.windows_total,
                "windows_accepted": self.windows_accepted,
                "rejected_leads_off": self.rejected_leads_off,
                "rejected_motion": self.rejected_motion,
                "sqi": w.sqi if w else None,
                "leads_off": w.leads_off if w else None,
                "motion_ms2": w.motion_ms2 if w else None,
                "motion_threshold_ms2": settings.serial_motion_sqi_threshold_ms2,
                "last_window": last_window,
                "heart_rate_bpm": self.heart_rate.bpm,
            },
            "model": {
                "name": self.model.name,
                **self.model.context(),
                "last_score": self.last_risk_score,
                "last_score_ts": self.last_risk_ts,
                "last_inference_ms": self.last_inference_ms,
            },
            "controller": {
                "mode": c.mode,
                "manual_mode": c.manual_mode,
                "risk_low": settings.risk_low,
                "risk_elevated": settings.risk_elevated,
                "risk_alert": settings.risk_alert,
                "verify_confirm_count": c.verify_confirm_count,
                "confirm_windows": settings.confirm_windows,
                "alert_cooldown_s": settings.alert_cooldown_s,
                "cooldown_remaining_s": cooldown_remaining,
                "recent_scores": [round(x, 3) for x in c.recent_scores],
                "alerting": self.last_alerting,
            },
            "foot": {
                "source": settings.gs_aux_source,
                "connected": self.aux_connected,
                "busy": self.foot_check_busy,
                "next_check_scheduled": self.next_foot_check_scheduled,
                "elevated_threshold_c": settings.foot_check_elevated_threshold_c,
                "normal_interval_s": settings.foot_check_normal_interval_s,
                "elevated_interval_s": settings.foot_check_elevated_interval_s,
                "invalid_retry_s": settings.foot_check_invalid_retry_s,
                "battery_min_pct": settings.battery_aux_min,
                "result_timeout_s": settings.aux_result_timeout_s,
                "last_check": self.last_foot_check,
            },
            # Present only when something is simulated, so the engineering
            # view can show the simulator controls.
            "simulator": {
                "ecg": self.simulator.state() if self.simulator is not None else None,
                "foot": self.aux_gateway.state() if isinstance(self.aux_gateway, SimulatedFootModule) else None,
                "enabled": settings.gs_enable_sim,
            },
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
