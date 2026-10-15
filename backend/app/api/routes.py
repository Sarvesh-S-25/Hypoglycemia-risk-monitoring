"""
Every REST endpoint in docs/API_CONTRACT.md section 3. Routes are thin: they
validate input, call into app/db.py or app/controller.py, and shape the
response per the contract's Pydantic models. No SQL here (AGENTS.md).
"""
from __future__ import annotations

import csv
import io
import logging
import time
import uuid
from typing import Optional

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from app import model_registry
from app.config import settings
from app.controller import is_foot_check_elevated, schedule_next_foot_check
from app.simulator import FOOT_MODES, SCENARIOS, SimulatedFootModule
from app.events import bus
from app.inference import OnnxRiskModel, StubRiskModel, load_risk_model
from app.models import (
    VALID_MODES,
    AlertAckResponse,
    ControllerModeRequest,
    ControllerModeResponse,
    EcgLatestResponse,
    FootCheckRecord,
    FootHistoryResponse,
    FootRequestResponse,
    ModelActionResponse,
    ModelInfo,
    ModelListResponse,
    RiskCurrentResponse,
    RiskHistoryPoint,
    RiskHistoryResponse,
    SessionSummaryResponse,
    SimFootRequest,
    SimScenarioRequest,
    SimSettingsRequest,
    StatusResponse,
)

logger = logging.getLogger("glucosentry.routes")

router = APIRouter(prefix="/api")

RANGE_SECONDS = {"15m": 15 * 60, "1h": 3600, "6h": 6 * 3600, "24h": 24 * 3600}


def gs(request: Request):
    return request.app.state.gs


@router.get("/status", response_model=StatusResponse)
async def get_status(request: Request) -> StatusResponse:
    return StatusResponse(**gs(request).status_dict())


@router.get("/risk/current", response_model=RiskCurrentResponse)
async def get_risk_current(request: Request) -> RiskCurrentResponse:
    state = gs(request)
    return RiskCurrentResponse(
        score=state.last_risk_score,
        mode=state.controller.state.mode,
        timestamp=state.last_risk_ts,
        alerting=state.last_alerting,
    )


@router.get("/diagnostics")
async def get_diagnostics(request: Request) -> dict:
    """The backend's working state -- counters, the model's buffer, the
    controller's thresholds and confirmation count, the foot scheduler -- for
    the engineering view. Read-only; nothing here is a second decision path."""
    return gs(request).diagnostics_dict()


@router.get("/risk/history", response_model=RiskHistoryResponse)
async def get_risk_history(request: Request, range: str = "1h") -> RiskHistoryResponse:
    if range not in RANGE_SECONDS:
        raise HTTPException(status_code=400, detail=f"range must be one of {list(RANGE_SECONDS)}")
    state = gs(request)
    since_ts = time.time() - RANGE_SECONDS[range]
    rows = await state.db.risk_history(state.session_id, since_ts)
    points = [
        RiskHistoryPoint(timestamp=r["timestamp"], score=r["risk_score"], mode=r["mode"]) for r in rows
    ]
    return RiskHistoryResponse(range=range, points=points)


@router.get("/ecg/latest", response_model=EcgLatestResponse)
async def get_ecg_latest(request: Request) -> EcgLatestResponse:
    state = gs(request)
    window = state.pipeline.latest()
    if window is None:
        return EcgLatestResponse(samples=[], sqi=0, window_start_ts=None, sample_rate_hz=settings.ecg_sample_rate_hz)
    return EcgLatestResponse(
        window_start_ts=window.window_start_ts,
        sample_rate_hz=window.sample_rate_hz,
        sqi=window.sqi,
        samples=window.samples,
    )


