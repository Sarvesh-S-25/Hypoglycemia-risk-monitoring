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
| `device_status` | notify | `{battery: uint8, mode: uint8, leads_off: bool}` packed | periodic health report |
| `controller_cmd` | write | `uint8` 0=Eco 1=Normal 2=Watch 3=Verify | mode command |
| `alert_cmd` | write | `uint8` | trigger the vibration motor |
| `aux_wake_cmd` | write | `uint8` | forward a wake signal to the auxiliary node |

### 2.2 Auxiliary node service

| Characteristic | Direction | Payload | Purpose |
|---|---|---|---|
| `wake` | write | `uint8` | wake trigger |
| `foot_temp_result` | notify | `{t_left: float, t_right: float, delta: float, valid: bool}` | bilateral reading |

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
  "battery_pct": 78
}
```

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
  "session_id": 4,
  "model": "Stub (heuristic)"
}
```

`source` is `"ble" | "simulator" | "none"` so the UI can label a demo honestly.

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
      "next_check_scheduled": 1732086400.0,
      "action": "scheduled_24h"
    }
  ],
  "next_check_scheduled": 1732086400.0
}
```

### `POST /api/foot/request`

Manually trigger an auxiliary foot check. Body is empty. Responds immediately with an
accepted-style acknowledgement; the result arrives later over the WebSocket, because
the wake-to-result cycle takes seconds.

```json
{ "requested": true, "request_id": "fc_8f21", "eta_s": 6 }
```

Returns **409** with `{"detail": "auxiliary node busy"}` if a check is already in
flight, and **503** if the battery is below the configured floor.

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

## 4. WebSocket `/ws/live`

The dashboard subscribes once on mount. Every frame is a JSON object with `type` and
`data`. The server also sends a `hello` frame on connect carrying the same payload as
`GET /api/status`, so the client has full state without a second request.

```jsonc
{ "type": "hello",  "data": { /* same shape as GET /api/status */ } }

{ "type": "ecg_window", "data": {
    "window_start_ts": 1732000000.0, "sample_rate_hz": 100,
    "sqi": 1, "samples": [/* int16 */] } }

{ "type": "risk_update", "data": {
    "score": 0.34, "mode": "Normal", "timestamp": 1732000000.0 } }

{ "type": "alert", "data": {
    "id": 9, "level": "high", "score": 0.83, "timestamp": 1732000000.0,
    "message": "Sustained elevated risk confirmed" } }

{ "type": "foot_check_result", "data": {
    "id": 12, "t_left": 31.2, "t_right": 32.3, "delta_t": 1.1,
    "valid": true, "timestamp": 1732000000.0,
    "next_check_scheduled": 1732086400.0 } }

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
