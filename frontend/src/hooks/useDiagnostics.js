import { useEffect, useState } from 'react'
import { api } from '../lib/api.js'

/**
 * Polls GET /api/diagnostics while the engineering view is mounted
 * (docs/API_CONTRACT.md). Polling rather than a WebSocket frame because only
 * this view needs it, and once a second is plenty for a debugging readout.
 */
export function useDiagnostics(intervalMs = 1000) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    async function poll() {
      try {
        const d = await api.getDiagnostics()
        if (!cancelled) {
          setData(d)
          setError(null)
        }
      } catch (err) {
        if (!cancelled) setError(err)
      }
    }
    poll()
    const id = setInterval(poll, intervalMs)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [intervalMs])

  return { data, error }
}
