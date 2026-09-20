/**
 * All number/time/duration formatting the dashboard shows, in one place --
 * per AGENTS.md, "numbers shown to the user are formatted by lib/format.js,
 * never inline."
 */

export function formatRiskScore(score) {
  if (score === null || score === undefined) return '--'
  return score.toFixed(2)
}

export function formatTemperature(celsius) {
  if (celsius === null || celsius === undefined) return '--'
  return `${celsius.toFixed(1)}°C`
}

export function formatBattery(pct) {
  if (pct === null || pct === undefined) return '--'
  return `${Math.round(pct)}%`
}

export function formatClockTime(unixSeconds) {
  if (!unixSeconds) return '--'
  const d = new Date(unixSeconds * 1000)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export function formatRelativeTime(unixSeconds, nowMs = Date.now()) {
  if (!unixSeconds) return '--'
  const diffS = Math.round((nowMs - unixSeconds * 1000) / 1000)
  if (diffS < 5) return 'just now'
  if (diffS < 60) return `${diffS}s ago`
  const diffMin = Math.round(diffS / 60)
  if (diffMin < 60) return `${diffMin}m ago`
  const diffH = Math.round(diffMin / 60)
  if (diffH < 24) return `${diffH}h ago`
  return `${Math.round(diffH / 24)}d ago`
}

/** For a countdown to a future timestamp -- foot-check "next check in ...". */
export function formatCountdown(targetUnixSeconds, nowMs = Date.now()) {
  if (!targetUnixSeconds) return '--'
  const diffS = Math.round(targetUnixSeconds * 1000 - nowMs) / 1000
  if (diffS <= 0) return 'due now'
  const h = Math.floor(diffS / 3600)
  const m = Math.floor((diffS % 3600) / 60)
  if (h > 0) return `${h}h ${m}m`
  const s = Math.floor(diffS % 60)
  return `${m}m ${s}s`
}

export function formatDuration(seconds) {
  if (!seconds || seconds < 0) return '0m'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

export function formatDeltaT(deltaT) {
  if (deltaT === null || deltaT === undefined) return '--'
  return `Δ${deltaT.toFixed(1)}°C`
}
