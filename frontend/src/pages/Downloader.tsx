import { useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { fetchConfig, requestDownload, saveBlob } from '../api'
import AsciiLogo from '../components/AsciiLogo'
import Terms from '../components/Terms'
import './Downloader.scss'

// Client-side input validation, mirroring the backend's source detection
// (clazzziks/sources.py). Only YouTube and SoundCloud are downloadable; a public
// Google Sheets URL is accepted too (the backend expands it). Everything else is
// flagged before submit so the user gets immediate, specific feedback.
const SUPPORTED_HOSTS: RegExp[] = [
  /(^|\.)youtube\.com$/,
  /(^|\.)youtu\.be$/,
  /(^|\.)youtube-nocookie\.com$/,
  /(^|\.)soundcloud\.com$/,
  /(^|\.)snd\.sc$/,
]
const SPOTIFY_HOSTS: RegExp[] = [/(^|\.)spotify\.com$/, /(^|\.)spotify\.link$/]
const SHEETS_RE = /^https?:\/\/docs\.google\.com\/spreadsheets\/d\//i

type LinkKind = 'ok' | 'spotify' | 'unsupported' | 'invalid'

function classifyLink(token: string): LinkKind {
  if (SHEETS_RE.test(token)) return 'ok' // Google Sheet — backend expands it
  let url: URL
  try {
    url = new URL(token)
  } catch {
    return 'invalid'
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return 'invalid'
  const host = url.hostname.toLowerCase()
  if (SUPPORTED_HOSTS.some((p) => p.test(host))) return 'ok'
  if (SPOTIFY_HOSTS.some((p) => p.test(host))) return 'spotify'
  return 'unsupported'
}

interface Validation {
  valid: string[]
  problems: string[]
}

function validateLinks(text: string): Validation {
  const tokens = text
    .split(/[\s,;]+/)
    .map((t) => t.trim())
    .filter(Boolean)
  const valid: string[] = []
  let spotify = 0
  let unsupported = 0
  let invalid = 0
  for (const token of tokens) {
    switch (classifyLink(token)) {
      case 'ok':
        valid.push(token)
        break
      case 'spotify':
        spotify++
        break
      case 'unsupported':
        unsupported++
        break
      default:
        invalid++
    }
  }
  const s = (n: number) => (n > 1 ? 's' : '')
  const problems: string[] = []
  if (spotify) problems.push(`${spotify} Spotify link${s(spotify)} — Spotify is no longer supported`)
  if (unsupported)
    problems.push(`${unsupported} unsupported link${s(unsupported)} — only YouTube & SoundCloud`)
  if (invalid) problems.push(`${invalid} ${invalid > 1 ? 'entries are' : 'entry is'} not a valid URL`)
  return { valid, problems }
}

export default function Downloader() {
  // Only used to probe backend availability — output is always MP3. Poll fast
  // (150ms) while offline so recovery shows almost immediately, then back off to
  // every 5s once the backend is reachable.
  const configQuery = useQuery({
    queryKey: ['config'],
    queryFn: fetchConfig,
    refetchInterval: (query) => (query.state.status === 'error' ? 150 : 5000),
    refetchIntervalInBackground: true,
  })

  const [links, setLinks] = useState('')

  const download = useMutation({
    mutationFn: requestDownload,
    onSuccess: ({ filename, blob }) => saveBlob(blob, filename),
  })

  const { valid, problems } = useMemo(() => validateLinks(links), [links])
  const validCount = valid.length
  const isBundle = validCount > 1

  function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (validCount === 0) return
    // Submit only the valid links so unsupported/invalid entries never reach the
    // backend (the UI has already told the user about them).
    download.mutate({ links: valid.join('\n') })
  }

  return (
    <div className="downloader">
      <div className="downloader__window">
        <div className="downloader__titlebar">
          <span>guest@clazzziks: ~/download</span>
          <BackendStatus status={configQuery.status} />
        </div>

        <div className="downloader__body">
          <AsciiLogo tagline="audio extraction terminal" />

          <p className="downloader__sub">
            &gt; paste one link for a single <strong>MP3</strong>, or many (newlines, CSV, or a
            public Google Sheets URL) for a <strong>MP3</strong> ZIP bundle.
          </p>

          <form onSubmit={onSubmit}>
            <label htmlFor="links">link(s)</label>
            <textarea
              id="links"
              value={links}
              spellCheck={false}
              onChange={(e) => setLinks(e.target.value)}
              placeholder={'https://youtu.be/...\nhttps://soundcloud.com/...'}
            />

            {problems.length > 0 && (
              <ul className="downloader__validation" role="alert">
                {problems.map((p) => (
                  <li key={p}>!! {p}</li>
                ))}
              </ul>
            )}

            <button type="submit" disabled={download.isPending || validCount === 0}>
              {download.isPending ? 'EXECUTING…' : isBundle ? `FETCH BUNDLE x${validCount}` : 'FETCH'}
            </button>
          </form>

          <StatusNote
            isPending={download.isPending}
            isError={download.isError}
            isSuccess={download.isSuccess}
            error={download.error}
            warnings={download.data?.warnings ?? null}
            filename={download.data?.filename ?? ''}
          />

          {configQuery.isError && (
            <p className="downloader__note downloader__note--error" role="alert">
              {`!! backend unreachable — ${
                (configQuery.error as Error)?.message ?? 'cannot reach API'
              }`}
            </p>
          )}

          <Terms />
        </div>
      </div>
    </div>
  )
}

function StatusNote({
  isPending,
  isError,
  isSuccess,
  error,
  warnings,
  filename,
}: {
  isPending: boolean
  isError: boolean
  isSuccess: boolean
  error: unknown
  warnings: string | null
  filename: string
}) {
  let kind = 'idle'
  let text = ''
  if (isPending) {
    kind = 'working'
    text = '>> working… this can take a moment per track'
  } else if (isError) {
    kind = 'error'
    text = `!! error: ${(error as Error)?.message ?? 'download failed'}`
  } else if (isSuccess) {
    kind = warnings ? 'warn' : 'ok'
    text = warnings ? `?? done with warnings: ${warnings}` : `ok: downloaded ${filename}`
  }
  return (
    <p className={`downloader__note downloader__note--${kind}`}>
      {text}
      {isPending && <span className="blink">_</span>}
    </p>
  )
}

function BackendStatus({ status }: { status: 'pending' | 'error' | 'success' }) {
  const label = status === 'pending' ? 'SCANNING' : status === 'success' ? 'ONLINE' : 'OFFLINE'
  const cls = status === 'pending' ? 'checking' : status === 'success' ? 'online' : 'offline'
  return (
    <span className={`downloader__status downloader__status--${cls}`} title={`backend ${label}`}>
      <i>█</i> {label}
    </span>
  )
}