@router.get("/foot/history", response_model=FootHistoryResponse)
async def get_foot_history(request: Request, limit: int = 50) -> FootHistoryResponse:
    state = gs(request)
    rows = await state.db.foot_history(state.session_id, limit=limit)
    checks = [
        FootCheckRecord(
            id=r["id"],
            timestamp=r["timestamp"],
            t_left=r["t_left"],
            t_right=r["t_right"],
            delta_t=r["delta_t"],
            valid=bool(r["valid"]),
            elevated=is_foot_check_elevated(r["delta_t"]),
            next_check_scheduled=r["next_check_scheduled"],
            action=r["action"],
        )
        for r in rows
    ]
    return FootHistoryResponse(checks=checks, next_check_scheduled=state.next_foot_check_scheduled)


@router.post("/foot/request", response_model=FootRequestResponse, status_code=202)
async def post_foot_request(request: Request) -> FootRequestResponse:
    """Manually trigger an auxiliary foot check (SRD 5.1 demo/testing button).

    Responds immediately; the result arrives later over the WebSocket as a
    `foot_check_result` frame, because the real wake-to-result cycle takes
    several seconds (docs/API_CONTRACT.md section 3). In simulator mode, the
    result comes from app/simulator.SimulatedFootModule; with GS_AUX_SOURCE=ble
    the real foot module is woken via app/aux_gateway.py. Same path for both.
    """
    state = gs(request)

    if state.foot_check_busy:
        raise HTTPException(status_code=409, detail="auxiliary node busy")

    # None = unmeasured (USB bus-powered); treated as sufficient, per API_CONTRACT 2.3.
    battery_pct = state.last_window.battery_pct if state.last_window else None
    if battery_pct is not None and battery_pct < settings.battery_aux_min:
        raise HTTPException(status_code=503, detail="battery insufficient for auxiliary wake")

    if state.aux_gateway is not None and not state.aux_gateway.connected:
        raise HTTPException(status_code=503, detail="foot module not connected")

    state.foot_check_busy = True
    request_id = f"fc_{uuid.uuid4().hex[:8]}"

    # Import here (not at module top) to avoid a circular import: main.py
    # imports this router, and the foot-check runner lives in main.py because
    # it needs the same AppState/event-bus wiring the source task uses.
    from app.main import run_foot_check

    import asyncio

    asyncio.create_task(run_foot_check(request.app, request_id))

    eta_s = state.aux_gateway.eta_s if state.aux_gateway is not None else settings.foot_check_eta_s
    return FootRequestResponse(requested=True, request_id=request_id, eta_s=eta_s)


@router.post("/controller/mode", response_model=ControllerModeResponse)
async def post_controller_mode(request: Request, body: ControllerModeRequest) -> ControllerModeResponse:
    if body.manual and body.mode not in VALID_MODES:
        raise HTTPException(status_code=400, detail=f"mode must be one of {VALID_MODES}")

    state = gs(request)
    state.controller.set_manual_mode(body.mode if body.manual else None)
    applied_ts = time.time()
    bus.publish("status", state.status_dict())
    return ControllerModeResponse(
        mode=state.controller.state.mode, manual=body.manual, applied_ts=applied_ts
    )


@router.get("/session/summary", response_model=SessionSummaryResponse)
async def get_session_summary(request: Request, session_id: Optional[int] = None) -> SessionSummaryResponse:
    state = gs(request)
    sid = session_id if session_id is not None else state.session_id
    session = await state.db.get_session(sid)
    if session is None:
        raise HTTPException(status_code=404, detail=f"no session {sid}")

    duration_s = (session["ended_ts"] or time.time()) - session["started_ts"]
    alerts_fired, alerts_acked = await state.db.alert_counts(sid)
    windows_total, windows_rejected = await state.db.window_counts(sid)
    mode_time_s = await state.db.mode_time_breakdown(sid)
    foot_checks = await state.db.foot_check_count(sid)
    mean_risk, peak_risk = await state.db.risk_stats(sid)

    return SessionSummaryResponse(
        session_id=sid,
        started_ts=session["started_ts"],
        duration_s=duration_s,
        alerts_fired=alerts_fired,
        alerts_acknowledged=alerts_acked,
        windows_total=windows_total,
        windows_rejected=windows_rejected,
        mode_time_s=mode_time_s,
        foot_checks=foot_checks,
        mean_risk=mean_risk,
        peak_risk=peak_risk,
    )


