import { useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { fetchConfig, requestDownload, saveBlob } from '../api'
import AsciiLogo from '../components/AsciiLogo'
import Terms from '../components/Terms'
import './Downloader.scss'

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

  const linkCount = useMemo(
    () => links.split(/[\s,;]+/).filter((t) => /^https?:\/\//.test(t)).length,
    [links],
  )
  const isBundle = linkCount > 1

  function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!links.trim()) return
    download.mutate({ links })
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
              placeholder={
                'https://youtu.be/...\nhttps://soundcloud.com/...\nhttps://open.spotify.com/track/...'
              }
            />

            <button type="submit" disabled={download.isPending}>
              {download.isPending ? 'EXECUTING…' : isBundle ? `FETCH BUNDLE x${linkCount}` : 'FETCH'}
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
