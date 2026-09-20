import styles from './Badge.module.css'

const MODE_VAR = {
  Eco: '--gs-mode-eco',
  Normal: '--gs-mode-normal',
  Watch: '--gs-mode-watch',
  Verify: '--gs-mode-verify',
}

/**
 * Pill badge with a colored dot + border. Used for controller mode and other
 * short status labels. `mode` picks one of the four clinical mode colors
 * (docs/DESIGN_SYSTEM.md section 2.1); pass `color` directly for anything else.
 */
export default function Badge({ mode, color, children, className = '' }) {
  const colorVar = mode ? `var(${MODE_VAR[mode] ?? '--gs-ink-muted'})` : color ?? 'var(--gs-ink-muted)'
  return (
    <span
      className={`${styles.badge} ${className}`}
      style={{ borderColor: colorVar, color: colorVar }}
    >
      <span className={styles.dot} style={{ background: colorVar }} aria-hidden="true" />
      {children}
    </span>
  )
}
