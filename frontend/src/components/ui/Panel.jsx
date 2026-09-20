import styles from './Panel.module.css'

/**
 * The floating white "device screen" panel that sits inside a Card. Every
 * chart lives in one of these (docs/DESIGN_SYSTEM.md section 8).
 */
export default function Panel({ className = '', children, ...rest }) {
  return (
    <div className={`${styles.panel} ${className}`} {...rest}>
      {children}
    </div>
  )
}
