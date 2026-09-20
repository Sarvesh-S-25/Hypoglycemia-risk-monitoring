# GlucoSentry — Frontend + Connectivity Build Plan

**Source documents:** `GlucoSentry_SRD.pdf` v1.0 (requirements) and `ruul-a6e6a6.mp4`
(visual reference, distilled into `DESIGN_SYSTEM.md`).

**Scope of this repository.** The dashboard and everything needed for it to be
genuinely connected and to persist data: the React frontend, the FastAPI backend
(REST, WebSocket, SQLite, controller state machine, BLE gateway) and a hardware
simulator that lets the whole chain run before the ESP32 firmware exists.

**Explicitly out of scope here**, because they are handled separately:
ML training, the CNN+BiLSTM architecture, the D1NAMO evaluation, the RL scheduler
comparison, and the ESP32/ESP32-C3 firmware itself. This repo *integrates* with all
of them through fixed interfaces (`inference.py` loads an ONNX file; `ble_gateway.py`
speaks the GATT profile) but does not implement them.

---

## 1. Guiding decisions

These are decided; do not relitigate them mid-build.

1. **The simulator is a first-class citizen, not a hack.** `ble_gateway` and
   `simulator` both emit the identical normalized window (API_CONTRACT section 2.3),
   and the rest of the backend cannot tell them apart. This is what makes SRD build
   step 6 ("build against mocked data first, then connect to live backend") real
   rather than throwaway work, and it means the dashboard can be demonstrated when
   the hardware is unavailable — which, on a review day, matters.
2. **The frontend never does clinical reasoning.** It does not threshold risk, does
   not decide modes, does not compute the next foot-check time. It renders what the
   backend states. Two components disagreeing about when an alert fires is the single
   most likely way this system embarrasses itself in a demo.
3. **Inference is behind an interface from day one.** `inference.py` exposes
   `RiskModel.predict(window) -> float`. The initial implementation is a heuristic
   stub; dropping in the real ONNX file later changes one class and nothing else.
4. **WebSocket for live, REST for history.** Per SRD 5.3, no polling for the risk
   score. History is fetched once and then extended from socket frames.
5. **One backend process.** No Redis, no Celery, no Docker. An asyncio task per
   concern, an in-process pub/sub hub, SQLite with WAL enabled. The SRD's
   non-functional target is local-only storage; anything more is unjustified weight.
6. **Empty state is a designed state, not an afterthought** (SRD 5.3). Device
   disconnected must look deliberate and must never crash a chart.

## 2. Architecture

```
ESP32 primary ──BLE──┐
ESP32-C3 aux  ──BLE──┤
                     v
              ble_gateway.py ──┐          (or simulator.py, same output)
                               v
                     signal_pipeline.py   confirm SQI, reshape
                               v
                        inference.py      ONNX / stub -> risk score
                               v
                        controller.py     mode state machine,
                               │          sustained-risk alerting,
                               │          foot-check scheduler
                   ┌───────────┼───────────┐
                   v           v           v
                 db.py     events.py   ble commands out
                (SQLite)   (pub/sub)   (mode, alert, aux wake)
                               v
                     api/ws.py + api/routes.py
                               v
                      React dashboard (Vite)
```

### 2.1 Backend module map

| File | Responsibility |
|---|---|
| `app/main.py` | FastAPI app, lifespan: open DB, start session, start source task, start controller |
| `app/config.py` | Settings from env: BLE UUIDs, thresholds, simulator toggle, DB path |
| `app/events.py` | In-process async pub/sub hub; every WebSocket client is a subscriber |
| `app/db.py` | Schema creation, migrations, all SQL. No SQL anywhere else |
| `app/models.py` | Pydantic models mirroring API_CONTRACT exactly |
| `app/ble_gateway.py` | `bleak` client, GATT subscribe, packet parsing, outgoing command queue |
| `app/simulator.py` | Synthetic ECG windows, battery drain, SQI dropouts, risk drift, `spike` |
| `app/signal_pipeline.py` | SQI gate, ring buffer of recent windows, normalization for the model |
| `app/inference.py` | `RiskModel` interface, `StubRiskModel`, `OnnxRiskModel` |
| `app/model_registry.py` | List/save/select uploaded `.onnx` files, persist the active selection across restarts |
| `app/controller.py` | Mode state machine, sustained-risk confirmation, foot-check scheduler |
| `app/api/routes.py` | Every REST endpoint in API_CONTRACT section 3, including model management |
| `app/api/ws.py` | `/ws/live`, hello frame, fan-out, disconnect cleanup |

### 2.2 Frontend module map

Follows SRD 5.2, extended with the primitives the design system needs.

