# CLAZZZIKS — Backend

FastAPI service that downloads audio from YouTube, SoundCloud, and Spotify and
transcodes it via ffmpeg/yt-dlp.

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
uv run api                               # http://127.0.0.1:5000
uv run api --port 8080 --reload
```

Or with uvicorn directly:

```bash
uv run uvicorn clazzziks.api:app --reload
```

## CLI

```bash
uv run clazzziks <url>                       # single track → MP3 320kbps, saved to tracks/
uv run clazzziks <url> -f wav -o ./out       # WAV, custom output directory
uv run clazzziks <url> -f flac -b 0         # FLAC (bitrate flag is ignored for lossless)
uv run clazzziks --batch links.txt -f flac  # batch → 4 parallel downloads → ZIP bundle
uv run clazzziks --batch "https://docs.google.com/spreadsheets/d/<id>/edit"
```

### CLI flags

| Flag | Default | Description |
|------|---------|-------------|
| `-f / --format` | `mp3` | Output format: `mp3`, `wav`, `flac` |
| `-b / --bitrate` | `320` | MP3 target bitrate in kbps (ignored for WAV/FLAC) |
| `-o / --outdir` | `tracks/` | Output directory |
| `--batch` | — | Batch mode: reads URLs from a file, CSV, or Google Sheets URL |
| `-v / --verbose` | — | Enable DEBUG logging |

Batch mode downloads up to 4 tracks in parallel and shows a live Rich progress
display with per-track spinners. Input accepts a text file (one URL per line),
a CSV, inline text, or a **public** Google Sheets URL. The resulting tracks are
packed into a single ZIP bundle.

## Testing

```bash
# Unit + contract tests (no network, fast)
uv run pytest

# End-to-end tests (real network, slow)
uv run pytest -m e2e -v
```

The e2e suite has two layers: `test_e2e.py` exercises the downloader layer
directly; `test_api_e2e.py` runs the same real downloads end-to-end through
the HTTP API (module-scoped live client, 300 s timeout per request).

## Logging

Controlled via environment variables:

| Variable | Values | Default |
|---|---|---|
| `CLAZZZIKS_LOG_LEVEL` | `DEBUG` / `INFO` / `WARNING` / … | `INFO` |
| `CLAZZZIKS_LOG_FORMAT` | `json` / `text` / `pretty` | `json` |

`pretty` uses [Rich](https://github.com/Textualize/rich) for coloured,
human-readable terminal output — recommended for local development:

```bash
CLAZZZIKS_LOG_FORMAT=pretty uv run api --reload
```

In production (Docker / ECS) the default `json` format is used so structured
logs flow cleanly into CloudWatch.

## Project structure

```
backend/
├── clazzziks/
│   ├── api.py              # FastAPI app + /api routes (cache, rate limit, admin)
│   ├── cli.py              # clazzziks CLI entry point
│   ├── admin.py            # clazzziks-db CLI (manage the VIP group from the shell)
│   ├── auth.py             # Firebase token verification + require_user/require_admin
│   ├── db.py               # SQLAlchemy ORM over Postgres (cache, VIP, rate-limit log)
│   ├── downloader/
│   │   ├── base.py         # Downloader ABC + shared yt-dlp pipeline
│   │   ├── youtube.py
│   │   ├── soundcloud.py
│   │   └── spotify.py      # resolves Spotify → YouTube search via oEmbed
│   ├── bundle.py           # multi-URL ZIP bundler (ThreadPoolExecutor, 4 workers)
│   ├── formats.py          # AudioFormat enum + bitrate warning rules
│   ├── inputs.py           # URL / batch input parsing (files, CSV, Google Sheets)
│   ├── sources.py          # platform detection + Spotify metadata resolution
│   ├── logging_config.py   # structured (json/text/pretty) logging setup
│   ├── contract.py         # loads openapi.json
│   └── openapi.json        # shared API contract (frontend + backend source of truth)
├── tests/
│   ├── conftest.py         # FastAPI TestClient fixture + isolated Postgres tables
│   ├── test_web.py         # API route tests (mocked downloaders)
│   ├── test_auth.py        # Firebase auth dependency tests
│   ├── test_db.py          # data-layer unit tests (cache, VIP, rate limit)
│   ├── test_vip_api.py     # DB-backed API tests (cache, rate limit, VIP admin)
│   ├── test_contract.py    # openapi.json conformance tests
│   ├── test_units.py       # unit tests
│   ├── test_e2e.py         # real-network downloader e2e tests (pytest -m e2e)
│   └── test_api_e2e.py     # real-network HTTP API e2e tests (pytest -m e2e)
├── tracks/                 # CLI audio output — gitignored, kept via .gitkeep
├── pyproject.toml
└── uv.lock
```

The API server writes downloads to `tracks/<request_id>/` at the **repo root**
(two levels above `api.py`). The CLI defaults to `backend/tracks/` when invoked
from `backend/`.

## API

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/` | Swagger UI (interactive docs) |
| `GET` | `/api/health` | `{"status": "ok"}` |
| `GET` | `/api/formats` | Supported formats + defaults (drives the frontend UI) |
| `GET` | `/api/openapi.json` | Shared API contract document |
| `GET` | `/api/me` | Caller's VIP/admin status + effective rate limit |
| `GET` | `/api/admin/vips` | List the VIP group (admin only) |
| `POST` | `/api/admin/vips` | Add/update a VIP (admin only) |
| `PATCH` | `/api/admin/vips/{email}` | Set a VIP's rate limit (admin only) |
| `DELETE` | `/api/admin/vips/{email}` | Remove a VIP (admin only) |
| `POST` | `/api/download` | Download one track or a ZIP bundle |

