import styles from './SectionHeader.module.css'

/**
 * Eyebrow + serif display heading on the left, action buttons on the right --
 * mirrors the reference's Sign-in/Create-invoice pair
 * (docs/DESIGN_SYSTEM.md section 5).
 */
export default function SectionHeader({ eyebrow, title, tail, actions }) {
  return (
    <div className={styles.header}>
      <div>
        {eyebrow && <p className="gs-eyebrow">{eyebrow}</p>}
        <h2 className="gs-display">
          {title}
          {tail && <span className="tail"> {tail}</span>}
        </h2>
      </div>
      {actions && <div className={styles.actions}>{actions}</div>}
    </div>
  )
}
