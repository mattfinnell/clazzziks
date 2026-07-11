import { GraphQLClient, gql, ClientError } from 'graphql-request'

// The GraphQL API lives at /graphql; produced audio files stream from /files/:token
// (see backend clazzziks/api.py). Both are same-origin in prod (CloudFront) and via
// the Vite dev proxy locally, so the base is empty unless explicitly overridden.
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

// graphql-request needs an *absolute* endpoint (it runs `new URL(endpoint)`, which
// throws on a relative path), so resolve the base against the page origin. An
// absolute VITE_API_BASE (a full backend URL) is preserved as-is.
const resolveUrl = (path: string): string => new URL(path, window.location.origin).toString()
const GQL_ENDPOINT = resolveUrl(`${API_BASE}/graphql`)
const FILES_BASE = resolveUrl(`${API_BASE}/files`)

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

const client = new GraphQLClient(GQL_ENDPOINT)

// Flatten graphql-request's errors into the single-message shape the UI shows.
// A GraphQL error (resolver threw) surfaces its message; a transport failure
// (DNS/connection/TLS) is surfaced distinctly so the UI can say *why*.
function toError(e: unknown): Error {
  if (e instanceof ClientError) {
    const msg = e.response.errors?.[0]?.message
    if (msg) return new Error(msg)
    return new Error(`GraphQL request failed (${e.response.status})`)
  }
  return new Error(`network error reaching ${GQL_ENDPOINT} (${(e as Error).message})`)
}

async function request<T>(document: string, variables?: Record<string, unknown>): Promise<T> {
  try {
    return await client.request<T>(document, variables, await authHeaders())
  } catch (e) {
    throw toError(e)
  }
}

// --- config ----------------------------------------------------------------

export interface Config {
  formats: string[]
  default_format: string
  bundle_format: string
}

const CONFIG_QUERY = gql`
  query {
    config {
      formats
      default_format
      bundle_format
    }
  }
`

export async function fetchConfig(): Promise<Config> {
  const data = await request<{ config: Config }>(CONFIG_QUERY)
  return data.config
}

// --- download --------------------------------------------------------------

interface DownloadParams {
  links: string
}

interface DownloadResult {
  filename: string
  blob: Blob
  warnings: string | null
}

const DOWNLOAD_MUTATION = gql`
  mutation ($links: String!) {
    download(links: $links) {
      token
      filename
      warnings
      failures
    }
  }
`

export async function requestDownload({ links }: DownloadParams): Promise<DownloadResult> {
  // Two-phase: the mutation does the work and hands back a token; the actual bytes
  // stream from /files/:token (GraphQL/JSON can't carry the binary payload).
  const data = await request<{
    download: { token: string; filename: string; warnings: string[]; failures: string[] }
  }>(DOWNLOAD_MUTATION, { links })
  const { token, filename, warnings, failures } = data.download

  let resp: Response
  try {
    resp = await fetch(`${FILES_BASE}/${token}`, { headers: await authHeaders() })
  } catch (e) {
    throw new Error(`network error fetching download (${(e as Error).message})`)
  }
  if (!resp.ok) {
    let message = resp.statusText
    try {
      message = (await resp.json()).error || message
    } catch {
      /* non-JSON error body */
    }
    throw new Error(message)
  }

  const blob = await resp.blob()
  const notes = [...warnings, ...failures]
  return { filename, blob, warnings: notes.length ? notes.join(' | ') : null }
}

// --- caller status + VIP admin ---------------------------------------------

export interface Me {
  email: string | null
  is_vip: boolean
  is_admin: boolean
  anonymous: boolean
  rate_limit: number | null
}

export interface Vip {
  email: string
  is_admin: boolean
  note: string | null
  rate_limit: number | null
  added_at: string
}

export interface User {
  email: string | null
  name: string | null
  email_verified: boolean
  disabled: boolean
  created_at: string | null
  last_sign_in: string | null
  provider: string | null
  is_vip: boolean
  is_admin: boolean
  rate_limit: number | null
  used_this_window: number
}

export interface UserList {
  users: User[]
  window_seconds: number
  auth_configured: boolean
  last_synced_at: string | null
}

const ME_QUERY = gql`
  query {
    me {
      email
      is_vip
      is_admin
      anonymous
      rate_limit
    }
  }
`

export async function fetchMe(): Promise<Me> {
  const data = await request<{ me: Me }>(ME_QUERY)
  return data.me
}

// Shared VIP/User selection sets so every operation returns the same shape.
const VIP_FIELDS = `email is_admin note rate_limit added_at`
const USERLIST_FIELDS = `
  users {
    email name email_verified disabled created_at last_sign_in provider
    is_vip is_admin rate_limit used_this_window
  }
  window_seconds auth_configured last_synced_at
`

const VIPS_QUERY = gql`query { vips { ${VIP_FIELDS} } }`
const USERS_QUERY = gql`query { users { ${USERLIST_FIELDS} } }`
const SYNC_USERS_MUTATION = gql`mutation { sync_users { ${USERLIST_FIELDS} } }`
const ADD_VIP_MUTATION = gql`
  mutation ($email: String!, $note: String, $is_admin: Boolean, $rate_limit: Int) {
    add_vip(email: $email, note: $note, is_admin: $is_admin, rate_limit: $rate_limit) { ${VIP_FIELDS} }
  }
`
const UPDATE_VIP_MUTATION = gql`
  mutation ($email: String!, $note: String, $is_admin: Boolean, $rate_limit: Int) {
    update_vip(email: $email, note: $note, is_admin: $is_admin, rate_limit: $rate_limit) { ${VIP_FIELDS} }
  }
`
const REMOVE_VIP_MUTATION = gql`
  mutation ($email: String!) {
    remove_vip(email: $email) { ${VIP_FIELDS} }
  }
`

export async function listVips(): Promise<Vip[]> {
  return (await request<{ vips: Vip[] }>(VIPS_QUERY)).vips
}

export async function listUsers(): Promise<UserList> {
  return (await request<{ users: UserList }>(USERS_QUERY)).users
}

export async function syncUsers(): Promise<UserList> {
  return (await request<{ sync_users: UserList }>(SYNC_USERS_MUTATION)).sync_users
}

export async function addVip(input: {
  email: string
  note?: string
  is_admin?: boolean
  rate_limit?: number | null
}): Promise<Vip[]> {
  return (await request<{ add_vip: Vip[] }>(ADD_VIP_MUTATION, input)).add_vip
}

export async function updateVip(
  email: string,
  changes: { note?: string | null; is_admin?: boolean; rate_limit?: number | null },
): Promise<Vip[]> {
  return (await request<{ update_vip: Vip[] }>(UPDATE_VIP_MUTATION, { email, ...changes })).update_vip
}

export async function removeVip(email: string): Promise<Vip[]> {
  return (await request<{ remove_vip: Vip[] }>(REMOVE_VIP_MUTATION, { email })).remove_vip
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