```
src/
  main.jsx
  App.jsx                      routes + layout shell
  styles/tokens.css            every value from DESIGN_SYSTEM.md
  styles/global.css            reset, typography, grid, utilities
  lib/api.js                   fetch wrapper, base URL, error normalization
  lib/ws.js                    reconnecting socket, typed frame dispatch
  lib/format.js                time, duration, risk, temperature formatting
  hooks/useWebSocket.js        subscribe to live frames (SRD 5.2)
  hooks/useApi.js              REST wrapper hook (SRD 5.2)
  hooks/useLiveState.js        merges hello + frames into one state object
  components/
    ui/Card.jsx  Panel.jsx  Button.jsx  Badge.jsx  FieldRow.jsx
    ui/Toggle.jsx  SectionHeader.jsx  EmptyState.jsx  GridBand.jsx
    ECGWaveform.jsx            live scrolling trace, canvas
    RiskTrend.jsx              risk line chart, range selector
    ModeIndicator.jsx          mode badge + explanation
    AlertBanner.jsx            dismissible, acknowledges via REST
    FootCheckPanel.jsx         last result, history, countdown, manual trigger
    DeviceStatus.jsx           battery / BLE / SQI / leads-off / active risk model
    SessionSummary.jsx         duration, alerts, mode-time breakdown, export
  pages/
    Dashboard.jsx  ModelManager.jsx  FootCheck.jsx  Session.jsx
```

### 2.3 Two chart libraries, deliberately

The SRD asks for Recharts. Recharts is used for `RiskTrend` and the mode-time
breakdown, where it is a good fit. `ECGWaveform` is a **raw canvas**: a scrolling
100 Hz trace redrawn every frame will make Recharts allocate and diff thousands of
SVG nodes per second and drop frames. This is a deviation from SRD 5.3 and is
recorded as such in section 7 below.

## 3. Build phases

Each phase ends in something demonstrable. `UPDATES.md` is updated at the end of
every phase — that file is the project's status of record.

### Phase 0 — Scaffolding
Directory layout, `package.json`, `vite.config.js`, `requirements.txt`, `.gitignore`,
`.env.example`, README with run instructions. Both servers start and serve a blank
page and a health endpoint.
**Done when:** `npm run dev` and `uvicorn app.main:app --reload` both run clean.

### Phase 1 — Backend data plane
`config.py`, `events.py`, `db.py` (full schema + indexes + WAL), `models.py`,
`simulator.py`. The simulator produces windows, the pipeline gates on SQI, the stub
model scores them, rows land in SQLite.
**Done when:** the DB file grows with plausible rows while the server runs, and
`sqlite3` inspection shows sensible modes and scores.

### Phase 2 — Controller
Mode state machine with the four modes and their trigger conditions (SRD 4.4),
sustained-risk confirmation before an alert, and the deterministic foot-check
scheduler (24h normal, 8h elevated, 1h retry on invalid, battery gate).
**Done when:** unit tests drive synthetic risk/battery sequences and assert the mode
path, that no alert fires without a completed confirmation window, and that the
scheduler picks the right next time in all four branches.

### Phase 3 — API surface
Every REST endpoint and the WebSocket, exactly per API_CONTRACT. CORS for the Vite
dev origin. CSV export.
**Done when:** each endpoint returns the documented shape, and `websocat`/a browser
console shows `hello` followed by a live frame stream.

### Phase 4 — Design system in code
`tokens.css`, `global.css`, and every `ui/` primitive.
**Done when:** the real dashboard (Phase 5) is side-by-side indistinguishable
in feel from the reference: cream canvas, three card tones, pill buttons,
serif metrics, floating white panels. (A dedicated `/kit` gallery route was
built for this check and later removed once confirmed live in a browser --
the user didn't want a standing "style guide" page; see UPDATES.md. Check the
primitives directly against `docs/reference/*.jpg` in the assembled dashboard
instead.)

### Phase 5 — Dashboard
`ECGWaveform`, `RiskTrend`, `ModeIndicator`, `DeviceStatus`, `AlertBanner`, assembled
per the DESIGN_SYSTEM section 6 layout, wired to live data.
**Done when:** with the simulator running, the trace scrolls smoothly, the risk line
extends live, the mode badge changes as risk climbs, and an induced spike produces a
banner that acknowledges cleanly. Pull the backend down: the page degrades to the
empty state without a single console error.

### Phase 6 — Foot-check and session views
The lime foot-check card with countdown, history table, threshold flagging above
2.2 °C, and the manual trigger. The session view with mode-time breakdown and CSV
export.
**Done when:** a manual check round-trips (POST, then a socket result, then the row
appears and the countdown resets), and the exported CSV opens in Excel with correct
columns.

### Phase 7 — Hardware connection
`ble_gateway.py` against the real ESP32: GATT discovery, notification subscription,
packet parsing, command writes. A `GS_SOURCE=ble|simulator|auto` switch, where `auto`
falls back to the simulator when no device is found within the scan timeout.
**Done when:** `source: "ble"` appears in `/api/status` with real hardware, and the
same dashboard code that ran on simulated data runs on live data with no changes.

### Phase 8 — Hardening and acceptance
Walk SRD section 8 item by item, measure the section 6 latency targets with real
timestamps, fix what misses, and write the results into `UPDATES.md`.

**Dependency order.** 0 → 1 → 2 → 3 gates everything; 4 can start in parallel with 1
because it touches no backend code; 5 and 6 need both 3 and 4; 7 needs firmware and
can slip without blocking anything else; 8 is last.

