"""
Pydantic models mirroring docs/API_CONTRACT.md exactly.

These are the shapes that cross a wire boundary: REST responses, WebSocket
frames, and the normalized internal ECG window. Nothing here should drift from
the contract doc -- if a field changes, the doc changes first (see AGENTS.md).
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Mode = Literal["Eco", "Normal", "Watch", "Verify"]
Source = Literal["ble", "serial", "simulator", "none"]
VALID_MODES = ("Eco", "Normal", "Watch", "Verify")


# --- Internal, normalized (API_CONTRACT section 2.3) ------------------------

class EcgWindow(BaseModel):
    """What ble_gateway and simulator both produce; signal_pipeline can't tell
    the difference, which is the point (docs/PLAN.md section 1, decision 1)."""

    device_id: str
    window_start_ts: float
    sample_rate_hz: int
    sqi: int  # 0 = reject, 1 = accept
    samples: list[int]
    # None when the source can't measure it (USB serial: bus-powered, no gauge).
    # Treated as sufficient everywhere, so an unknown battery never forces Eco
    # or blocks an auxiliary wake (docs/API_CONTRACT.md section 2.3).
    battery_pct: Optional[int]
    leads_off: bool = False
    # Std-dev of |acceleration| over the window, m/s^2; None without an
    # accelerometer (docs/API_CONTRACT.md section 2.3).
    motion_ms2: Optional[float] = None


# --- REST response models (API_CONTRACT section 3) --------------------------

class StatusResponse(BaseModel):
    connected: bool
    source: Source
    device_id: Optional[str] = None
    battery_pct: Optional[int] = None
    mode: Mode = "Normal"
    leads_off: bool = False
    sqi: int = 0
    last_packet_ts: Optional[float] = None
    aux_connected: bool = False
    aux_source: str = "simulator"  # "ble" | "simulator"
    aux_state: str = "missing"  # "awake" | "asleep" | "missing"
    aux_next_wake_ts: Optional[float] = None
    aux_check_queued: bool = False
    session_id: Optional[int] = None
    # Human-readable label for whichever RiskModel is actually scoring data
    # right now -- "Stub (heuristic)" until a trained model is configured via
    # GS_MODEL_PATH, or "ONNX: <filename>" once one is. See app/inference.py.
    model: str = "Stub (heuristic)"
    heart_rate_bpm: Optional[float] = None
    motion_ms2: Optional[float] = None
    moving: Optional[bool] = None
    # Seconds of clean signal the model still needs before it can score;
    # 0 when scoring, None when there is no clean signal at all.
    risk_ready_in_s: Optional[float] = None


class RiskCurrentResponse(BaseModel):
    # None until the first window has been scored (no signal yet, leads off,
    # or a fixed-length model still filling its buffer) -- never a fake 0.0.
    score: Optional[float] = None
    mode: Mode
    timestamp: Optional[float] = None
    alerting: bool = False


class RiskHistoryPoint(BaseModel):
    timestamp: float
    score: float
    mode: Mode


class RiskHistoryResponse(BaseModel):
    range: str
    points: list[RiskHistoryPoint]


class EcgLatestResponse(BaseModel):
    window_start_ts: Optional[float] = None
    sample_rate_hz: int = 100
    sqi: int = 0
    samples: list[int] = Field(default_factory=list)


class FootCheckRecord(BaseModel):
    id: int
    timestamp: float
    t_left: Optional[float] = None
    t_right: Optional[float] = None
    delta_t: Optional[float] = None
    valid: bool
    # Backend's verdict on delta_t against the IWGDF reference threshold;
    # None for an invalid check. The UI shows it, never recomputes it.
    elevated: Optional[bool] = None
    next_check_scheduled: Optional[float] = None
    action: Optional[str] = None


class FootHistoryResponse(BaseModel):
    checks: list[FootCheckRecord]
    next_check_scheduled: Optional[float] = None


class FootRequestResponse(BaseModel):
    requested: bool
    request_id: str
    eta_s: int


class ControllerModeRequest(BaseModel):
    # Deliberately `str`, not the `Mode` Literal: API_CONTRACT section 3
    # specifies "400 on an unknown mode string" as an explicit, documented
    # response. Using Literal here would make FastAPI's request validation
    # reject it with a 422 before the route body ever runs, which is a
    # different (undocumented) status code. The route validates membership
    # itself and raises the contract's 400.
    mode: str
    manual: bool = True


class ControllerModeResponse(BaseModel):
    mode: Mode
    manual: bool
    applied_ts: float


class SessionSummaryResponse(BaseModel):
    session_id: int
    started_ts: float
    duration_s: float
    alerts_fired: int
    alerts_acknowledged: int
    windows_total: int
    windows_rejected: int
    mode_time_s: dict[str, float]
    foot_checks: int
    mean_risk: Optional[float] = None
    peak_risk: Optional[float] = None


class AlertAckResponse(BaseModel):
    id: int
    acknowledged: bool


# --- Model management (docs/API_CONTRACT.md section 3.1) --------------------

class ModelInfo(BaseModel):
    filename: str
    size_bytes: int
    uploaded_ts: float
    active: bool


class ModelListResponse(BaseModel):
    models: list[ModelInfo]
    active: str  # "stub" or a filename


class ModelActionResponse(BaseModel):
    ok: bool
    active_model: str  # the resulting RiskModel.name, e.g. "ONNX: risk_model.onnx"
    message: str


# --- WebSocket frame payloads (API_CONTRACT section 4) ----------------------

class AlertPayload(BaseModel):
    id: int
    level: str
    score: float
    timestamp: float
    message: str


class FootCheckResultPayload(BaseModel):
    id: int
    t_left: Optional[float] = None
    t_right: Optional[float] = None
    delta_t: Optional[float] = None
    valid: bool
    elevated: Optional[bool] = None
    timestamp: float
    next_check_scheduled: Optional[float] = None
    action: Optional[str] = None


class RiskUpdatePayload(BaseModel):
    score: float
    mode: Mode
    timestamp: float


# --- Simulator controls (development only, config.gs_enable_sim) -----------

class SimScenarioRequest(BaseModel):
    name: str  # validated against simulator.SCENARIOS by the route (400, not 422)
    duration_s: Optional[float] = Field(default=None, gt=0, le=3600)


class SimSettingsRequest(BaseModel):
    heart_rate_bpm: Optional[float] = Field(default=None, ge=30, le=200)
    battery_pct: Optional[float] = Field(default=None, ge=0, le=100)
    random_artifacts: Optional[bool] = None


class SimFootRequest(BaseModel):
    mode: str  # validated against simulator.FOOT_MODES by the route