@router.get("/session/export")
async def get_session_export(request: Request, session_id: Optional[int] = None) -> StreamingResponse:
    state = gs(request)
    sid = session_id if session_id is not None else state.session_id
    rows = await state.db.export_rows(sid)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["timestamp", "iso_time", "mode", "sqi", "risk_score", "alert_fired",
         "acknowledged", "foot_delta_t", "foot_valid", "battery_pct"]
    )
    for r in rows:
        iso_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(r["timestamp"]))
        writer.writerow(
            [
                r["timestamp"], iso_time, r["mode"], r["sqi"], r["risk_score"],
                bool(r["alert_id"]), bool(r["acknowledged"]) if r["acknowledged"] is not None else "",
                r["foot_delta_t"] if r["foot_delta_t"] is not None else "",
                bool(r["foot_valid"]) if r["foot_valid"] is not None else "",
                r["battery_pct"] if r["battery_pct"] is not None else "",
            ]
        )
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=session_{sid}_export.csv"},
    )


# --- Model management (docs/API_CONTRACT.md section 3.1) --------------------
#
# Lets a trained model be uploaded and swapped in from the frontend's Model
# page at runtime, instead of only via GS_MODEL_PATH + a manual restart. The
# swap is immediate: the very next ECG window is scored by whichever model is
# now active (app/main.py's _handle_window reads state.model on every tick),
# so "compare against real-time data" just falls out of the existing live
# pipeline -- there is no separate comparison mechanism to build.


def _apply_model(request: Request, path) -> ModelActionResponse:
    """Shared by upload and select: loads `path` (or None for the stub) and,
    only if that load actually succeeds, swaps it into the live pipeline and
    persists the choice so a restart resumes on the same model.

    Deliberately does NOT go through inference.load_risk_model()'s built-in
    fallback here: that function always returns *some* model (falling back to
    the stub internally on failure), which made it impossible to tell "the
    load failed" apart from "the caller asked for the stub" without fragile
    string-matching on the resulting name. Loading OnnxRiskModel directly and
    catching the exception ourselves means a bad upload can be rejected
    without ever touching state.model -- confirmed necessary by testing: the
    first version of this function called load_risk_model unconditionally and
    always assigned its result to state.model, so uploading a corrupt .onnx
    file silently replaced a perfectly good, already-active model with the
    stub instead of leaving it alone.
    """
    state = gs(request)

    if path is None:
        state.model = StubRiskModel()
        model_registry.write_selection(None)
        return ModelActionResponse(ok=True, active_model=state.model.name, message="Reverted to the stub model")

    try:
        new_model = OnnxRiskModel(str(path))
    except Exception as exc:
        # state.model and the persisted selection are untouched -- whatever
        # was working before is still working.
        return ModelActionResponse(
            ok=False,
            active_model=state.model.name,
            message=f"Failed to load {path.name}: {exc}. Keeping the previous model active.",
        )

    state.model = new_model
    model_registry.write_selection(path.name)
    return ModelActionResponse(
        ok=True, active_model=new_model.name, message=f"Now scoring live data with: {new_model.name}"
    )


@router.get("/model/list", response_model=ModelListResponse)
async def get_model_list(request: Request) -> ModelListResponse:
    state = gs(request)
    active_filename = None
    if not isinstance(state.model, StubRiskModel) and state.model.name.startswith("ONNX:"):
        active_filename = state.model.name.removeprefix("ONNX: ")

    models = [
        ModelInfo(**m, active=(m["filename"] == active_filename)) for m in model_registry.list_models()
    ]
    return ModelListResponse(models=models, active=active_filename or "stub")


