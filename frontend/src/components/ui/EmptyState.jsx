import styles from './EmptyState.module.css'

/**
 * Deliberate empty/disconnected state (SRD 5.3: "must render correctly with
 * no data ... don't crash on empty state"). Used inside a Panel whenever
 * there's nothing to chart yet.
 */
export default function EmptyState({ title = 'No data yet', hint }) {
  return (
    <div className={styles.wrap}>
      <p className={styles.title}>{title}</p>
      {hint && <p className={styles.hint}>{hint}</p>}
    </div>
  )
}
