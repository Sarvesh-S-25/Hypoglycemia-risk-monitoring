// @vitest-environment jsdom
import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'

const diagnostics = {
  timestamp: 1,
  link: { source: 'ble', connected: true, last_packet_ts: null, battery_pct: null, aux_source: 'ble', aux_connected: false, aux_state: 'missing' },
  pipeline: {
    sample_rate_hz: 100, windows_total: 10, windows_accepted: 6, rejected_leads_off: 3, rejected_motion: 1,
    sqi: 0, leads_off: false, motion_ms2: 1.7, motion_threshold_ms2: 1.0,
    last_window: { n_samples: 100, min: -5, max: 9, ptp: 14, mean: 0.1 }, heart_rate_bpm: null,
  },
  model: {
    name: 'ONNX: m.onnx', needed_s: 30, buffered_s: 12, input_len: 7500, input_rate_hz: 250,
    output: 'logit -> sigmoid', last_score: null, last_score_ts: null, last_inference_ms: null,
  },
  controller: {
    mode: 'Watch', manual_mode: null, risk_low: 0.3, risk_elevated: 0.55, risk_alert: 0.75,
    verify_confirm_count: 2, confirm_windows: 3, alert_cooldown_s: 300, cooldown_remaining_s: null,
    recent_scores: [0.6, 0.62], alerting: false,
  },
  foot: {
    source: 'ble', connected: false, busy: false, next_check_scheduled: null, elevated_threshold_c: 2.2,
    normal_interval_s: 86400, elevated_interval_s: 28800, invalid_retry_s: 3600, battery_min_pct: 15,
    result_timeout_s: 10, last_check: { action: 'scheduled_8h', valid: true, t_left: 30, t_right: 32.5, delta_t: 2.5, timestamp: 1 },
  },
}

vi.mock('../lib/api.js', () => ({
  api: { getDiagnostics: vi.fn(() => Promise.resolve(diagnostics)) },
  ApiError: class extends Error {},
}))

const { default: EngineeringView } = await import('./EngineeringView.jsx')
const { default: Policies } = await import('./Policies.jsx')
const { default: RiskNow } = await import('../components/RiskNow.jsx')

afterEach(cleanup)

describe('RiskNow', () => {
  it('shows -- and the warm-up countdown instead of a fake 0.00', () => {
    render(<RiskNow score={null} mode="Normal" status={{ connected: true, sqi: 1, risk_ready_in_s: 18 }} />)
    expect(screen.getByLabelText('current risk').textContent).toBe('--')
    expect(screen.getByText(/Warming up -- 18 s more/)).toBeTruthy()
  })

  it('says leads off before anything else when the electrodes are off', () => {
    render(<RiskNow score={null} mode="Normal" status={{ connected: true, leads_off: true, moving: true }} />)
    expect(screen.getByText(/Leads off/)).toBeTruthy()
  })
})

describe('EngineeringView', () => {
  it('renders the backend state it was given', async () => {
    render(<EngineeringView live={{ ecgWindow: null, status: { session_id: 7 } }} />)
    expect(await screen.findByText('Signal pipeline')).toBeTruthy()
    expect(screen.getByText('60% (6/10) accepted')).toBeTruthy()
    expect(screen.getByText('12 s / 30 s')).toBeTruthy()
    expect(screen.getByText('2 / 3')).toBeTruthy()
    expect(screen.getAllByText('not found').length).toBeGreaterThan(0)
    // the scheduler highlights the rule the backend's last action names
    expect(screen.getByText('Valid, |ΔT| > 2.2 °C').closest('li').className).toMatch(/ruleActive/)
  })
})

describe('Policies', () => {
  it('fills policy numbers from the live configuration', async () => {
    render(<Policies />)
    expect(await screen.findByText(/An alert needs 3 consecutive scored windows/)).toBeTruthy()
    expect(screen.getByText(/next in 24 h/)).toBeTruthy()
  })
})
