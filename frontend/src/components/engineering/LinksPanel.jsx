import { KeyValue } from '../ui/index.js'
import { formatBattery, formatRelativeTime } from '../../lib/format.js'
import styles from './Engineering.module.css'

/** Transport state for both nodes, as the backend sees it. */
export default function LinksPanel({ link, sessionId }) {
  const l = link ?? {}
  let aux = 'simulated'
  if (l.aux_source === 'ble') aux = l.aux_connected ? 'connected (BLE)' : 'scanning'

  return (
    <div>
      <div className={styles.head}>
        <h3 className="gs-card-title" style={{ margin: 0 }}>Links</h3>
      </div>
      <p className={styles.lede}>Both nodes connect to this host directly.</p>
      <KeyValue
        rows={[
          ['ECG node', l.connected ? `connected (${l.source})` : 'disconnected'],
          ['Last ECG packet', l.last_packet_ts ? formatRelativeTime(l.last_packet_ts) : '--'],
          ['Battery', l.battery_pct === null || l.battery_pct === undefined ? 'not measured (USB)' : formatBattery(l.battery_pct)],
          ['Foot module', aux],
          ['Session', sessionId ?? '--'],
        ]}
      />
    </div>
  )
}
