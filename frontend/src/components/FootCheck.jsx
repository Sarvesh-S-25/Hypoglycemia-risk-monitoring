import { useEffect, useState } from 'react'
import { Badge, Button, EmptyState, FieldRow, Panel } from './ui/index.js'
import { useApi } from '../hooks/useApi.js'
import { api, ApiError } from '../lib/api.js'
import {
  formatClockTime,
  formatCountdown,
  formatDeltaT,
  formatRelativeTime,
  formatTemperature,
} from '../lib/format.js'
import styles from './FootCheck.module.css'

const HISTORY_ROWS = 8

/**
 * Foot-check card (SRD 5.1): last bilateral result, countdown to the next
 * scheduled check, history, and the manual "request check now" trigger.
 * The schedule and the elevated flag both come from the backend's scheduler;
 * per AGENTS.md this component never compares delta_t to a threshold.
 */
export default function FootCheck({ liveResult, status }) {
  // Refetch history whenever a new result arrives over the WebSocket, so the
  // list and the next-check time stay in step with the live frame.
  const { data: history } = useApi((a) => a.getFootHistory(HISTORY_ROWS), [liveResult?.id])
  const [requesting, setRequesting] = useState(false)
  const [message, setMessage] = useState(null)
  const [, setTick] = useState(0)

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 1000)
    return () => clearInterval(id)
  }, [])

  // A request in flight ends when its result frame arrives.
  useEffect(() => {
    if (liveResult) setRequesting(false)
  }, [liveResult?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  const checks = history?.checks ?? []
  const last = liveResult ?? checks[0] ?? null
  const nextCheck = liveResult?.next_check_scheduled ?? history?.next_check_scheduled ?? null

  const auxSim = (status?.aux_source ?? 'simulator') === 'simulator'
  // Before the first status frame arrives, don't claim the module is gone.
  const auxConnected = status ? status.aux_connected : true
  let auxLabel = auxConnected ? 'Connected (BLE)' : 'Not found -- power on the foot module'
  if (auxSim) auxLabel = auxConnected ? 'Simulated' : 'Simulated -- set to offline'

  async function requestNow() {
    setMessage(null)
    setRequesting(true)
    try {
      await api.requestFootCheck()
    } catch (err) {
      setRequesting(false)
      setMessage(err instanceof ApiError ? err.detail : 'Request failed')
    }
  }

  return (
    <div className={styles.split}>
      <div className={styles.copy}>
        <h3 className="gs-card-title">Foot check</h3>
        <p className="gs-body" style={{ color: 'var(--gs-lime-ink)' }}>
          Bilateral foot temperature from the auxiliary module. It sleeps between checks;
          the controller wakes it sooner after an elevated or invalid result.
        </p>
        <div className={styles.fields}>
          <FieldRow icon="⌁" label="Last check" value={<LastResult result={last} />} />
          <FieldRow icon="⏱" label="Next check" value={formatCountdown(nextCheck)} />
          <FieldRow icon={auxConnected ? '●' : '○'} label="Foot module" value={auxLabel} />
        </div>
      </div>

      <Panel className={styles.panel}>
        <div className={styles.panelHead}>
          <span className="gs-label">History</span>
          <Button
            variant="dark"
            arrow
            onClick={requestNow}
            disabled={requesting || !auxConnected}
          >
            {requesting ? 'Checking…' : 'Request check now'}
          </Button>
        </div>
        {message && <p className={styles.error}>{message}</p>}
        {checks.length === 0 ? (
          <EmptyState title="No foot checks yet" hint="Request one now, or wait for the schedule." />
        ) : (
          <ul className={styles.history}>
            {checks.map((c) => (
              <li key={c.id} className={styles.row}>
                <span className={styles.time}>{formatClockTime(c.timestamp)}</span>
                <span className={styles.temps}>
                  {c.valid ? `L ${formatTemperature(c.t_left)} · R ${formatTemperature(c.t_right)}` : '--'}
                </span>
                <span className={styles.delta}>{formatDeltaT(c.delta_t)}</span>
                <ResultBadge check={c} />
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  )
}

function LastResult({ result }) {
  if (!result) return 'None yet'
  if (!result.valid) return `Invalid · ${formatRelativeTime(result.timestamp)}`
  return `${formatDeltaT(result.delta_t)} · L ${formatTemperature(result.t_left)} R ${formatTemperature(
    result.t_right
  )} · ${formatRelativeTime(result.timestamp)}`
}

function ResultBadge({ check }) {
  if (!check.valid) return <Badge color="var(--gs-warn)">Invalid</Badge>
  if (check.elevated) return <Badge color="var(--gs-danger)">Elevated</Badge>
  return <Badge color="var(--gs-ok)">Normal</Badge>
}
