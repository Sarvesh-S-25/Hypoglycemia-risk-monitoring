import { useCallback, useRef, useState } from 'react'
import { Card, Panel, SectionHeader, Button, FieldRow } from '../components/ui/index.js'
import { useApi } from '../hooks/useApi.js'
import { api, ApiError } from '../lib/api.js'
import { formatRelativeTime } from '../lib/format.js'

function formatSize(bytes) {
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/**
 * Model page: upload a trained risk model (.onnx) and it immediately starts
 * scoring live data -- no separate "comparison" step, because the backend's
 * pipeline (signal_pipeline -> inference -> controller) always scores
 * whichever model is active right now. Switching models here is switching
 * what the dashboard's risk score, mode, and alerts are driven by.
 */
export default function ModelManager() {
  const { data, refetch } = useApi((api) => api.listModels(), [])
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState(null) // { ok, text }
  const fileInputRef = useRef(null)

  const runAction = useCallback(async (fn) => {
    setBusy(true)
    setMessage(null)
    try {
      const result = await fn()
      setMessage({ ok: result.ok !== false, text: result.message })
    } catch (err) {
      setMessage({ ok: false, text: err instanceof ApiError ? err.detail : 'Request failed' })
    } finally {
      setBusy(false)
      refetch()
    }
  }, [refetch])

  function handleFileChosen(e) {
    const file = e.target.files?.[0]
    e.target.value = '' // allow re-selecting the same file later
    if (!file) return
    runAction(() => api.uploadModel(file))
  }

  const models = data?.models ?? []
  const active = data?.active ?? 'stub'

  return (
    <div className="gs-page">
      <SectionHeader
        eyebrow="[02] Model"
        title="Choose which model scores your "
        tail="live ECG data."
        actions={
          <Button variant="ghost" onClick={() => window.location.assign('/')}>
            Back to dashboard
          </Button>
        }
      />

      <p className="gs-body" style={{ marginBottom: 32 }}>
        Upload a trained risk model exported to ONNX. Once uploaded it is
        applied immediately -- every ECG window the simulator or device sends
        from that point on is scored by it, and the dashboard's risk score,
        mode, and alerts reflect its output live. No restart needed.
      </p>

      <div className="gs-grid">
        <div className="gs-span-7">
          <Card tone="grey">
            <h3 className="gs-card-title">Upload a model</h3>
            <p className="gs-body" style={{ marginBottom: 16 }}>
              .onnx files only, up to 200&nbsp;MB. Input shape (1, 1, N) float32 --
              see backend/.env.example for the exact export instructions.
            </p>
            <input
              ref={fileInputRef}
              type="file"
              accept=".onnx"
              onChange={handleFileChosen}
              style={{ display: 'none' }}
            />
            <Button variant="dark" arrow onClick={() => fileInputRef.current?.click()} disabled={busy}>
              {busy ? 'Uploading...' : 'Choose .onnx file'}
            </Button>

            {message && (
              <p
                className="gs-body"
                style={{ marginTop: 16, color: message.ok ? 'var(--gs-ok)' : 'var(--gs-danger)' }}
              >
                {message.text}
              </p>
            )}
          </Card>
        </div>

        <div className="gs-span-5">
          <Card tone="plain">
            <h3 className="gs-card-title">Currently active</h3>
            <Panel>
              <FieldRow
                icon={active === 'stub' ? 'ƒ' : '✓'}
                label="Model"
                value={active === 'stub' ? 'Stub (heuristic)' : active}
                active={active !== 'stub'}
              />
            </Panel>
            {active !== 'stub' && (
              <Button
                variant="ghost"
                style={{ marginTop: 12 }}
                onClick={() => runAction(() => api.resetModel())}
                disabled={busy}
              >
                Revert to stub
              </Button>
            )}
          </Card>
        </div>
      </div>

      <div className="gs-section">
        <h3 className="gs-card-title">Uploaded models</h3>
        {models.length === 0 ? (
          <p className="gs-body">No models uploaded yet.</p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxWidth: 640 }}>
            {models.map((m) => (
              <FieldRow
                key={m.filename}
                icon={m.active ? '✓' : 'ƒ'}
                active={m.active}
                label={`${formatSize(m.size_bytes)} · uploaded ${formatRelativeTime(m.uploaded_ts)}`}
                value={m.filename}
                trailing={
                  !m.active && (
                    <Button
                      variant="ghost"
                      onClick={() => runAction(() => api.selectModel(m.filename))}
                      disabled={busy}
                    >
                      Use this
                    </Button>
                  )
                }
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