The full contract is defined in `clazzziks/openapi.json`. See the Database and
Authentication sections of `CLAUDE.md` for the cache, VIP group, and rate-limit
behaviour behind these routes.

## Authentication

`POST /api/download` accepts a Firebase ID token via `Authorization: Bearer <token>`.
Auth is **enforced only when configured** — without a Firebase credential the API
stays open (anonymous), which keeps local dev and the test suite frictionless.

Configure via environment (see `.env.example` for the full list). `uv run api`
auto-loads `backend/.env` (existing/exported vars take precedence); run it from
`backend/` so a relative `CLAZZZIKS_FIREBASE_CREDENTIALS` path resolves:

| Variable | Purpose |
|---|---|
| `CLAZZZIKS_FIREBASE_CREDENTIALS` | Path to a Firebase service-account JSON (enables auth) |
| `CLAZZZIKS_FIREBASE_PROJECT_ID` | Project id (for application-default credentials) |
| `CLAZZZIKS_ALLOWED_EMAILS` | Comma-separated allowlist; others get `403`. Unset = any signed-in user |

Verification lives in `clazzziks/auth.py` (the `require_user` dependency). Token
verification failures return `401`, un-allowlisted users `403`, both in the
`{"error": ...}` contract shape.

## Audio formats

| Format | Notes |
|---|---|
| MP3 | Default for single tracks. 320kbps target; warns if source or requested bitrate is lower |
| WAV | Lossless PCM — no compression |
| FLAC | Lossless compressed; default for batch bundles; **recommended for best quality** |

**Quality ceiling:** YouTube's best audio stream is ~160kbps Opus. Requesting
320kbps MP3 tells ffmpeg what to encode *to*, but re-encoding a 160kbps source
does not recover quality — it just inflates the file. Use FLAC to avoid a second
generation of lossy compression. `source_bitrate_warning()` in `formats.py`
surfaces this automatically.

## Platform notes

| Platform | Strategy | Known limitation |
|---|---|---|
| YouTube | Direct yt-dlp download | CDN returns 403 in headless/cookie-less environments; max source quality ~160kbps Opus |
| SoundCloud | Direct yt-dlp download | Many tracks are AES/DRM-encrypted and cannot be downloaded |
| Spotify | Resolves track metadata via oEmbed → YouTube search → yt-dlp | Quality capped by the YouTube match; depends on YouTube's search ranking |
