/**
 * Reconnecting WebSocket client for /ws/live (docs/API_CONTRACT.md section 4).
 * Exponential backoff starting at 1s, capped at 15s, per that doc's notes.
 * Components never construct `new WebSocket` directly (AGENTS.md) -- they go
 * through `hooks/useWebSocket.js`, which wraps this class.
 */
const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'
const WS_URL = API_BASE.replace(/^http/, 'ws') + '/ws/live'

const MIN_BACKOFF_MS = 1000
const MAX_BACKOFF_MS = 15000

export class LiveSocket {
  constructor({ onFrame, onConnectionChange } = {}) {
    this.onFrame = onFrame
    this.onConnectionChange = onConnectionChange
    this.ws = null
    this.backoff = MIN_BACKOFF_MS
    this.closedByUser = false
    this._reconnectTimer = null
  }

  connect() {
    this.closedByUser = false
    this._open()
  }

  _open() {
    try {
      this.ws = new WebSocket(WS_URL)
    } catch {
      this._scheduleReconnect()
      return
    }

    this.ws.onopen = () => {
      this.backoff = MIN_BACKOFF_MS
      this.onConnectionChange?.(true)
    }

    this.ws.onmessage = (event) => {
      let frame
      try {
        frame = JSON.parse(event.data)
      } catch {
        return // malformed frame -- ignore rather than crash the dashboard
      }
      // Per docs/API_CONTRACT.md section 4: tolerate unknown frame types by
      // ignoring them, so the backend can add frames later without breaking
      // a deployed dashboard. onFrame itself does the type dispatch.
      this.onFrame?.(frame)
    }

    this.ws.onclose = () => {
      this.onConnectionChange?.(false)
      if (!this.closedByUser) this._scheduleReconnect()
    }

    this.ws.onerror = () => {
      this.ws?.close()
    }
  }

  _scheduleReconnect() {
    clearTimeout(this._reconnectTimer)
    this._reconnectTimer = setTimeout(() => {
      this.backoff = Math.min(this.backoff * 2, MAX_BACKOFF_MS)
      this._open()
    }, this.backoff)
  }

  close() {
    this.closedByUser = true
    clearTimeout(this._reconnectTimer)
    this.ws?.close()
  }
}
