import { Card, Panel } from '../components/ui/index.js'
import ECGWaveform from '../components/ECGWaveform.jsx'
import RiskTrend from '../components/RiskTrend.jsx'
import RiskNow from '../components/RiskNow.jsx'
import HeartRate from '../components/HeartRate.jsx'
import Activity from '../components/Activity.jsx'
import SystemSummary from '../components/SystemSummary.jsx'
import FootCheck from '../components/FootCheck.jsx'

/**
 * What the wearer sees: the ECG, the current risk with a plain reason when
 * there is none, vitals, a one-line-per-part system summary, the trend, and
 * the foot check (docs/DESIGN_SYSTEM.md section 6).
 */
export default function PatientView({ live, score, scoreTs, mode }) {
  const { status, ecgWindow, risk, footCheck } = live
  const deviceConnected = status?.connected ?? live.connected

  return (
    <div className="gs-grid">
      <div className="gs-span-8">
        <Card tone="dark" style={{ height: '100%' }}>
          <h3 className="gs-card-title" style={{ color: 'var(--gs-ink-invert)' }}>ECG waveform</h3>
          <p className="gs-body" style={{ color: 'var(--gs-ink-invert-mut)', marginBottom: 16 }}>
            {deviceConnected ? 'Last ~10 seconds, live.' : 'Device disconnected.'}
          </p>
          <Panel>
            <ECGWaveform window={ecgWindow} />
          </Panel>
        </Card>
      </div>

      <div className="gs-span-4">
        <Card tone="grey" style={{ height: '100%' }}>
          <h3 className="gs-card-title">Current risk</h3>
          <RiskNow score={score} scoreTs={scoreTs} mode={mode} status={status} />
        </Card>
      </div>

      <div className="gs-span-4">
        <Card tone="white" style={{ height: '100%' }}>
          <h3 className="gs-card-title">Heart rate</h3>
          <HeartRate status={status} />
        </Card>
      </div>

      <div className="gs-span-4">
        <Card tone="white" style={{ height: '100%' }}>
          <h3 className="gs-card-title">Activity</h3>
          <Activity status={status} />
        </Card>
      </div>

      <div className="gs-span-4">
        <Card tone="white" style={{ height: '100%' }}>
          <h3 className="gs-card-title">System</h3>
          <SystemSummary status={status} />
        </Card>
      </div>

      <div className="gs-span-12">
        <Card tone="grey">
          <Panel>
            <RiskTrend liveRisk={risk} />
          </Panel>
        </Card>
      </div>

      <div className="gs-span-12">
        <Card tone="lime">
          <FootCheck liveResult={footCheck} status={status} />
        </Card>
      </div>
    </div>
  )
}
