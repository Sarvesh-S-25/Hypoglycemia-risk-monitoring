import styles from './Meter.module.css'

/**
 * Horizontal fill bar for a value the backend already computed against its
 * own limit (buffer seconds of needed seconds, motion of threshold). Purely
 * visual: `tone` is chosen by the caller from backend state, never by
 * comparing numbers here.
 */
export default function Meter({ value, max, tone = 'ink', marker, label }) {
  const pct = max > 0 && value !== null && value !== undefined ? Math.min(100, (value / max) * 100) : 0
  const markerPct = marker !== undefined && max > 0 ? Math.min(100, (marker / max) * 100) : null
  return (
    <div className={styles.track} role="meter" aria-label={label} aria-valuenow={value ?? 0} aria-valuemax={max}>
      <div className={`${styles.fill} ${styles[tone]}`} style={{ width: `${pct}%` }} />
      {markerPct !== null && <div className={styles.marker} style={{ left: `${markerPct}%` }} />}
    </div>
  )
}