@router.post("/model/upload", response_model=ModelActionResponse)
async def post_model_upload(request: Request, file: UploadFile = File(...)) -> ModelActionResponse:
    if not file.filename or not file.filename.lower().endswith(".onnx"):
        raise HTTPException(status_code=400, detail="only .onnx files are accepted")

    content = await file.read()
    try:
        path = model_registry.save_upload(file.filename, content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    result = _apply_model(request, path)
    if not result.ok:
        # The file was saved but failed to load as a valid ONNX model (e.g.
        # wrong input signature, corrupted export) -- remove it rather than
        # leaving an unusable file cluttering the model list.
        model_registry.delete_model(file.filename)
    return result


@router.post("/model/select", response_model=ModelActionResponse)
async def post_model_select(request: Request, body: dict) -> ModelActionResponse:
    filename = body.get("filename")
    if not filename:
        # Explicit "use the stub" -- filename omitted or null.
        return _apply_model(request, None)
    try:
        path = model_registry.model_path(filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"no uploaded model named {filename}")
    return _apply_model(request, path)


@router.post("/model/reset", response_model=ModelActionResponse)
async def post_model_reset(request: Request) -> ModelActionResponse:
    return _apply_model(request, None)


@router.post("/alerts/{alert_id}/ack", response_model=AlertAckResponse)
async def post_alert_ack(request: Request, alert_id: int) -> AlertAckResponse:
    state = gs(request)
    ok = await state.db.acknowledge_alert(alert_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"no alert {alert_id}")
    return AlertAckResponse(id=alert_id, acknowledged=True)


# --- Development-only simulator controls (config.gs_enable_sim) -------------


def _require_sim() -> None:
    if not settings.gs_enable_sim:
        raise HTTPException(status_code=404, detail="simulator controls disabled")


def _sim_state(state) -> dict:
    foot = state.aux_gateway.state() if isinstance(state.aux_gateway, SimulatedFootModule) else None
    return {
        "ecg": state.simulator.state() if state.simulator is not None else None,
        "foot": foot,
        "scenarios": list(SCENARIOS),
        "foot_modes": list(FOOT_MODES),
    }


@router.get("/sim/state")
async def get_sim_state(request: Request) -> dict:
    _require_sim()
    return _sim_state(gs(request))


@router.post("/sim/scenario")
async def post_sim_scenario(request: Request, body: SimScenarioRequest) -> dict:
    _require_sim()
    state = gs(request)
    if state.simulator is None:
        raise HTTPException(status_code=400, detail="no simulated ECG (GS_SOURCE is not simulator)")
    try:
        state.simulator.set_scenario(body.name, body.duration_s)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _sim_state(state)


@router.post("/sim/settings")
async def post_sim_settings(request: Request, body: SimSettingsRequest) -> dict:
    _require_sim()
    state = gs(request)
    if state.simulator is None:
        raise HTTPException(status_code=400, detail="no simulated ECG (GS_SOURCE is not simulator)")
    sim = state.simulator
    if body.heart_rate_bpm is not None:
        sim.base_hr_bpm = body.heart_rate_bpm
    if body.battery_pct is not None:
        sim.set_battery(body.battery_pct)
    if body.random_artifacts is not None:
        sim.random_artifacts = body.random_artifacts
    return _sim_state(state)


@router.post("/sim/foot")
async def post_sim_foot(request: Request, body: SimFootRequest) -> dict:
    _require_sim()
    state = gs(request)
    if not isinstance(state.aux_gateway, SimulatedFootModule):
        raise HTTPException(status_code=400, detail="no simulated foot module (GS_AUX_SOURCE is not simulator)")
    try:
        state.aux_gateway.set_mode(body.mode)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    state.aux_connected = state.aux_gateway.connected
    bus.publish("status", state.status_dict())
    return _sim_state(state)


@router.post("/sim/{action}")
async def post_sim_action(request: Request, action: str) -> dict:
    if not settings.gs_enable_sim:
        raise HTTPException(status_code=404, detail="simulator controls disabled")

    state = gs(request)
    if state.simulator is None:
        raise HTTPException(status_code=400, detail="no simulator active (GS_SOURCE is not simulator)")

    if action == "start":
        state.simulator.start()
    elif action == "stop":
        state.simulator.stop()
    elif action == "spike":
        state.simulator.spike()
    else:
        raise HTTPException(status_code=400, detail="action must be one of: start, stop, spike")

    return {"action": action, "ok": True}
