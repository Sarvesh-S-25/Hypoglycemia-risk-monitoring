import { KeyValue, Meter } from '../ui/index.js'
import PolicyTags from './PolicyTags.jsx'
import { formatMs, formatRelativeTime, formatRiskScore, formatSeconds } from '../../lib/format.js'
import styles from './Engineering.module.css'

/** The risk model: what it needs, how full its buffer is, what it said (P2). */
export default function ModelPanel({ model }) {
  const m = model ?? {}
  const buffering = m.needed_s > 0
  const ready = buffering && m.buffered_s >= m.needed_s

  return (
    <div>
      <div className={styles.head}>
        <h3 className="gs-card-title" style={{ margin: 0 }}>Risk model</h3>
        <PolicyTags ids={['P2']} />
      </div>
      <p className={styles.lede}>{m.name ?? '--'}</p>

      {buffering && (
        <div>
          <div className={styles.blockLabel}>
            <span>Contiguous clean ECG buffered</span>
            <span className={styles.mono}>
              {formatSeconds(m.buffered_s)} / {formatSeconds(m.needed_s)}
            </span>
          </div>
          <Meter value={m.buffered_s} max={m.needed_s} tone={ready ? 'ok' : 'ink'} label="model buffer" />
        </div>
      )}

      <div className={styles.block}>
        <KeyValue
          rows={[
            ['Input', m.input_len ? `${m.input_len} samples @ ${m.input_rate_hz} Hz` : `per window @ ${m.input_rate_hz ?? '--'} Hz`],
            ['Preprocessing', buffering ? '0.5–40 Hz band-pass, 50 Hz notch, z-score' : 'baseline removal'],
            ['Output', m.output ?? '--'],
            ['Last score', formatRiskScore(m.last_score)],
            ['Last scored', m.last_score_ts ? formatRelativeTime(m.last_score_ts) : '--'],
            ['Inference time', formatMs(m.last_inference_ms)],
          ]}
        />
      </div>
    </div>
  )
}
