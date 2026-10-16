// @vitest-environment jsdom
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import ECGWaveform from './ECGWaveform.jsx'
import HeartRate from './HeartRate.jsx'
import Activity from './Activity.jsx'

/**
 * The hardware-facing states added with the USB serial source: leads off,
 * a rejected window, no heart-rate estimate yet, and motion -- each must say
 * what is going on instead of drawing a flat line or a bare dash.
 */

afterEach(cleanup)

const window100 = (over = {}) => ({
  window_start_ts: 1, sample_rate_hz: 100, sqi: 1, leads_off: false,
  samples: Array.from({ length: 100 }, (_, i) => Math.round(1000 * Math.sin(i / 5))),
  ...over,
})

describe('ECGWaveform hardware states', () => {
  it('shows a leads-off message instead of a flat trace', () => {
    render(<ECGWaveform window={window100({ sqi: 0, leads_off: true, samples: Array(100).fill(0) })} />)
    expect(screen.getByText('Leads off')).toBeTruthy()
    expect(screen.queryByText('No ECG signal')).toBeNull()
  })

  it('flags a rejected window without hiding the trace', () => {
    render(<ECGWaveform window={window100({ sqi: 0 })} />)
    expect(screen.getByText(/rejected/i)).toBeTruthy()
    expect(screen.queryByText('Leads off')).toBeNull()
  })

  it('shows neither message for a clean window', () => {
    render(<ECGWaveform window={window100()} />)
    expect(screen.queryByText('Leads off')).toBeNull()
    expect(screen.queryByText(/rejected/i)).toBeNull()
  })
})

describe('HeartRate', () => {
  it('shows the backend estimate', () => {
    render(<HeartRate status={{ connected: true, heart_rate_bpm: 72.4 }} />)
    expect(screen.getByLabelText('heart rate').textContent).toContain('72')
  })

  it('explains a missing estimate when leads are off', () => {
    render(<HeartRate status={{ connected: true, leads_off: true, heart_rate_bpm: null }} />)
    expect(screen.getByText('--')).toBeTruthy()
    expect(screen.getByText(/attach the electrodes/i)).toBeTruthy()
  })

  it('renders with no status at all', () => {
    render(<HeartRate status={null} />)
    expect(screen.getByText('Device disconnected.')).toBeTruthy()
  })
})

describe('Activity', () => {
  it('displays the backend moving verdict', () => {
    render(<Activity status={{ moving: true, motion_ms2: 3.2 }} />)
    expect(screen.getByText('Moving')).toBeTruthy()
    expect(screen.getByText(/3\.20 m\/s²/)).toBeTruthy()
  })

  it('shows still when not moving', () => {
    render(<Activity status={{ moving: false, motion_ms2: 0.04 }} />)
    expect(screen.getByText('Still')).toBeTruthy()
  })

  it('handles a source without an accelerometer', () => {
    render(<Activity status={{ moving: null, motion_ms2: null }} />)
    expect(screen.getByText('No data')).toBeTruthy()
  })
})
