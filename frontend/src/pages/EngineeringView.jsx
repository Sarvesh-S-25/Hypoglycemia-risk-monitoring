import { Card, EmptyState, Panel } from '../components/ui/index.js'
import ECGWaveform from '../components/ECGWaveform.jsx'
import LinksPanel from '../components/engineering/LinksPanel.jsx'
import PipelinePanel from '../components/engineering/PipelinePanel.jsx'
import ModelPanel from '../components/engineering/ModelPanel.jsx'
import ControllerPanel from '../components/engineering/ControllerPanel.jsx'
import SchedulerPanel from '../components/engineering/SchedulerPanel.jsx'
import SimulatorPanel from '../components/engineering/SimulatorPanel.jsx'
import { useDiagnostics } from '../hooks/useDiagnostics.js'

/**
 * What the backend is working with: link state, window counts and rejection
 * reasons, the model's buffer, the controller's thresholds and confirmation
 * count, and the foot scheduler. All from GET /api/diagnostics, so it shows
 * the same numbers the decisions were made from.
 */
export default function EngineeringView({ live }) {
  const { data: d, error } = useDiagnostics()

  if (!d) {
    return (
      <Card tone="white">
        <EmptyState
          title={error ? 'Backend not reachable' : 'Loading diagnostics'}
          hint={error ? 'Start the backend, then this view refreshes every second.' : undefined}
        />
      </Card>
    )
  }

  const sim = d.simulator
  const showSim = sim?.enabled && (sim.ecg || sim.foot)

  return (
    <div className="gs-grid">
      {showSim && (
        <div className="gs-span-12">
          <Card tone="grey">
            <SimulatorPanel sim={sim} />
          </Card>
        </div>
      )}

      <div className="gs-span-8">
        <Card tone="dark" style={{ height: '100%' }}>
          <h3 className="gs-card-title" style={{ color: 'var(--gs-ink-invert)' }}>Raw ECG stream</h3>
          <p className="gs-body" style={{ color: 'var(--gs-ink-invert-mut)', marginBottom: 16 }}>
            As received: {d.pipeline.sample_rate_hz} Hz ADC counts, unfiltered. The model sees a filtered copy.
          </p>
          <Panel>
            <ECGWaveform window={live.ecgWindow} />
          </Panel>
        </Card>
      </div>

      <div className="gs-span-4">
        <Card tone="white" style={{ height: '100%' }}>
          <LinksPanel link={d.link} sessionId={live.status?.session_id} />
        </Card>
      </div>

      <div className="gs-span-6">
        <Card tone="white" style={{ height: '100%' }}>
          <PipelinePanel pipeline={d.pipeline} />
        </Card>
      </div>

      <div className="gs-span-6">
        <Card tone="white" style={{ height: '100%' }}>
          <ModelPanel model={d.model} />
        </Card>
      </div>

      <div className="gs-span-12">
        <Card tone="white">
          <ControllerPanel controller={d.controller} />
        </Card>
      </div>

      <div className="gs-span-12">
        <Card tone="white">
          <SchedulerPanel foot={d.foot} />
        </Card>
      </div>
    </div>
  )
}
