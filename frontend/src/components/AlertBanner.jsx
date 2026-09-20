import { useState } from 'react'
import Button from './ui/Button.jsx'
import Badge from './ui/Badge.jsx'
import { formatClockTime, formatRiskScore } from '../lib/format.js'
import { api } from '../lib/api.js'

/**
 * Dismissible high-risk alert banner (SRD 5.1). Dismissing acknowledges the
 * alert via REST (docs/API_CONTRACT.md POST /api/alerts/{id}/ack) in addition
 * to removing it locally, so the acknowledgement is recorded for the session
 * summary/export -- a purely-local dismiss would silently lose that.
 */
export default function AlertBanner({ alert, onDismiss }) {
  const [acking, setAcking] = useState(false)

  if (!alert) return null

  async function handleDismiss() {
    setAcking(true)
    try {
      await api.ackAlert(alert.id)
    } catch {
      // Even if the ack call fails (e.g. backend restarted), still remove it
      // locally -- a stuck banner is worse than a possibly-unacknowledged row.
    } finally {
      setAcking(false)
      onDismiss?.(alert.id)
    }
  }

  return (
    // Per docs/DESIGN_SYSTEM.md section 8 ("don't flood a whole card in a
    // status color"), the alert surface stays the normal white/line
    // treatment; urgency is carried only by the Badge's dot + border color
    // and a colored left rule, matching how the design system uses status
    // color everywhere else (mode badges).
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 16,
        background: 'var(--gs-surface-white)',
        borderLeft: '3px solid var(--gs-danger)',
        borderRadius: 'var(--gs-radius-field)',
        padding: '14px 20px',
        marginBottom: 24,
        boxShadow: 'var(--gs-shadow-pop)',
      }}
      role="alert"
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <Badge color="var(--gs-danger)">High risk</Badge>
        <span style={{ fontSize: 13, color: 'var(--gs-ink-muted)' }}>
          Sustained elevated risk confirmed -- score {formatRiskScore(alert.score)} at {formatClockTime(alert.timestamp)}
        </span>
      </div>
      <Button variant="ghost" onClick={handleDismiss} disabled={acking}>
        {acking ? 'Acknowledging...' : 'Dismiss'}
      </Button>
    </div>
  )
}
