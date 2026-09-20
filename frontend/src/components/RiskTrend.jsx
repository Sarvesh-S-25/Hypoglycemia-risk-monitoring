import { useState, useMemo } from 'react'
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, ReferenceLine,
} from 'recharts'
import { useApi } from '../hooks/useApi.js'
import { formatClockTime, formatRiskScore } from '../lib/format.js'
import EmptyState from './ui/EmptyState.jsx'

const RANGES = ['15m', '1h', '6h', '24h']

/**
 * Rolling hypoglycemia-risk trace, selectable 1-6hr range (SRD 5.1). Fetches
 * history once via REST on mount/range-change, then is extended live by
 * `liveRisk` (the most recent risk_update frame) so the line keeps moving
 * between polls without re-fetching the whole history over WebSocket.
 */
export default function RiskTrend({ liveRisk, riskAlertThreshold = 0.75 }) {
  const [range, setRange] = useState('1h')
  const { data, loading } = useApi((api) => api.getRiskHistory(range), [range])

  const points = useMemo(() => {
    const history = data?.points ?? []
    if (!liveRisk) return history
    const last = history[history.length - 1]
    // Avoid double-plotting the same instant if the REST snapshot already
    // includes the latest live point.
    if (last && Math.abs(last.timestamp - liveRisk.timestamp) < 0.5) return history
    return [...history, liveRisk]
  }, [data, liveRisk])

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <h3 className="gs-card-title" style={{ margin: 0 }}>Risk trend</h3>
        <div style={{ display: 'flex', gap: 4 }}>
          {RANGES.map((r) => (
            <button
              key={r}
              onClick={() => setRange(r)}
              style={{
                border: 'none',
                background: r === range ? 'var(--gs-surface-dark)' : 'transparent',
                color: r === range ? 'var(--gs-ink-invert)' : 'var(--gs-ink-muted)',
                borderRadius: 'var(--gs-radius-pill)',
                padding: '4px 10px',
                fontSize: 12,
                cursor: 'pointer',
              }}
            >
              {r}
            </button>
          ))}
        </div>
      </div>

      {!loading && points.length === 0 ? (
        <EmptyState title="No risk data yet" hint="History appears once the device has been running for a bit." />
      ) : (
        <ResponsiveContainer width="100%" height={220}>
          {/* left margin must be >= 0: a negative value here previously
              pulled the whole chart (including Y-axis tick text) past the
              Panel's edge, clipping labels like "0.75" down to just "5" --
              found by screenshotting the live dashboard. YAxis width={40}
              gives "0.75" (4 characters at 11px) enough room to render
              without clipping or overlapping the plot area. */}
          <LineChart data={points} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <XAxis
              dataKey="timestamp"
              tickFormatter={formatClockTime}
              stroke="var(--gs-ink-faint)"
              fontSize={11}
              tickLine={false}
              axisLine={false}
              minTickGap={40}
            />
            <YAxis
              domain={[0, 1]}
              tickFormatter={formatRiskScore}
              stroke="var(--gs-ink-faint)"
              fontSize={11}
              tickLine={false}
              axisLine={false}
              width={40}
            />
            <Tooltip
              formatter={(value) => [formatRiskScore(value), 'Risk']}
              labelFormatter={formatClockTime}
              contentStyle={{
                background: 'var(--gs-surface-white)',
                border: '1px solid var(--gs-line)',
                borderRadius: 'var(--gs-radius-field)',
                fontSize: 12,
              }}
            />
            <ReferenceLine y={riskAlertThreshold} stroke="var(--gs-mode-verify)" strokeDasharray="4 4" />
            <Line
              type="monotone"
              dataKey="score"
              stroke="var(--gs-mode-normal)"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}
