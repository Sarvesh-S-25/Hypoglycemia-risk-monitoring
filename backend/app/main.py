"""
FastAPI application entrypoint. Lifespan wires together every piece built in
Phases 1-2 (db, pipeline, inference, controller, simulator) into one running
system, and mounts the Phase 3 API surface (routes + WebSocket).

The background task started here (`_consume_source`) is the one place that
ties the whole chain together: source (simulator, or BLE in Phase 7) ->
signal_pipeline -> inference -> controller -> db + event bus. Every REST
endpoint and the WebSocket only ever *read* state this task produces; per
AGENTS.md, the frontend and the routes never re-derive a mode or a risk score.
"""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import model_registry
from app.api.routes import router as rest_router
from app.api.ws import router as ws_router
from app.aux_gateway import AuxGateway, AuxUnavailable
from app.config import settings
from app.controller import (
    Controller,
    foot_checkin_should_read,
    foot_sleep_seconds,
    is_foot_check_elevated,
    schedule_next_foot_check,
    should_fire_foot_check,
)
from app.db import Database
from app.events import bus
from app.inference import load_risk_model
from app.models import EcgWindow
from app.ble_gateway import BleGateway, find_device
from app.serial_gateway import SerialGateway
from app.signal_pipeline import SignalPipeline
from app.simulator import SimulatedFootModule, Simulator
from app.state import AppState

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("glucosentry")


async def _handle_window(app: FastAPI, window: EcgWindow) -> None:
    """The core pipeline tick: one accepted-or-rejected ECG window in, zero or
    more WebSocket frames and DB rows out. Called once per window regardless
    of whether it came from the simulator or (Phase 7) real BLE hardware."""
    state: AppState = app.state.gs
    state.last_window = window
    state.device_connected = True

    arr = state.pipeline.ingest(window)
    state.heart_rate.update(window)
    score: float | None = None
    mode = state.controller.state.mode

    state.windows_total += 1
    if arr is None:
        if window.leads_off:
            state.rejected_leads_off += 1
        else:
            state.rejected_motion += 1
        # The accepted ECG is no longer contiguous; a model scoring a rolling
        # multi-window buffer must start over.
        state.model.reset()
    else:
        state.windows_accepted += 1
        # None while a fixed-length model is still filling its buffer (the
        # first 30 s after start or after a rejected window).
        t0 = time.perf_counter()
        score = state.model.predict(arr)
        if score is not None:
            state.last_inference_ms = round((time.perf_counter() - t0) * 1000, 2)

    if score is not None:
        decision = state.controller.evaluate(
            score=score, battery_pct=window.battery_pct, sqi=window.sqi, timestamp=window.window_start_ts
        )
        mode = decision.mode
        state.last_risk_score = score
        state.last_risk_ts = window.window_start_ts

        await state.db.insert_ecg_window(state.session_id, window.window_start_ts, window.sqi, score, mode)
        bus.publish("risk_update", {"score": score, "mode": mode, "timestamp": window.window_start_ts})

        if decision.fire_alert:
            state.last_alerting = True
            alert_id = await state.db.insert_alert(state.session_id, window.window_start_ts, score)
            bus.publish(
                "alert",
                {
                    "id": alert_id,
                    "level": "high",
                    "score": score,
                    "timestamp": window.window_start_ts,
                    "message": "Sustained elevated risk confirmed",
                },
            )
        elif mode != "Verify":
            state.last_alerting = False
    else:
        # Rejected (or not yet scorable) window: still recorded (risk_score
        # NULL) so window_counts reflects reality, per docs/API_CONTRACT.md
        # section 5.
        await state.db.insert_ecg_window(state.session_id, window.window_start_ts, window.sqi, None, mode)

    bus.publish(
        "ecg_window",
        {
            "window_start_ts": window.window_start_ts,
            "sample_rate_hz": window.sample_rate_hz,
            "sqi": window.sqi,
            "leads_off": window.leads_off,
            "samples": window.samples,
        },
    )

    # device_status row + throttled status frame (docs/API_CONTRACT.md section 4:
    # "at most once per second, and only when something actually changed").
    await state.db.insert_device_status(
        state.session_id, window.window_start_ts, window.battery_pct, mode, leads_off=window.leads_off
    )
    if state.status_changed():
        bus.publish("status", state.status_dict())

    # Automatic foot-check firing: SRD 4.4's "if scheduled_time_reached and
    # battery_sufficient: wake_auxiliary_node()", checked on every window tick.
    # A deep-sleeping real node can't be woken on demand; its checks happen
    # when it checks in (_aux_checkin), so this applies to the simulated one.
    if (
        not getattr(state.aux_gateway, "rendezvous", False)
        and not state.foot_check_busy
        and should_fire_foot_check(
            scheduled_time=state.next_foot_check_scheduled,
            battery_pct=window.battery_pct,
            now=window.window_start_ts,
        )
    ):
        state.foot_check_busy = True
        asyncio.create_task(run_foot_check(app, request_id=f"fc_auto_{int(window.window_start_ts)}"))


