import { useState } from 'react'
import { SectionHeader, Button, Segmented } from '../components/ui/index.js'
import AlertBanner from '../components/AlertBanner.jsx'
import SimulatedNotice from '../components/SimulatedNotice.jsx'
import PatientView from './PatientView.jsx'
import EngineeringView from './EngineeringView.jsx'
import { useLiveState } from '../hooks/useLiveState.js'
import { useApi } from '../hooks/useApi.js'

const VIEWS = [
  { value: 'patient', label: 'Patient view' },
  { value: 'engineering', label: 'Engineering view' },
]

function initialView() {
  return new URLSearchParams(window.location.search).get('view') === 'engineering' ? 'engineering' : 'patient'
}

/**
 * Main dashboard (SRD 5.1). Two views of the same live state: what the
 * wearer needs to see, and what the backend is working with. Per AGENTS.md
 * neither view computes a mode or thresholds a score -- both render backend
 * state.
 */
export default function Dashboard() {
  const live = useLiveState()
  const { status, risk, alerts, dismissAlert } = live
  const [view, setView] = useState(initialView)

  // First-paint fallback before any WebSocket frame has arrived -- the
  // "hello" frame covers status, but risk/current is fetched once via REST
  // so the risk metric isn't blank for the first second of a page load.
  const { data: initialRisk } = useApi((api) => api.getRiskCurrent(), [])

  const score = risk?.score ?? initialRisk?.score ?? null
  const scoreTs = risk?.timestamp ?? initialRisk?.timestamp ?? null
  // Same fallback chain as score, then status?.mode, so the mode badge never
  // shows "Unknown" once any source has reported a real mode (caught by
  // Dashboard.test.jsx's "renders live risk score and mode once data arrives").
  const mode = risk?.mode ?? initialRisk?.mode ?? status?.mode ?? null
  const activeAlert = alerts[0] ?? null

  function changeView(next) {
    setView(next)
    const url = new URL(window.location.href)
    if (next === 'patient') url.searchParams.delete('view')
    else url.searchParams.set('view', next)
    window.history.replaceState(null, '', url)
  }

  return (
    <div className="gs-page">
      <SectionHeader
        eyebrow={view === 'patient' ? '[01] Live monitoring' : '[01] Live monitoring · backend state'}
        title="Continuous ECG-based hypoglycemia "
        tail="risk monitoring."
        actions={
          <>
            <Segmented options={VIEWS} value={view} onChange={changeView} label="Dashboard view" />
            <Button variant="ghost" onClick={() => window.location.assign('/policies')}>
              Policies
            </Button>
            <Button variant="ghost" onClick={() => window.location.assign('/model')}>
              Model
            </Button>
          </>
        }
      />

      {activeAlert && <AlertBanner alert={activeAlert} onDismiss={dismissAlert} />}

      <SimulatedNotice status={status} onOpen={() => changeView('engineering')} showLink={view === 'patient'} />

      {view === 'patient' ? (
        <PatientView live={live} score={score} scoreTs={scoreTs} mode={mode} />
      ) : (
        <EngineeringView live={live} />
      )}
    </div>
  )
}
