import { describe, it, expect } from 'vitest'
import {
  formatRiskScore, formatTemperature, formatBattery, formatCountdown,
  formatDuration, formatDeltaT, formatRelativeTime, formatHeartRate, formatMotion,
} from './format.js'

describe('formatRiskScore', () => {
  it('formats to two decimals', () => {
    expect(formatRiskScore(0.3421)).toBe('0.34')
  })
  it('handles null/undefined without crashing (SRD 5.3 empty state)', () => {
    expect(formatRiskScore(null)).toBe('--')
    expect(formatRiskScore(undefined)).toBe('--')
  })
})

describe('formatTemperature', () => {
  it('formats with one decimal and the degree symbol', () => {
    expect(formatTemperature(31.24)).toBe('31.2°C')
  })
  it('handles missing data', () => {
    expect(formatTemperature(null)).toBe('--')
  })
})

describe('formatBattery', () => {
  it('rounds to the nearest integer percent', () => {
    expect(formatBattery(77.6)).toBe('78%')
  })
})

describe('formatDeltaT', () => {
  it('prefixes with the delta symbol', () => {
    expect(formatDeltaT(1.1)).toBe('Δ1.1°C')
  })
})

describe('formatCountdown', () => {
  it('says "due now" for a past or equal timestamp', () => {
    const now = 1_700_000_000_000
    expect(formatCountdown(1_700_000_000 - 10, now)).toBe('due now')
  })
  it('formats hours and minutes remaining', () => {
    const now = 1_700_000_000_000
    const target = now / 1000 + 2 * 3600 + 15 * 60 // 2h15m from now
    expect(formatCountdown(target, now)).toBe('2h 15m')
  })
  it('formats minutes and seconds when under an hour', () => {
    const now = 1_700_000_000_000
    const target = now / 1000 + 5 * 60 + 30
    expect(formatCountdown(target, now)).toBe('5m 30s')
  })
  it('handles a null target without crashing', () => {
    expect(formatCountdown(null)).toBe('--')
  })
})

describe('formatDuration', () => {
  it('formats hours and minutes', () => {
    expect(formatDuration(3 * 3600 + 25 * 60)).toBe('3h 25m')
  })
  it('formats minutes only when under an hour', () => {
    expect(formatDuration(42 * 60)).toBe('42m')
  })
  it('handles zero/negative without crashing', () => {
    expect(formatDuration(0)).toBe('0m')
    expect(formatDuration(-5)).toBe('0m')
  })
})

describe('formatRelativeTime', () => {
  it('says "just now" for very recent timestamps', () => {
    const now = 1_700_000_000_000
    expect(formatRelativeTime(now / 1000 - 2, now)).toBe('just now')
  })
  it('formats seconds, minutes, hours, and days appropriately', () => {
    const now = 1_700_000_000_000
    expect(formatRelativeTime(now / 1000 - 30, now)).toBe('30s ago')
    expect(formatRelativeTime(now / 1000 - 120, now)).toBe('2m ago')
    expect(formatRelativeTime(now / 1000 - 7200, now)).toBe('2h ago')
    expect(formatRelativeTime(now / 1000 - 172800, now)).toBe('2d ago')
  })
})

describe('formatHeartRate', () => {
  it('rounds to whole beats per minute', () => {
    expect(formatHeartRate(72.4)).toBe('72')
    expect(formatHeartRate(59.6)).toBe('60')
  })
  it('handles no estimate yet', () => {
    expect(formatHeartRate(null)).toBe('--')
    expect(formatHeartRate(undefined)).toBe('--')
  })
})

describe('formatMotion', () => {
  it('formats with two decimals and units', () => {
    expect(formatMotion(0.0412)).toBe('0.04 m/s²')
  })
  it('handles a source without an accelerometer', () => {
    expect(formatMotion(null)).toBe('--')
  })
})
