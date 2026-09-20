import Badge from './ui/Badge.jsx'

const MODE_EXPLANATIONS = {
  Eco: 'Risk low, battery conserving, sampling reduced.',
  Normal: 'Default operating state.',
  Watch: 'Risk trending upward -- sampling increased.',
  Verify: 'Risk crossed the alert threshold -- confirming before firing.',
}

/**
 * Current controller mode badge with color coding (SRD 5.1). The mode always
 * comes from the backend's status/risk_update frames -- per AGENTS.md, this
 * component never computes a mode itself.
 */
export default function ModeIndicator({ mode }) {
  if (!mode) {
    return <Badge color="var(--gs-ink-faint)">Unknown</Badge>
  }
  return (
    <div>
      <Badge mode={mode}>{mode}</Badge>
      <p className="gs-body" style={{ marginTop: 8, fontSize: 13 }}>
        {MODE_EXPLANATIONS[mode] ?? ''}
      </p>
    </div>
  )
}
