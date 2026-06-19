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
uv run clazzziks <url>                       # single track → mp3 320kbps
uv run clazzziks <url> -f wav -o ./out       # wav, custom output dir
uv run clazzziks --batch links.txt -f flac   # batch → zip bundle
```

Examples

```bash
uv run clazzziks https://www.youtube.com/watch?v=ijo-otbV0Dw&list=RDIxFQ9aUAAJM&index=2
uv run clazzziks https://soundcloud.com/mattfinnell/lockyear
uv run clazzziks https://docs.google.com/spreadsheets/d/1-6gWbrj5YGPcMN4Iah2t6LqyqUDPv3l5Ok-5TrNoHg8/edit?gid=0#gid=0 
```

## Testing

```bash
# Unit + contract tests (no network, fast)
uv run pytest

# End-to-end tests (real network, slow)
uv run pytest -m e2e -v
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
│   └── test_e2e.py         # real-network e2e tests (pytest -m e2e)
├── tracks/                 # runtime audio output (gitignored, kept via .gitkeep)
├── pyproject.toml
└── uv.lock
```

## API

| Method | Path | Description |
|---|---|---|
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
| FLAC | Lossless compressed; default for batch bundles |

## Platform notes

| Platform | Strategy | Known limitation |
|---|---|---|
| YouTube | Direct yt-dlp download | Private/members-only videos |
| SoundCloud | Direct yt-dlp download | Many tracks are AES/DRM-encrypted and cannot be downloaded |
| Spotify | Resolves track metadata → YouTube search → yt-dlp | Quality depends on YouTube match |
