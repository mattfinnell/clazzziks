import { useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { fetchConfig, requestDownload, saveBlob, type Config } from '../api'
import AsciiLogo from '../components/AsciiLogo'
import './Downloader.scss'

const FALLBACK_CONFIG: Config = {
  formats: ['wav', 'mp3', 'flac'],
  default_format: 'mp3',
  bundle_format: 'flac',
  bitrates: [320, 256, 192],
  default_bitrate: 320,
}

export default function Downloader() {
  const configQuery = useQuery({ queryKey: ['config'], queryFn: fetchConfig })
  const config = configQuery.data ?? FALLBACK_CONFIG

  const [links, setLinks] = useState('')
  const [format, setFormat] = useState<string | null>(null)
  const [bitrate, setBitrate] = useState<number | null>(null)

  // Default the controls to the backend's config once it loads, while still
  // letting the user override them.
  const activeFormat = format ?? config.default_format
  const activeBitrate = bitrate ?? config.default_bitrate

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
    download.mutate({ links, format: activeFormat, bitrate: activeBitrate })
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
            &gt; paste one link for a single file, or many (newlines, CSV, or a public Google
            Sheets URL) for a lossless <strong>{config.bundle_format?.toUpperCase()}</strong> ZIP
            bundle.
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

            <div className="downloader__row">
              <div>
                <label htmlFor="format">format</label>
                <select id="format" value={activeFormat} onChange={(e) => setFormat(e.target.value)}>
                  {config.formats.map((f) => (
                    <option key={f} value={f}>
                      {f.toUpperCase()}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label htmlFor="bitrate">mp3 bitrate [kbps]</label>
                <select
                  id="bitrate"
                  value={activeBitrate}
                  disabled={activeFormat !== 'mp3'}
                  onChange={(e) => setBitrate(Number(e.target.value))}
                >
                  {config.bitrates.map((b) => (
                    <option key={b} value={b}>
                      {b}
                    </option>
                  ))}
                </select>
              </div>
            </div>

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
