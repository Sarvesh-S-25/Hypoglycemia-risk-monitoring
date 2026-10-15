import { KeyValue, Meter } from '../ui/index.js'
import PolicyTags from './PolicyTags.jsx'
import { formatCounts, formatHeartRate, formatMotion, formatShare, formatThreshold } from '../../lib/format.js'
import styles from './Engineering.module.css'

/** Signal pipeline: what came in, what was rejected and why (P1). */
export default function PipelinePanel({ pipeline }) {
  const p = pipeline ?? {}
  const total = p.windows_total ?? 0
  const pct = (n) => (total ? `${(n / total) * 100}%` : '0%')
  const w = p.last_window

  let sqiLabel = '--'
  if (p.sqi === 1) sqiLabel = '1 (accepted)'
  else if (p.sqi === 0) sqiLabel = p.leads_off ? '0 (leads off)' : '0 (motion/noise)'

  return (
    <div>
      <div className={styles.head}>
        <h3 className="gs-card-title" style={{ margin: 0 }}>Signal pipeline</h3>
        <PolicyTags ids={['P1']} />
      </div>
      <p className={styles.lede}>1 s windows at {p.sample_rate_hz ?? '--'} Hz. Rejected windows are drawn but never scored.</p>

      <div className={styles.blockLabel}>
        <span>Windows this session</span>
        <span className={styles.mono}>{formatShare(p.windows_accepted, total)} accepted</span>
      </div>
      <div className={styles.stack} aria-label="window acceptance">
        <div className={styles.ok} style={{ width: pct(p.windows_accepted ?? 0) }} />
        <div className={styles.faint} style={{ width: pct(p.rejected_leads_off ?? 0) }} />
        <div className={styles.warn} style={{ width: pct(p.rejected_motion ?? 0) }} />
      </div>
      <div className={styles.legend}>
        <span><span className={`${styles.swatch} ${styles.ok}`} />Accepted {p.windows_accepted ?? 0}</span>
        <span><span className={`${styles.swatch} ${styles.faint}`} />Leads off {p.rejected_leads_off ?? 0}</span>
        <span><span className={`${styles.swatch} ${styles.warn}`} />Motion {p.rejected_motion ?? 0}</span>
      </div>

      <div className={styles.block}>
        <div className={styles.blockLabel}>
          <span>Motion (MPU6050) vs reject threshold</span>
          <span className={styles.mono}>
            {formatMotion(p.motion_ms2)} / {formatThreshold(p.motion_threshold_ms2, ' m/s²')}
          </span>
        </div>
        <Meter
          value={p.motion_ms2}
          max={(p.motion_threshold_ms2 ?? 1) * 2}
          marker={p.motion_threshold_ms2}
          tone={p.sqi === 0 && !p.leads_off ? 'warn' : 'ok'}
          label="motion"
        />
      </div>

      <div className={styles.block}>
        <KeyValue
          rows={[
            ['Current SQI', sqiLabel],
            ['AD8232 leads-off', p.leads_off === null || p.leads_off === undefined ? '--' : p.leads_off ? 'yes' : 'no'],
            ['Last window samples', formatCounts(w?.n_samples)],
            ['Last window min / max (counts)', w ? `${w.min} / ${w.max}` : '--'],
            ['Last window peak-to-peak', formatCounts(w?.ptp)],
            ['Heart rate (R-peaks)', p.heart_rate_bpm ? `${formatHeartRate(p.heart_rate_bpm)} bpm` : '--'],
          ]}
        />
      </div>
    </div>
  )
}
