import styles from './Card.module.css'

/**
 * Outer card in one of the three surface tones (or `plain`, no fill).
 * docs/DESIGN_SYSTEM.md section 8: never add a shadow here -- outer cards
 * are flat; only Panel (the inner "device screen") floats.
 */
export default function Card({ tone = 'plain', className = '', children, ...rest }) {
  const gridOverlay = tone === 'dark' ? styles.gridOverlay : ''
  return (
    <div className={`${styles.card} ${styles[tone]} ${gridOverlay} ${className}`} {...rest}>
      {children}
    </div>
  )
}