## 4. Controller specification (implementation detail for Phase 2)

Thresholds live in `config.py` so they are tunable without a code change. Starting
values, to be adjusted once the real model's score distribution is known:

```python
RISK_LOW      = 0.30   # below this, eligible for Eco
RISK_ELEVATED = 0.55   # above this, escalate to Watch
RISK_ALERT    = 0.75   # above this, enter Verify and begin confirmation
CONFIRM_WINDOWS = 3    # consecutive Verify windows above RISK_ALERT before firing
ALERT_COOLDOWN_S = 300 # no re-fire within this period unless risk drops and returns
BATTERY_ECO_PCT  = 25  # below this, prefer Eco when risk permits
BATTERY_AUX_MIN  = 15  # below this, refuse an auxiliary wake
```

Mode transitions, evaluated once per scored window:

| From | Condition | To |
|---|---|---|
| any | `score >= RISK_ALERT` | `Verify` |
| any | `RISK_ELEVATED <= score < RISK_ALERT`, or risk rising over the last 3 windows | `Watch` |
| any | `score < RISK_LOW` and battery below `BATTERY_ECO_PCT` and SQI stable over 5 windows | `Eco` |
| any | otherwise | `Normal` |

`Verify` is sticky: it holds until either `CONFIRM_WINDOWS` are satisfied (fire the
alert, then drop to `Watch` and start the cooldown) or the score falls below
`RISK_ALERT` (drop to `Watch` without firing). **A single spike must never fire an
alert** — that behavior is the entire reason the false-alert-rate result in SRD
section 6 is defensible.

Foot-check scheduler, per SRD 4.4:

```
previous result normal   -> next check in 24h
previous result elevated -> next check in 8h   (elevated = delta_t > 2.2 C)
previous check invalid   -> retry in 1h
fire only when the scheduled time is reached AND battery_pct >= BATTERY_AUX_MIN
```

## 5. Testing

- **Backend unit:** `pytest` on the controller state machine (the priority — it holds
  the clinical logic), the foot-check scheduler branches, the SQI gate, and CSV
  export shape.
- **Backend integration:** spin the app with the simulator via `TestClient`, assert
  that rows are persisted and that the WebSocket delivers `hello` then a risk update.
- **Frontend:** Vitest on `lib/format.js` and the socket-frame reducer in
  `useLiveState`. Components are verified visually against the reference frames
  rather than snapshot-tested; snapshot tests on a design-driven UI mostly test the
  snapshots.
- **Manual acceptance:** the SRD section 8 checklist, executed and recorded in
  `UPDATES.md` with actual measured numbers, not ticks.

## 6. Running it

```bash
# backend
cd backend
python -m venv .venv && .venv/Scripts/activate      # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# frontend
cd frontend
npm install
npm run dev            # http://localhost:5173
```

Environment (`backend/.env`, see `.env.example`):

```
GS_SOURCE=simulator        # simulator | ble | auto
GS_DB_PATH=./data/glucosentry.db
GS_ENABLE_SIM=1
GS_MODEL_PATH=             # empty -> StubRiskModel; set to an .onnx to use the real model
```

## 7. Deviations from the SRD, and why

Each of these is a deliberate choice, recorded so the review can defend it rather
than be surprised by it.

1. **`ecg_sample` frames became `ecg_window` frames** (SRD 4.3). Sending whole windows
   holds the socket at about one message per second instead of a hundred, and the
   waveform component wants a contiguous window anyway.
2. **The ECG chart is canvas, not Recharts** (SRD 5.3). Recharts remains in use for
   the risk trend and mode breakdown. A 100 Hz scrolling trace in SVG drops frames.
3. **A `sessions` table was added** (SRD 4.5). The SRD's own Session view requires a
   session duration and a mode-time breakdown, which nothing in the given schema can
   answer. The four specified tables are otherwise unchanged and gain a
   `session_id` foreign key.
4. **Raw ECG samples are not persisted.** The specified `ecg_windows` table stores
   only derived values, and full-rate capture would add roughly 70 MB per day with no
   requirement behind it. Recent windows live in an in-memory ring buffer. An opt-in
   NDJSON sink can be added if the evaluation needs raw capture.
5. **`GET /api/session/summary` was added.** Without it, the Session view would have
   to pull the entire window history and aggregate in the browser.
6. **`POST /api/sim/*` was added,** development-only and env-gated. SRD section 8
   requires demonstrating the alert path via an induced test signal; this is that
   mechanism.

## 8. Risks

| Risk | Mitigation |
|---|---|
| Firmware slips and there is nothing to demo | The simulator path is built first and is never removed |
| The real model's score distribution invalidates the thresholds | Thresholds are config, not constants; recalibrate in one file |
| BLE throughput will not sustain 100 Hz windows | Windows are already decimated and gated on SQI on-device; if it still saturates, raise the window length before lowering the rate |
| SQLite write contention with 1 Hz inserts plus reads | WAL mode, single writer task, batched commits |
| The dashboard looks like a generic admin template | `DESIGN_SYSTEM.md` is binding, and Phase 4 gates on a side-by-side check against the reference frames |
