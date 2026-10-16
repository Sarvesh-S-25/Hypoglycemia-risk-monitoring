import { Badge, KeyValue } from '../ui/index.js'
import PolicyTags from './PolicyTags.jsx'
import { formatRiskScore, formatSeconds } from '../../lib/format.js'
import styles from './Engineering.module.css'

/**
 * The controller's thresholds as a scale, where the last score sits on it,
 * and how far Verify has got towards firing (P3, P4). The highlighted zone
 * is the backend's *mode*, not a comparison done here.
 */
export default function ControllerPanel({ controller }) {
  const c = controller ?? {}
  const scores = c.recent_scores ?? []
  const last = scores.length ? scores[scores.length - 1] : null

  const zones = c.risk_alert
    ? [
        { mode: 'Eco', from: 0, to: c.risk_low, label: 'Eco ok' },
        { mode: 'Normal', from: c.risk_low, to: c.risk_elevated, label: 'Normal' },
        { mode: 'Watch', from: c.risk_elevated, to: c.risk_alert, label: 'Watch' },
        { mode: 'Verify', from: c.risk_alert, to: 1, label: 'Verify' },
      ]
    : []

  return (
    <div>
      <div className={styles.head}>
        <h3 className="gs-card-title" style={{ margin: 0 }}>Controller</h3>
        <PolicyTags ids={['P3', 'P4']} />
      </div>
      <p className={styles.lede}>
        Mode from each scored window; an alert needs {c.confirm_windows ?? '--'} consecutive windows in Verify.
      </p>

      <div className={styles.cols}>
        <div>
          <div className={styles.blockLabel}>
            <span>Score scale</span>
            <span className={styles.mono}>last {formatRiskScore(last)}</span>
          </div>
          <div className={styles.scale} aria-label="risk thresholds">
            {zones.map((z) => (
              <div
                key={z.mode}
                className={`${styles.zone} ${c.mode === z.mode ? styles.zoneActive : ''}`}
                style={{ width: `${(z.to - z.from) * 100}%`, background: `var(--gs-mode-${z.mode.toLowerCase()})` }}
              >
                {z.label}
              </div>
            ))}
            {last !== null && <div className={styles.scoreMarker} style={{ left: `${last * 100}%` }} />}
          </div>
          <div className={styles.ticks}>
            {[c.risk_low, c.risk_elevated, c.risk_alert].filter((t) => t !== undefined).map((t) => (
              <span key={t} className={styles.tick} style={{ left: `${t * 100}%` }}>{t}</span>
            ))}
          </div>

          <div className={styles.block}>
            <div className={styles.blockLabel}>
              <span>Recent scores (oldest → newest)</span>
            </div>
            {scores.length ? (
              <div className={styles.bars}>
                {scores.map((s, i) => (
                  <div key={i} className={styles.bar} style={{ height: `${Math.max(2, s * 100)}%` }} title={formatRiskScore(s)} />
                ))}
              </div>
            ) : (
              <p className={styles.lede}>No scored windows yet.</p>
            )}
          </div>
        </div>

        <div>
          <div className={styles.blockLabel}>
            <span>Verify confirmation</span>
            <span className={styles.mono}>{c.verify_confirm_count ?? 0} / {c.confirm_windows ?? '--'}</span>
          </div>
          <div className={styles.dots}>
            {Array.from({ length: c.confirm_windows ?? 0 }, (_, i) => (
              <span key={i} className={`${styles.dot} ${i < (c.verify_confirm_count ?? 0) ? styles.dotOn : ''}`} />
            ))}
          </div>
          <div className={styles.block}>
            <KeyValue
              rows={[
                ['Mode', c.mode ? <Badge mode={c.mode}>{c.mode}</Badge> : '--'],
                ['Manual override', c.manual_mode ?? 'off'],
                ['Alerting', c.alerting ? 'yes' : 'no'],
                ['Alert cooldown', formatSeconds(c.alert_cooldown_s)],
                ['Cooldown remaining', c.cooldown_remaining_s ? formatSeconds(c.cooldown_remaining_s) : 'none'],
              ]}
            />
          </div>
        </div>
      </div>
    </div>
  )
}
