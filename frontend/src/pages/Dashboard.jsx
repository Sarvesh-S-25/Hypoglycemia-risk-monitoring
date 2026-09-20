import { Card, Panel, SectionHeader, Button } from '../components/ui/index.js'
import ECGWaveform from '../components/ECGWaveform.jsx'
import RiskTrend from '../components/RiskTrend.jsx'
import ModeIndicator from '../components/ModeIndicator.jsx'
import DeviceStatus from '../components/DeviceStatus.jsx'
import AlertBanner from '../components/AlertBanner.jsx'
import { useLiveState } from '../hooks/useLiveState.js'
import { useApi } from '../hooks/useApi.js'
import { formatRiskScore } from '../lib/format.js'

/**
 * Main dashboard (SRD 5.1, layout per docs/DESIGN_SYSTEM.md section 6).
 * Everything shown here comes from the backend's live WebSocket state or its
 * REST snapshots -- per AGENTS.md, this page never computes a mode or
 * thresholds a risk score itself.
 */
export default function Dashboard() {
  const { status, ecgWindow, risk, alerts, connected, dismissAlert } = useLiveState()

  // First-paint fallback before any WebSocket frame has arrived -- the
  // "hello" frame covers status, but risk/current is fetched once via REST
  // so the risk metric isn't blank for the first second of a page load.
  const { data: initialRisk } = useApi((api) => api.getRiskCurrent(), [])

  const currentScore = risk?.score ?? initialRisk?.score ?? null
  // Same fallback chain as currentScore, and status?.mode as a further
  // fallback for the case where the initial REST call also hasn't resolved
  // yet but a WebSocket status frame already has -- originally this only
  // checked status?.mode and skipped initialRisk?.mode entirely, so the mode
  // badge showed "Unknown" for a moment even after the REST fetch of
  // /api/risk/current had already returned a real mode. Caught by
  // Dashboard.test.jsx's "renders live risk score and mode once data arrives".
  const currentMode = risk?.mode ?? initialRisk?.mode ?? status?.mode ?? null
  const activeAlert = alerts[0] ?? null

  const deviceConnected = status?.connected ?? connected

  return (
    <div className="gs-page">
      <SectionHeader
        eyebrow="[01] Live monitoring"
        title="Continuous ECG-based hypoglycemia "
        tail="risk monitoring."
        actions={
          <Button variant="ghost" onClick={() => window.location.assign('/model')}>
            Model
          </Button>
        }
      />

      {activeAlert && <AlertBanner alert={activeAlert} onDismiss={dismissAlert} />}

      <div className="gs-grid">
        <div className="gs-span-8">
          <Card tone="dark">
            <h3 className="gs-card-title" style={{ color: 'var(--gs-ink-invert)' }}>
              ECG waveform
            </h3>
            <p className="gs-body" style={{ color: 'var(--gs-ink-invert-mut)', marginBottom: 16 }}>
              {deviceConnected ? 'Last ~10 seconds, live over WebSocket.' : 'Device disconnected.'}
            </p>
            <Panel>
              <ECGWaveform window={ecgWindow} />
            </Panel>
          </Card>
        </div>

        <div className="gs-span-4">
          <Card tone="grey">
            <h3 className="gs-card-title">Current risk</h3>
            <div className="gs-metric" style={{ marginBottom: 16 }}>
              {formatRiskScore(currentScore)}
            </div>
            <ModeIndicator mode={currentMode} />
          </Card>
        </div>

        <div className="gs-span-8">
          <Card tone="grey">
            <Panel>
              <RiskTrend liveRisk={risk} />
            </Panel>
          </Card>
        </div>

        <div className="gs-span-4">
          <Card tone="plain">
            <h3 className="gs-card-title">Device status</h3>
            <DeviceStatus status={status} />
          </Card>
        </div>
      </div>
    </div>
  )
}
