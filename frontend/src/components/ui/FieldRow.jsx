import styles from './FieldRow.module.css'

/**
 * The reference's "$ / Client pays / USD" row pattern
 * (docs/DESIGN_SYSTEM.md section 5): a leading icon chip, a small label
 * above the value, and an optional trailing element (e.g. a chevron or a
 * secondary value).
 */
export default function FieldRow({ icon, label, value, active = false, trailing, className = '' }) {
  return (
    <div className={`${styles.row} ${className}`}>
      <span className={`${styles.chip} ${active ? styles.chipActive : ''}`}>{icon}</span>
      <span className={styles.text}>
        <span className="gs-label">{label}</span>
        <span className={styles.value}>{value}</span>
      </span>
      {trailing && <span className={styles.trailing}>{trailing}</span>}
    </div>
  )
}
