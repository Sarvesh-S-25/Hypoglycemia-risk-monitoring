import { Badge } from './ui/index.js'

/**
 * Says plainly when any of the data on screen is synthetic, so a demo is
 * never mistaken for a reading from a person (docs/POLICIES.md P10).
 */
export default function SimulatedNotice({ status, onOpen, showLink }) {
  const ecgSim = status?.source === 'simulator'
  const footSim = (status?.aux_source ?? 'simulator') === 'simulator'
  if (!status || (!ecgSim && !footSim)) return null

  let what = 'ECG and foot readings are simulated'
  if (ecgSim && !footSim) what = 'The ECG is simulated; foot readings are real'
  if (!ecgSim && footSim) what = 'The ECG is real; foot readings are simulated'

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        flexWrap: 'wrap',
        marginBottom: 'var(--gs-gap)',
        fontSize: 13,
        color: 'var(--gs-ink-muted)',
      }}
    >
      <Badge color="var(--gs-warn)">Simulated data</Badge>
      <span>{what} -- not from a person.</span>
      {showLink && (
        <button
          type="button"
          onClick={onOpen}
          style={{
            border: 'none',
            background: 'none',
            padding: 0,
            color: 'var(--gs-ink)',
            textDecoration: 'underline',
            cursor: 'pointer',
            fontSize: 13,
            fontFamily: 'var(--gs-font-sans)',
          }}
        >
          Simulator controls
        </button>
      )}
    </div>
  )
}
