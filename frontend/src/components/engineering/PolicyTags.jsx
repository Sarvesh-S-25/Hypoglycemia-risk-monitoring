import styles from './Engineering.module.css'

/**
 * Links a panel to the policies that govern it (docs/POLICIES.md). `plain`
 * renders labels instead of links, for use inside a button.
 */
export default function PolicyTags({ ids, plain = false }) {
  return (
    <span className={styles.tags}>
      {ids.map((id) =>
        plain ? (
          <span key={id} className={styles.tag}>{id}</span>
        ) : (
          <a key={id} className={styles.tag} href={`/policies#${id.toLowerCase()}`}>
            {id}
          </a>
        )
      )}
    </span>
  )
}
