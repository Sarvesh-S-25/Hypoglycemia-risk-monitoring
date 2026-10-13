# GlucoSentry — Dashboard and Connectivity

ECG-based adaptive hypoglycemia monitoring system. This repository holds the
**frontend dashboard and the connectivity/persistence layer** it talks to: a React +
Vite dashboard, a FastAPI backend with REST and WebSocket APIs, SQLite persistence,
the adaptive controller, a BLE gateway for the ESP32 nodes, and a hardware simulator
so the whole chain runs before firmware exists.

ML training and ESP32 firmware are developed separately and integrate here through
fixed interfaces.

## Documents

| File | What it is |
|---|---|
| `AGENTS.md` | Working rules — read first if you are an agent |
| `UPDATES.md` | Status of record: phase, checklist, decisions, measured results |
| `docs/PLAN.md` | Architecture, eight build phases, controller spec, deviations, risks |
| `docs/API_CONTRACT.md` | Every wire format: BLE, REST, WebSocket, SQLite. Binding |
| `docs/DESIGN_SYSTEM.md` | Visual tokens sampled from the reference recording. Binding |
| `docs/SRD_SUMMARY.md` | The SRD distilled, with a requirement-to-file traceability table |
| `docs/reference/` | Frames extracted from the visual reference, plus the SRD text |

## Quick start

```bash
# backend
cd backend
python -m venv .venv
.venv/Scripts/activate           # Windows;  source .venv/bin/activate elsewhere
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000

# frontend, in a second terminal
cd frontend
npm install
npm run dev                      # http://localhost:5173
```

With `GS_SOURCE=simulator` (the default) no hardware is needed: synthetic ECG windows
flow through the same pipeline the real device will use, so the dashboard is fully
live against simulated data.

## Using your own trained model

Open the dashboard, click **Model**, and upload your `.onnx` file. It's applied
immediately -- every ECG window from that point on is scored by it, and the
dashboard's risk score, mode, and alerts reflect its output live. No restart
needed, and the choice is remembered across restarts. Uploaded models can be
switched between (or reverted to the built-in stub) from the same page without
re-uploading. See `docs/API_CONTRACT.md`'s "Model management" section for the
full API, and `backend/.env.example` for the equivalent config-file approach.

## Configuration

`backend/.env`:

```
GS_SOURCE=simulator        # simulator | serial | ble | auto
GS_SERIAL_PORT=            # serial only; empty auto-detects /dev/ttyACM*, /dev/ttyUSB*
GS_DB_PATH=./data/glucosentry.db
GS_ENABLE_SIM=1            # exposes POST /api/sim/* for demo/induced-signal testing
GS_MODEL_PATH=             # empty uses the stub model; set to an .onnx file to serve the real one
```

`frontend/.env`:

```
VITE_API_BASE=http://127.0.0.1:8000
```

## Privacy

All data stays on the host machine in a local SQLite file. There is no cloud
transmission, no analytics and no external telemetry anywhere in this repository —
that is a requirement from the SRD, not a preference.
