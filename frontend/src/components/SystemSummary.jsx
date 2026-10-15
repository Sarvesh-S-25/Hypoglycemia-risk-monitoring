import styles from './SystemSummary.module.css'

const SOURCE_LABELS = { simulator: 'Simulator', ble: 'Bluetooth', serial: 'USB cable' }

/**
 * One line per part of the system, for the patient view: is it there and
 * working. The full readout lives in the engineering view.
 */
export default function SystemSummary({ status }) {
  const connected = status?.connected ?? false
  const model = status?.model ?? ''
  const auxSim = (status?.aux_source ?? 'simulator') === 'simulator'
  const auxState = status?.aux_state ?? 'missing'
  const auxReachable = auxState !== 'missing'

  const rows = [
    {
      label: 'ECG sensor',
      value: connected ? SOURCE_LABELS[status?.source] ?? 'Connected' : 'Disconnected',
      state: connected ? 'ok' : 'off',
    },
    {
      label: 'Signal',
      value: !connected ? '--' : status?.leads_off ? 'Leads off' : status?.sqi === 1 ? 'Good' : 'Unusable (movement/noise)',
      state: !connected ? 'off' : status?.sqi === 1 ? 'ok' : 'warn',
    },
    {
      label: 'Foot module',
      value: auxSim
        ? auxReachable ? 'Simulated' : 'Simulated, offline'
        : { awake: 'Awake', asleep: 'Asleep (normal)', missing: 'Not found' }[auxState],
      state: !auxReachable ? 'warn' : auxSim ? 'off' : 'ok',
    },
    {
      label: 'Risk model',
      value: model.startsWith('ONNX:') ? 'Trained model' : model.startsWith('Stub (failed') ? 'Failed to load' : 'Placeholder',
      state: model.startsWith('ONNX:') ? 'ok' : 'warn',
    },
  ]

  return (
    <ul className={styles.list}>
      {rows.map((r) => (
        <li key={r.label} className={styles.row}>
          <span className={`${styles.dot} ${styles[r.state]}`} aria-hidden="true" />
          <span className={styles.label}>{r.label}</span>
          <span className={styles.value}>{r.value}</span>
        </li>
      ))}
    </ul>
  )
}
