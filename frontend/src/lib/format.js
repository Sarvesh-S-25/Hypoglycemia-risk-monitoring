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

export function formatHeartRate(bpm) {
  if (bpm === null || bpm === undefined) return '--'
  return `${Math.round(bpm)}`
}

/** Motion intensity: std-dev of acceleration magnitude, m/s^2. */
export function formatMotion(ms2) {
  if (ms2 === null || ms2 === undefined) return '--'
  return `${ms2.toFixed(2)} m/s²`
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

/** A share of a total, e.g. accepted windows: "80% (96/120)". */
export function formatShare(part, total) {
  if (part === null || part === undefined || !total) return '--'
  return `${Math.round((part / total) * 100)}% (${part}/${total})`
}

export function formatMs(ms) {
  if (ms === null || ms === undefined) return '--'
  return `${ms.toFixed(1)} ms`
}

/** Short durations: "18 s", "4m 10s". */
export function formatSeconds(seconds) {
  if (seconds === null || seconds === undefined) return '--'
  if (seconds < 60) return `${Math.round(seconds)} s`
  const m = Math.floor(seconds / 60)
  return `${m}m ${Math.round(seconds % 60)}s`
}

/** Schedule intervals: 86400 -> "24 h", 1800 -> "30 min". */
export function formatInterval(seconds) {
  if (seconds === null || seconds === undefined) return '--'
  if (seconds >= 3600) return `${+(seconds / 3600).toFixed(1)} h`
  return `${Math.round(seconds / 60)} min`
}

/** Raw ADC counts from the ADS1115 (0.125 mV each at +-4.096 V). */
export function formatCounts(n) {
  if (n === null || n === undefined) return '--'
  return `${n}`
}

export function formatThreshold(value, unit = '') {
  if (value === null || value === undefined) return '--'
  return `${value}${unit}`
}
