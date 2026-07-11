# Backend — Claude Instructions

## Running commands

Always prefix with `uv run` from `backend/`:

```bash
# In the devcontainer, Postgres runs automatically as the `db` service and
# CLAZZZIKS_DATABASE_URL / CLAZZZIKS_TEST_DATABASE_URL are already exported.
# Outside the devcontainer, start Postgres yourself from the repo root:
docker compose up -d db        # Postgres — required for tests/app
uv run pytest                  # unit + contract tests (need Postgres up)
uv run pytest -m e2e -v        # real-network e2e tests
uv run api --reload  # dev server (JSON logs, default)
CLAZZZIKS_LOG_FORMAT=pretty uv run api --reload  # coloured dev logs
uv run clazzziks-db vip ls     # manage the VIP group / rate limits
```

## Adding a new platform downloader

1. Create `clazzziks/downloader/<platform>.py` — subclass `Downloader`, set `source`, implement `resolve()`.
2. Override `_explain_failure()` for platform-specific DRM/geo error messages.
3. Register the class in `_DOWNLOADERS` in `clazzziks/downloader/__init__.py`.
4. Add the source variant to `clazzziks/sources.py` (`Source` enum + `detect_source`).
5. Add an e2e test case in `tests/test_e2e.py` marked `@pytest.mark.e2e`.

The YouTube and SoundCloud downloaders show the direct-download pattern. YouTube also handles `ytsearch1:` queries (from URL-less spreadsheet rows), whose playlist-shaped result the base `_select_result` unwraps to the top match.

## API surface & contract

The API is **GraphQL** (Strawberry) at `POST /graphql` (GraphiQL on `GET /graphql`).
The code-first schema in `clazzziks/schema.py` is the **single source of truth**; its
emitted SDL, `clazzziks/schema.graphql`, is the committed contract shared with the
frontend. `auto_camel_case` is **disabled**, so field names stay snake_case
(`is_vip`, `rate_limit`, …) to match what the React client builds against.

Binary payloads can't travel over GraphQL, so the `download` mutation returns a
short-lived **token** and the produced MP3/ZIP bytes stream from the one
non-GraphQL route, `GET /files/{token}` (in `api.py`, auth-gated).

If you add or change an operation:

1. Edit the types/resolvers in `clazzziks/schema.py`.
2. Regenerate the SDL:
   `uv run python -c "from clazzziks.schema import schema; open('clazzziks/schema.graphql','w').write(schema.as_str()+'\n')"`
3. Run `pytest tests/test_contract.py` — it fails if the emitted schema drifts from the committed SDL.

Never change the schema without regenerating `schema.graphql`.

## Authentication

`clazzziks/auth.py` verifies Firebase ID tokens and exposes `require_user` /
`require_admin`. GraphQL has one endpoint, so authz is enforced **per resolver** via
the `IsUser` / `IsAdmin` permission classes in `clazzziks/schema.py`, which wrap those
functions and stash the resolved user on the request context. `IsUser` gates the
`download` mutation and `me` query; `IsAdmin` gates `vips`/`users` and the VIP
mutations. Key rule: **auth is enforced only when configured** — `auth_configured()`
is false without a Firebase credential, so `require_user` returns an anonymous user
and the suite/dev stay open. Tests make it "configured" via env
(`CLAZZZIKS_FIREBASE_PROJECT_ID`) and monkeypatch `clazzziks.auth.verify_token` — they
never need firebase-admin or the network (see `tests/test_auth.py`).

