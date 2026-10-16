import styles from './Segmented.module.css'

/**
 * Pill segmented control (the Risk trend range picker, made reusable).
 * `options` is a list of { value, label }.
 */
export default function Segmented({ options, value, onChange, label }) {
  return (
    <div className={styles.wrap} role="group" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          className={`${styles.item} ${o.value === value ? styles.active : ''}`}
          aria-pressed={o.value === value}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
