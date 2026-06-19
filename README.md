# CLAZZZIKS

Audio downloader for **YouTube**, **SoundCloud**, and **Spotify**. Outputs
**WAV**, **MP3** (320kbps default, warns if lower), or **FLAC** — via a React
web utility, a CLI, or a small HTTP API.

## Project layout

```
backend/    Python package (yt-dlp + ffmpeg core, CLI, FastAPI API) + tests
frontend/   React + Vite web utility that talks to the backend over /api
```

The frontend calls the backend only through `/api`. In development the Vite
dev server proxies `/api` to FastAPI (no CORS/port juggling); the backend also
sends permissive CORS headers so the two can run on separate origins if needed.

## Quick start (both halves)

```bash
# 1. Backend  (terminal A — needs uv and ffmpeg on PATH)
cd backend
uv sync --extra dev
uv run clazzziks-web --port 5000

# 2. Frontend (terminal B)
cd frontend
npm install
npm run dev                            # http://localhost:5173
```

Point the proxy elsewhere with `VITE_API_TARGET=http://host:port npm run dev`.

## How it works

- **YouTube / SoundCloud** are downloaded directly with [`yt-dlp`](https://github.com/yt-dlp/yt-dlp)
  and transcoded with `ffmpeg`.
- **Spotify** streams are DRM-protected and cannot be downloaded. CLAZZZIKS reads
  the track's public metadata and finds the matching recording on YouTube (the
  same approach `spotdl` uses).

## Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- `ffmpeg` on your `PATH`

```bash
cd backend
uv sync --extra dev
```

## CLI

```bash
cd backend
# Single link -> one audio file (saved to tracks/ by default)
uv run clazzziks "https://youtu.be/<id>"                    # MP3 320 by default
uv run clazzziks "https://youtu.be/<id>" -f wav -o ./out

# Many links -> 4 parallel downloads -> one FLAC ZIP bundle
uv run clazzziks --batch links.txt -f flac -o ./out
uv run clazzziks --batch "https://docs.google.com/spreadsheets/d/<id>/edit"
```

Batch mode downloads up to 4 tracks simultaneously with a live per-track progress
display. Input accepts a text file (one URL per line), a CSV, inline text, or a
**public** Google Sheets URL. After `uv sync` the `clazzziks` and `clazzziks-web`
commands are available directly.

## Web utility (React frontend)

The frontend (`frontend/`) is a Vite + React single-page app. Run the backend
and `npm run dev` (see Quick start), then open http://localhost:5173. It fetches
the supported formats from the backend, detects single-vs-bundle from the link
count, shows backend health, and surfaces quality warnings. `npm run build`
emits static assets to `frontend/dist/` for hosting behind any web server.

The FastAPI backend also serves a minimal no-build fallback form at `/`.

## HTTP API

```
GET  /api/              -> Swagger UI (interactive docs)
GET  /api/health        -> {"status":"ok"}
GET  /api/openapi.json  -> the shared API contract (see below)
GET  /api/formats       -> supported formats + defaults (drives the UI)
POST /api/download      form/JSON: { links, format?, bitrate? }
                        -> audio file (1 link) or application/zip bundle (many)
```

```bash
curl -X POST localhost:5000/api/download \
  -d 'links=https://youtu.be/<id>' -d 'format=mp3' -OJ
```

Quality warnings are returned in the `X-Clazzziks-Warnings` response header.

### Shared API contract

`backend/clazzziks/openapi.json` (OpenAPI 3.1) is the **single source of truth**
for the `/api` surface shared by the backend and the React frontend. The backend
serves it at `/api/openapi.json`; the frontend client (`frontend/src/api.js`)
builds against the same shapes; and `backend/tests/test_contract.py` validates
the backend's live responses against it, so the two halves can't silently drift.

## Formats & quality

| Format | Lossless | Notes                                         |
|--------|----------|-----------------------------------------------|
| WAV    | yes      | uncompressed                                  |
| FLAC   | yes      | default for bundles; recommended for quality  |
| MP3    | no       | 320kbps default; warns below 320              |

MP3 requests below 320kbps, and sources whose real bitrate can't reach 320kbps,
produce warnings (CLI output / API `X-Clazzziks-Warnings` header).

**Quality ceiling:** YouTube serves audio at ~160kbps Opus. Requesting 320kbps
MP3 sets the *encoding target* — re-encoding a 160kbps source does not recover
quality. Use FLAC to preserve the source without a second lossy transcode.

## Tests

```bash
cd backend
uv run pytest                # offline: unit, web API, and contract tests
uv run pytest -m e2e -v      # real-network end-to-end tests (requires ffmpeg + network)
```

The e2e suite has two layers: `test_e2e.py` exercises the downloader directly;
`test_api_e2e.py` runs the same real downloads through the full HTTP API stack.