- **Verified email required.** The whole authz model (allowlist, admin, VIP) keys
  off the token's `email`, so `require_user` rejects an **unverified** address
  ("Verify your email address before continuing" — surfaced as a GraphQL error).
  This matters because
  email/password signup is enabled — an unverified `email` claim is attacker-chosen
  (they could register the admin's address), so it must never be trusted. Google
  sign-in is always verified; password accounts must confirm the emailed link first.
  Hardening: set the Firebase project to **one account per email** and prefer
  keeping privileged (admin) accounts on the Google provider.
- `CLAZZZIKS_ALLOWED_EMAILS` (optional) restricts access to an allowlist.
- A denied resolver surfaces the auth message as a GraphQL error (HTTP stays 200,
  the permission borrows the underlying `HTTPException.detail`). The `/files` route
  still raises `HTTPException`, rendered by the `api.py` handler in the
  `{"error": ...}` shape.
- When adding a protected operation, attach `permission_classes=[IsUser]` (or
  `IsAdmin`) to its field/mutation in `schema.py` and regenerate `schema.graphql`.

## Database (cache, VIP group, rate limiting)

`clazzziks/db.py` is a **SQLAlchemy ORM** layer over **Postgres**. Connection from
`CLAZZZIKS_DATABASE_URL` (default = the local `docker compose up -d db` Postgres),
read lazily; the engine is cached per-URL so tests can point at another database.
Public functions return small frozen dataclasses (`CachedTrack`, `Vip`) — callers
never touch ORM sessions. Three tables (`Base.metadata`, auto-created on first use):

- **`track_cache`** — keyed by `(url, fmt)` (download source + file type). `api.py`
  checks it before a single-link download and re-serves the existing file on a hit
  (a stale row whose file is gone is pruned → miss). Bundle items are cached too.
- **`vip`** — rate-limit policy per user: `is_admin` flag + nullable `rate_limit`
  (**NULL = unlimited**, the default for a VIP). The owner (`CLAZZZIKS_ADMIN_EMAIL`)
  is **upserted as a VIP + admin on every startup** (`_seed_admin`, idempotent):
  the owner row is created with `is_admin=True` if missing, or promoted to admin
  if it exists (a deliberately-set `rate_limit` is preserved), so a fresh deploy
  always has a working admin and you can't lock yourself out. A removal that
  empties the group also re-seeds the owner. There is no built-in default — when
  the variable is unset, no owner is seeded.
- **`download_log`** — one row per served download; drives the rate-limit count.

**Rate limiting lives in the `download` resolver** (`_over_rate_limit` in
`clazzziks/schema.py`), checked before any work begins. `db.effective_rate_limit(email)`
resolves the cap: a normal user gets `CLAZZZIKS_RATE_LIMIT` (default **20**) per
`CLAZZZIKS_RATE_WINDOW_SECONDS` (default 3600); a VIP gets their configured
`rate_limit` (unlimited unless an admin set a number). Over the cap → a
`RateLimitError` surfaced as a GraphQL error. The pre-check only *enforces*; the
resolver *records* each downloaded track via `db.log_download`, so the count reflects
what was actually served. Open/dev mode (auth not configured) is anonymous and unlimited.

**VIP is distinct from the auth allowlist.** `CLAZZZIKS_ALLOWED_EMAILS` (in
`auth.py`) gates *access* (403); the VIP group governs *rate-limit policy*.

**Admin surface:** the `IsAdmin` permission gates the `vips`/`users` queries and the
`add_vip`/`update_vip`/`remove_vip`/`sync_users` mutations (DB admins; anonymous in
open mode). The `me` query reports the caller's VIP/admin status + effective
`rate_limit` to the React `#/admin` dashboard (`frontend/`). Shell admin:
`clazzziks-db vip add|limit|rm|ls` (`clazzziks/admin.py`).

**Tests need a live Postgres** — automatic inside the devcontainer (the `db`
service from `.devcontainer/docker-compose.yml` + the repo-root `docker-compose.yml`),
or `docker compose up -d db` outside it. The `isolated_db` autouse fixture
(`tests/conftest.py`) truncates all tables between tests against the `clazzziks_test`
database (`CLAZZZIKS_TEST_DATABASE_URL`, auto-created if missing). See
`tests/test_db.py` and `tests/test_vip_api.py`.

## Test patterns

- **Unit/contract tests** (`test_web.py`, `test_contract.py`, `test_units.py`): use `monkeypatch` to mock `clazzziks.schema.download_audio` / `download_bundle`. Drive GraphQL via the `tests/gql.py` helpers (`gql_data`, `gql_error`, `do_download`). No network. These run by default.
- **Downloader e2e tests** (`test_e2e.py`): hit real URLs through the downloader layer directly. Mark with `@pytest.mark.e2e`. Use `tmp_path` as `outdir` — never write into `tracks/` from tests.
- **API e2e tests** (`test_api_e2e.py`): hit real URLs through the full HTTP API stack (no mocking). Also marked `@pytest.mark.e2e`. Uses a `module`-scoped `live_client` fixture with a 300 s timeout to accommodate slow downloads.

## Audio quality rules

Defined in `clazzziks/formats.py`:

- MP3 below 320kbps → `mp3_bitrate_warning()` emits a warning (does not block the download).
- If the source's actual bitrate (`info["abr"]`) is below 320 → `source_bitrate_warning()` warns that re-encoding won't recover quality.
- Both warnings surface to the caller via `DownloadResult.warnings` (the CLI) and the `download` mutation's `warnings` field (the web/API).

## Batch downloads

`_run_batch` in `cli.py` downloads up to 4 tracks concurrently via `ThreadPoolExecutor` (`_BATCH_WORKERS = 4`). The Rich progress display shows one overall bar plus a per-slot spinner for each active download; completed slots are removed immediately. All result/failure collection is guarded by a `threading.Lock`.

## File output

- API server writes downloads to `tracks/<request_id>/` (one subdirectory per HTTP request, keyed by the 8-char observability request ID from `request.state.request_id`).
- CLI writes to the directory passed via `-o/--outdir` (default: `tracks/`).
- `tracks/` is gitignored for audio content; the directory itself is kept via `.gitkeep`.

## Error hierarchy

| Exception | HTTP status | Meaning |
|---|---|---|
| `ValueError` | 400 | Bad input (unsupported URL, bad format, no links) |
| `DownloadUnavailableError` | 422 | Track exists but can't be downloaded (DRM, geo-block, removed) |
| Any other exception | 502 | Unexpected failure (ffmpeg crash, network error, etc.) |

`DownloadUnavailableError` is the correct exception for DRM and geo-restriction cases — not `RuntimeError`.
