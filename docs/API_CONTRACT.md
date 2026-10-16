# GlucoSentry API Contract

This is the single source of truth for every boundary in the system: firmware to
backend (BLE), backend to frontend (REST + WebSocket), and backend to disk (SQLite).
It is derived from SRD v1.0 sections 3, 4 and 5.

**Rule for all agents:** if a change is needed here, change this file *first*, then
the backend, then the frontend, and note it in `UPDATES.md`. Never let the frontend
and backend drift apart by patching one side only.

---

## 1. Conventions

- All timestamps are **float UNIX seconds, UTC** (`time.time()`), never ISO strings
  on the wire. The frontend formats for display.
- All risk scores are floats in `[0.0, 1.0]`.
- Modes are the exact strings `"Eco" | "Normal" | "Watch" | "Verify"` — capitalized,
  matching the SRD. The BLE layer uses the integer enum `0..3` in that same order and
  the backend translates.
- Temperatures are degrees Celsius, floats.
- Errors use FastAPI's default shape: `{"detail": "..."}` with a 4xx/5xx status.
- Base URL in development: `http://127.0.0.1:8000`. The frontend reads it from
  `VITE_API_BASE`, defaulting to that value.

## 2. BLE layer (firmware to backend)

Mirrors SRD 3.3. UUIDs are placeholders until firmware bring-up; the backend reads
them from `backend/app/config.py` so firmware can fix them without a code change.

### 2.1 Primary node service

| Characteristic | Direction | Payload | Purpose |
|---|---|---|---|
| `ecg_data` | notify | packed `int16` little-endian array, preceded by a `double` window-start timestamp | one filtered, decimated ECG window |
| `sqi_flag` | notify | `uint8` (0 reject, 1 accept) | per-window signal quality |
| `device_status` | notify | `{battery: uint8, mode: uint8, leads_off: uint8, motion: uint16}` packed, little-endian, 5 bytes | per-window health report |
| `controller_cmd` | write | `uint8` 0=Eco 1=Normal 2=Watch 3=Verify | mode command |
| `alert_cmd` | write | `uint8` | trigger the vibration motor |
| `aux_wake_cmd` | write | `uint8` | forward a wake signal to the auxiliary node |

Wire details, fixed at firmware bring-up (2026-10-13):

- **Advertising.** Device name `GlucoSentry-ECG`, primary service UUID in the
  advertisement so the gateway can filter a scan by service.
- **MTU.** One `ecg_data` notification is a whole window: 8 + 2 × 100 = 208 bytes,
  so the link needs an ATT MTU of at least 211. The firmware requests 247; BlueZ
  negotiates it automatically.
- **Order per window**, once a second: `sqi_flag`, then `ecg_data`, then
  `device_status`. The gateway pairs each `ecg_data` with the most recent
  `sqi_flag` and `device_status`.
- **Timestamp.** The ESP32 has no wall clock, so the `double` is device uptime in
  seconds. The gateway stamps windows with host arrival time minus the window
  length (same as the serial source) and uses the device value only to detect
  dropped windows.
- **`battery`** is 0–100, or **255 = not measured** (bus-powered bench build),
  which the gateway maps to `battery_pct: null` (section 2.3).
- **`mode`** echoes the last `controller_cmd` received, so the backend can see that
  a command landed.
