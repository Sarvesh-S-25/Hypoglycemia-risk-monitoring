/**
 * Summary of docs/POLICIES.md for the /policies page. The prose lives here;
 * every number is filled in from GET /api/diagnostics so the page always
 * shows the backend's live configuration. Keep the wording in step with
 * docs/POLICIES.md, which is the full version.
 */
import { formatInterval, formatSeconds, formatThreshold } from './format.js'

export const COMPONENTS = [
  {
    node: 'ECG node',
    parts: [
      ['AD8232', 'Amplifies the ~1 mV heart signal from three electrodes and flags leads-off on LO+/LO−, so a lost electrode is known rather than guessed from a flat line.'],
      ['ADS1115', '16-bit ADC sampling the AD8232 at 250 Hz. Much cleaner than the ESP32’s own 12-bit ADC, which matters because the model reads beat shape.'],
      ['MPU6050', 'Accelerometer. Decides whether the ECG can be trusted at all; see below.'],
      ['ESP32', 'Samples, computes signal quality from leads-off and motion, decimates to 100 Hz, and sends 1 s windows over Bluetooth.'],
      ['Motor + BC547', 'Planned haptic alert. The on-board LED stands in for it on the bench build.'],
    ],
  },
  {
    node: 'Foot module',
    parts: [
      ['2 × NTC thermistor', 'One per foot. Resistance falls as temperature rises. Left/right asymmetry is an early inflammation sign.'],
      ['2 × 1 kΩ', 'Turns each thermistor’s resistance into a voltage the ADC can read, sized for the 100 Ω parts.'],
      ['ESP32', 'Separate and independently powered. Wakes on request, reads both feet twice, validates, reports, powers the sensors down.'],
    ],
  },
  {
    node: 'Host',
    parts: [
      ['Backend', 'Bluetooth links, the risk model, the controller (modes and alerts) and the foot-check scheduler. Local SQLite only.'],
      ['Risk model', 'CNN + BiLSTM trained on D1NAMO. Scores 30 s of filtered ECG into a 0–1 risk value.'],
      ['Dashboard', 'Shows what the backend decided; never decides anything itself.'],
    ],
  },
]

export const MPU_STEPS = [
  'Moving shifts the electrodes and fires the muscles under them, adding artifact that is often bigger than the heartbeat and can look like a risk-related ECG change.',
  'Every 1 s window, the ESP32 takes the spread (standard deviation) of the acceleration magnitude. Sitting still is about 0.02–0.05 m/s².',
  (d) => `Above ${formatThreshold(d?.pipeline?.motion_threshold_ms2, ' m/s²')} the window is rejected: drawn on the waveform, never scored.`,
  'A rejected window also restarts the model’s 30 s buffer, so it never scores across a movement.',
  'The same number drives the Activity card, so the wearer sees why there is no score.',
]

export const POLICIES = [
  {
    id: 'P1',
    title: 'Signal-quality gate',
    rule: (d) =>
      `A window is rejected if the AD8232 reports leads-off or motion exceeds ${formatThreshold(d?.pipeline?.motion_threshold_ms2, ' m/s²')}. Rejected windows are shown and counted but never scored, so they can never change the mode or fire an alert.`,
  },
  {
    id: 'P2',
    title: 'Model context',
    rule: (d) =>
      `The model needs ${formatSeconds(d?.model?.needed_s)} of contiguous clean ECG. Until then there is no score, shown as “--” with the reason, never as 0.00. Any rejected window restarts the count.`,
  },
  {
    id: 'P3',
    title: 'Mode selection',
    rule: (d) =>
      `Verify at score ≥ ${d?.controller?.risk_alert ?? '--'}; Watch from ${d?.controller?.risk_elevated ?? '--'} or when scores keep rising; Eco below ${d?.controller?.risk_low ?? '--'} only on low battery with stable signal; otherwise Normal.`,
  },
  {
    id: 'P4',
    title: 'Alert confirmation',
    rule: (d) =>
      `An alert needs ${d?.controller?.confirm_windows ?? '--'} consecutive scored windows in Verify. One high window never fires. After an alert there is a ${formatSeconds(d?.controller?.alert_cooldown_s)} cooldown.`,
  },
  {
    id: 'P5',
    title: 'Foot-check scheduling',
    rule: (d) =>
      `Normal result (|ΔT| ≤ ${formatThreshold(d?.foot?.elevated_threshold_c, ' °C')}): next in ${formatInterval(d?.foot?.normal_interval_s)}. Elevated: next in ${formatInterval(d?.foot?.elevated_interval_s)}. Invalid or no answer: retry in ${formatInterval(d?.foot?.invalid_retry_s)}. A due check needs battery ≥ ${formatThreshold(d?.foot?.battery_min_pct, '%')}.`,
  },
  {
    id: 'P6',
    title: 'Foot-reading validity',
    rule: (d) =>
      `Both feet are read twice, 100 ms apart. Outside 10–45 °C, a 0.5 °C disagreement, or no answer within ${formatSeconds(d?.foot?.result_timeout_s)} makes the check invalid. Invalid is never treated as normal.`,
  },
  {
    id: 'P7',
    title: 'Battery',
    rule: () => 'An unmeasured battery (USB power) counts as sufficient. Low battery allows Eco mode, and a lower floor blocks foot checks.',
  },
  {
    id: 'P8',
    title: 'Data and privacy',
    rule: () => 'Everything stays on this computer, in local SQLite. No cloud, no analytics. Raw ECG is kept only in a short in-memory buffer. Export is a deliberate action.',
  },
  {
    id: 'P9',
    title: 'Display',
    rule: () => 'The dashboard only shows what the backend reports and always says why data is missing. It never compares a score, motion value or temperature to a threshold itself.',
  },
  {
    id: 'P10',
    title: 'Not a medical device',
    rule: () => 'Research prototype, no diagnostic claim. When electrodes are on a person, run the laptop on battery with the charger unplugged.',
  },
]

export const FAILURES = [
  ['Electrode falls off', 'Window rejected, “Leads off” shown, model buffer reset', ''],
  ['Wearer moves', 'Window rejected, “Moving” shown, buffer reset', 'Long movement means no score for that time'],
  ['50 Hz mains hum', 'Notch filter before scoring, matching training', 'Live waveform shown unfiltered'],
  ['ECG link drops', 'Marked disconnected after 5 s, rescans forever', 'No on-device storage: the gap is lost'],
  ['Foot module out of range', '“Not found”; manual request refused; due check recorded invalid and retried', ''],
  ['Bad thermistor contact', 'Range and stability checks make it invalid', ''],
  ['Model fails to load', 'Falls back to the placeholder, labelled in the UI', ''],
  ['Single spurious high score', 'Needs consecutive windows; cooldown stops repeats', ''],
  ['Model wrong on real ECG', 'Visible in the engineering view’s recent scores', 'Open: only checked on synthetic ECG (normal ≈ 0.03, hypo pattern ≈ 0.95); no real-data evaluation yet'],
  ['Foot module deep sleep', 'Sensors unpowered between checks', 'Open: deep sleep can’t hear a Bluetooth wake; needs a timer or wired wake'],
]
