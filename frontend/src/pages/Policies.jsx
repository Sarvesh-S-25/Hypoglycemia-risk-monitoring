import { Button, Card, SectionHeader } from '../components/ui/index.js'
import { useDiagnostics } from '../hooks/useDiagnostics.js'
import { COMPONENTS, FAILURES, MPU_STEPS, POLICIES } from '../lib/policies.js'
import styles from './Policies.module.css'

/**
 * Operating policies, what each part does, and failure mitigations -- a
 * summary of docs/POLICIES.md with every number taken live from the
 * backend's configuration (GET /api/diagnostics).
 */
export default function Policies() {
  const { data: d } = useDiagnostics(5000)

  return (
    <div className="gs-page">
      <SectionHeader
        eyebrow="[02] How it works"
        title="Policies, parts and "
        tail="failure handling."
        actions={
          <Button variant="ghost" onClick={() => window.location.assign('/')}>
            Back to dashboard
          </Button>
        }
      />

      <div className="gs-grid">
        <div className="gs-span-12">
          <Card tone="dark">
            <h3 className="gs-card-title" style={{ color: 'var(--gs-ink-invert)' }}>
              Why the MPU6050 matters
            </h3>
            <ol className={styles.steps}>
              {MPU_STEPS.map((s, i) => (
                <li key={i}>{typeof s === 'function' ? s(d) : s}</li>
              ))}
            </ol>
          </Card>
        </div>

        {COMPONENTS.map((group) => (
          <div key={group.node} className="gs-span-4">
            <Card tone="white" style={{ height: '100%' }}>
              <h3 className="gs-card-title">{group.node}</h3>
              <dl className={styles.parts}>
                {group.parts.map(([name, job]) => (
                  <div key={name}>
                    <dt>{name}</dt>
                    <dd>{job}</dd>
                  </div>
                ))}
              </dl>
            </Card>
          </div>
        ))}

        <div className="gs-span-12">
          <Card tone="grey">
            <h3 className="gs-card-title">Policies</h3>
            <p className="gs-body" style={{ marginBottom: 16 }}>
              {d ? 'Numbers are the backend’s live settings.' : 'Start the backend to fill in the live settings.'}
            </p>
            <div className={styles.policyGrid}>
              {POLICIES.map((p) => (
                <section key={p.id} id={p.id.toLowerCase()} className={styles.policy}>
                  <span className={styles.policyId}>{p.id}</span>
                  <h4 className={styles.policyTitle}>{p.title}</h4>
                  <p className={styles.policyRule}>{p.rule(d)}</p>
                </section>
              ))}
            </div>
          </Card>
        </div>

        <div className="gs-span-12">
          <Card tone="white">
            <h3 className="gs-card-title">Failure modes and mitigations</h3>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>What goes wrong</th>
                  <th>Mitigation in place</th>
                  <th>Still open</th>
                </tr>
              </thead>
              <tbody>
                {FAILURES.map(([what, mitigation, open]) => (
                  <tr key={what}>
                    <td>{what}</td>
                    <td>{mitigation}</td>
                    <td className={open ? styles.open : ''}>{open || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="gs-body" style={{ marginTop: 16, fontSize: 13 }}>
              Full version with every failure mode: docs/POLICIES.md in the repository.
            </p>
          </Card>
        </div>
      </div>
    </div>
  )
}
