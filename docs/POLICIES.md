# Operating policies, failure modes and mitigations

What the system does with its data, why each hardware part is there, and what happens
when something goes wrong. Every number below is the live value in
`backend/app/config.py`. If the two disagree, the config wins and this file is out of
date. The dashboard's **Engineering** view shows each of these values live, and its
**Policies** page summarises this file.

GlucoSentry is a research prototype. It is **not a medical device**, it makes no
diagnostic claim, and nothing it shows should drive a treatment decision.

---

## 1. What each part does

### ECG node (worn continuously)

| Part | Job | Why it is needed |
|---|---|---|
| **AD8232** | ECG analog front end. It amplifies the microvolt heart signal from three electrodes (RA, LA, RL) and reports **leads-off** on its LO+ and LO− pins. | Skin electrodes give about 1 mV. Nothing downstream can read that directly. The leads-off pins are the only way to know that the electrode contact is gone, rather than seeing a flat line and guessing. |
| **ADS1115** | 16-bit ADC over I2C, sampling the AD8232 output at 250 Hz (±4.096 V range, 0.125 mV per count). | The ESP32's own ADC is 12-bit, noisy and non-linear. ECG morphology (QRS width, T-wave shape) is exactly what the model reads, so the conversion has to be clean. |
| **MPU6050 / MPU6500** (accelerometer) | Measures acceleration on 3 axes at 25 Hz. Each 1 s window gets one number: the standard deviation of the acceleration **magnitude** (`motion_ms2`). | **It decides whether the ECG can be trusted.** See section 1.1. |
| **ESP32 (primary)** | Samples at 250 Hz, computes the SQI from leads-off and motion, decimates to 100 Hz (3-tap smoothing, then interpolation), and sends 1 s windows over BLE. It receives mode and alert commands. **The bench firmware does not band-pass or notch filter.** The host applies the training notebook's filter before scoring (see the Host table). | Computing the SQI on the device means bad windows are flagged before they leave it. |
| **Vibration motor + BC547** (planned) | Haptic alert. The ESP32 GPIO drives the BC547 through 1 kΩ, which switches the motor, with a flyback diode across it. | A GPIO can't supply a motor's current. On the bench build the on-board LED (GPIO2) stands in for the motor. |

### 1.1 How the MPU6050 helps

ECG electrodes measure tiny voltages. When the wearer moves, the electrodes shift on
the skin and the muscles under them fire. That adds **motion artifact**: baseline
jumps, spikes and EMG noise, often larger than the heartbeat itself. The model reads
the shape of each beat, so a window corrupted by movement can look like a
risk-related ECG change. That is a false alarm, or a missed real change hidden in
noise.

The accelerometer measures the movement directly instead of guessing it from the ECG:

1. Every 1 s window, the ESP32 takes the standard deviation of |acceleration|.
   Sitting still measures about **0.02–0.05 m/s²**. Walking or arm movement is
   several m/s².
2. Above **1.0 m/s²** (`serial_motion_sqi_threshold_ms2`), the window gets
   `sqi = 0`. It is **shown on the waveform but never scored** (policy P1).
3. Because the model needs 30 s of *contiguous* clean ECG, a motion window also
   **resets** the model's buffer (P2). The model never stitches the two sides of a
   movement together.
4. The same number drives the dashboard's **Activity** card, so the wearer can see
   *why* there is no risk score ("Moving") instead of a blank.

Without the MPU6050, the only defence against motion would be guessing from the ECG
itself, which fails exactly when it matters, because artifacts and real changes can
look alike.

### Foot module (asleep between checks)

| Part | Job | Why it is needed |
|---|---|---|
| **2 × NTC thermistor** | One per foot. Resistance falls as temperature rises. The bench parts are **100 Ω NTCs (marked 101)**, Beta 3950 assumed. | Asymmetry in foot temperature is an early sign of inflammation before a diabetic foot ulcer. The IWGDF reference threshold is 2.2 °C, cited as background, not as a diagnosis. |
| **2 × 1 kΩ resistor** | Makes a voltage divider with each thermistor (3V3 → 1 kΩ → ADC pin → NTC → GND). | An ADC measures voltage, not resistance. 1 kΩ matches a 100 Ω NTC so the reading falls around 300 mV, inside the ADC's most accurate range (0 dB attenuation). |
| **ESP32 (auxiliary)** | Waits for a BLE `wake`, powers the dividers, reads both sides twice, validates them, sends `t_left`, `t_right`, `delta`, `valid`, then powers the dividers down. | It's a separate, independently powered node, as the invention disclosure requires (claim 5). |

### Host (laptop)

| Part | Job |
|---|---|
| **Backend (FastAPI)** | Runs the BLE links, the SQI confirmation, the **ONNX model**, the **controller** (modes and alerts), and the **foot-check scheduler**. It stores everything in local SQLite. |
| **ONNX model** (CNN + BiLSTM, D1NAMO) | Scores 30 s of ECG into a 0–1 risk value. Before scoring, the backend resamples to 250 Hz (7500 samples), applies the notebook's 0.5–40 Hz Butterworth band-pass and 50 Hz notch at zero phase (`app/ecg_filter.py`), and z-scores, so the model sees the same kind of signal it was trained on. |
| **Dashboard (React)** | Displays what the backend decided. It never decides anything itself (P9). |

---

## 2. Policies

**P1. Signal-quality gate.** A window is rejected (`sqi = 0`) if the AD8232 reported
leads-off at any point in it, or if motion exceeded **1.0 m/s²**. Rejected windows
are drawn on the waveform and counted in the database, but **never scored**, and they
can never move the mode or fire an alert.