async def run_foot_check(app: FastAPI, request_id: str) -> None:
    """One foot check against whichever foot module is configured: the real
    node over BLE (GS_AUX_SOURCE=ble) or the simulated one. Both expose the
    same read(), so the scheduler path is identical."""
    state: AppState = app.state.gs
    try:
        try:
            reading = await state.aux_gateway.read()
        except AuxUnavailable as e:
            # No answer counts as an invalid check: the scheduler retries soon
            # instead of treating the check as done.
            logger.warning("foot check %s: %s", request_id, e)
            await _record_foot_check(state, request_id, None, None, False)
            return
        if reading.valid:
            await _record_foot_check(state, request_id, reading.t_left, reading.t_right, True)
        else:
            await _record_foot_check(state, request_id, None, None, False)
    finally:
        state.foot_check_busy = False


async def _aux_checkin(app: FastAPI, gateway: AuxGateway) -> float:
    """The real foot module woke from deep sleep and is connected. Take a
    reading if one is due or was requested, then return how long it should
    sleep (invention disclosure item 8, steps 3-8)."""
    state: AppState = app.state.gs
    now = time.time()
    manual = state.foot_check_requested or gateway.wake_reason == "button"
    if foot_checkin_should_read(
        now=now,
        scheduled_time=state.next_foot_check_scheduled,
        battery_pct=state.last_window.battery_pct if state.last_window else None,
        manual_requested=manual,
        busy=state.foot_check_busy,
    ):
        state.foot_check_requested = False
        state.foot_check_busy = True
        kind = "manual" if manual else "scheduled"
        await run_foot_check(app, request_id=f"fc_{kind}_{int(now)}")  # reschedules from the result
    return foot_sleep_seconds(now=time.time(), scheduled_time=state.next_foot_check_scheduled)


async def _record_foot_check(
    state: AppState, request_id: str, t_left: float | None, t_right: float | None, valid: bool
) -> None:
    """Close the loop: reschedule from this result, persist it, publish it."""
    delta_t = round(abs(t_right - t_left), 2) if valid and t_left is not None and t_right is not None else None
    decision = schedule_next_foot_check(last_result_valid=valid, last_delta_t=delta_t)
    state.next_foot_check_scheduled = decision.next_check_scheduled

    ts = time.time()
    check_id = await state.db.insert_foot_check(
        state.session_id, ts, t_left, t_right, delta_t, valid, decision.next_check_scheduled, decision.action
    )

    result = {
        "id": check_id,
        "t_left": t_left,
        "t_right": t_right,
        "delta_t": delta_t,
        "valid": valid,
        "elevated": is_foot_check_elevated(delta_t),
        "timestamp": ts,
        "next_check_scheduled": decision.next_check_scheduled,
        "action": decision.action,
    }
    state.last_foot_check = result
    bus.publish("foot_check_result", result)
    logger.info("foot check %s complete: valid=%s delta_t=%s action=%s", request_id, valid, delta_t, decision.action)


async def _set_link(app: FastAPI, connected: bool) -> None:
    """A hardware source's port opened or dropped. The simulator never calls
    this; it is "connected" from its first window onward."""
    state: AppState = app.state.gs
    state.device_connected = connected
    if state.status_changed():
        bus.publish("status", state.status_dict())


async def _set_aux_link(app: FastAPI, connected: bool) -> None:
    """The foot module's BLE link came up or dropped."""
    state: AppState = app.state.gs
    state.aux_connected = connected
    if state.status_changed():
        bus.publish("status", state.status_dict())


