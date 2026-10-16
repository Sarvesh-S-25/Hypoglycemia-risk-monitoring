import ModeIndicator from './ModeIndicator.jsx'
import { formatRelativeTime, formatRiskScore, formatSeconds } from '../lib/format.js'

/**
 * The current risk score, or -- with the reason there isn't one. Every
 * reason is a backend fact (connection, leads-off, the backend's motion
 * verdict, risk_ready_in_s); nothing here thresholds a number (AGENTS.md,
 * docs/POLICIES.md P2 and P9).
 */
export default function RiskNow({ score, mode, scoreTs, status }) {
  return (
    <div>
      <div className="gs-metric" aria-label="current risk" style={{ fontSize: 56, marginBottom: 12 }}>
        {formatRiskScore(score)}
      </div>
      <ModeIndicator mode={mode} />
      <p className="gs-body" style={{ marginTop: 12, fontSize: 13 }}>
        {reason(score, scoreTs, status)}
      </p>
    </div>
  )
}

function reason(score, scoreTs, status) {
  if (!status?.connected) return 'ECG node disconnected -- no score.'
  if (status.leads_off) return 'Leads off -- attach the electrodes to get a score.'
  if (status.moving) return 'Hold still -- movement makes the ECG unreadable, so it is not scored.'
  if (status.risk_ready_in_s > 0) {
    return `Warming up -- ${formatSeconds(status.risk_ready_in_s)} more of still, clean ECG needed.`
  }
  if (score === null || score === undefined) return 'Waiting for the first score.'
  return `Scored from the last 30 s of ECG, ${formatRelativeTime(scoreTs)}.`
}