**P2. Model context.** The trained model needs **30 s of contiguous accepted ECG**.
No score exists until then (`risk_ready_in_s` counts down), and any rejected window
restarts the 30 s. The UI shows "--" with the reason, **never a placeholder 0.00**,
because 0.00 would read as "no risk".

**P3. Mode selection** (`controller.py`), evaluated on every scored window:

| Mode | Condition |
|---|---|
| Verify | score ≥ **0.75** (`risk_alert`) |
| Watch | **0.55** ≤ score < 0.75, or the last **3** scores rising by more than 0.05 overall |
| Eco | score < **0.30** *and* battery < **25 %** *and* the last **5** windows all accepted |
| Normal | otherwise |

The mode is sent to the ECG node. On the bench build the node only echoes it back;
it samples at 250 Hz in every mode.

**P4. Alert confirmation.** An alert fires only after **3 consecutive** scored windows
at or above 0.75 while in Verify. A single high window never fires. If the score falls
back under 0.75, Verify drops to Watch without firing. After an alert there is a
**300 s cooldown** before the next one.

**P5. Foot-check scheduling** (the invention's loop):

| Last result | Next check |
|---|---|
| Valid, \|ΔT\| ≤ 2.2 °C (normal) | 24 h |
| Valid, \|ΔT\| > 2.2 °C (elevated) | 8 h |
| Invalid, or no answer | retry in 1 h |

A due check fires only if the battery is ≥ **15 %** (`battery_aux_min`). Every result
reschedules the next one. The **Request check now** button skips the wait but uses the
same path.

**P6. Foot-reading validity.** The foot module reads both sides twice, 100 ms apart. A
reading is **invalid** if either side is outside **10–45 °C** (an open or shorted
sensor) or the two reads differ by **0.5 °C** or more (unstable contact). If the
module doesn't answer within **10 s**, that check is also invalid. An invalid check
is never treated as "normal".

**P7. Battery.** An unknown battery (USB-powered bench build) is treated as
sufficient, so it never forces Eco mode and never blocks a foot check. A measured
battery under 25 % allows Eco, and under 15 % blocks foot checks.

**P8. Data and privacy.** Everything stays on the host: local SQLite, no cloud, no
analytics. Raw ECG samples are held only in a short in-memory ring buffer. The
database stores per-window SQI, score and mode, plus foot checks, alerts and device
status. CSV export is a deliberate user action.

**P9. Display.** The dashboard renders only what the backend reports. It never
compares a score, motion value or temperature against a threshold. When data is
missing, it says why: disconnected, leads off, moving, warming up or not found.

**P10. Electrical safety.** When electrodes are on a person, the laptop runs **on
battery with the charger unplugged**. The AD8232 is powered from 3V3, never 5 V.

---

## 3. Failure modes and mitigations

| What can go wrong | How it shows up | Mitigation in place | Still open |
|---|---|---|---|
| Electrode falls off | AD8232 LO pins high | P1: window rejected, waveform shows "Leads off", HR blank, model buffer reset | — |
| Wearer moves | motion > 1.0 m/s² | P1/P2: rejected and buffer reset; Activity shows "Moving" | Long movement means long gaps with no score |
| Mains interference | 50 Hz hum on the trace | 50 Hz notch applied by the host before scoring (`model_prefilter`), matching training | The live waveform is shown unfiltered; not configurable for 60 Hz regions |
| ECG node BLE link drops | no notifications for 5 s | Gateway marks it disconnected and rescans forever; the dashboard shows "Disconnected" | Data during the gap is lost (no on-device storage) |
| Foot module out of range | not found in scan | Status shows "Not found"; manual request returns 503 with the reason; a due check is recorded invalid → retried in 1 h (P5) | — |
| Foot module doesn't answer a wake | 10 s timeout | Recorded as invalid, retried in 1 h | — |
| Bad thermistor contact | outside 10–45 °C, or unstable | P6: invalid, never "normal" | — |
| Absolute temperature wrong | — | ΔT only needs left and right to agree; they matched within about 0.5 °C on the bench | Not calibrated against a reference thermometer; Beta assumed |
| Thermistor self-heating | reads warm | Dividers powered only during a reading (GPIO32), if wired to GPIO32 | Bench build feeds them from 3V3 directly |
| Model file won't load | — | Falls back to the heuristic stub, **labelled** "Stub (failed to load …)" in the UI | — |
| Model is wrong on real ECG | unexpected scores | Visible in the Engineering view (recent scores); documented in UPDATES.md | **Open:** the model has only been checked on *synthetic* ECG. There it scores normal rhythm about 0.03, ignores a fast but normal-shaped rhythm (97–120 bpm: 0.00), and rises to about 0.95 on the full hypo test pattern. (An earlier "no skill" finding came from the old sine-wave simulator, not the model.) Its performance on real ECG with real glucose labels is unknown: the notebook saved no evaluation results |
| Single spurious high score | one window ≥ 0.75 | P4: needs 3 in a row; cooldown prevents repeats | — |
| Alert missed while the wearer moves | no score during motion | — | **Open:** P1 trades coverage for reliability; a long movement period has no risk score |
| Foot module wants deep sleep | — | Dividers unpowered and the radio idle between checks | **Open:** an ESP32 in deep sleep can't hear a BLE wake. True deep sleep needs a timer or GPIO wake |
| No device clock | — | Windows are stamped with host arrival time (latency is far below the 1 s window) | — |
| Two BLE scans start at once | "Operation already in progress" | Caught and retried; each gateway scans only while disconnected | — |
| Serial port held by another program | upload or backend can't open it | Only one program may hold the port; documented in HANDOFF.md | — |
