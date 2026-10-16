import { useState } from 'react'
import { Badge, Button, Meter, Segmented, Toggle } from '../ui/index.js'
import PolicyTags from './PolicyTags.jsx'
import { api, ApiError } from '../../lib/api.js'
import { formatBattery, formatSeconds } from '../../lib/format.js'
import styles from './SimulatorPanel.module.css'

const SCENARIOS = [
  { name: 'normal', label: 'Normal', duration: null, shows: 'Clean sinus rhythm.', policies: [] },
  { name: 'motion', label: 'Motion artifact', duration: 15, shows: 'Accelerometer over the limit: windows rejected, model buffer reset.', policies: ['P1', 'P2'] },
  { name: 'leads_off', label: 'Leads off', duration: 15, shows: 'AD8232 flags leads-off: flat trace, no heart rate, no score.', policies: ['P1'] },
  { name: 'hypo', label: 'Hypo test pattern', duration: 180, shows: 'Ramps in long QT, flat T, ST dip and faster rate over 2 min. Drives a model that reads ECG shape towards Verify and an alert.', policies: ['P3', 'P4'] },
  { name: 'spike', label: 'Amplitude spike', duration: 20, shows: 'Triples the amplitude: the induced alert test for the placeholder model.', policies: ['P4'] },
]

const HR_OPTIONS = [55, 72, 95, 120].map((v) => ({ value: v, label: `${v} bpm` }))
const BATTERY_OPTIONS = [100, 50, 20, 10].map((v) => ({ value: v, label: `${v}%` }))
const FOOT_OPTIONS = [
  { value: 'random', label: 'Random' },
  { value: 'normal', label: 'Normal' },
  { value: 'elevated', label: 'Elevated ΔT' },
  { value: 'invalid', label: 'Invalid' },
  { value: 'offline', label: 'Offline' },
]

/**
 * Drives the simulator so every path the real hardware can take is
 * demonstrable on demand (POST /api/sim/*). State shown here is the
 * backend's (diagnostics.simulator), refreshed by the parent's poll.
 */
export default function SimulatorPanel({ sim }) {
  const [message, setMessage] = useState(null)
  const ecg = sim?.ecg
  const foot = sim?.foot

  async function call(fn) {
    setMessage(null)
    try {
      await fn()
    } catch (err) {
      setMessage(err instanceof ApiError ? err.detail : 'Request failed')
    }
  }

  const active = SCENARIOS.find((s) => s.name === ecg?.scenario)

  return (
    <div>
      <div className={styles.head}>
        <div>
          <h3 className="gs-card-title" style={{ margin: 0 }}>Simulator</h3>
          <p className={styles.lede}>Synthetic hardware with the same data shapes as the real nodes. Use it to demonstrate each path.</p>
        </div>
        {ecg && (
          <Button variant="ghost" onClick={() => call(() => api.simAction(ecg.running ? 'stop' : 'start'))}>
            {ecg.running ? 'Pause stream' : 'Resume stream'}
          </Button>
        )}
      </div>
      {message && <p className={styles.error}>{message}</p>}

      <div className={styles.cols}>
        <section>
          <span className="gs-label">ECG node</span>
          {!ecg ? (
            <p className={styles.note}>Real hardware (GS_SOURCE is not simulator).</p>
          ) : (
            <>
              <div className={styles.scenarios}>
                {SCENARIOS.map((s) => (
                  <button
                    key={s.name}
                    type="button"
                    className={`${styles.scenario} ${ecg.scenario === s.name ? styles.scenarioActive : ''}`}
                    onClick={() => call(() => api.simScenario(s.name, s.duration))}
                  >
                    <span className={styles.scenarioTop}>
                      <span className={styles.scenarioName}>{s.label}</span>
                      <span className={styles.scenarioMeta}>{s.duration ? formatSeconds(s.duration) : 'ongoing'}</span>
                    </span>
                    <span className={styles.scenarioShows}>{s.shows}</span>
                    {s.policies.length > 0 && <PolicyTags ids={s.policies} plain />}
                  </button>
                ))}
              </div>

              <div className={styles.now}>
                <Badge color={ecg.scenario === 'normal' ? 'var(--gs-ok)' : 'var(--gs-warn)'}>
                  {active?.label ?? ecg.scenario}
                </Badge>
                <span className={styles.nowText}>
                  {ecg.scenario_remaining_s !== null ? `${formatSeconds(ecg.scenario_remaining_s)} left` : 'until changed'}
                  {' · '}
                  {Math.round(ecg.heart_rate_bpm)} bpm now
                </span>
              </div>
              {ecg.hypo_progress !== null && (
                <div className={styles.progress}>
                  <span className={styles.progressLabel}>Pattern strength {Math.round(ecg.hypo_progress * 100)}%</span>
                  <Meter value={ecg.hypo_progress} max={1} tone="warn" label="hypo pattern" />
                </div>
              )}

              <div className={styles.row}>
                <span className={styles.rowLabel}>Resting heart rate</span>
                <Segmented
                  options={HR_OPTIONS}
                  value={ecg.base_heart_rate_bpm}
                  onChange={(v) => call(() => api.simSettings({ heart_rate_bpm: v }))}
                  label="heart rate"
                />
              </div>
              <div className={styles.row}>
                <span className={styles.rowLabel}>Battery ({formatBattery(ecg.battery_pct)})</span>
                <Segmented
                  options={BATTERY_OPTIONS}
                  value={BATTERY_OPTIONS.some((o) => o.value === ecg.battery_pct) ? ecg.battery_pct : null}
                  onChange={(v) => call(() => api.simSettings({ battery_pct: v }))}
                  label="battery"
                />
              </div>
              <div className={styles.row}>
                <span className={styles.rowLabel}>Random motion artifacts (~3% of windows)</span>
                <Toggle
                  checked={ecg.random_artifacts}
                  onChange={(v) => call(() => api.simSettings({ random_artifacts: v }))}
                />
              </div>
            </>
          )}
        </section>

        <section>
          <span className="gs-label">Foot module</span>
          {!foot ? (
            <p className={styles.note}>Real hardware (GS_AUX_SOURCE is ble).</p>
          ) : (
            <>
              <p className={styles.note}>Forces what the next foot checks return, to show each scheduler branch.</p>
              <Segmented
                options={FOOT_OPTIONS}
                value={foot.mode}
                onChange={(v) => call(() => api.simFoot(v))}
                label="foot module mode"
              />
              <ul className={styles.footHints}>
                <li><b>Normal</b> → next check in 24 h <PolicyTags ids={['P5']} /></li>
                <li><b>Elevated ΔT</b> → next check in 8 h, flagged <PolicyTags ids={['P5']} /></li>
                <li><b>Invalid</b> → retry in 1 h, never “normal” <PolicyTags ids={['P6']} /></li>
                <li><b>Offline</b> → “Not found”, request refused, due check retried <PolicyTags ids={['P6']} /></li>
              </ul>
              <p className={styles.note}>Then press “Request check now” on the Patient view.</p>
            </>
          )}
        </section>
      </div>
    </div>
  )
}
