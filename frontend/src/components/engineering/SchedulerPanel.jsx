import { KeyValue } from '../ui/index.js'
import PolicyTags from './PolicyTags.jsx'
import {
  formatCountdown,
  formatDeltaT,
  formatInterval,
  formatRelativeTime,
  formatSeconds,
  formatTemperature,
  formatThreshold,
} from '../../lib/format.js'
import styles from './Engineering.module.css'

/**
 * The foot-check scheduler: its three rules with the one the last result
 * triggered highlighted (from the backend's `action`), the next due time,
 * and the raw last reading (P5, P6).
 */
export default function SchedulerPanel({ foot }) {
  const f = foot ?? {}
  const last = f.last_check
  const rules = [
    { action: 'scheduled_24h', when: `Valid, |ΔT| ≤ ${formatThreshold(f.elevated_threshold_c, ' °C')}`, next: formatInterval(f.normal_interval_s) },
    { action: 'scheduled_8h', when: `Valid, |ΔT| > ${formatThreshold(f.elevated_threshold_c, ' °C')}`, next: formatInterval(f.elevated_interval_s) },
    { action: 'retry_1h', when: 'Invalid or no answer', next: `retry ${formatInterval(f.invalid_retry_s)}` },
  ]

  let link = 'simulated'
  if (f.source === 'ble') link = f.connected ? 'connected (BLE)' : 'not found'

  return (
    <div>
      <div className={styles.head}>
        <h3 className="gs-card-title" style={{ margin: 0 }}>Foot-check scheduler</h3>
        <PolicyTags ids={['P5', 'P6']} />
      </div>
      <p className={styles.lede}>Each result sets the next wake. The module sleeps in between.</p>

      <div className={styles.cols}>
        <div>
          <div className={styles.blockLabel}><span>Rule → next check</span></div>
          <ul className={styles.rules}>
            {rules.map((r) => (
              <li key={r.action} className={`${styles.rule} ${last?.action === r.action ? styles.ruleActive : ''}`}>
                <span>{r.when}</span>
                <span className={styles.mono}>{r.next}</span>
              </li>
            ))}
          </ul>
          <div className={styles.block}>
            <KeyValue
              rows={[
                ['Next check', formatCountdown(f.next_check_scheduled)],
                ['Battery floor for a wake', formatThreshold(f.battery_min_pct, '%')],
                ['Result timeout', formatSeconds(f.result_timeout_s)],
              ]}
            />
          </div>
        </div>
        <div>
          <div className={styles.blockLabel}><span>Last reading (raw)</span></div>
          <KeyValue
            rows={[
              ['Module link', link],
              ['Check in flight', f.busy ? 'yes' : 'no'],
              ['When', last ? formatRelativeTime(last.timestamp) : '--'],
              ['Left / right', last?.valid ? `${formatTemperature(last.t_left)} / ${formatTemperature(last.t_right)}` : '--'],
              ['|ΔT|', last?.valid ? formatDeltaT(last.delta_t) : '--'],
              ['Valid', last ? (last.valid ? 'yes' : 'no') : '--'],
              ['Scheduler action', last?.action ?? '--'],
            ]}
          />
        </div>
      </div>
    </div>
  )
}
