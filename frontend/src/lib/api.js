/**
 * REST fetch wrapper. Every component goes through this -- per AGENTS.md, no
 * bare `fetch` inside a component. Base URL and every endpoint shape are
 * defined in docs/API_CONTRACT.md; this file does not reshape responses, it
 * only transports and normalizes errors.
 */
const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail || `API error ${status}`)
    this.status = status
    this.detail = detail
  }
}

async function request(path, options = {}) {
  // FormData bodies (model upload) must NOT get an explicit Content-Type --
  // the browser sets one itself with the multipart boundary, and overriding
  // it here would break the upload.
  const isFormData = options.body instanceof FormData
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { ...(isFormData ? {} : { 'Content-Type': 'application/json' }), ...(options.headers || {}) },
    ...options,
  })
  if (!res.ok) {
    let detail
    try {
      const body = await res.json()
      detail = body.detail
    } catch {
      detail = res.statusText
    }
    throw new ApiError(res.status, detail)
  }
  const contentType = res.headers.get('content-type') || ''
  if (contentType.includes('application/json')) return res.json()
  return res.text()
}

export const api = {
  base: API_BASE,

  getStatus: () => request('/api/status'),
  getRiskCurrent: () => request('/api/risk/current'),
  getRiskHistory: (range = '1h') => request(`/api/risk/history?range=${range}`),
  getEcgLatest: () => request('/api/ecg/latest'),
  getFootHistory: (limit = 50) => request(`/api/foot/history?limit=${limit}`),
  requestFootCheck: () => request('/api/foot/request', { method: 'POST' }),
  setControllerMode: (mode, manual = true) =>
    request('/api/controller/mode', { method: 'POST', body: JSON.stringify({ mode, manual }) }),
  getSessionSummary: () => request('/api/session/summary'),
  ackAlert: (id) => request(`/api/alerts/${id}/ack`, { method: 'POST' }),
  simAction: (action) => request(`/api/sim/${action}`, { method: 'POST' }),

  // Model management -- upload a trained .onnx file and it immediately
  // starts scoring live data; select/reset switch between an already-
  // uploaded model and the built-in stub without re-uploading.
  listModels: () => request('/api/model/list'),
  uploadModel: (file) => {
    const form = new FormData()
    form.append('file', file)
    return request('/api/model/upload', { method: 'POST', body: form })
  },
  selectModel: (filename) =>
    request('/api/model/select', { method: 'POST', body: JSON.stringify({ filename }) }),
  resetModel: () => request('/api/model/reset', { method: 'POST' }),

  // Export triggers a real navigation/download rather than a fetch, so the
  // browser handles the Content-Disposition attachment header itself.
  sessionExportUrl: () => `${API_BASE}/api/session/export`,
}
