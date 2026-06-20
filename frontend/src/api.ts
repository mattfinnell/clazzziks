const API_BASE = import.meta.env.VITE_API_BASE || '/api'

export interface Config {
  formats: string[]
  default_format: string
  bundle_format: string
  bitrates: number[]
  default_bitrate: number
}

export async function fetchConfig(): Promise<Config> {
  const resp = await fetch(`${API_BASE}/formats`)
  if (!resp.ok) throw new Error(`Backend unavailable (${resp.status})`)
  return resp.json()
}

export async function fetchContract(): Promise<unknown> {
  const resp = await fetch(`${API_BASE}/openapi.json`)
  if (!resp.ok) throw new Error(`Contract unavailable (${resp.status})`)
  return resp.json()
}

interface DownloadParams {
  links: string
  format: string
  bitrate: number
}

interface DownloadResult {
  filename: string
  blob: Blob
  warnings: string | null
}

export async function requestDownload({
  links,
  format,
  bitrate,
}: DownloadParams): Promise<DownloadResult> {
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

function filenameFromResponse(resp: Response): string {
  const disposition = resp.headers.get('Content-Disposition') || ''
  const match = disposition.match(/filename\*?=(?:UTF-8'')?"?([^";]+)/i)
  return match ? decodeURIComponent(match[1]) : 'clazzziks-download'
}

export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
