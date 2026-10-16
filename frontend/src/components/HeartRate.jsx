import { formatHeartRate } from '../lib/format.js'

/**
 * Heart rate from the backend's R-peak estimate (`heart_rate_bpm` in
 * /api/status). Null means "not enough clean signal yet", which is a normal
 * state -- leads off, motion, or the first few seconds after attaching --
 * so it says why instead of showing a bare dash.
 */
export default function HeartRate({ status }) {
  const bpm = status?.heart_rate_bpm ?? null

  let hint = 'Estimated from R-peaks over the last few seconds.'
  if (bpm === null) {
    if (!status?.connected) hint = 'Device disconnected.'
    else if (status?.leads_off) hint = 'Leads off -- attach the electrodes.'
    else hint = 'Needs a few seconds of clean, still signal.'
  }

  return (
    <div>
      <div className="gs-metric" aria-label="heart rate">
        {formatHeartRate(bpm)}
        {bpm !== null && (
          <span className="gs-body" style={{ marginLeft: 8, fontSize: 15 }}>bpm</span>
        )}
      </div>
      <p className="gs-body" style={{ marginTop: 8, fontSize: 13 }}>{hint}</p>
    </div>
  )
}