- **`motion`** is the window's acceleration-magnitude std-dev in units of
  0.01 m/s² (section 2.3's `motion_ms2` × 100).
- **`alert_cmd`** blinks the on-board LED (GPIO2) for 3 s on the bench build,
  standing in for the vibration motor.
- The on-device SQI uses the same rule as the serial source: reject on any
  leads-off sample or motion above 1.0 m/s².

### 2.2 Auxiliary node service

| Characteristic | Direction | Payload | Purpose |
|---|---|---|---|
| `wake` | write | `uint8` | take a bilateral reading now |
| `foot_temp_result` | notify | `{t_left: float, t_right: float, delta: float, valid: bool}` | bilateral reading |
| `sleep` (`0000b003-…`) | write | `uint32` LE seconds | go into deep sleep for this long |
| `node_info` (`0000b004-…`) | read | `uint8 wake_reason, uint32 boot_count, uint32 last_sleep_s` | why the node woke: 0 power-on, 1 timer, 2 button |

Notes for implementers:

- **`foot_temp_result`** is 13 bytes, little-endian: `float32 t_left`, `float32
  t_right`, `float32 delta` (all °C, `delta = t_left - t_right`), then `uint8 valid`.
  An invalid reading (a temperature outside 10–45 °C, or two reads 100 ms apart
  disagreeing by 0.5 °C or more) carries `valid = 0` and zeros for the temperatures.
  The backend stores `|delta|` as `delta_t`.
- **Deep-sleep check-ins.** The node deep-sleeps (radio off, dividers unpowered with
  GPIO32 held low) and wakes on its RTC timer or its BOOT button. It then advertises
  for up to 20 s. The backend (`app/aux_gateway.py`, `GS_AUX_SOURCE=ble`) connects,
  reads `node_info`, and lets the scheduler decide
  (`controller.foot_checkin_should_read`). If a check is due, or a manual one was
  queued or the button woke the node, it writes `wake` and waits for
  `foot_temp_result`. It **always** finishes by writing `sleep` with
  `controller.foot_sleep_seconds`: the time until the next scheduled check, clamped
  to `aux_min_sleep_s`–`aux_max_sleep_s` (5–30 s by default, so manual requests stay
  responsive in a demo). With no host in the 20 s window, or no `sleep` within 30 s
  of connecting, the node sleeps 60 s and tries again.
- Because the node can't be woken over BLE, `POST /api/foot/request` *queues* the
  check for the next check-in (its `eta_s` covers the wait). A `wake` with no result
  within `aux_result_timeout_s` is recorded as an invalid check, so the scheduler
  retries. `aux_wake_cmd` on the primary node is not used.
- Measured on the bench (2026-10-15): check-in to result in 227 ms; the node was
  back in deep sleep about 90 ms after the result. The dev board's USB bridge, LED
  and regulator still draw milliamps in deep sleep, so microamp figures need a bare
  module.

### 2.3 Normalized ECG window (internal, after parsing)

This is what `ble_gateway` hands to `signal_pipeline`, and exactly what the simulator
produces, so nothing downstream can tell live hardware from simulation:

```json
{
  "device_id": "esp32_primary_01",
  "window_start_ts": 1732000000.0,
  "sample_rate_hz": 100,
  "sqi": 1,
  "samples": [12, -4, 33, "... int16"],
  "battery_pct": 78,
  "leads_off": false,
  "motion_ms2": 0.04
}
```

`battery_pct` is `null` when the source cannot measure it (the USB serial source:
the board is bus-powered and has no battery gauge). A null battery is treated as
sufficient: it never forces Eco mode and never blocks an auxiliary wake.
`leads_off` is `true` if the AD8232 reported lead-off at any point in the window;
such a window always has `sqi: 0`. `motion_ms2` is the standard deviation of the
acceleration magnitude over the window (m/s²), or `null` if the source has no
accelerometer; the simulator synthesizes it, high in its motion-artifact windows.

### 2.4 USB serial transport (interim, `GS_SOURCE=serial`)

Lets the real ESP32 drive the dashboard over its USB cable before the BLE firmware
exists. The firmware streams one ASCII line per ECG sample at **250 Hz**, 921600 baud:

```
ecg_mV,leads_off,ax,ay,az
1652.4,0,1.02,0.41,9.73
```

| Field | Type | Meaning |
|---|---|---|
| `ecg_mV` | float | ADS1115 AIN0 in millivolts (0.125 mV/LSB at ±4.096 V); `0.0` while leads are off |
| `leads_off` | `0`/`1` | AD8232 LO+ or LO− asserted |
| `ax, ay, az` | float | MPU6050/6500 acceleration, m/s² (refreshed at 25 Hz, repeated between reads) |

Lines that do not parse as exactly five numbers (boot messages, partial lines) are
ignored. `serial_gateway` groups 250 consecutive samples into one window, converts
millivolts back to int16 ADC counts, decimates 250 → 100 Hz, and sets `sqi: 0` if
leads were off or the acceleration magnitude's standard deviation over the window
exceeds `serial_motion_sqi_threshold_ms2` (SRD 3.1's MPU-based motion gating). The
result is the normalized window in 2.3, so nothing downstream can tell serial from
BLE or the simulator. The port is auto-detected (`/dev/ttyACM*`, `/dev/ttyUSB*`)
unless `GS_SERIAL_PORT` is set; if it disappears, the source reports
`connected: false` and keeps retrying.

## 3. REST API

All routes are prefixed `/api`.

### `GET /api/status`

Current device and link state. Never 404s; returns a disconnected object instead, so
the dashboard can render an honest empty state.

```json
{
  "connected": true,
  "source": "simulator",
  "device_id": "esp32_primary_01",
  "battery_pct": 78,
  "mode": "Normal",
  "leads_off": false,
  "sqi": 1,
  "last_packet_ts": 1732000000.0,
  "aux_connected": false,
  "aux_source": "simulator",
  "aux_state": "awake",
  "aux_next_wake_ts": null,
  "aux_check_queued": false,
  "session_id": 4,
  "model": "Stub (heuristic)",
  "heart_rate_bpm": 72.4,
  "motion_ms2": 0.04,
  "moving": false,
  "risk_ready_in_s": 0
}
```

`heart_rate_bpm` is estimated by the backend (`app/heart_rate.py`) from R-peaks in
the last `hr_window_s` seconds of consecutive accepted windows; it is `null` until
that much clean signal exists, and resets to `null` on any rejected window rather
than reporting a stale rate. `motion_ms2` is the latest window's value (see 2.3) and
`moving` is the backend's verdict on it against `serial_motion_sqi_threshold_ms2`,
`null` when `motion_ms2` is. The UI displays these; it does not threshold them.
`aux_state` is `"awake"` (checked in right now), `"asleep"` (deep sleep, due back at
`aux_next_wake_ts`) or `"missing"` (never seen, or more than `aux_missing_grace_s`
overdue). The simulated module is always `"awake"`, or `"missing"` when set to
offline. `aux_check_queued` is true while a manual check waits for the next
check-in. `aux_connected` stays as the raw link state.
`risk_ready_in_s` is how many more seconds of clean signal the model needs before it
can score: `0` while scoring, `null` when there is no clean signal to buffer.
`aux_source` is `"ble"` when foot checks go to the real node (then `aux_connected`
is its live link state) or `"simulator"` when they are synthesized.

`source` is `"ble" | "serial" | "simulator" | "none"` so the UI can label a demo
honestly. `battery_pct` is `null` when the source cannot measure it (see 2.3).
`leads_off` is the real AD8232 state for `serial` (and `ble` once implemented);
the simulator always reports `false`.

`model` is a human-readable label for whichever `RiskModel` is actually scoring
data right now (`app/inference.py`): `"Stub (heuristic)"` until a trained model
is configured, `"ONNX: <filename>"` once `GS_MODEL_PATH` points at a real one,
or `"Stub (failed to load <filename>: <error>)"` if that file couldn't be
loaded and the backend silently fell back to the stub. The frontend surfaces
this directly (`DeviceStatus`'s Model row) so a bad model path is visible in
the UI, not just in a server log nobody may be watching.

### `GET /api/risk/current`

```json
{ "score": 0.34, "mode": "Normal", "timestamp": 1732000000.0, "alerting": false }
```

`score` and `timestamp` are `null` until a window has actually been scored (no clean
signal yet, or a fixed-length model still filling its buffer). The backend never
reports a placeholder `0.0`, because a real score of 0.0 means "no risk".

### `GET /api/diagnostics`

The backend's working state for the dashboard's engineering view. It's read-only and
comes from the same objects that make the decisions, so it is never a second decision
path. The frontend polls it about once a second while that view is open.

```json
{
  "timestamp": 1732000000.0,
  "link": { "source": "ble", "connected": true, "last_packet_ts": 1732000000.0,
            "battery_pct": null, "aux_source": "ble", "aux_connected": true },
  "pipeline": { "sample_rate_hz": 100, "windows_total": 120, "windows_accepted": 96,
                "rejected_leads_off": 20, "rejected_motion": 4, "sqi": 1,
                "leads_off": false, "motion_ms2": 0.04, "motion_threshold_ms2": 1.0,
                "last_window": { "n_samples": 100, "min": -812, "max": 2210, "ptp": 3022, "mean": 4.1 },
                "heart_rate_bpm": 72.4 },
  "model": { "name": "ONNX: glucosentry_cnn_bilstm.onnx", "needed_s": 30.0, "buffered_s": 30.0,
             "input_len": 7500, "input_rate_hz": 250, "output": "logit -> sigmoid",
             "last_score": 0.41, "last_score_ts": 1732000000.0, "last_inference_ms": 3.8 },
  "controller": { "mode": "Normal", "manual_mode": null, "risk_low": 0.3, "risk_elevated": 0.55,
                  "risk_alert": 0.75, "verify_confirm_count": 0, "confirm_windows": 3,
                  "alert_cooldown_s": 300.0, "cooldown_remaining_s": null,
                  "recent_scores": [0.39, 0.41], "alerting": false },
  "foot": { "source": "ble", "connected": true, "busy": false, "next_check_scheduled": 1732086400.0,
            "elevated_threshold_c": 2.2, "normal_interval_s": 86400.0, "elevated_interval_s": 28800.0,
            "invalid_retry_s": 3600.0, "battery_min_pct": 15, "result_timeout_s": 10.0,
            "last_check": { "/* same shape as the foot_check_result frame */": null } }
}
```

Rejected windows count toward `rejected_leads_off` when the AD8232 reported leads-off
in them, and toward `rejected_motion` otherwise (an `sqi = 0` window with the leads
on). `needed_s` is 0 for a model that scores each window on its own.

### `GET /api/risk/history?range=1h`

`range` accepts `15m`, `1h`, `6h`, `24h` (default `1h`). Returns oldest first,
downsampled server-side to at most 600 points so the chart stays cheap.

```json
{
  "range": "1h",
  "points": [ { "timestamp": 1732000000.0, "score": 0.31, "mode": "Normal" } ]
}
```

### `GET /api/ecg/latest`

The most recent accepted window, for first paint before the WebSocket delivers
anything.

```json
{
  "window_start_ts": 1732000000.0,
  "sample_rate_hz": 100,
  "sqi": 1,
  "samples": [12, -4, 33]
}
```

Returns `{"samples": [], "sqi": 0, "window_start_ts": null, "sample_rate_hz": 100}`
when nothing has arrived yet.

### `GET /api/foot/history?limit=50`

```json
{
  "checks": [
    {
      "id": 12,
      "timestamp": 1732000000.0,
      "t_left": 31.2,
      "t_right": 32.3,
      "delta_t": 1.1,
      "valid": true,
      "elevated": false,
      "next_check_scheduled": 1732086400.0,
      "action": "scheduled_24h"
    }
  ],
  "next_check_scheduled": 1732086400.0
}
```

Most recent first. `elevated` is the backend's verdict on `delta_t` against
`foot_check_elevated_threshold_c` (2.2 °C, the IWGDF reference, cited as background
and not as a diagnostic claim), and `null` for an invalid check. The UI shows it and
never compares `delta_t` itself.

### `POST /api/foot/request`

Manually trigger an auxiliary foot check. Body is empty. Responds immediately with an
accepted-style acknowledgement; the result arrives later over the WebSocket, because
the wake-to-result cycle takes seconds.

```json
{ "requested": true, "request_id": "fc_8f21", "eta_s": 6 }
```

Returns **409** with `{"detail": "auxiliary node busy"}` if a check is already in
flight, and **503** if the battery is below the configured floor or, with
`GS_AUX_SOURCE=ble`, with `{"detail": "foot module not connected"}` when the node is
out of range. `eta_s` is the simulated delay, or `aux_eta_s` (about 1 s) for the real
node.

### `POST /api/controller/mode`

Manual override, for testing and the demo.

Request: `{ "mode": "Watch", "manual": true }`
Response: `{ "mode": "Watch", "manual": true, "applied_ts": 1732000000.0 }`

Sending `{"manual": false}` returns control to the automatic state machine. **400**
on an unknown mode string.

### Model management

Lets a trained model be uploaded and swapped in from the frontend's Model page
(`/model`) at runtime, instead of only via `GS_MODEL_PATH` and a manual restart.
The swap is immediate: the very next ECG window is scored by whichever model is
now active, so "compare against real-time data" is just the existing live
pipeline picking up the new model -- there is no separate comparison mechanism.

**`GET /api/model/list`** -- every uploaded `.onnx` file plus which one (if any)
is active.

```json
{
  "models": [
    { "filename": "risk_model.onnx", "size_bytes": 48213, "uploaded_ts": 1732000000.0, "active": true }
  ],
  "active": "risk_model.onnx"
}
```

`active` is `"stub"` when no uploaded model is selected.

**`POST /api/model/upload`** -- multipart form upload, field name `file`, `.onnx`
only, up to `GS_MAX_MODEL_UPLOAD_MB` (default 200MB). Saves the file, attempts
to load it, and only on success makes it the active model.

```json
{ "ok": true, "active_model": "ONNX: risk_model.onnx", "message": "Now scoring live data with: ONNX: risk_model.onnx" }
```

**400** if the extension isn't `.onnx` or the file exceeds the size limit. If
the file loads successfully but the load itself fails (corrupt export, wrong
input signature), the response is **200** with `"ok": false` and the error in
`message` -- **the previously active model is left running untouched**, and the
bad file is deleted rather than left cluttering the list. This was a real bug
during development: an earlier version swapped to the stub on any failure,
silently replacing a working model. See `routes.py`'s `_apply_model` docstring
and `tests/test_model_registry.py`.

**`POST /api/model/select`** -- switch to an already-uploaded model without
re-uploading it.

Request: `{ "filename": "risk_model.onnx" }`, or `{ "filename": null }` to
switch to the stub (equivalent to `/api/model/reset`).
Response: same `ModelActionResponse` shape as upload. **404** if the filename
doesn't match an uploaded model.

**`POST /api/model/reset`** -- revert to the built-in stub model. No body.

**Persistence.** Whichever model is selected (via upload or select) is written
to `GS_MODEL_SELECTION_PATH` (default `backend/data/model_selection.txt`) and
takes priority over `GS_MODEL_PATH` on the next backend startup, so a restart
resumes on the same model instead of silently reverting to the stub.

### `GET /api/session/export`

Returns `text/csv` with `Content-Disposition: attachment`. One row per ECG window,
joined with alerts and foot checks:

```
timestamp,iso_time,mode,sqi,risk_score,alert_fired,acknowledged,foot_delta_t,foot_valid,battery_pct
```

Optional `?session_id=4`; defaults to the current session.

### `GET /api/session/summary`

Backs the Session view (SRD 5.1) without making the frontend aggregate:

```json
{
  "session_id": 4,
  "started_ts": 1731990000.0,
  "duration_s": 10000.0,
  "alerts_fired": 3,
  "alerts_acknowledged": 2,
  "windows_total": 640,
  "windows_rejected": 41,
  "mode_time_s": { "Eco": 3200.0, "Normal": 5400.0, "Watch": 1200.0, "Verify": 200.0 },
  "foot_checks": 2,
  "mean_risk": 0.28,
  "peak_risk": 0.81
}
```

### `POST /api/alerts/{id}/ack`

Acknowledge an alert from the dismissible banner.
Response: `{ "id": 9, "acknowledged": true }`

### `POST /api/sim/{action}`  *(development only)*

`action` is one of `start`, `stop`, `spike`. `spike` drives synthetic risk upward so
the mode escalation and the sustained-risk alert path can be demonstrated without
inducing real hypoglycemia (SRD section 8). Disabled when `GS_ENABLE_SIM=0`.

### Simulator controls  *(development only, all 404 when `GS_ENABLE_SIM=0`)*

`GET /api/sim/state`, and every `POST` below, return:

```json
{
  "ecg": { "running": true, "scenario": "hypo", "scenario_remaining_s": 92.0,
           "hypo_progress": 0.6, "heart_rate_bpm": 87.0, "base_heart_rate_bpm": 72.0,
           "battery_pct": 97, "random_artifacts": true },
  "foot": { "mode": "random", "connected": true },
  "scenarios": ["normal", "motion", "leads_off", "hypo", "spike"],
  "foot_modes": ["random", "normal", "elevated", "invalid", "offline"]
}
```

`ecg` is `null` unless `GS_SOURCE=simulator`, and `foot` is `null` unless
`GS_AUX_SOURCE=simulator`. The same object appears as `simulator` in
`GET /api/diagnostics`, with an added `enabled` flag.

- `POST /api/sim/scenario` `{ "name": "motion", "duration_s": 15 }`. `duration_s` is
  optional (defaults: motion 15, leads_off 15, hypo 180, spike 20; `normal` has no
  end). The scenario reverts to `normal` when it expires. 400 on an unknown name.
- `POST /api/sim/settings` `{ "heart_rate_bpm": 95, "battery_pct": 20, "random_artifacts": false }`.
  All fields are optional (heart rate 30–200, battery 0–100).
- `POST /api/sim/foot` `{ "mode": "elevated" }`. Forces what the next simulated foot
  checks return. `offline` sets `aux_connected: false`, so `POST /api/foot/request`
  returns 503 exactly as it does for an out-of-range real module. 400 on an unknown
  mode.

The `hypo` scenario is a **test pattern** (tachycardia, QT prolongation, T-wave
flattening and mild ST depression, ramped in over two thirds of its duration), not
validated physiology.

## 4. WebSocket `/ws/live`

The dashboard subscribes once on mount. Every frame is a JSON object with `type` and
`data`. The server also sends a `hello` frame on connect carrying the same payload as
`GET /api/status`, so the client has full state without a second request.

```jsonc
{ "type": "hello",  "data": { /* same shape as GET /api/status */ } }

{ "type": "ecg_window", "data": {
    "window_start_ts": 1732000000.0, "sample_rate_hz": 100,
    "sqi": 1, "leads_off": false, "samples": [/* int16 */] } }

{ "type": "risk_update", "data": {
    "score": 0.34, "mode": "Normal", "timestamp": 1732000000.0 } }

{ "type": "alert", "data": {
    "id": 9, "level": "high", "score": 0.83, "timestamp": 1732000000.0,
    "message": "Sustained elevated risk confirmed" } }

{ "type": "foot_check_result", "data": {
    "id": 12, "t_left": 31.2, "t_right": 32.3, "delta_t": 1.1,
    "valid": true, "elevated": false, "timestamp": 1732000000.0,
    "next_check_scheduled": 1732086400.0, "action": "scheduled_24h" } }

{ "type": "status", "data": { /* same shape as GET /api/status */ } }
```

Notes that matter for implementation:

- The SRD names the ECG frame `ecg_sample`; we send whole windows rather than single
  samples, so the type is `ecg_window`. One frame per window keeps the socket at
  roughly 1 message/second instead of 100.
- The server pushes a `status` frame at most once per second, and only when something
  actually changed, to avoid flooding the client.
- The client must tolerate unknown `type` values by ignoring them. That is what lets
  the backend add frames later without breaking a deployed dashboard.
- Reconnect with exponential backoff starting at 1s, capped at 15s. On reconnect the
  client refetches `GET /api/risk/history` because it may have missed points.

## 5. SQLite schema

As specified in SRD 4.5, plus a `sessions` table, which the SRD's own Session view
requires but does not define, and two indexes the history queries need.

```sql
CREATE TABLE sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_ts REAL NOT NULL,
    ended_ts REAL,
    device_id TEXT,
    notes TEXT
);

CREATE TABLE ecg_windows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER REFERENCES sessions(id),
    timestamp REAL NOT NULL,
    sqi INTEGER NOT NULL,
    risk_score REAL,
    mode TEXT
);

CREATE TABLE alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER REFERENCES sessions(id),
    timestamp REAL NOT NULL,
    risk_score REAL NOT NULL,
    acknowledged BOOLEAN DEFAULT 0
);

CREATE TABLE foot_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER REFERENCES sessions(id),
    timestamp REAL NOT NULL,
    t_left REAL,
    t_right REAL,
    delta_t REAL,
    valid BOOLEAN,
    next_check_scheduled REAL
);

CREATE TABLE device_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER REFERENCES sessions(id),
    timestamp REAL NOT NULL,
    battery_pct INTEGER,
    mode TEXT,
    leads_off BOOLEAN
);

CREATE INDEX idx_ecg_ts    ON ecg_windows(timestamp);
CREATE INDEX idx_alerts_ts ON alerts(timestamp);
CREATE INDEX idx_foot_ts   ON foot_checks(timestamp);
```

**Raw samples are deliberately not stored.** The SRD's `ecg_windows` table holds only
the derived row, and storing 100 Hz raw ECG would grow the file by roughly 70 MB per
day for no stated requirement. The most recent windows are kept in an in-memory ring
buffer for `GET /api/ecg/latest`. If raw capture is needed for the evaluation, add an
opt-in NDJSON sink rather than changing this table.

## 6. Controller behavior the frontend can rely on

From SRD 4.4, restated as guarantees the UI is allowed to assume:

- Mode changes are announced in the `risk_update` frame's `mode` field and in
  `status` frames. The UI never computes a mode itself.
- An alert is emitted **only** after the sustained-risk confirmation window in
  `Verify` mode completes. The UI does not threshold the risk score on its own,
  because doing so would show a warning the device never actually fired.
- Foot-check scheduling is entirely backend-resident. The UI displays
  `next_check_scheduled` and counts down to it; it never recomputes the interval.
