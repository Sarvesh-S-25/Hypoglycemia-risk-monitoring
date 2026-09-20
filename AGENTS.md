# AGENTS.md — working rules for this repository

GlucoSentry is an ECG-based adaptive hypoglycemia monitoring system. This repository
holds the **dashboard and its connectivity layer**: the React frontend, the FastAPI
backend, SQLite persistence, the controller, the BLE gateway and a hardware
simulator. ML training and ESP32 firmware live elsewhere and are integrated through
fixed interfaces.

## Read before writing code

1. `docs/PLAN.md` — architecture, phases, and the decisions already made.
2. `docs/API_CONTRACT.md` — every wire format. **Binding.**
3. `docs/DESIGN_SYSTEM.md` — every visual token. **Binding.**
4. `UPDATES.md` — what is already done and what is next. **Update it as you go.**

If a task is not obviously covered by those four, it probably needs a decision rather
than a guess — say so instead of inventing one.

## Non-negotiables

- **The contract comes first.** To change a payload, edit `docs/API_CONTRACT.md`,
  then the backend, then the frontend, in that order, and note it in `UPDATES.md`.
  Never patch one side of a boundary alone.
- **Use the design tokens.** No hard-coded hex values, no new fonts, no new radii in
  component files. Everything comes from `styles/tokens.css`, which is generated from
  `docs/DESIGN_SYSTEM.md`. If a needed value is missing, add it to the token file and
  to the doc.
- **The frontend does no clinical reasoning.** It never thresholds a risk score,
  decides a mode, or computes the next foot-check time. It renders what the backend
  reports. The backend is the only source of truth for anything a clinician would
  care about.
- **Never crash on empty data.** Device disconnected, zero samples, null risk and an
  empty history are all normal states that must render deliberately (SRD 5.3).
- **Keep the simulator working.** Every change to the data path must keep
  `GS_SOURCE=simulator` running end to end. That path is how this gets demonstrated
  when hardware is not on the bench.
- **Nothing leaves the machine.** Local-only storage, no cloud calls, no analytics, no
  external telemetry. That is a stated requirement, not a preference.
- **Do not fake results.** If a test fails or a phase is partly done, write that in
  `UPDATES.md`. A checklist of ticks that does not match the code is worse than no
  checklist.

## Conventions

**Python (backend)**
- Python 3.10+, `async def` for anything touching I/O, type hints on public functions.
- All SQL lives in `app/db.py`. No SQL in routes, controller or pipeline.
- All tunable numbers live in `app/config.py`. No magic numbers in logic files.
- Timestamps are float UNIX seconds everywhere internally. Format only at the edge.
- Log with the stdlib `logging` module, never bare `print`.

**JavaScript (frontend)**
- React 18, function components and hooks only. No class components.
- Plain CSS with custom properties and CSS modules where scoping helps. No Tailwind,
  no CSS-in-JS runtime — the design system is a token file and stays readable.
- One component per file, named the same as the file.
- Data fetching goes through `lib/api.js`; live frames go through `lib/ws.js`. No
  bare `fetch` or `new WebSocket` inside a component.
- Numbers shown to the user are formatted by `lib/format.js`, never inline.

**Both**
- Comment *why*, not *what*. Match the density of the surrounding file.
- Small, working commits at phase boundaries. Do not commit a half-migrated contract.

## Definition of done for a phase

A phase is done when the "Done when" line in `docs/PLAN.md` is literally true, its
tests pass, `UPDATES.md` records the result including anything that fell short, and
the simulator path still runs end to end.

## Repository map

```
docs/            PLAN.md, API_CONTRACT.md, DESIGN_SYSTEM.md, SRD_SUMMARY.md
backend/app/     FastAPI app, controller, pipeline, BLE gateway, simulator, DB
backend/tests/   pytest, controller logic first
frontend/src/    React dashboard (see PLAN.md section 2.2 for the module map)
UPDATES.md       status of record, updated at every phase boundary
AGENTS.md        this file
```

## Working style expected here

Finish the phase you are on before starting the next. If something in the plan turns
out to be wrong once code exists, say so plainly and propose the change rather than
silently working around it — the plan is a tool, not a contract with the universe.
The contract documents, on the other hand, are binding, because two halves of a
system drifting apart is the failure mode that costs the most time to find.
