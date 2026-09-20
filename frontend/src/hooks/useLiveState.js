import { useCallback, useReducer } from 'react'
import { useWebSocket } from './useWebSocket.js'

const MAX_ALERTS = 5

const initialState = {
  status: null, // GET /api/status shape, from the "hello" frame then "status" frames
  ecgWindow: null, // most recent ecg_window frame
  risk: null, // most recent risk_update frame
  alerts: [], // unacknowledged alerts, most recent first
  footCheck: null, // most recent foot_check_result frame
}

// Exported separately (not just used internally) so it can be unit-tested
// directly without rendering a component or a DOM environment -- see
// src/hooks/useLiveState.test.js.
export function liveStateReducer(state, frame) {
  switch (frame.type) {
    case 'hello':
    case 'status':
      return { ...state, status: frame.data }
    case 'ecg_window':
      return { ...state, ecgWindow: frame.data }
    case 'risk_update':
      return { ...state, risk: frame.data }
    case 'alert':
      return { ...state, alerts: [frame.data, ...state.alerts].slice(0, MAX_ALERTS) }
    case 'foot_check_result':
      return { ...state, footCheck: frame.data }
    case '__dismiss_alert':
      return { ...state, alerts: state.alerts.filter((a) => a.id !== frame.data.id) }
    default:
      // Per docs/API_CONTRACT.md section 4: unknown frame types are ignored,
      // not an error -- lets the backend add frames without breaking this build.
      return state
  }
}

/**
 * Merges the WebSocket's hello frame and every subsequent live frame into one
 * coherent object (SRD 5.2, extended per docs/PLAN.md section 2.2). This is
 * the single source of live data for the dashboard -- per AGENTS.md, the
 * frontend never re-derives a mode or risk score, it only displays what
 * arrives here.
 */
export function useLiveState() {
  const [state, dispatch] = useReducer(liveStateReducer, initialState)
  const { connected } = useWebSocket(dispatch)

  const dismissAlert = useCallback((id) => {
    dispatch({ type: '__dismiss_alert', data: { id } })
  }, [])

  return { ...state, connected, dismissAlert }
}
