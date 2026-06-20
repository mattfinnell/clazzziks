# Project Root - CLAZZZIKS

Audio downloader supporting YouTube, SoundCloud, and Spotify. Outputs MP3, WAV, or FLAC via a CLI, web UI, or HTTP API.

## Layout

```
backend/    Python core (yt-dlp + ffmpeg), FastAPI API, CLI
frontend/   React + Vite web utility (TypeScript, SCSS, pnpm)
```

All backend work lives in `backend/` and uses `uv`. See `backend/CLAUDE.md` for conventions.

## Audio formats

- **MP3** — 320kbps default; warns if the requested or source bitrate is below 320
- **WAV** — lossless PCM
- **FLAC** — lossless compressed; default for batch bundles; preferred when source quality matters

**Quality ceiling:** YouTube's best audio is ~160kbps Opus. Re-encoding to 320kbps MP3 does not recover quality. Use FLAC to avoid a second lossy transcode.

## Platforms

- **YouTube** — direct yt-dlp download; CDN returns 403 in cookie-less environments
- **SoundCloud** — direct yt-dlp download; many tracks are DRM-encrypted
- **Spotify** — DRM-protected; resolved via public metadata → YouTube search → yt-dlp
