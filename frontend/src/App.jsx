import { useEffect, useMemo, useState } from 'react'
import { fetchConfig, requestDownload, saveBlob } from './api.js'

const FALLBACK_CONFIG = {
  formats: ['wav', 'mp3', 'flac'],
  default_format: 'mp3',
  bundle_format: 'flac',
  bitrates: [320, 256, 192],
  default_bitrate: 320,
}

export default function App() {
  const [config, setConfig] = useState(FALLBACK_CONFIG)
  const [backendOk, setBackendOk] = useState(null)
  const [links, setLinks] = useState('')
  const [format, setFormat] = useState(FALLBACK_CONFIG.default_format)
  const [bitrate, setBitrate] = useState(FALLBACK_CONFIG.default_bitrate)
  const [status, setStatus] = useState({ kind: 'idle', text: '' })

  useEffect(() => {
    fetchConfig()
      .then((cfg) => {
        setConfig(cfg)
        setFormat(cfg.default_format)
        setBitrate(cfg.default_bitrate)
        setBackendOk(true)
      })
      .catch(() => setBackendOk(false))
  }, [])

  const linkCount = useMemo(
    () => links.split(/[\s,;]+/).filter((t) => /^https?:\/\//.test(t)).length,
    [links],
  )
  const isBundle = linkCount > 1
  const busy = status.kind === 'working'

  async function onSubmit(e) {
    e.preventDefault()
    if (!links.trim()) {
      setStatus({ kind: 'error', text: 'Paste at least one link.' })
      return
    }
    setStatus({ kind: 'working', text: 'Working… this can take a moment per track.' })
    try {
      const { filename, blob, warnings } = await requestDownload({ links, format, bitrate })
      saveBlob(blob, filename)
      setStatus(
        warnings
          ? { kind: 'warn', text: `Done with warnings: ${warnings}` }
          : { kind: 'ok', text: `Downloaded ${filename}` },
      )
    } catch (err) {
      setStatus({ kind: 'error', text: `Error: ${err.message}` })
    }
  }

  return (
    <div className="page">
      <div className="card">
        <header className="head">
          <h1>CLAZZZIKS</h1>
          <BackendDot ok={backendOk} />
        </header>
        <p className="sub">
          Paste one link for a single file, or many links (newlines, CSV text, or a
          public Google Sheets URL) for a lossless{' '}
          <strong>{config.bundle_format?.toUpperCase()}</strong> ZIP bundle.
        </p>

        <form onSubmit={onSubmit}>
          <label htmlFor="links">Link(s)</label>
          <textarea
            id="links"
            value={links}
            onChange={(e) => setLinks(e.target.value)}
            placeholder={'https://youtu.be/...\nhttps://soundcloud.com/...\nhttps://open.spotify.com/track/...'}
          />

          <div className="row">
            <div>
              <label htmlFor="format">Format</label>
              <select id="format" value={format} onChange={(e) => setFormat(e.target.value)}>
                {config.formats.map((f) => (
                  <option key={f} value={f}>{f.toUpperCase()}</option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="bitrate">MP3 bitrate (kbps)</label>
              <select
                id="bitrate"
                value={bitrate}
                disabled={format !== 'mp3'}
                onChange={(e) => setBitrate(Number(e.target.value))}
              >
                {config.bitrates.map((b) => (
                  <option key={b} value={b}>{b}</option>
                ))}
              </select>
            </div>
          </div>

          <button type="submit" disabled={busy}>
            {busy ? 'Downloading…' : isBundle ? `Download bundle (${linkCount})` : 'Download'}
          </button>
        </form>

        <p className={`note ${status.kind}`}>{status.text}</p>
      </div>
    </div>
  )
}

function BackendDot({ ok }) {
  const label = ok === null ? 'checking backend…' : ok ? 'backend online' : 'backend offline'
  const cls = ok === null ? 'checking' : ok ? 'online' : 'offline'
  return (
    <span className={`dot ${cls}`} title={label}>
      <i /> {label}
    </span>
  )
}
