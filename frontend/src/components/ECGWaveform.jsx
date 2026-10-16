import { useEffect, useRef } from 'react'
import EmptyState from './ui/EmptyState.jsx'

/**
 * Live scrolling ECG trace (SRD 5.1: "last ~10 sec", via WebSocket).
 *
 * Deliberately a raw <canvas>, not Recharts -- documented in docs/PLAN.md
 * section 2.3 and section 7 item 2: a 100 Hz scrolling trace redrawn every
 * frame would make Recharts allocate/diff thousands of SVG nodes per second
 * and drop frames. RiskTrend (a slow line chart) uses Recharts; this doesn't.
 *
 * Redraws on the animation frame, never via CSS animation (DESIGN_SYSTEM
 * section 7).
 */
export default function ECGWaveform({ window: ecgWindow, height = 220 }) {
  const canvasRef = useRef(null)
  const rafRef = useRef(null)
  const bufferRef = useRef([]) // flat sample history for smooth scrolling across window boundaries

  const leadsOff = ecgWindow?.leads_off === true

  useEffect(() => {
    if (ecgWindow?.leads_off) {
      // The device sends flat zeros while leads are off. Plotting them draws a
      // dead line, and keeping them in the buffer would squash the vertical
      // scale for the first ~10 s after the electrodes go back on -- so drop
      // the history and show the leads-off state instead.
      bufferRef.current = []
      return
    }
    if (ecgWindow?.samples?.length) {
      // Append new samples; keep a rolling buffer wide enough for ~10s at
      // the reported sample rate (SRD 5.1's "last ~10 sec").
      const maxSamples = (ecgWindow.sample_rate_hz || 100) * 10
      bufferRef.current = [...bufferRef.current, ...ecgWindow.samples].slice(-maxSamples)
    }
  }, [ecgWindow])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    // getContext('2d') can return null (context unavailable, or a
    // non-canvas test environment like jsdom without the `canvas` package)
    // -- bail out instead of throwing on every animation frame.
    if (!ctx) return

    function draw() {
      const dpr = window.devicePixelRatio || 1
      const rect = canvas.getBoundingClientRect()
      const w = Math.max(1, Math.round(rect.width))
      const h = Math.max(1, Math.round(rect.height))
      if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
        canvas.width = w * dpr
        canvas.height = h * dpr
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, w, h)

      const samples = bufferRef.current
      if (samples.length > 1) {
        const isStale = ecgWindow?.sqi === 0
        const strokeStyle = isStale
          ? getComputedStyle(document.documentElement).getPropertyValue('--gs-trace-stale').trim()
          : getComputedStyle(document.documentElement).getPropertyValue('--gs-trace').trim()

        const min = Math.min(...samples)
        const max = Math.max(...samples)
        const range = max - min || 1
        const pad = h * 0.1

        ctx.beginPath()
        ctx.strokeStyle = strokeStyle || '#1B2821'
        ctx.lineWidth = 1.5
        ctx.lineJoin = 'round'
        samples.forEach((v, i) => {
          const x = (i / (samples.length - 1)) * w
          const y = h - pad - ((v - min) / range) * (h - pad * 2)
          if (i === 0) ctx.moveTo(x, y)
          else ctx.lineTo(x, y)
        })
        ctx.stroke()
      }

      rafRef.current = requestAnimationFrame(draw)
    }

    rafRef.current = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(rafRef.current)
  }, [ecgWindow?.sqi])

  const hasData = bufferRef.current.length > 0 || ((ecgWindow?.samples?.length ?? 0) > 0 && !leadsOff)
  const rejected = ecgWindow?.sqi === 0 && !leadsOff && hasData

  return (
    <div style={{ position: 'relative', height }}>
      <canvas ref={canvasRef} style={{ width: '100%', height: '100%', display: 'block' }} />
      {leadsOff && (
        <div style={{ position: 'absolute', inset: 0 }} role="status">
          <EmptyState
            title="Leads off"
            hint="Attach the electrodes (RA, LA, RL) to see the ECG trace."
          />
        </div>
      )}
      {!leadsOff && !hasData && (
        <div style={{ position: 'absolute', inset: 0 }}>
          <EmptyState title="No ECG signal" hint="Waiting for device or simulator data..." />
        </div>
      )}
      {rejected && (
        <span
          className="gs-label"
          role="status"
          style={{ position: 'absolute', top: 8, left: 12, color: 'var(--gs-warn)' }}
        >
          Window rejected -- motion or noise
        </span>
      )}
    </div>
  )
}
