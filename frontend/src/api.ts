const API_BASE = import.meta.env.VITE_API_BASE || '/api'

// The auth layer registers a getter here (see AuthContext) so requests can
// attach the signed-in user's Firebase ID token without api.ts importing
// Firebase. Returns null when signed out or auth is disabled.
type TokenProvider = () => Promise<string | null>
let tokenProvider: TokenProvider | null = null

export function setAuthTokenProvider(provider: TokenProvider | null): void {
  tokenProvider = provider
}

async function authHeaders(): Promise<Record<string, string>> {
  if (!tokenProvider) return {}
  try {
    const token = await tokenProvider()
    return token ? { Authorization: `Bearer ${token}` } : {}
  } catch {
    return {}
  }
}

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
  const resp = await fetch(`${API_BASE}/download`, {
    method: 'POST',
    headers: await authHeaders(),
    body,
  })

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

// --- caller status + VIP admin ---------------------------------------------

export interface Me {
  email: string | null
  is_vip: boolean
  is_admin: boolean
  anonymous: boolean
}

export interface Vip {
  email: string
  is_admin: boolean
  note: string | null
  added_at: string
}

async function jsonOrThrow<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    let message = resp.statusText
    try {
      message = (await resp.json()).error || message
    } catch {
      /* non-JSON error body */
    }
    throw new Error(message)
  }
  return resp.json() as Promise<T>
}

export async function fetchMe(): Promise<Me> {
  const resp = await fetch(`${API_BASE}/me`, { headers: await authHeaders() })
  return jsonOrThrow<Me>(resp)
}

export async function listVips(): Promise<Vip[]> {
  const resp = await fetch(`${API_BASE}/admin/vips`, { headers: await authHeaders() })
  return (await jsonOrThrow<{ vips: Vip[] }>(resp)).vips
}

export async function addVip(input: {
  email: string
  note?: string
  is_admin?: boolean
}): Promise<Vip[]> {
  const resp = await fetch(`${API_BASE}/admin/vips`, {
    method: 'POST',
    headers: { ...(await authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  return (await jsonOrThrow<{ vips: Vip[] }>(resp)).vips
}

export async function removeVip(email: string): Promise<Vip[]> {
  const resp = await fetch(`${API_BASE}/admin/vips/${encodeURIComponent(email)}`, {
    method: 'DELETE',
    headers: await authHeaders(),
  })
  return (await jsonOrThrow<{ vips: Vip[] }>(resp)).vips
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