async def _consume_source(app: FastAPI) -> None:
    """Runs whichever data source is configured: the simulator, or the real
    ESP32 over USB serial. Phase 7 adds a `ble_gateway` branch here behind the
    same `_handle_window` sink, which is the entire point of docs/PLAN.md
    section 1 decision 1."""
    state: AppState = app.state.gs

    if settings.gs_source == "simulator":
        assert state.simulator is not None
        await state.simulator.run(lambda w: _handle_window(app, w))
    elif settings.gs_source == "serial":
        await SerialGateway().run(lambda w: _handle_window(app, w), lambda c: _set_link(app, c))
    elif settings.gs_source == "ble":
        await BleGateway().run(lambda w: _handle_window(app, w), lambda c: _set_link(app, c))
    elif settings.gs_source == "auto":
        # One scan up front: a node in range wins, otherwise the simulator
        # keeps the system demoable (docs/PLAN.md Phase 7).
        device = await find_device(settings.gs_ble_scan_timeout_s)
        if device is not None:
            logger.info("GS_SOURCE=auto: found %s, using BLE", device.address)
            state.source = "ble"
            await BleGateway().run(lambda w: _handle_window(app, w), lambda c: _set_link(app, c), device=device)
        else:
            logger.info("GS_SOURCE=auto: no BLE node within %.0fs, using the simulator", settings.gs_ble_scan_timeout_s)
            state.source = "simulator"
            assert state.simulator is not None
            await state.simulator.run(lambda w: _handle_window(app, w))
    else:
        logger.error("unknown GS_SOURCE=%s; no data source running", settings.gs_source)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = Database(settings.db_path)
    await db.connect()

    device_id = "esp32_primary_01"
    session_id = await db.start_session(device_id)

    pipeline = SignalPipeline()
    # A model chosen at runtime via POST /api/model/select or /upload (the
    # frontend's Model page) is persisted to disk and takes priority over
    # GS_MODEL_PATH on restart, so a restart doesn't silently revert to
    # whatever the .env file says. GS_MODEL_PATH remains the one-time
    # startup default for a machine that has never had a selection made.
    persisted_selection = model_registry.read_selection()
    if persisted_selection:
        startup_model_path = str(model_registry.model_path(persisted_selection))
    else:
        startup_model_path = settings.gs_model_path
    model = load_risk_model(startup_model_path)
    controller = Controller()
    # No simulator object for the hardware-only sources, so /api/sim/* answers
    # "no simulator active" instead of starting a simulator nothing consumes.
    simulator = (
        Simulator(device_id=device_id, sample_rate_hz=settings.ecg_sample_rate_hz)
        if settings.gs_source not in ("ble", "serial")
        else None
    )

    state = AppState(
        db=db,
        pipeline=pipeline,
        model=model,
        controller=controller,
        session_id=session_id,
        simulator=simulator,
        source=settings.gs_source,
        # First foot check is scheduled a full normal interval out at session
        # start; the manual "request check now" button (SRD 5.1) is always
        # available in the meantime regardless of this schedule.
        next_foot_check_scheduled=time.time() + settings.foot_check_normal_interval_s,
    )
    app.state.gs = state

    tasks = [asyncio.create_task(_consume_source(app))]
    if settings.gs_aux_source == "ble":
        state.aux_gateway = AuxGateway()
        tasks.append(
            asyncio.create_task(
                state.aux_gateway.run(lambda c: _set_aux_link(app, c), lambda gw: _aux_checkin(app, gw))
            )
        )
    else:
        state.aux_gateway = SimulatedFootModule()
        state.aux_connected = state.aux_gateway.connected
    logger.info(
        "GlucoSentry backend started: session_id=%d source=%s aux=%s",
        session_id, settings.gs_source, settings.gs_aux_source,
    )

    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await db.end_session(session_id)
        await db.close()
        logger.info("GlucoSentry backend shut down cleanly")


app = FastAPI(title="GlucoSentry Backend", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.gs_cors_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(rest_router)
app.include_router(ws_router)


@app.get("/api/health")
async def health() -> dict:
    return {"ok": True, "source": settings.gs_source}
