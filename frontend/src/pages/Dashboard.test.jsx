// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import Dashboard from './Dashboard.jsx'

/**
 * Render smoke tests for the exact SRD 5.3 requirement: "Must render
 * correctly with no data (device disconnected) -- don't crash on empty
 * state." No mocked/dedicated backend runs during the frontend test suite,
 * so every network call must fail, and the dashboard must still mount
 * without throwing.
 */

class FakeWebSocket {
  constructor() {
    // Never calls onopen/onmessage -- simulates a backend that never
    // accepts the connection, the worst case for the empty-state test.
  }
  close() {}
}

beforeEach(() => {
  vi.stubGlobal('WebSocket', FakeWebSocket)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('Dashboard empty/disconnected state', () => {
  it('does not throw when every REST call rejects (backend unreachable)', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new TypeError('Failed to fetch'))))

    expect(() => render(<Dashboard />)).not.toThrow()
    // Several fields (risk metric, battery, last packet, ...) all fall back
    // to '--' rather than crashing on null data -- there are legitimately
    // several of them, so assert at least one rather than a single match.
    const placeholders = await screen.findAllByText('--')
    expect(placeholders.length).toBeGreaterThan(0)
  })

  it('does not throw when REST calls resolve with genuinely empty payloads', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url) => {
        const body = url.includes('/risk/current')
          ? { score: null, mode: 'Normal', timestamp: 0, alerting: false }
          : {}
        return Promise.resolve({
          ok: true,
          headers: { get: () => 'application/json' },
          json: () => Promise.resolve(body),
        })
      }),
    )

    expect(() => render(<Dashboard />)).not.toThrow()
    expect(await screen.findByText('ECG waveform')).toBeTruthy()
    expect(screen.getByText('No ECG signal')).toBeTruthy()
  })

  it('renders the mode indicator gracefully when mode is entirely unknown', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new TypeError('Failed to fetch'))))
    render(<Dashboard />)
    expect(await screen.findByText('Unknown')).toBeTruthy()
  })
})

describe('Dashboard populated state', () => {
  it('renders live risk score and mode once data arrives', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url) => {
        const body = url.includes('/risk/current')
          ? { score: 0.42, mode: 'Watch', timestamp: 1700000000, alerting: false }
          : url.includes('/risk/history')
            ? { range: '1h', points: [] }
            : {}
        return Promise.resolve({
          ok: true,
          headers: { get: () => 'application/json' },
          json: () => Promise.resolve(body),
        })
      }),
    )

    render(<Dashboard />)
    expect(await screen.findByText('0.42')).toBeTruthy()
    expect(await screen.findByText('Watch')).toBeTruthy()
  })
})
