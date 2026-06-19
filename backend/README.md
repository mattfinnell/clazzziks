# CLAZZZIKS — Backend

FastAPI service that downloads audio from YouTube, SoundCloud, and Spotify and transcodes it via ffmpeg/yt-dlp.

## Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- ffmpeg on `$PATH`

## Setup

```bash
cd backend
uv sync --extra dev   # installs runtime + test dependencies into .venv
```

## Running the server

```bash
uv run clazzziks-web                     # http://127.0.0.1:5000
uv run clazzziks-web --port 8080 --reload
```

Or with uvicorn directly:

```bash
uv run uvicorn clazzziks.web:app --reload
```

## CLI

```bash
uv run clazzziks <url>                       # single track → mp3 320kbps, saved to tracks/
uv run clazzziks <url> -f wav -o ./out       # wav, custom output dir
uv run clazzziks --batch links.txt -f flac   # batch → 4 parallel downloads → zip bundle
uv run clazzziks --batch "https://docs.google.com/spreadsheets/d/<id>/edit"
```

Batch mode downloads up to 4 tracks in parallel and shows a live progress display with per-track spinners. Single-track mode saves to `tracks/` by default.

## Testing

```bash
# Unit + contract tests (no network, fast)
uv run pytest

# End-to-end tests (real network, slow)
uv run pytest -m e2e -v
```

The e2e suite has two layers: `test_e2e.py` exercises the downloader layer
directly; `test_api_e2e.py` runs the same real downloads end-to-end through
the HTTP API.

## Logging

Controlled via environment variables:

| Variable | Values | Default |
|---|---|---|
| `CLAZZZIKS_LOG_LEVEL` | `DEBUG` / `INFO` / `WARNING` / … | `INFO` |
| `CLAZZZIKS_LOG_FORMAT` | `json` / `text` / `pretty` | `json` |

`pretty` uses [Rich](https://github.com/Textualize/rich) for coloured,
human-readable terminal output — recommended for local development:

```bash
CLAZZZIKS_LOG_FORMAT=pretty uv run clazzziks-web --reload
```

## Project structure

```
backend/
├── clazzziks/
│   ├── web.py              # FastAPI app + /api routes
│   ├── cli.py              # clazzziks CLI entry point
│   ├── downloader/
│   │   ├── base.py         # Downloader ABC + shared yt-dlp pipeline
│   │   ├── youtube.py
│   │   ├── soundcloud.py
│   │   └── spotify.py      # resolves Spotify → YouTube search
│   ├── bundle.py           # multi-URL zip bundler
│   ├── formats.py          # AudioFormat enum + bitrate rules
│   ├── inputs.py           # URL/batch input parsing
│   ├── sources.py          # platform detection + Spotify metadata resolution
│   ├── contract.py         # loads openapi.json
│   └── openapi.json        # shared API contract (frontend + backend source of truth)
├── tests/
│   ├── conftest.py         # FastAPI TestClient fixture
│   ├── test_web.py         # API route tests (mocked downloaders)
│   ├── test_contract.py    # openapi.json conformance tests
│   ├── test_units.py       # unit tests
│   ├── test_e2e.py         # real-network downloader e2e tests (pytest -m e2e)
│   └── test_api_e2e.py     # real-network HTTP API e2e tests (pytest -m e2e)
├── tracks/                 # runtime audio output (gitignored, kept via .gitkeep)
├── pyproject.toml
└── uv.lock
```

## API

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/` | Swagger UI (interactive docs) |
| `GET` | `/api/health` | `{"status": "ok"}` |
| `GET` | `/api/formats` | Supported formats + defaults |
| `GET` | `/api/openapi.json` | Shared API contract document |
| `POST` | `/api/download` | Download one track or a ZIP bundle |

The full contract is defined in `clazzziks/openapi.json`.

## Audio formats

| Format | Notes |
|---|---|
| MP3 | Default. 320kbps target; warns if source or requested bitrate is lower |
| WAV | Lossless PCM |
| FLAC | Lossless compressed; default for batch bundles; **recommended for best quality** |

**Quality ceiling:** YouTube's best audio stream is ~160kbps Opus. Requesting 320kbps MP3 tells ffmpeg what to encode *to*, but re-encoding a 160kbps source does not recover quality — it just inflates the file. Use FLAC to avoid a second generation of lossy compression. `source_bitrate_warning()` surfaces this to the user automatically.

## Platform notes

| Platform | Strategy | Known limitation |
|---|---|---|
| YouTube | Direct yt-dlp download | CDN returns 403 in headless/cookie-less environments; max source quality ~160kbps Opus |
| SoundCloud | Direct yt-dlp download | Many tracks are AES/DRM-encrypted and cannot be downloaded |
| Spotify | Resolves track metadata → YouTube search → yt-dlp | Quality capped by the YouTube match |
