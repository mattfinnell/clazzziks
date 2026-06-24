import { useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { fetchConfig, requestDownload, saveBlob, type Config } from '../api'
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
      <div className="downloader__card">
        <header className="downloader__head">
          <div>
            <p className="downloader__brand">CLAZZZIKS</p>
            <h1>Download</h1>
          </div>
          <BackendDot status={configQuery.status} />
        </header>
        <p className="downloader__sub">
          Paste one link for a single file, or many links (newlines, CSV text, or a public Google
          Sheets URL) for a lossless <strong>{config.bundle_format?.toUpperCase()}</strong> ZIP
          bundle.
        </p>

        <form onSubmit={onSubmit}>
          <label htmlFor="links">Link(s)</label>
          <textarea
            id="links"
            value={links}
            onChange={(e) => setLinks(e.target.value)}
            placeholder={
              'https://youtu.be/...\nhttps://soundcloud.com/...\nhttps://open.spotify.com/track/...'
            }
          />

          <div className="downloader__row">
            <div>
              <label htmlFor="format">Format</label>
              <select id="format" value={activeFormat} onChange={(e) => setFormat(e.target.value)}>
                {config.formats.map((f) => (
                  <option key={f} value={f}>
                    {f.toUpperCase()}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="bitrate">MP3 bitrate (kbps)</label>
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
            {download.isPending ? 'Downloading…' : isBundle ? `Download bundle (${linkCount})` : 'Download'}
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
    text = 'Working… this can take a moment per track.'
  } else if (isError) {
    kind = 'error'
    text = `Error: ${(error as Error)?.message ?? 'download failed'}`
  } else if (isSuccess) {
    kind = warnings ? 'warn' : 'ok'
    text = warnings ? `Done with warnings: ${warnings}` : `Downloaded ${filename}`
  }
  return <p className={`downloader__note downloader__note--${kind}`}>{text}</p>
}

function BackendDot({ status }: { status: 'pending' | 'error' | 'success' }) {
  const label =
    status === 'pending' ? 'checking backend…' : status === 'success' ? 'backend online' : 'backend offline'
  const cls = status === 'pending' ? 'checking' : status === 'success' ? 'online' : 'offline'
  return (
    <span className={`downloader__dot downloader__dot--${cls}`} title={label}>
      <i /> {label}
    </span>
  )
}
