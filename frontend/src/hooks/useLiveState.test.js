import { describe, it, expect } from 'vitest'
import { liveStateReducer } from './useLiveState.js'

const initial = { status: null, ecgWindow: null, risk: null, alerts: [], footCheck: null }

describe('liveStateReducer', () => {
  it('adopts the hello frame as status', () => {
    const state = liveStateReducer(initial, { type: 'hello', data: { connected: true, mode: 'Normal' } })
    expect(state.status).toEqual({ connected: true, mode: 'Normal' })
  })

  it('updates status on a later status frame', () => {
    let state = liveStateReducer(initial, { type: 'hello', data: { mode: 'Normal' } })
    state = liveStateReducer(state, { type: 'status', data: { mode: 'Watch' } })
    expect(state.status.mode).toBe('Watch')
  })

  it('replaces ecgWindow and risk on each new frame (not accumulated)', () => {
    let state = liveStateReducer(initial, { type: 'ecg_window', data: { window_start_ts: 1 } })
    state = liveStateReducer(state, { type: 'ecg_window', data: { window_start_ts: 2 } })
    expect(state.ecgWindow).toEqual({ window_start_ts: 2 })

    state = liveStateReducer(state, { type: 'risk_update', data: { score: 0.5 } })
    expect(state.risk).toEqual({ score: 0.5 })
  })

  it('prepends new alerts, most recent first', () => {
    let state = liveStateReducer(initial, { type: 'alert', data: { id: 1 } })
    state = liveStateReducer(state, { type: 'alert', data: { id: 2 } })
    expect(state.alerts.map((a) => a.id)).toEqual([2, 1])
  })

  it('caps alert history at 5 entries', () => {
    let state = initial
    for (let i = 0; i < 8; i++) {
      state = liveStateReducer(state, { type: 'alert', data: { id: i } })
    }
    expect(state.alerts.length).toBe(5)
    expect(state.alerts[0].id).toBe(7) // most recent kept
  })

  it('dismisses an alert by id without touching others', () => {
    let state = initial
    state = liveStateReducer(state, { type: 'alert', data: { id: 1 } })
    state = liveStateReducer(state, { type: 'alert', data: { id: 2 } })
    state = liveStateReducer(state, { type: '__dismiss_alert', data: { id: 1 } })
    expect(state.alerts.map((a) => a.id)).toEqual([2])
  })

  it('ignores unknown frame types instead of throwing (forward compatibility)', () => {
    expect(() => liveStateReducer(initial, { type: 'future_frame_type', data: {} })).not.toThrow()
    const state = liveStateReducer(initial, { type: 'future_frame_type', data: {} })
    expect(state).toEqual(initial)
  })

  it('adopts a foot_check_result frame', () => {
    const state = liveStateReducer(initial, { type: 'foot_check_result', data: { delta_t: 1.1, valid: true } })
    expect(state.footCheck).toEqual({ delta_t: 1.1, valid: true })
  })
})
