import FieldRow from './ui/FieldRow.jsx'
import { formatBattery, formatRelativeTime } from '../lib/format.js'

/**
 * Battery / BLE connection / signal-quality status bar (SRD 5.1, 5.2).
 * `status` is the backend's GET /api/status shape verbatim.
 */
export default function DeviceStatus({ status }) {
  const connected = status?.connected ?? false
  const sourceLabel = status?.source === 'simulator' ? 'Simulator' : status?.source === 'ble' ? 'BLE' : 'Disconnected'

  // "Stub (failed to load ...)" means GS_MODEL_PATH pointed at a model that
  // couldn't be loaded, and the backend silently fell back to the heuristic
  // -- surfaced here so that failure is visible in the UI, not just a server
  // log (see app/inference.py's load_risk_model).
  const modelLabel = status?.model ?? 'Stub (heuristic)'
  const modelFailed = modelLabel.startsWith('Stub (failed')
  const modelIsReal = modelLabel.startsWith('ONNX:')

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <FieldRow
        icon={connected ? '●' : '○'}
        label="Connection"
        value={sourceLabel}
        active={connected}
      />
      <FieldRow
        icon={modelFailed ? '⚠' : modelIsReal ? '✓' : 'ƒ'}
        label="Risk model"
        value={modelLabel}
        active={modelIsReal}
      />
      <FieldRow
        icon="⚡"
        label="Battery"
        value={formatBattery(status?.battery_pct)}
      />
      <FieldRow
        icon={status?.sqi === 1 ? '✓' : '⚠'}
        label="Signal quality"
        value={status?.sqi === 1 ? 'Good' : status?.sqi === 0 ? 'Rejected (motion/noise)' : '--'}
      />
      {status?.leads_off && (
        <FieldRow icon="⚠" label="Leads" value="Off -- check electrode contact" />
      )}
      <FieldRow
        icon="⏱"
        label="Last packet"
        value={status?.last_packet_ts ? formatRelativeTime(status.last_packet_ts) : '--'}
      />
    </div>
  )
}
