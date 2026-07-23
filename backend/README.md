# CLAZZZIKS — Backend

FastAPI service that downloads audio from YouTube and SoundCloud and transcodes
it via ffmpeg/yt-dlp.

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
| `-f / --format` | `mp3` single / `flac` batch | Output format: `mp3`, `wav`, `flac` |
| `-b / --bitrate` | `320` | MP3 target bitrate in kbps (ignored for WAV/FLAC) |
| `-o / --outdir` | `tracks/` | Output directory |
| `--batch` | — | Batch mode: treat `input` as many links (file, CSV, inline text, or Google Sheets URL) |
| `-v / --verbose` | — | Emit structured logs to stderr: `-v` for INFO, `-vv` for DEBUG (overridden by `CLAZZZIKS_LOG_LEVEL`) |

Batch mode downloads up to 4 tracks in parallel and shows a live Rich progress
display with per-track spinners. Input accepts a text file (one URL per line),
a CSV, inline text, or a **public** Google Sheets URL. URL-less spreadsheet rows
(song + artist) are resolved via a `ytsearch1:` YouTube query. The resulting
tracks are packed into a single ZIP bundle.

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
│   ├── api.py              # FastAPI host: mounts /graphql + /files/{token} stream
│   ├── schema.py           # Strawberry GraphQL schema (queries, mutations, auth, rate limit)
│   ├── cli.py              # clazzziks CLI entry point
│   ├── admin.py            # clazzziks-db CLI (manage the VIP group from the shell)
│   ├── auth.py             # Firebase token verification + require_user/require_admin
│   ├── db.py               # SQLAlchemy ORM over Postgres (cache, VIP, rate-limit log)
│   ├── downloader/
│   │   ├── base.py         # Downloader ABC + shared yt-dlp pipeline
│   │   ├── youtube.py      # direct download; also handles ytsearch1: queries
│   │   └── soundcloud.py
│   ├── bundle.py           # multi-URL ZIP bundler (ThreadPoolExecutor, 4 workers)
│   ├── formats.py          # AudioFormat enum + bitrate warning rules
│   ├── inputs.py           # URL / batch input parsing (files, CSV, Google Sheets)
│   ├── sources.py          # platform detection (YouTube / SoundCloud)
│   ├── logging_config.py   # structured (json/text/pretty) logging setup
│   └── schema.graphql      # emitted SDL — shared API contract (source of truth: schema.py)
├── tests/
│   ├── conftest.py         # FastAPI TestClient fixture + isolated Postgres tables
│   ├── gql.py              # GraphQL test helpers (gql_data, gql_error, do_download)
│   ├── test_web.py         # GraphQL API tests (mocked downloaders)
│   ├── test_auth.py        # Firebase auth / permission tests
│   ├── test_db.py          # data-layer unit tests (cache, VIP, rate limit)
│   ├── test_vip_api.py     # DB-backed API tests (cache, rate limit, VIP admin)
│   ├── test_contract.py    # SDL-drift conformance test
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

The API is **GraphQL** at `POST /graphql` (GraphiQL on `GET /graphql`, subscriptions
over WebSocket at the same path). Plus two plain HTTP routes: `GET /health` and the
`GET /files/{token}` download stream (auth-gated; `token` comes from the terminal
`DownloadComplete` progress event).

**Queries**

| Operation | Description |
|---|---|
| `config` | Served format + defaults (always MP3; drives the frontend UI) |
| `me` | Caller's VIP/admin status + effective rate limit |
| `vips` | List the VIP group (admin only) |
| `users` | All users joined with VIP state + usage (admin only) |

**Mutations**

| Operation | Description |
|---|---|
| `download(links)` | Start a background download job → `{job_id, count}` |
| `add_vip(email, note, is_admin, rate_limit)` | Add/update a VIP (admin only) |
| `update_vip(email, …)` | Change a VIP's note/role/rate limit (admin only) |
| `remove_vip(email)` | Remove a VIP (admin only) |
| `sync_users` | Refresh the Firebase→Postgres user mirror (admin only) |

**Subscription**

| Operation | Description |
|---|---|
| `progress(job_id)` | Stream `TrackProgress` events (queued → downloading → transcoding → done/failed, 4 tracks in parallel), ending with `DownloadComplete { token, filename, warnings, failures }` |

The job orchestration lives in `clazzziks/jobs.py` (a daemon-thread `DownloadJob`
per request, with history replay for reconnecting subscribers). The contract is the
emitted SDL, `clazzziks/schema.graphql` (source of truth: `clazzziks/schema.py`). See
the Database and Authentication sections of `CLAUDE.md` for the cache, VIP group, and
rate-limit behaviour behind these operations.

## Authentication

The `download` mutation (and admin operations) accept a Firebase ID token via
`Authorization: Bearer <token>`. Auth is **enforced only when configured** — without
a Firebase credential the API stays open (anonymous), which keeps local dev and the
test suite frictionless.

Configure via environment (see `.env.example` for the full list). `uv run api`
auto-loads `backend/.env` (existing/exported vars take precedence); run it from
`backend/` so a relative `CLAZZZIKS_FIREBASE_CREDENTIALS` path resolves:

| Variable | Purpose |
|---|---|
| `CLAZZZIKS_FIREBASE_CREDENTIALS` | Path to a Firebase service-account JSON (enables auth) |
| `CLAZZZIKS_FIREBASE_PROJECT_ID` | Project id (for application-default credentials) |
| `CLAZZZIKS_ALLOWED_EMAILS` | Comma-separated allowlist; others get `403`. Unset = any signed-in user |

Verification lives in `clazzziks/auth.py` and is enforced per-resolver by the
`IsUser` / `IsAdmin` permission classes in `clazzziks/schema.py`. A denied operation
returns a GraphQL error carrying the auth message (invalid token, unverified email,
un-allowlisted user, or non-admin).

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
