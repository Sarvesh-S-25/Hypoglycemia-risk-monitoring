# SRD v1.0 — distilled, with traceability

A condensed reading of `GlucoSentry_SRD.pdf` (Nithish Kannan M, v1.0), kept so an
agent does not need the PDF open. Where this file and the PDF disagree, the PDF wins;
where the PDF and `docs/API_CONTRACT.md` disagree, the contract wins, and the reason
is recorded in `docs/PLAN.md` section 7.

## The system in four lines

```
ECG (AD8232 + ADS1115) -> ESP32 (filter + SQI via MPU6050) -> BLE
    -> Host: CNN+BiLSTM -> risk score
    -> Controller -> { ECG mode, alert, auxiliary foot-check }
                  -> bilateral temperature clip (BLE, on demand)
```

Single-wearer prototype. No mobile app, no cloud, no multi-user accounts.

## Technology, as specified

| Layer | Technology |
|---|---|
| Primary node | ESP32, C/C++ (Arduino or ESP-IDF) |
| Auxiliary node | ESP32-C3, low power, deep sleep by default |
| Backend | Python, FastAPI |
| ML | PyTorch for training, ONNX Runtime for serving |
| Database | SQLite |
| Frontend | React + Vite |
| Charts | Recharts preferred over Chart.js |

## What the hardware promises the backend

The primary node samples at 250 Hz, bandpass filters 0.5–40 Hz with a 50 Hz notch,
computes an SQI from MPU6050 motion magnitude, **rejects low-SQI windows rather than
transmitting them**, decimates to 100 Hz, buffers 30–60 second windows and sends them
over BLE. It accepts mode, alert and auxiliary-wake commands, and reports leads-off
state from the AD8232 LO pins.

The auxiliary node sleeps until a BLE wake prompt, reads both thermistors, reports
left, right, delta and a validity flag, then sleeps again.

The consequence for this repository: **filtering and SQI computation are already
done on-device.** The backend confirms the SQI flag and reshapes for the model; it
does not re-filter.

## Controller, as specified (SRD 4.4)

| Mode | Sampling | Inference interval | Trigger |
|---|---|---|---|
| Eco | 100 Hz | sparse | risk low, battery low, SQI stable |
| Normal | 200 Hz | normal | default operating state |
| Watch | 250 Hz | frequent | risk trending upward |
| Verify | 250 Hz | continuous burst | risk crossed the alert threshold — confirm before firing |

Foot-check scheduling is a deterministic state machine: 24 h after a normal result,
8 h after an elevated one, 1 h retry after an invalid one, and it fires only when the
scheduled time is reached and the battery is sufficient. An RL/Q-learning variant is
a separate comparative experiment and **is not a dependency for the working demo**.

## Frontend requirements (SRD 5)

**Main dashboard** — live scrolling ECG waveform (last ~10 s, over WebSocket), a
rolling risk trace with a selectable 1–6 h range, a color-coded mode indicator,
battery, BLE and signal-quality status, and a dismissible alert banner on high-risk
events.

**Foot-check panel** — last result (delta-T, timestamp, valid or invalid), a history
of delta-T over time flagging values above 2.2 °C per the IWGDF reference threshold
(cited as background, not as a diagnostic claim), a countdown to the next scheduled
check, and a manual "request check now" button for demonstration.

**Session/report view** — duration, alerts fired, a mode-time breakdown that feeds
the battery-life result, and a CSV export.

**Non-functional** — a new risk score must appear within 2 s, over WebSocket and not
polling; the dashboard must render correctly with no data and must not crash on an
empty state.

The component structure specified in SRD 5.2 is followed as given; `docs/PLAN.md`
section 2.2 adds only UI primitives beneath it.

## System-wide non-functional targets (SRD 6)

| Requirement | Target |
|---|---|
| ECG sample to dashboard risk update | < 3 s |
| Sustained risk to alert fired | < 5 s across verification windows |
| Primary node battery life, Normal mode | measured, not assumed — this is a key result |
| BLE range | on-body wear, host in the same room |
| False-alert rate | measured and reported; the sustained-window logic exists to reduce it |
| Data privacy | local-only SQLite on the host, no cloud transmission |

## Build sequence (SRD 7) and where this repository sits

1. ESP32 firmware: sampling, filtering, SQI — *separate*
2. BLE link, primary node to backend — *phase 7 here*
3. Backend inference, CNN+BiLSTM via ONNX Runtime, tested offline on D1NAMO — *model separate; the serving interface is phase 1 here*
4. Controller: discrete mode state machine, tested against simulated risk and battery inputs — *phase 2 here*
5. Auxiliary node bring-up — *separate; the backend side is phases 2–3 and 7*
6. **Frontend: build against mocked WebSocket data first, then connect live** — *phases 4–6 here; this is why the simulator is first-class*
7. Full integration on real hardware — *phase 7*
8. Evaluation: battery life and false-alert rate, adaptive versus fixed-rate — *phase 8, recorded in `UPDATES.md`*

## Acceptance criteria (SRD 8)

Tracked with measured values in `UPDATES.md`, not here.

- Live ECG visible within 3 s of device power-on.
- Risk score updates continuously and visibly changes mode at the defined thresholds.
- The vibration alert fires only after sustained-risk confirmation, demonstrated with
  an induced test signal rather than real hypoglycemia.
- The auxiliary node stays asleep unless explicitly woken, and the wake-to-result
  cycle completes and logs correctly.
- Session export produces a usable CSV.
- The battery-life comparison produces a measured, reportable number.

## Traceability: requirement to implementation

| SRD | Where it is satisfied |
|---|---|
| 3.3 BLE GATT profile | `docs/API_CONTRACT.md` section 2, `backend/app/ble_gateway.py`, `backend/app/config.py` |
| 3.4 ECG window packet | `docs/API_CONTRACT.md` section 2.3, `backend/app/signal_pipeline.py` |
| 4.1 Core modules | `backend/app/` — one file per specified module |
| 4.2 REST endpoints | `docs/API_CONTRACT.md` section 3, `backend/app/api/routes.py` |
| 4.3 WebSocket stream | `docs/API_CONTRACT.md` section 4, `backend/app/api/ws.py` |
| 4.4 Controller logic | `docs/PLAN.md` section 4, `backend/app/controller.py`, `backend/tests/test_controller.py` |
| 4.5 Database schema | `docs/API_CONTRACT.md` section 5, `backend/app/db.py` |
| 5.1 Pages and views | `frontend/src/pages/` |
| 5.2 Component structure | `frontend/src/components/`, `frontend/src/hooks/` |
| 5.3 Frontend non-functional | Phase 5 "done when" criteria in `docs/PLAN.md` |
| 6 Non-functional targets | Measured and recorded in `UPDATES.md` |
| 8 Acceptance criteria | Checklist with measured values in `UPDATES.md` |
