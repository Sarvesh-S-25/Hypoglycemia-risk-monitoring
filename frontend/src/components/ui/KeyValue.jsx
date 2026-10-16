import styles from './KeyValue.module.css'

/**
 * Two-column label/value list for the engineering view. `rows` is a list of
 * [label, value] pairs; values are already formatted by lib/format.js.
 */
export default function KeyValue({ rows }) {
  return (
    <dl className={styles.list}>
      {rows.map(([label, value]) => (
        <div key={label} className={styles.row}>
          <dt className={styles.label}>{label}</dt>
          <dd className={styles.value}>{value}</dd>
        </div>
      ))}
    </dl>
  )
}
