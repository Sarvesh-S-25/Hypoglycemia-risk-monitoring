import styles from './Toggle.module.css'

/**
 * The "Early Pay" switch from the reference: 52x30 pill, 24px knob
 * (docs/DESIGN_SYSTEM.md section 5). Controlled component.
 */
export default function Toggle({ checked, onChange, label, disabled = false }) {
  return (
    <label className={`${styles.wrap} ${disabled ? styles.disabled : ''}`}>
      {label && <span className={styles.label}>{label}</span>}
      <span
        role="switch"
        aria-checked={checked}
        tabIndex={disabled ? -1 : 0}
        className={`${styles.track} ${checked ? styles.on : ''}`}
        onClick={() => !disabled && onChange?.(!checked)}
        onKeyDown={(e) => {
          if (!disabled && (e.key === 'Enter' || e.key === ' ')) {
            e.preventDefault()
            onChange?.(!checked)
          }
        }}
      >
        <span className={styles.knob} />
      </span>
    </label>
  )
}
