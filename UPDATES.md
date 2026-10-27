# UPDATES — GlucoSentry dashboard and connectivity

Status of record. Every agent updates this at the end of every phase, and whenever a
decision changes. Newest entry at the top of the log. Do not tick a box that is not
actually true in the code.

---

## Current state

| | |
|---|---|
| **Phase** | 6 — Foot-check and session views (foot check done; session views not started) |
| **Last updated** | 2026-10-27 |
| **Next action** | Phase 6: SessionSummary (mode-time breakdown, CSV export button). Evaluate the trained model on real labelled ECG (it has only been checked on synthetic ECG; see the 2026-10-15 simulator entry) |
| **Blocked on** | Nothing |
| **Runnable end to end?** | Yes, verified live in an actual connected browser (Claude-in-Chrome), not just via curl: navigated the real dashboard, scrolled through every panel, clicked through to the Model page and back, uploaded a real ONNX file through the actual file input, and confirmed zero console errors throughout. The main dashboard (ECG waveform, risk trend, mode indicator, device status, alert banner) and a new Model management page (upload/select/reset a trained `.onnx` risk model, applied to live data immediately) are both built, tested, and verified working end to end. Foot-check panel and session summary views do not exist yet. `/kit` (the Phase 4 style-guide gallery) was removed entirely at the user's request -- the design tokens it was built to check now only need to look right in the real dashboard, which has been visually confirmed. |

## Phase checklist

Phase definitions and their "Done when" criteria are in `docs/PLAN.md` section 3.

- [x] **Phase 0 — Scaffolding.** Layout, `package.json`, `vite.config.js`,
      `requirements.txt`, `.gitignore`, `.env.example`, README. Both dev servers run.
- [x] **Phase 1 — Backend data plane.** `config`, `events`, `db`, `models`,
      `simulator`, `signal_pipeline`, `inference` stub. Rows persist to SQLite.
- [x] **Phase 2 — Controller.** Four-mode state machine, sustained-risk confirmation,
      foot-check scheduler, unit tests covering all branches.
- [x] **Phase 3 — API surface.** Every REST endpoint plus `/ws/live`, per
      `docs/API_CONTRACT.md`. CORS. CSV export.
- [x] **Phase 4 — Design system in code.** `tokens.css`, `global.css`, `ui/`
      primitives. Originally checked via a `/kit` gallery route; that page has
      since been **removed** at the user's request (it read as an unnecessary
      "style guide" rather than a feature) once the tokens were confirmed
      correct in the real dashboard via a live browser session.
- [x] **Phase 5 — Dashboard.** ECG waveform, risk trend, mode indicator, device
      status, alert banner, wired live. Degrades cleanly when the backend is down.
      Visually verified in a real browser (see log below) -- found and fixed a
      clipped Y-axis label bug in the process.
- [x] **Additional feature (user-requested, not in the original 8 phases) —
      Model management.** A `/model` page to upload a trained `.onnx` risk
      model through the UI, list previously uploaded ones, switch between them
      or revert to the stub, all without a backend restart. See
      `docs/API_CONTRACT.md`'s "Model management" section and the log below.
- [ ] **Phase 6 — Foot-check and session views.** Lime foot-check card with
      countdown and manual trigger, history table, session summary, CSV export.
- [ ] **Phase 7 — Hardware connection.** `ble_gateway` against real ESP32 hardware,
      `GS_SOURCE=ble|simulator|auto`.
      *Partial (2026-10-13):* `GS_SOURCE=ble` works against the real ESP32 (status
      `source: "ble"`, live windows, mode commands acknowledged by the device), plus an
      interim `GS_SOURCE=serial`. Unticked until an accepted-window ECG and the alert
      LED path are verified on hardware -- see log.
- [ ] **Phase 8 — Hardening and acceptance.** SRD section 8 walked item by item with
      measured numbers recorded below.

## SRD acceptance criteria (section 8)

Record the measured result, not just a tick.

- [ ] Live ECG visible on the dashboard within 3 s of device power-on — *measured: —*
- [ ] Risk score updates continuously and visibly changes controller mode at the
      defined thresholds — *measured: —*
- [ ] Vibration alert fires only after sustained-risk confirmation, demonstrated via
      an induced test signal — *measured: —*
- [ ] Auxiliary node stays asleep unless explicitly woken; the wake-to-result cycle
      completes and logs correctly — *measured: —*
- [ ] Session export produces a usable CSV for the evaluation report — *measured: —*
- [ ] Battery-life comparison, adaptive versus fixed-rate, produces a reportable
      number — *measured: —*

## Non-functional targets (SRD section 6)

- [ ] End-to-end latency, ECG sample to dashboard risk update: target < 3 s — *measured: —*
- [ ] End-to-end latency, sustained risk to alert fired: target < 5 s — *measured: —*
- [ ] False-alert rate measured and reported — *measured: —*

## Decisions log

Append here when something is decided, so a later session does not reopen it.

