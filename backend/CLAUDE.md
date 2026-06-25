# Backend — Claude Instructions

## Running commands

Always prefix with `uv run` from `backend/`:

```bash
docker compose up -d db        # Postgres (from repo root) — required for tests/app
uv run pytest                  # unit + contract tests (need Postgres up)
uv run pytest -m e2e -v        # real-network e2e tests
uv run clazzziks-web --reload  # dev server (JSON logs, default)
CLAZZZIKS_LOG_FORMAT=pretty uv run clazzziks-web --reload  # coloured dev logs
uv run clazzziks-db vip ls     # manage the VIP group / rate limits
```

## Adding a new platform downloader

1. Create `clazzziks/downloader/<platform>.py` — subclass `Downloader`, set `source`, implement `resolve()`.
2. Override `_explain_failure()` for platform-specific DRM/geo error messages.
3. Register the class in `_DOWNLOADERS` in `clazzziks/downloader/__init__.py`.
4. Add the source variant to `clazzziks/sources.py` (`Source` enum + `detect_source`).
5. Add an e2e test case in `tests/test_e2e.py` marked `@pytest.mark.e2e`.

The Spotify downloader (`downloader/spotify.py`) is the reference for search-based platforms. The YouTube and SoundCloud downloaders show the direct-download pattern.

## API contract

`clazzziks/openapi.json` is the **single source of truth** for the `/api` surface. FastAPI's auto-generated schema is disabled (`openapi_url=None`). If you add or change an endpoint:

1. Update `openapi.json` by hand.
2. Run `pytest tests/test_contract.py` — it validates live responses against the schema.

Never add a new route without updating the contract.

## Authentication

`clazzziks/auth.py` verifies Firebase ID tokens and exposes the `require_user`
FastAPI dependency that protects `POST /api/download`. Key rule: **auth is
enforced only when configured** — `auth_configured()` is false without a Firebase
credential, so `require_user` returns an anonymous user and the suite/dev stay
open. Tests make it "configured" via env (`CLAZZZIKS_FIREBASE_PROJECT_ID`) and
monkeypatch `clazzziks.auth.verify_token` — they never need firebase-admin or the
network (see `tests/test_auth.py`).

- `CLAZZZIKS_ALLOWED_EMAILS` (optional) restricts access to an allowlist → `403`.
- Auth aborts use `HTTPException`; a handler in `web.py` renders them in the
  `{"error": ...}` contract shape (so `401`/`403` match the `Error` schema).
- When adding a protected route, add its `security` + `401`/`403` responses to
  `openapi.json` (the `firebaseToken` bearer scheme is already defined there).

## Database (cache, VIP group, rate limiting)

`clazzziks/db.py` is a **SQLAlchemy ORM** layer over **Postgres**. Connection from
`CLAZZZIKS_DATABASE_URL` (default = the local `docker compose up -d db` Postgres),
read lazily; the engine is cached per-URL so tests can point at another database.
Public functions return small frozen dataclasses (`CachedTrack`, `Vip`) — callers
never touch ORM sessions. Three tables (`Base.metadata`, auto-created on first use):

- **`track_cache`** — keyed by `(url, fmt)` (download source + file type). `web.py`
  checks it before a single-link download and re-serves the existing file on a hit
  (a stale row whose file is gone is pruned → miss). Bundle items are cached too.
- **`vip`** — rate-limit policy per user: `is_admin` flag + nullable `rate_limit`
  (**NULL = unlimited**, the default for a VIP). The owner (`CLAZZZIKS_ADMIN_EMAIL`,
  default `mattfinnell104@gmail.com`) is **seeded as admin whenever the group is
  empty** (including after a removal empties it), so you can't lock yourself out.
- **`download_log`** — one row per served download; drives the rate-limit count.

**Rate limiting is FastAPI middleware** (`_rate_limit` in `web.py`'s `create_app`),
enforced before any work on `POST /api/download`. `db.effective_rate_limit(email)`
resolves the cap: a normal user gets `CLAZZZIKS_RATE_LIMIT` (default **20**) per
`CLAZZZIKS_RATE_WINDOW_SECONDS` (default 3600); a VIP gets their configured
`rate_limit` (unlimited unless an admin set a number). Over the cap → **429**. The
middleware only *enforces* (pre-check); the handler *records* each downloaded track
via `db.log_download`, so the count reflects what was actually served. Open/dev mode
(auth not configured) is anonymous and unlimited.

**VIP is distinct from the auth allowlist.** `CLAZZZIKS_ALLOWED_EMAILS` (in
`auth.py`) gates *access* (403); the VIP group governs *rate-limit policy*.

**Admin surface:** `require_admin` (in `auth.py`) gates `GET/POST /api/admin/vips`,
`PATCH /api/admin/vips/{email}` (set a VIP's rate limit), `DELETE …` to DB admins
(anonymous in open mode). `GET /api/me` reports the caller's VIP/admin status +
effective `rate_limit` to the React `#/admin` dashboard (`frontend/`). Shell admin:
`clazzziks-db vip add|limit|rm|ls` (`clazzziks/admin.py`).

**Tests need a live Postgres** (`docker compose up -d db`). The `isolated_db`
autouse fixture (`tests/conftest.py`) truncates all tables between tests against the
`clazzziks_test` database (`CLAZZZIKS_TEST_DATABASE_URL`). See `tests/test_db.py`
and `tests/test_vip_api.py`.

## Test patterns

- **Unit/contract tests** (`test_web.py`, `test_contract.py`, `test_units.py`): use `monkeypatch` to mock `download_audio` / `download_bundle`. No network. These run by default.
- **Downloader e2e tests** (`test_e2e.py`): hit real URLs through the downloader layer directly. Mark with `@pytest.mark.e2e`. Use `tmp_path` as `outdir` — never write into `tracks/` from tests.
- **API e2e tests** (`test_api_e2e.py`): hit real URLs through the full HTTP API stack (no mocking). Also marked `@pytest.mark.e2e`. Uses a `module`-scoped `live_client` fixture with a 300 s timeout to accommodate slow downloads.

## Audio quality rules

Defined in `clazzziks/formats.py`:

- MP3 below 320kbps → `mp3_bitrate_warning()` emits a warning (does not block the download).
- If the source's actual bitrate (`info["abr"]`) is below 320 → `source_bitrate_warning()` warns that re-encoding won't recover quality.
- Both warnings surface to the caller via `DownloadResult.warnings` and the `X-Clazzziks-Warnings` HTTP header.

## Batch downloads

`_run_batch` in `cli.py` downloads up to 4 tracks concurrently via `ThreadPoolExecutor` (`_BATCH_WORKERS = 4`). The Rich progress display shows one overall bar plus a per-slot spinner for each active download; completed slots are removed immediately. All result/failure collection is guarded by a `threading.Lock`.

## File output

- Web server writes downloads to `tracks/<request_id>/` (one subdirectory per HTTP request, keyed by the 8-char observability request ID from `request.state.request_id`).
- CLI writes to the directory passed via `-o/--outdir` (default: `tracks/`).
- `tracks/` is gitignored for audio content; the directory itself is kept via `.gitkeep`.

## Error hierarchy

| Exception | HTTP status | Meaning |
|---|---|---|
| `ValueError` | 400 | Bad input (unsupported URL, bad format, no links) |
| `DownloadUnavailableError` | 422 | Track exists but can't be downloaded (DRM, geo-block, removed) |
| Any other exception | 502 | Unexpected failure (ffmpeg crash, network error, etc.) |

`DownloadUnavailableError` is the correct exception for DRM and geo-restriction cases — not `RuntimeError`.
