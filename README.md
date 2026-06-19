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
# 1. Backend  (terminal A)
cd backend
pip install -r requirements.txt        # needs ffmpeg on PATH
python -m clazzziks.web --port 5000

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
- `ffmpeg` on your `PATH`

```bash
cd backend
pip install -r requirements.txt   # or: pip install -e .
```

## CLI

```bash
cd backend
# Single link -> one audio file
python -m clazzziks "https://youtu.be/<id>"                 # MP3 320 by default
python -m clazzziks "https://youtu.be/<id>" -f wav -o ./out

# Many links -> one lossless (FLAC) ZIP bundle
python -m clazzziks --batch links.txt -f flac -o ./out
python -m clazzziks --batch "https://docs.google.com/spreadsheets/d/<id>/edit"
```

Batch input accepts a text file (one URL per line), a CSV file, inline text, or
a **public** Google Sheets URL. After `pip install -e .` the `clazzziks` and
`clazzziks-web` commands are available directly.

## Web utility (React frontend)

The frontend (`frontend/`) is a Vite + React single-page app. Run the backend
and `npm run dev` (see Quick start), then open http://localhost:5173. It fetches
the supported formats from the backend, detects single-vs-bundle from the link
count, shows backend health, and surfaces quality warnings. `npm run build`
emits static assets to `frontend/dist/` for hosting behind any web server.

The FastAPI backend also serves a minimal no-build fallback form at `/`.

## HTTP API

```
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

| Format | Lossless | Notes                              |
|--------|----------|------------------------------------|
| WAV    | yes      | uncompressed                       |
| FLAC   | yes      | default for bundles                |
| MP3    | no       | 320kbps default; warns below 320   |

MP3 requests below 320kbps, and sources whose real bitrate can't reach 320kbps,
produce warnings (CLI stderr / API response header).

## Tests

```bash
cd backend
pip install -e ".[dev]"   # pytest + jsonschema (contract validation)
python -m pytest          # offline: unit, web API, and contract tests
```
