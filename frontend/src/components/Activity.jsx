import Badge from './ui/Badge.jsx'
import { formatMotion } from '../lib/format.js'

/**
 * Wearer activity from the accelerometer (SRD 3.1's motion gating made
 * visible). `moving` is the backend's verdict -- per AGENTS.md this component
 * only displays it, it never thresholds `motion_ms2` itself.
 */
export default function Activity({ status }) {
  const moving = status?.moving ?? null
  const motion = status?.motion_ms2 ?? null

  let badge
  if (moving === null) badge = <Badge color="var(--gs-ink-faint)">No data</Badge>
  else if (moving) badge = <Badge color="var(--gs-warn)">Moving</Badge>
  else badge = <Badge color="var(--gs-ok)">Still</Badge>

  return (
    <div>
      {badge}
      <p className="gs-body" style={{ marginTop: 8, fontSize: 13 }}>
        Motion {formatMotion(motion)}.{' '}
        {moving ? 'ECG windows are rejected while moving.' : 'Movement rejects ECG windows as artifact.'}
      </p>
    </div>
  )
}