| Date | Decision | Why |
|---|---|---|
| 2026-09-20 | `/kit` (the design-system gallery page) was removed entirely | User feedback: it read as an unnecessary "style guide" page rather than a feature. Its job (checking the tokens look right) was already done via a live browser check of the real dashboard, so nothing was lost by deleting it |
| 2026-09-20 | A model can be uploaded/selected/reset at runtime from a `/model` page, not only via `GS_MODEL_PATH` + a restart | User-requested: they have trained models separately and want to plug them into the running dashboard without editing config files. The selection is persisted to disk so it survives a restart, and `GS_MODEL_PATH` remains the one-time startup default for a machine that has never had a UI selection made |
| 2026-09-20 | Model upload validates by actually attempting to load the file (`OnnxRiskModel(path)`) before ever touching `state.model`, rather than going through `inference.load_risk_model`'s built-in fallback | The first version called `load_risk_model` unconditionally and always assigned its result to `state.model`. `load_risk_model` always returns *some* model, falling back to the stub internally on failure, which meant uploading a corrupt `.onnx` file silently replaced a perfectly good, already-active model with the stub instead of leaving it alone. Found by deliberately testing the failure path, not by a user report. Guarded permanently by `test_corrupt_upload_does_not_disturb_a_working_active_model` |
| 2026-09-20 | Alert banner uses white background + colored left rule + a `Badge`, not a solid danger-colored fill | `docs/DESIGN_SYSTEM.md` section 8 explicitly says "don't flood a whole card in a status color" -- the first draft did exactly that. Status stays carried by the mode-color badges only, consistent with how the rest of the UI uses color |
| 2026-09-20 | `ECGWaveform` bails out of its draw effect entirely if `canvas.getContext('2d')` returns `null` | Without the guard it threw on every animation frame once the context was unavailable (confirmed via jsdom in the test suite, but the same failure mode exists in any real browser situation where a 2D context can't be obtained). The uncaught per-frame exception also corrupted an unrelated test's async timing in the same run |
| 2026-09-20 | `POST /api/controller/mode` accepts `mode` as a plain `str`, not a `Mode` Literal, in its request model | A Pydantic `Literal` would make FastAPI reject an invalid mode with a 422 before the route body runs, but `docs/API_CONTRACT.md` documents a 400 for that case. Validating membership manually in the route body preserves the documented status code |
| 2026-09-20 | CSV export uses nested correlated subqueries, not a LEFT JOIN, to attach the nearest alert/foot-check/status row to each ECG window | A range-based LEFT JOIN multiplied rows (device_status is dense, ~1 Hz, so an `ABS(diff) < 5.0` join condition matches several rows per window). The straightforward correlated-subquery fix then failed against this project's SQLite (3.35.5), which resolves an outer-query column in a subquery's WHERE/SELECT list but not in its ORDER BY. Fixed with a nested subquery that computes the distance as a plain column first. See `db.py`'s `export_rows` docstring |
| 2026-09-20 | `last_alert_ts` sentinel is `None`, not `0.0` | `0.0` is indistinguishable from a real epoch timestamp near the Unix epoch; a session starting near t=0 (e.g. relative timestamps in tests) would look like it's within the cooldown of a phantom prior alert. Found via failing cooldown tests in `test_controller.py` |
| 2026-09-20 | `StubRiskModel` weights amplitude at 0.85 and baseline at 0.5 (was 0.4/0.6) | The original weighting had a mathematical ceiling of 0.67, always below the default `risk_alert` of 0.75 — meaning the alert path could never be demonstrated against the simulator regardless of tuning. Guarded permanently by `test_stub_model_ceiling_clears_risk_alert_threshold` |
| 2026-09-20 | ECG windows are normalized by a fixed reference divisor (`config.ecg_normalize_scale`), not per-window z-score | Per-window z-score normalization is scale-invariant to the window's own amplitude, which erased the exact signal an induced spike or real amplitude anomaly needs to be visible as. Found and fixed during Phase 1 by writing a test that asserted a spike must raise the risk score — see the log entry below | 
| 2026-09-20 | Simulator is a permanent first-class data source, not throwaway scaffolding | Lets the full chain run and be demonstrated before firmware exists; SRD build step 6 asks for exactly this |
| 2026-09-20 | ECG waveform uses raw canvas; Recharts is kept for the risk trend | A 100 Hz scrolling trace in SVG drops frames. Deviation from SRD 5.3, recorded in `docs/PLAN.md` section 7 |
| 2026-09-20 | WebSocket sends `ecg_window` frames rather than the SRD's `ecg_sample` | Holds the socket at about 1 message/s instead of 100; the waveform wants a contiguous window anyway |
| 2026-09-20 | Added a `sessions` table and `GET /api/session/summary` | The SRD's own Session view needs duration and a mode-time breakdown, which the specified schema cannot answer |
| 2026-09-20 | Raw ECG samples are not persisted; recent windows live in an in-memory ring buffer | Roughly 70 MB/day for no stated requirement. Add an opt-in NDJSON sink if the evaluation needs raw capture |
| 2026-09-20 | Visual language taken from `ruul-a6e6a6.mp4`, tokenized in `docs/DESIGN_SYSTEM.md` | Colors were sampled from extracted video frames, so they are exact rather than eyeballed |
| 2026-10-13 | Add an interim `GS_SOURCE=serial` source (ESP32 over USB) ahead of BLE; BLE (Phase 7 proper) follows as the next step | Hardware (ESP32 + ADS1115 + AD8232 + MPU6500) is on the bench and streaming over USB, while the BLE firmware doesn't exist yet. Serial gets real data onto the dashboard now through the same `_handle_window` sink, so nothing downstream changes when BLE replaces it. The firmware streams raw 250 Hz samples, so decimation to 100 Hz and MPU-based SQI gating run backend-side in `serial_gateway.py` for now (contract section 2.4). `battery_pct` became nullable rather than reporting a made-up 100% for a bus-powered board, and `leads_off` now carries the real AD8232 state |

## Open questions

Answer these as the information arrives; do not block on them.

1. **BLE UUIDs** are placeholders in `app/config.py` until firmware bring-up fixes them.
2. **Model score distribution** is unknown, so the controller thresholds in
   `config.py` are provisional and will need recalibration once the real ONNX model
   is available.
3. **ONNX input shape** — `inference.py` assumes a `(1, 1, N)` float32 window.
   `signal_pipeline._reshape` now scales by a *fixed* reference divisor
   (`config.ecg_normalize_scale`, currently 1000.0, calibrated against the
   simulator's synthetic amplitude) rather than per-window z-score, specifically
   so amplitude information survives into the model input — see the Phase 1 log
   entry below for why the original per-window approach was a bug. Confirm both
   the shape and the normalization strategy against how the real model was
   trained; if it was trained on per-window-normalized data, this divisor
   approach will need to change to match, not just its value.
4. **Auxiliary wake-to-result latency** on real hardware is unmeasured; the
   `eta_s: 6` in `POST /api/foot/request` is a placeholder.

## Log

### 2026-10-27 — ECG BLE gateway no longer spins when a scan fails

Seen live during the 2026-10-20 demo: after the ECG node's link dropped, the
backend logged "no GlucoSentry node found" about 8,000 times in 9 seconds. A
failed scan (BlueZ "Operation already in progress" while the foot gateway was
scanning) returns instantly, and `BleGateway.run` went straight back to scanning
with no pause. The loop never yielded, so it also starved the rest of the event
loop while it spun.

- New `ble_rescan_pause_s` (1.0 s) in `config.py`; the ECG gateway waits that long
  after a scan that finds nothing. The foot gateway already paused 1.0 s, hard-coded;
  it now uses the same setting.
- "No node found" is logged once per outage instead of once per scan.
- New test `test_failed_scans_pause_and_log_once`. Against the old code it hangs
  (killed by a 60 s timeout); with the fix it passes. Backend suite: 101 pass.
- Not changed: the foot gateway still logs "aux: scan failed" once per second while
  the adapter is busy. Separately, if the ECG node is paired in BlueZ, Linux can
  connect to it by itself so it stops advertising; `bluetoothctl disconnect` (or
  `remove`) frees it.

### 2026-10-16 — Firmware moved into the repo

Both ESP32 projects now live under `firmware/`: `ecg-node/` (was
`~/esp32-projects/glucosentry-firmware`) and `foot-module/` (was
`~/esp32-projects/glucosentry-aux-firmware`). The old paths are symlinks on the dev
machine, so existing commands still work. Both build from the new location.
`firmware/README.md` covers build and flash commands and wiring. AGENTS.md's repo map
is updated. PlatformIO build output (`.pio/`) is ignored.

### 2026-10-15 (night) — Foot module deep sleep with host-set wake times

**Done, verified on hardware.** The foot module now deep-sleeps between check-ins,
matching step 8 of the invention disclosure ("the host tells the foot module to go
back to sleep until the next scheduled wake-up").

- **Firmware** (`~/esp32-projects/glucosentry-aux-firmware`, outside this repo):
  deep sleep on an RTC timer, or a BOOT-button wake (ext0, GPIO0). GPIO32, which
  powers the dividers, is held low through sleep. On waking, the node advertises for
  20 s. It has new characteristics `sleep` (uint32 seconds) and `node_info` (wake
  reason, boot count, last sleep). With no host, or no `sleep` command, it sleeps 60 s
  and retries.
- **Backend:** `AuxGateway` now meets the node at each check-in instead of holding a
  link. `controller.foot_checkin_should_read` (due, manual, or button wake, gated on
  battery) and `controller.foot_sleep_seconds` (until the next check, clamped to
  5–30 s) decide what happens; the node is always sent back to sleep.
  `POST /api/foot/request` queues the check for the next wake (a 503 only when the
  node is missing). The status gains `aux_state` (awake/asleep/missing),
  `aux_next_wake_ts` and `aux_check_queued`. Contract and POLICIES updated.
- **UI:** the foot card shows "Asleep -- checks in 18s" and says when a request is
  queued; the engineering scheduler panel shows next check-in, wake reason and
  check-in count.
- **Measured on the bench:** timer check-ins every ~33 s (30 s sleep plus boot and
  connect). A queued manual check ran at the next check-in: **227 ms from check-in to
  result**, then back to sleep about 90 ms later.
- Tests: backend 100 passed (10 new in `test_aux_sleep.py`), frontend 49 passed.
- **FIG. 1 block diagram** for the disclosure (labeled, and numbered with a key),
  black-and-white line art, in `~/Downloads/GlucoSentry_Fig1_block_diagram_*.png/.svg`.

**Fell short / open:**
- The bench dividers are still wired to 3V3, not GPIO32, so they draw ~6 mA through
  sleep until the wire is moved (left side, row 12 → row 18).
- Sleep current is not measured. The dev board's USB-serial bridge, LED and
  regulator draw milliamps regardless, so microamp figures need a bare module.
- The simulated foot module doesn't emulate sleep; it stays always reachable.
- BOOT-button wake is implemented but not yet pressed in a test.

### 2026-10-15 (evening) — Simulator rebuilt: realistic ECG, scenarios, simulated foot module, dashboard controls

**Done, verified live** with `GS_SOURCE=simulator GS_AUX_SOURCE=simulator` and the
trained ONNX model.

- **Realistic synthetic ECG** (`app/simulator.py`): Gaussian P/Q/R/S/T beats (the
  ECGSYN idea), respiratory heart-rate variability, baseline wander, 50 Hz pickup and
  noise, about 1200 counts per mV. It replaces a sine-plus-spike that had no P or T
  waves. Plotted and checked by eye.
- **Scenarios** (`POST /api/sim/scenario`): `motion` (EMG plus baseline steps,
  accelerometer over the limit), `leads_off` (flat, leads-off flag set), `hypo` (a
  **test pattern** ramping in tachycardia, QT prolongation, T-wave flattening and ST
  depression) and `spike` (the legacy ×3 amplitude). Plus `POST /api/sim/settings`
  (heart rate, battery, random artifacts) and `GET /api/sim/state`. Contract updated.
  Random artifact windows are now actually corrupted, not just flagged.
- **Simulated foot module** (`SimulatedFootModule`): the same `connected` / `eta_s` /
  `read()` interface as `AuxGateway`, so simulated and real checks share one code path.
  `run_simulated_foot_check` is gone. Modes are random, normal, elevated, invalid and
  offline (`POST /api/sim/foot`). Offline behaves like an out-of-range real module
  (503, `aux_connected: false`).
- **Dashboard:** a Simulator panel at the top of the Engineering view (scenario cards
  with the policies each one exercises, heart-rate and battery presets, the artifact
  toggle, pause/resume, foot-module mode). A "Simulated data" notice on both views
  says which streams are synthetic.
- **Live run:** with the hypo scenario, the trained model stayed near 0.00 until about
  75% pattern strength, then reached Verify (0.88). One dip to 0.59 reset the
  confirmation (P4), then three consecutive windows ≥ 0.75 **fired the alert**. Foot
  modes, live: normal → `scheduled_24h`, elevated (ΔT 2.69) → `scheduled_8h`, invalid →
  `retry_1h`, offline → 503.
- Tests: backend 90 passed (11 new in `test_simulator.py`), frontend 48 passed.
  `test_simulator_reads_about_72_bpm` now turns random artifacts off, because artifact
  windows really are corrupted now.

**Correction to the earlier entries today:** the finding that "the trained model does
not discriminate" (scores swinging 0.00–0.97 on normal ECG) was caused by the old
simulator's non-ECG waveform, not by the model. On the realistic synthetic ECG
(4 seeds, 244 scored windows each), the model scores:

| Input | Mean score | Windows ≥ 0.75 |
|---|---|---|
| Normal shape, 72 bpm | 0.03 | 0% |
| Normal shape, 97 bpm and 120 bpm (exercise-like) | 0.00 | 0% |
| Hypo pattern shape at 72 bpm | 0.92 | 96% |
| Hypo pattern shape at 97 bpm | 0.95 | 100% |

So it responds to ECG morphology, not heart rate. **Still open:** all of this is
synthetic. The hypo pattern was written from literature descriptions, not taken from
recordings, and the model's performance on real labelled ECG is unknown (the
notebook saved no evaluation output). The thresholds were not tuned to these results.

### 2026-10-15 (later) — Patient/Engineering views, diagnostics endpoint, policies, training-filter parity

**Done, verified live** (headless Chrome screenshots of all three pages against the
running backend, with both BLE nodes connected).

- **Patient view** redesigned: the risk card shows "--" with the reason (leads off,
  moving, warming up with seconds left, disconnected), never a placeholder 0.00. A row
  of three tiles (Heart rate, Activity, System summary), then the trend, then the
  lime foot check. Fixed the clipped serif titles: `plain` cards had zero padding
  plus `overflow: hidden`.
- **Engineering view** (`?view=engineering`): raw stream, links, the signal pipeline
  (acceptance bar split by leads-off and motion, motion against threshold, last-window
  ADC stats), the model (buffer seconds, input spec, output, last score, inference
  time), the controller (threshold scale with the backend's mode highlighted, Verify
  confirmation dots, recent scores, cooldown) and the foot scheduler (rule table with
  the backend's last `action` highlighted, raw last reading). Each panel links to the
  policy that governs it.
- **`GET /api/diagnostics`** (contract updated): one read-only snapshot of the
  objects that make the decisions. Session counters were added to `AppState`.
  `RiskModel.context()` reports buffer state. The status gains `risk_ready_in_s`.
  **`/api/risk/current` now returns `score: null`** instead of a fake `0.0` before the
  first scored window. The `foot_check_result` frame carries `action`.
- **`docs/POLICIES.md`** plus an in-app **/policies** page with live numbers: the role
  of each part, why the MPU6050 matters, policies P1–P10, and the failure-mode table.
- **Found and fixed: the bench ECG firmware does not filter.** Neither the SRD's
  0.5–40 Hz band-pass nor the 50 Hz notch is implemented on the device (it only
  decimates), while the model was trained on filtered ECG. `app/ecg_filter.py`
  reproduces the notebook's `filtfilt(butter(4))` + `iirnotch(50, 30)` at zero phase
  in numpy (no scipy in the venv). It is verified: −3 dB at 0.5 Hz, unity passband,
  null at 50 Hz. `OnnxRiskModel` applies it before z-scoring (`model_prefilter`).
- Tests: backend 79 passed, frontend 47 passed.

**Fell short / open:**
- With the filter applied, the model **still** swings 0.004–0.965 between windows
  that share 29 of their 30 s (simulated normal ECG, mean 0.55). Preprocessing
  mismatch is ruled out as the cause; the model itself needs evaluation and
  retraining.
- The ECG firmware still doesn't filter on-device as the SRD says. The host filter
  covers the model input only; the live waveform stays unfiltered.
- The UI was checked with headless screenshots, not interactively (the Chrome
  extension was not connected).

### 2026-10-15 — Real foot module over BLE, trained ONNX model wired in, foot-check card

**Done, verified on hardware.** Both ESP32 nodes ran at once over BLE: the primary
(ECG) via `ble_gateway`, and the new foot module via the new `app/aux_gateway.py`
(`GS_AUX_SOURCE=ble`). A manual check from `POST /api/foot/request` woke the real
node and returned L 21.85 °C / R 22.18 °C, delta 0.33 °C, valid. The scheduler set
`scheduled_24h` and the row was persisted. The firmware is
`~/esp32-projects/glucosentry-aux-firmware` (outside this repo, like the primary's).

- **Contract (`docs/API_CONTRACT.md`):** `foot_temp_result` is now pinned to 13 bytes
  (`<fffB`). The status gains `aux_source`. Foot-check records and frames gain
  `elevated`, decided by `controller.is_foot_check_elevated`, so the UI never compares
  `delta_t`. `POST /api/foot/request` returns 503 when the real module is out of
  range. The bench node idles awake (dividers unpowered, radio advertising), because
  an ESP32 in deep sleep cannot receive a BLE write. True deep sleep needs a timer or
  GPIO wake, which is still open.
- **Model:** the D1NAMO CNN+BiLSTM (`glucosentry_cnn_bilstm.onnx`) takes exactly
  `(batch, 1, 7500)`, which is 30 s at 250 Hz, z-scored per window, and outputs a
  **logit**. Loaded as before, every `predict` would have raised. `OnnxRiskModel`
  now buffers 30 s of accepted windows, resamples 100 → 250 Hz, z-scores, applies a
  sigmoid to `*logit*` outputs, and returns `None` until the buffer is full.
  `main.py` calls `model.reset()` on every rejected window, so the model never scores
  across a gap. That means **no risk score for the first 30 s and for 30 s after any
  motion or leads-off window.** Dynamic-length models behave as before.
- **Frontend:** a lime `FootCheck` card (last result, countdown, foot-module state,
  history with backend-decided Normal/Elevated/Invalid badges, and the manual
  trigger, disabled when the real module is out of range).
- **Tests:** backend 74 passed (4 new: buffering, reset, packet parsing), frontend 43
  passed (3 new). The simulator path is unchanged and still the default for both
  sources.

**Fell short / open:**
- **The trained model does not yet discriminate on our signal.** On simulated normal
  ECG it scored 0.05–0.96 window to window (mean 0.68, 30 windows), and pure Gaussian
  noise scored 0.11–0.59. With the current thresholds (0.30 / 0.55 / 0.75), normal
  ECG will sit in Watch and can fire alerts. The training notebook saved no outputs,
  so its validation F1 is unknown. The model needs evaluation (and probably more
  training) before its alerts mean anything. Thresholds were deliberately not retuned
  to hide this.
- The thermistors on the bench are 100 Ω NTCs (marked 101), used with 1 kΩ fixed
  resistors and Beta 3950 assumed. Readings are uncalibrated in absolute terms; left
  and right agree within about 0.5 °C, which is what delta-T needs.
- Not checked in a browser this session (the Chrome extension was not connected). The
  page and modules serve, the API answers through the stack, and component tests
  pass.

### 2026-10-13 — BLE gateway live on hardware; heart rate, activity and leads-off UI; two bugs fixed

**BLE (Phase 7).** Firmware (outside this repo, `esp32-projects/glucosentry-firmware`)
is a GATT server per contract 2.1, advertising as `GlucoSentry-ECG`; it decimates
250 → 100 Hz and computes SQI on-device, and still streams the serial format so
`GS_SOURCE=serial` keeps working with the same build. Contract 2.1 now fixes the
details left open: MTU ≥ 211, per-window order `sqi_flag → ecg_data → device_status`,
uptime timestamp re-stamped by the host, battery 255 = unmeasured, a `motion` field in
`device_status` (now 5 bytes), `mode` echoed back. `app/ble_gateway.py` scans by
service UUID, pairs packets into windows, reconnects forever, and writes
`controller_cmd` on mode changes (from `risk_update` *and* `status` frames — the latter
found necessary because with leads off no `risk_update` frames exist) and `alert_cmd`
on alerts. `GS_SOURCE=auto` now really scans and falls back to the simulator.

Measured on hardware, no electrodes attached:
- Scan finds the node; `/api/status` → `source: "ble", connected: true`, real
  leads-off and motion (0.02–0.03 m/s² on a desk); full 100-sample windows.
- 60 windows in 60 s over a watched minute with no drops.
- Backend restart (host-side drop) → device re-advertises → reconnected in ~2 s.
- `POST /api/controller/mode {"mode":"Watch"}` → device echoed `Watch` in
  `device_status`.
- One unexplained link stall ~18 s into the very first connection (stall timeout was
  3 s then, now `ble_stall_timeout_s = 5`). Not reproduced since; watch for it.
- bleak on BlueZ reports `mtu_size = 23` as a placeholder even when a larger MTU is
  negotiated — the gateway now checks real packet length instead of trusting it.

Not verified on hardware: `alert_cmd` → LED blink (needs a real alert, i.e. accepted
windows); unit-tested only.

**UI.** Heart rate card (backend `heart_rate.py` R-peak estimate, null until 8 s of
clean signal, resets on any rejected window), Activity card (backend `moving` verdict
and `motion_ms2`), ECG panel shows an explicit "Leads off" state and drops the
leads-off zeros so the scale recovers instantly on reattach, plus a "window rejected"
label. Risk trend moved to a full-width row. Contract section 3/4 updated first.

**Bugs fixed.**
- `tests/test_db_export.py` never closed its DB → aiosqlite's non-daemon thread hung
  every full `pytest` run after all tests passed. Now a closing fixture; full suite
  exits in ~1 s.
- `simulator.py` computed the QRS phase from the per-window index, restarting the
  rhythm every second: a doubled beat at each window boundary and an effective 60 bpm
  instead of the intended 72. Found by the new heart-rate tests; now uses a global
  sample index.

Tests: backend 70 passed (new: test_ble_gateway 15, test_heart_rate 5), frontend 40
passed (new: LiveVitals.test.jsx 9, format 4). Frontend not seen in a browser this
session (extension unavailable) — verified by tests and a production build only.

### 2026-10-13 — Interim USB serial source: real ESP32 data on the dashboard (Phase 7 partial)

Hardware on the bench: 30-pin ESP32 DevKit (ESP32-D0WD-V3), ADS1115 (0x48) reading
the AD8232 output on A0, AD8232 LO+/LO− on GPIO32/33, and an MPU6050-branded board
that is actually an **MPU6500** (`WHO_AM_I = 0x70` -- the Adafruit MPU6050 library
rejects it, so the firmware reads registers directly). Firmware streams
`ecg_mV,leads_off,ax,ay,az` at 250 Hz over USB at 921600 baud; it lives outside this
repo, per AGENTS.md.

Done:
- Contract first: `docs/API_CONTRACT.md` section 2.3 (`leads_off` field, nullable
  `battery_pct`), new section 2.4 (serial line format and processing), and the
  `source` enum gained `"serial"`.
- `app/serial_gateway.py`: parses lines, groups 250 samples per 1 s window, converts mV
  back to ADS1115 counts, decimates 250 → 100 Hz (3-tap smoother + interpolation),
  SQI 0 on leads-off or accel-magnitude std above `serial_motion_sqi_threshold_ms2`.
  Auto-detects the port, reconnects forever, flips `connected` false on loss.
- `main.py` wires it behind the same `_handle_window` sink; `leads_off` now flows to
  `/api/status` and `device_status` rows instead of the hard-coded `False`. No
  simulator object is created for `serial`, so `/api/sim/*` answers 400 honestly.
- Null battery is treated as sufficient in the controller (never forces Eco), the
  foot-check scheduler and `POST /api/foot/request`.
- Frontend: `DeviceStatus` labels `serial` as "USB serial". No other UI change needed.

Verified (measured, not assumed):
- `tests/test_serial_gateway.py`: 10 passed. Every other test file passes unchanged
  (controller 23, db_export 3, model_registry 11, phase1 4, phase2 2). Frontend vitest:
  27 passed.
- Live, with the board attached and no electrodes on: `/api/status` →
  `source: "serial", connected: true, leads_off: true, battery_pct: null, sqi: 0`;
  `/ws/live` delivers `hello`, `status` and 100-sample `ecg_window` frames at ~1/s
  (9 windows in 9.3 s); `session/summary` counts them all as rejected, as it should.

Not yet verified -- do not tick:
- An accepted (sqi=1) window from real electrodes; none were available. The motion
  threshold (1.0 m/s²) and `ecg_normalize_scale` are still provisional against real
  ADS1115 counts (open question 3).
- The dashboard in a browser on serial data (backend + WebSocket checked directly).

Found, pre-existing, not fixed: `pytest` on `tests/test_db_export.py` passes its 3 tests
but the process never exits (reproduced on the unmodified commit in a clean worktree),
so a full `pytest` run hangs at the end. Likely an un-closed aiosqlite connection in
that test file.

### 2026-09-20 — Live browser verification, /kit removed, Model management page added; two more real bugs found and fixed
This entry covers a follow-up session using an actually-connected browser
(Claude-in-Chrome), not just curl/pytest, plus a new user-requested feature.

**Live browser verification of Phase 0-5 work.** Started both servers and
drove the real dashboard in Chrome: confirmed the live ECG canvas animates
smoothly, the risk trend chart updates, mode badges change live, and the
device status panel tracks battery drain and connection state in real time.

- **Bug found: `/kit`'s navigation was a dead end.** The gallery page had no
  link back to the dashboard -- the user got stuck on it. (This became moot
  once `/kit` was removed entirely later in the session, per user feedback
  that it was an unnecessary page; see below.)
- **Bug found: `RiskTrend`'s Y-axis labels were clipped.** A screenshot of the
  live dashboard showed axis labels reading just "0", "5", "0", "5", "0"
  instead of "1.00", "0.75", "0.50", "0.25", "0.00". Root cause: the chart's
  `margin.left` was `-16` (intended to pull the axis tight against the
  panel edge) combined with a `YAxis width={32}` too narrow for 4-character
  labels like "0.75" -- together they pushed the tick text past the Panel's
  edge and clipped it. Fixed: `margin.left: 0`, `YAxis width={40}`. Confirmed
  fixed with a second screenshot showing full labels.

**`/kit` removed entirely**, per direct user feedback that a design-system
"style guide" page wasn't wanted -- "keep everything functional and neat."
Deleted `pages/ComponentGallery.jsx`; `App.jsx` now only routes between the
real Dashboard and the new Model page (below). The Dashboard's link to it was
replaced with a link to `/model`.

**New feature, user-requested: Model management (`/model` page).** The user
has trained ML models separately and wanted a way to plug a trained model into
the running dashboard through the UI rather than only by editing
`GS_MODEL_PATH` and restarting. Built:

- Backend: `app/model_registry.py` (list/save/select/delete files under
  `backend/models/`, persist the active selection to
  `backend/data/model_selection.txt` so it survives a restart), four new
  routes (`GET /api/model/list`, `POST /api/model/upload`, `POST
  /api/model/select`, `POST /api/model/reset`), a `model` field added to
  `GET /api/status` and the WebSocket's hello/status frames (`RiskModel.name`
  in `inference.py`, e.g. `"Stub (heuristic)"` or `"ONNX: risk_model.onnx"`),
  and `main.py`'s startup now checks the persisted selection before falling
  back to `GS_MODEL_PATH`.
- Frontend: `pages/ModelManager.jsx` (upload via a hidden file input, a list
  of previously uploaded models each with a "Use this" button, a "Revert to
  stub" button, and a live status message), plus `lib/api.js` additions
  (`uploadModel`, `listModels`, `selectModel`, `resetModel`) and a fix to the
  shared `request()` helper, which previously forced a
  `Content-Type: application/json` header onto every request -- fine for JSON
  bodies, but it would have silently broken the multipart file upload by
  overriding the browser's own boundary-bearing Content-Type. Also added a
  "Risk model" row to `DeviceStatus` so the active model is visible on the
  main dashboard too, not just on the Model page.
- "Compare with real-time data" needed no separate mechanism: the backend's
  existing per-window pipeline (`signal_pipeline` -> `inference` ->
  `controller`) already reads `state.model` on every tick, so swapping the
  model *is* swapping what scores the live stream -- confirmed by watching
  the dashboard's risk score visibly change immediately after a model switch.

**One real bug found and fixed while hand-testing the failure path (not left
for later):** the first version of the upload/select logic
(`routes.py`'s `_apply_model`) called `inference.load_risk_model()`
unconditionally and always assigned its result to `state.model`.
`load_risk_model` always returns *some* model, silently falling back to the
stub internally on any load failure -- which meant uploading a corrupt
`.onnx` file replaced a perfectly good, already-active model with the stub
instead of leaving it alone. Verified the bug directly: uploaded a real,
working ONNX model, confirmed `GET /api/status` showed it active, then
uploaded a corrupt file and watched the active model incorrectly fall back to
"Stub (failed to load ...)". Fixed by loading `OnnxRiskModel` directly inside
`_apply_model` and only committing the swap (`state.model` and the persisted
selection) on success; a failed load now leaves the previous model running
and returns `ok: false` with a clear message. Re-verified the same sequence:
the good model stayed active after the corrupt upload was rejected.

Added `tests/test_model_registry.py` (11 tests: empty list, non-.onnx
rejection, successful upload activates immediately, **the corrupt-upload
regression guard**, reset, select without re-upload, unknown filename 404,
path-traversal rejection, selection persists across a simulated restart,
oversized upload rejection). Uses a hand-built minimal ONNX graph
(`onnx.helper`) rather than depending on PyTorch being installed for tests;
had to pin `model.ir_version = 9` on that fixture because the installed
`onnx` package (1.23.0) defaults new models to IR version 14, newer than the
installed `onnxruntime` (1.20.1) supports (max IR version 10) -- a
package-version-skew issue in the test fixture itself, not the app code.

**Verified in the real browser, not just via curl:** uploaded an actual
PyTorch-exported ONNX model through the live file input (not a mocked
upload), watched the UI show "Now scoring live data with: ONNX:
test_model.onnx", clicked "Revert to stub" and "Use this" (via element
references after raw pixel-coordinate clicks proved unreliable across
screenshots taken at different viewport sizes -- a lesson for any future
browser-driven verification in this project: prefer `find`+ref clicks over
remembered coordinates), and confirmed each transition via
`read_network_requests` and a fresh `GET /api/status`. Confirmed zero console
errors across the entire session's browser interaction.

Full test suites after all of the above: backend `python -m pytest tests/ -v`
→ **43 passed** (32 from before + 11 new model-registry tests); frontend
`npm run test` → **27 passed** (unchanged; no frontend logic tests were
affected). Production build (`npm run build`) → 619 modules, 0 errors.

Test artifacts from this verification (uploaded ONNX file, model selection
file, local SQLite db) were deleted before finishing; both dev servers were
left running with a clean stub-model, no-data starting state.

### 2026-09-20 — Phase 5 complete: main dashboard built, wired live, verified end to end with both servers running; three real bugs found and fixed
Wrote the data layer: `lib/api.js` (fetch wrapper, `ApiError`, every endpoint
from `docs/API_CONTRACT.md` section 3), `lib/ws.js` (`LiveSocket`: reconnecting
WebSocket client, exponential backoff 1s→15s per the contract's notes),
`lib/format.js` (every number/time/duration formatter the dashboard needs), and
the SRD 5.2 hooks: `useApi` (REST fetch-on-mount with loading/error/refetch),
`useWebSocket` (thin subscription wrapper around `LiveSocket`), and
`useLiveState` (a reducer merging `hello`/`status`/`ecg_window`/`risk_update`/
`alert`/`foot_check_result` frames into one coherent object, ignoring unknown
frame types per the contract's forward-compatibility note).

Built the dashboard components: `ECGWaveform` (raw `<canvas>`, redrawn on
`requestAnimationFrame`, rolling ~10s buffer, per the documented deviation from
Recharts in `docs/PLAN.md` section 2.3), `RiskTrend` (Recharts line chart with
a 15m/1h/6h/24h range selector, REST history extended live by the latest
`risk_update` frame), `ModeIndicator` (mode badge + one-line explanation),
`DeviceStatus` (connection/battery/SQI/leads-off `FieldRow`s), and
`AlertBanner` (dismiss both removes locally and calls `POST
/api/alerts/{id}/ack`). Assembled them into `pages/Dashboard.jsx` per
`docs/DESIGN_SYSTEM.md` section 6's layout (dark ECG card span-8 / grey
risk-now card span-4, grey risk-trend card span-8 / plain device-status card
span-4) and wired `App.jsx` to route to it.

**Three real bugs found and fixed, all while writing tests before trusting the
code, not left for later:**

1. **Design-system violation in `AlertBanner`.** The first draft filled the
   entire banner background with `--gs-danger` (a solid terracotta fill).
   `docs/DESIGN_SYSTEM.md` section 8 explicitly lists "don't flood a whole
   card in a status color" as a rule. Rewrote it to a white surface with a
   colored left rule and a `Badge`, matching how status color is used
   everywhere else in the system (a dot + border, never a fill).

2. **Canvas crash on missing 2D context.** `ECGWaveform`'s draw effect called
   `canvas.getContext('2d')` and immediately used the result without checking
   for `null`. Writing a render smoke test (jsdom has no canvas backend by
   default) surfaced this as a real uncaught exception thrown on *every*
   animation frame, which also corrupted the timing of an unrelated test
   running later in the same suite. The same failure mode -- `getContext`
   returning `null` -- is a real possibility in an actual browser too (context
   exhaustion, an already-requested WebGL context on the same canvas, etc.),
   not just a jsdom artifact. Fixed by bailing out of the effect entirely when
   the context is unavailable.

3. **Dropped fallback in `Dashboard`'s mode calculation.** `currentScore` had
   a three-way fallback (`risk?.score ?? initialRisk?.score ?? null`) so the
   metric isn't blank before the WebSocket's first frame arrives, but
   `currentMode` was written as `risk?.mode ?? status?.mode ?? null` --
   skipping `initialRisk?.mode` entirely. A render test that mocked
   `GET /api/risk/current` to resolve with `mode: "Watch"` but never sent any
   WebSocket frame caught this directly: the badge showed "Unknown" instead
   of "Watch" even though the data to show the right mode had already
   arrived over REST. Fixed to match the score's fallback chain.

Added `format.test.js` (14 tests), `useLiveState.test.js` (8 tests, exercising
the reducer directly rather than through a rendered component, including the
`__dismiss_alert` action and unknown-frame-type tolerance), and
`pages/Dashboard.test.jsx` (4 render smoke tests covering the exact SRD 5.3
requirement -- "must render correctly with no data ... don't crash on empty
state" -- for both a fully-rejecting backend and a genuinely empty-but-valid
payload, plus one populated-state test that caught bug 3 above). Installed
`jsdom` + `@testing-library/react` + `@testing-library/dom` as dev
dependencies to make these render tests possible; configured `vite.config.js`
with `test.environment: 'jsdom'`.

Full frontend test suite: `npm run test` → 27 passed. Production build:
`npm run build` → 619 modules transformed, 0 errors (one expected warning
about the Recharts-driven bundle exceeding 500kB -- not a correctness issue,
not addressed here since code-splitting a single-page demo dashboard isn't
worth the complexity yet).

**Verified live, end to end, with both servers actually running
simultaneously** (not just each in isolation as in earlier phases): confirmed
CORS headers are correct for the Vite origin (`access-control-allow-origin:
http://localhost:5173` on a real request), confirmed a real Node.js
`WebSocket` client connecting to the running backend's `/ws/live` receives
`hello` → `ecg_window` → `risk_update` → `ecg_window` in order, and confirmed
the frontend's compiled `lib/api.js` resolves `API_BASE` to the backend's real
URL. This is the "connectivity between frontend and backend" the project asked
for, demonstrated actually working, not just each side tested alone.

**Still outstanding:** no browser automation was available in this environment
(the Claude-in-Chrome extension was not connected), so `/kit` and the
dashboard have not been visually screenshotted and compared against
`docs/reference/*.jpg`. The design tokens themselves were sampled directly
from those frames during planning, so colors/type/radii should be exact: what
a visual pass would actually catch is layout/spacing/composition mistakes in
how the primitives were assembled into the dashboard. Recommended before
trusting the layout further: open the dashboard in a browser (with the
backend running) and eyeball it against the reference frames.

### 2026-09-20 — Phase 4 complete: design system primitives built, /kit gallery verified
Wrote `styles/tokens.css` (every value from `docs/DESIGN_SYSTEM.md` sections 2-4,
copied verbatim -- colors, type scale, radii, shadows) and `styles/global.css`
(font imports, reset, the 12-column grid utilities, typography utility classes
matching the doc's roles table, and the grid-overlay/divider-band treatment).

Built every primitive listed in `docs/PLAN.md` section 2.2 under
`components/ui/`, each as a `.jsx` + scoped `.module.css` pair: `Button` (dark/
white/lime/ghost variants, optional trailing arrow), `Card` (dark/grey/lime/
plain tones, dark tone gets the faint grid overlay), `Panel` (the floating
white "device screen" with `--gs-shadow-panel`), `Badge` (mode-colored dot +
border, keyed off the four controller mode colors), `FieldRow` (the reference's
icon-chip + label/value row, reused later for foot-check and device-status
rows), `Toggle` (52x30 pill switch), `SectionHeader` (eyebrow + serif heading +
right-aligned actions), `EmptyState` (for SRD 5.3's "must render correctly with
no data" requirement), and `GridBand` (the divider band, used once above the
Session section per the layout spec).

Added `pages/ComponentGallery.jsx` at `/kit`, rendering every primitive
together, and wired `App.jsx` to route to it via a plain pathname check (no
router dependency added -- Vite's default SPA fallback serves `index.html` for
any path, so `/kit` works with zero config).

Verified via the Vite dev server: `/kit` returns 200, and every module it
imports (`main.jsx`, `App.jsx`, `ComponentGallery.jsx`, `components/ui/index.js`,
each `.module.css`) transforms with zero errors. Inspected a compiled CSS
module directly to confirm Vite's automatic class-name scoping is working
(`Card.module.css` compiled to `._card_19mdq_1` etc., not a plain reused
`.card`) and that `global.css` correctly inlines `tokens.css` and the Google
Fonts import.

**No visual verification was possible in this environment:** the
Claude-in-Chrome browser extension was not connected, so `/kit` could not be
screenshotted and compared pixel-for-pixel against the reference frames in
`docs/reference/*.jpg`. This is a real gap, not a formality -- code that
compiles cleanly can still look wrong. Because the color/type/radius *values*
themselves were sampled directly from the reference video during planning
(not eyeballed), the tokens are very likely correct regardless; what a visual
pass would actually catch is layout/spacing/composition mistakes in how the
primitives are assembled. **Recommended before trusting Phase 5's dashboard
layout:** open `/kit` in a browser and eyeball it next to
`docs/reference/ref-cards-dark-grey.jpg` and `ref-lime-card-panel.jpg`.

### 2026-09-20 — Phase 3 complete: full REST + WebSocket API verified live, one more real bug found and fixed
Wrote `app/state.py` (`AppState`: the one object holding db/pipeline/model/
controller/session/live-snapshot, with `status_dict()` and a throttled
`status_changed()` gate per the WebSocket's "at most once per second, and only
when something actually changed" rule), `app/api/ws.py` (`/ws/live`: sends a
`hello` frame with the same shape as `GET /api/status` on connect, then fans out
the event bus until disconnect), `app/api/routes.py` (every endpoint in
`docs/API_CONTRACT.md` section 3), and rewired `app/main.py`'s lifespan to
actually start the simulator, run the per-window pipeline
(`signal_pipeline` → `inference` → `controller` → `db` + event-bus publish),
auto-fire foot checks via the scheduler, and shut down cleanly.

`POST /api/foot/request` and the automatic scheduler both go through a shared
`run_simulated_foot_check` coroutine that sleeps `foot_check_eta_s`, produces a
plausible bilateral reading (90% valid, occasional elevated delta-T), calls the
Phase 2 scheduler, persists the row, and publishes `foot_check_result` --
standing in for the real auxiliary-node wake cycle until Phase 7.

**One more real bug found and fixed, this time in the CSV export
(`GET /api/session/export`), caught by hand-testing the live app rather than
by a pre-written test:**

- First attempt used a `LEFT JOIN` on `device_status` with an `ABS(timestamp
  diff) < 5.0` condition to attach the nearest battery reading to each ECG
  window. Since `device_status` is inserted once per window at roughly the
  same 1 Hz cadence, that condition matched *several* status rows per window
  instead of one, multiplying the export: a live run with 4 windows produced
  16 CSV rows.
- The natural fix -- a correlated scalar subquery with
  `ORDER BY ABS(d.timestamp - w.timestamp) LIMIT 1` -- then failed outright
  with `sqlite3.OperationalError: no such column: w.timestamp`, even though
  the exact same outer reference worked fine in a `WHERE` clause one line
  above it. Isolated with a minimal repro: this project's SQLite (3.35.5)
  resolves an outer-query column inside a subquery's `WHERE` or `SELECT` list,
  but not inside that subquery's `ORDER BY`.
- Fixed with a nested subquery: the innermost `SELECT` computes the timestamp
  distance as a plain column using the outer reference (where correlation
  does resolve), and the enclosing `ORDER BY diff LIMIT 1` then sorts by that
  already-materialized column instead of needing correlation of its own.
  Verified against a live app run: exactly one export row per window, with
  the correct battery/alert/foot-check values attached.

Added `tests/test_db_export.py` (3 tests) as a permanent guard, specifically
including a test with dense per-window status rows -- the exact shape that
caused the original multiplication -- and a test that a distant (50s-away)
alert must not attach to an unrelated window.

Verified live, end to end, with a real HTTP client and a real WebSocket
connection against the running app (not mocked): `/api/health`, `/api/status`,
`/api/risk/current`, `/api/risk/history`, `/api/ecg/latest`, `/api/foot/history`,
`/api/foot/request` (including the 409-busy and battery-gate paths),
`/api/controller/mode` (valid, invalid-400, and override-clear), `/api/session/
summary`, `/api/session/export` (row-count-matches-window-count, confirmed
above), `/api/alerts/{id}/ack` (including 404), `/api/sim/spike`, and `/ws/live`
(hello frame, then live `risk_update`/`ecg_window` frames).

Full backend test suite: `python -m pytest tests/ -v` → 32 passed (23 controller
+ 4 Phase 1 pipeline + 2 Phase 2 integration + 3 export regression tests).

### 2026-09-20 — Phase 2 complete: controller verified end to end, two real bugs found and fixed
Wrote `app/controller.py`: the four-mode state machine (Eco/Normal/Watch/Verify)
exactly per SRD 4.4's trigger table, sustained-risk confirmation in Verify mode
(`confirm_windows` consecutive above-threshold windows before firing, reset on
any dip below threshold, cooldown before re-firing), manual override via
`set_manual_mode()` (used by `POST /api/controller/mode` in Phase 3), and the
foot-check scheduler as pure functions (`schedule_next_foot_check`,
`should_fire_foot_check`) covering all four SRD 4.4 branches: normal→24h,
elevated→8h, invalid→1h retry, and the battery gate at fire time.

**Two real bugs found and fixed while writing tests, not left for later:**

1. **Cooldown sentinel bug.** `last_alert_ts` defaulted to `0.0`. Since `0.0` is
   indistinguishable from a real (if implausible) epoch timestamp, a session
   whose first alert-worthy window arrived at a timestamp close to `0` looked
   like it was within the cooldown of a phantom prior alert, silently
   suppressing the very first legitimate alert. Real production timestamps
   (`time.time()`, ~1.7 billion) would have masked this, but the test suite's
   relative timestamps caught it immediately. Fixed by making the sentinel
   `None` and checking `is None` explicitly.

2. **Stub model ceiling bug.** Wiring the controller to the real simulator +
   stub model chain (not just direct-score unit tests) showed that a full
   20-second induced spike never fired an alert. Root cause: `StubRiskModel`'s
   original `0.6*baseline + 0.4*amplitude` weighting has a mathematical maximum
   of `0.6*0.45 + 0.4*1.0 = 0.67`, which is below the default `risk_alert`
   threshold of `0.75` in every possible case. This meant SRD acceptance
   criterion 8 — "vibration alert fires only after sustained-risk
   confirmation, demonstrable via induced test signal" — could never actually
   be demonstrated against the simulator, independent of how the demo was
   run. Fixed by reweighting to `0.5*baseline + 0.85*amplitude` (new ceiling
   ~1.0, floor with zero amplitude still ~0.025-0.225) and added a permanent
   test (`test_stub_model_ceiling_clears_risk_alert_threshold`) that checks the
   ceiling directly, plus an integration test that runs the full chain and
   asserts an alert actually lands in the database.

This second bug is the reason `tests/test_phase2_integration.py` exists as a
separate file from the controller's own unit tests: per-component unit tests
that drive the controller's `score` parameter directly are correct but cannot
see a calibration mismatch between the (stub) model's actual output range and
the controller's thresholds. Only wiring the real chain together caught it.

Verified end to end: simulator with a 20-second induced spike at window 10
reaches `Verify` mode at window 10, accumulates 3 consecutive confirmations,
fires exactly one alert at window 12, and drops back to `Watch` immediately
after — matching SRD 4.4's transition table exactly.

Full backend test suite: `python -m pytest tests/ -v` → 29 passed (23 controller
unit tests + 4 Phase 1 pipeline tests + 2 Phase 2 integration tests).

### 2026-09-20 — Phase 1 complete: backend data plane verified end to end
Wrote `app/events.py` (asyncio pub/sub `EventBus`, bounded per-subscriber queues
that drop-oldest under backpressure), `app/db.py` (full schema per
`docs/API_CONTRACT.md` section 5 plus `sessions`/`session_id`, WAL mode, and every
query the API layer will need: risk history downsampling, mode-time breakdown,
session export join, alert/foot-check CRUD), `app/signal_pipeline.py` (SQI gate +
ring buffer for `/api/ecg/latest`), `app/inference.py` (`RiskModel` protocol,
`StubRiskModel`, `OnnxRiskModel` with lazy `onnxruntime` import so the stub path
never requires it), and `app/simulator.py` (synthetic ECG generator with battery
drain, ~3% SQI dropout, and an on-demand `spike()` for the induced-test-signal
acceptance criterion in SRD section 8).

**Bug found and fixed during integration testing, not left for later:** the
original `signal_pipeline._reshape` normalized each window by its own
mean/standard-deviation (per-window z-score). Testing `simulator.spike()`
end-to-end showed the risk score did not move at all when the induced signal's
raw amplitude tripled — because dividing by a window's own std makes the result
scale-invariant to that window's amplitude, destroying exactly the information a
real amplitude anomaly (or the induced test signal SRD acceptance criterion 8
requires) would need to be visible as. Fixed by switching to a fixed reference
divisor (`config.ecg_normalize_scale`) instead of per-window std, and recalibrated
`StubRiskModel`'s amplitude-response thresholds to match. Verified: normal-window
risk scores now cluster around 0.12-0.18, spike-window scores jump to 0.33-0.52 in
the same run. This is recorded as an open question (item 3) because the *real*
trained model's expected normalization is still unknown — if it was trained on
per-window-normalized input, this fix will need to be revisited to match, not
reverted.

Added `backend/tests/test_phase1_pipeline.py` (4 tests, all passing) as a
permanent regression guard, specifically including a test that a spike must
raise the risk score by a clear margin, so this exact bug class cannot silently
return. Full backend test suite: `python -m pytest tests/ -v` → 4 passed.

End-to-end smoke test confirmed: simulator produces windows -> pipeline gates on
SQI (rejected windows correctly excluded from risk history, still visible via
`.latest()`) -> stub model scores accepted windows -> rows persist to SQLite with
correct `total`/`rejected` counts and `mean`/`peak` risk stats.

### 2026-09-20 — Phase 0 complete: scaffolding verified end to end
Backend: created `backend/app/{__init__,config,models,main}.py`,
`backend/app/api/__init__.py`, `backend/tests/__init__.py`, `requirements.txt`,
`.env.example`/`.env`. Set up a `.venv`, installed all dependencies (FastAPI,
uvicorn, pydantic-settings, aiosqlite, bleak, onnxruntime, pytest, httpx), and
confirmed `uvicorn app.main:app` boots and `GET /api/health` returns
`{"ok": true, "source": "simulator"}`.

Frontend: hand-scaffolded (the target directory already had planned
subdirectories, so `npm create vite` refused non-interactively) with
`package.json`, `vite.config.js`, `index.html`, placeholder `App.jsx` /
`main.jsx` / `global.css`, `.env.example`/`.env`. Used Recharts 3.2.1, Vite 8 and
Vitest 5 instead of the versions first drafted, because those were current and
starting on the latest stable versions avoided five known dev-server
vulnerabilities in the older esbuild/vite-node chain (`npm audit`: 0 vulnerabilities
after the bump). Confirmed `npm run dev` boots and serves the page — note for future
sessions: Vite 8 binds `[::1]` (IPv6 loopback) by default, so use `localhost`
rather than `127.0.0.1` when curling it locally.

Added root `.gitignore` (venv, node_modules, local SQLite data, .env files).

`config.py` centralizes every tunable per AGENTS.md, including the controller
thresholds and foot-check intervals from `docs/PLAN.md` section 4, and BLE UUID
placeholders per `docs/API_CONTRACT.md` section 2. `models.py` mirrors every
REST/WebSocket shape in `docs/API_CONTRACT.md` section 3-4 with Pydantic models,
so routes and the WebSocket handler (Phase 3) will type-check against the contract
rather than hand-building dicts.

Both dev servers verified running simultaneously; no data plane, controller, or
UI beyond a placeholder page exists yet. Proceeding directly to Phase 1.

### 2026-09-20 — Planning complete, no code yet
Read `GlucoSentry_SRD.pdf` v1.0 and extracted frames from `ruul-a6e6a6.mp4` to derive
the visual language. Wrote `docs/PLAN.md` (architecture, eight phases, controller
spec, deviations, risks), `docs/API_CONTRACT.md` (BLE, REST, WebSocket and SQLite
schema) and `docs/DESIGN_SYSTEM.md` (tokens sampled from the reference frames), plus
`AGENTS.md`. Created the directory skeleton. No application code has been written.
