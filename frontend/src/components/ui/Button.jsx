import styles from './Button.module.css'

/**
 * Pill button in one of four variants (docs/DESIGN_SYSTEM.md section 5).
 * `arrow` adds the trailing "->" used on primary actions in the reference.
 */
export default function Button({
  variant = 'dark',
  arrow = false,
  children,
  className = '',
  ...rest
}) {
  return (
    <button className={`${styles.btn} ${styles[variant]} ${className}`} {...rest}>
      <span>{children}</span>
      {arrow && <span className={styles.arrow} aria-hidden="true">&rarr;</span>}
    </button>
  )
}
