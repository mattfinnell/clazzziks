// Thin client for the CLAZZZIKS backend API (proxied at /api in dev).
//
// The request/response shapes here follow the shared API contract, which is the
// single source of truth for both backend and frontend:
//   backend/clazzziks/openapi.json  (served live at `${API_BASE}/openapi.json`)
// The backend's responses are validated against it in tests/test_contract.py.

const API_BASE = import.meta.env.VITE_API_BASE || '/api'

export async function fetchConfig() {
  const resp = await fetch(`${API_BASE}/formats`)
  if (!resp.ok) throw new Error(`Backend unavailable (${resp.status})`)
  return resp.json()
}

// Fetch the shared OpenAPI contract the backend serves (single source of truth).
export async function fetchContract() {
  const resp = await fetch(`${API_BASE}/openapi.json`)
  if (!resp.ok) throw new Error(`Contract unavailable (${resp.status})`)
  return resp.json()
}

// Returns { filename, blob, warnings }. Throws Error(message) on failure.
export async function requestDownload({ links, format, bitrate }) {
  const body = new URLSearchParams({ links, format, bitrate: String(bitrate) })
  const resp = await fetch(`${API_BASE}/download`, { method: 'POST', body })

  if (!resp.ok) {
    let message = resp.statusText
    try {
      const data = await resp.json()
      message = data.error || message
    } catch {
      /* non-JSON error body */
    }
    throw new Error(message)
  }

  const warnings = resp.headers.get('X-Clazzziks-Warnings')
  const blob = await resp.blob()
  return { filename: filenameFromResponse(resp), blob, warnings }
}

function filenameFromResponse(resp) {
  const disposition = resp.headers.get('Content-Disposition') || ''
  const match = disposition.match(/filename\*?=(?:UTF-8'')?"?([^";]+)/i)
  return match ? decodeURIComponent(match[1]) : 'clazzziks-download'
}

// Trigger a browser "Save as" for a blob received from the API.
export function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
