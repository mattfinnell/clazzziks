# CLAZZZIKS

Audio downloader for **YouTube** and **SoundCloud**. The web utility and GraphQL API
always output **320kbps MP3** (single files and ZIP bundles alike); the CLI can
additionally emit lossless **WAV**/**FLAC** on request.

## Project layout

```
backend/    Python package (yt-dlp + ffmpeg core, CLI, GraphQL API) + tests
frontend/   React + Vite web utility that talks to the backend GraphQL API
infra/      Pulumi (TypeScript) — EC2, S3, CloudFront, ECR
Dockerfile  Container image for the FastAPI/GraphQL backend (used by Pulumi/ECR)
```

The frontend calls the backend through GraphQL (`/graphql`) plus the `/files/:token`
download stream. In development the Vite dev server proxies both to the backend (no
CORS/port juggling); the backend also sends permissive CORS headers so the two can
run on separate origins if needed.

## Quick start (both halves)

```bash
# 1. Backend  (terminal A — needs uv and ffmpeg on PATH)
cd backend
uv sync --extra dev
uv run api --port 5000

# 2. Frontend (terminal B)
cd frontend
pnpm install
pnpm dev                               # http://localhost:5173
```

Point the proxy elsewhere with `VITE_API_TARGET=http://host:port pnpm dev`.

By default this runs **open** (no login). To require sign-in, configure Firebase
on both halves — see [Authentication](#authentication).

## How it works

- **YouTube / SoundCloud** are downloaded directly with [`yt-dlp`](https://github.com/yt-dlp/yt-dlp)
  and transcoded with `ffmpeg`.
- **Bulk input** — paste many links, or a public Google Sheets URL; URL-less sheet
  rows (song + artist) are resolved via a YouTube search.

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

# Many links -> 4 parallel downloads -> one MP3 ZIP bundle (-f flac for lossless)
uv run clazzziks --batch links.txt -o ./out
uv run clazzziks --batch "https://docs.google.com/spreadsheets/d/<id>/edit"
```

Batch mode downloads up to 4 tracks simultaneously with a live per-track progress
display. Input accepts a text file (one URL per line), a CSV, inline text, or a
**public** Google Sheets URL. After `uv sync` the `clazzziks` and `api`
commands are available directly.

## Web utility (React frontend)

The frontend (`frontend/`) is a Vite + React single-page app written in
TypeScript + SCSS. Run the backend and `pnpm dev` (see Quick start), then open
http://localhost:5173. A top nav switches between the landing page and the
download UI. The download page detects single-vs-bundle from the link count,
shows backend health, and surfaces quality warnings (output is always MP3).
`pnpm build` emits static assets to `frontend/dist/`
for hosting behind any web server.

## GraphQL API

The API is **GraphQL**, served at `POST /graphql` with the GraphiQL explorer on
`GET /graphql`. Because GraphQL/JSON can't carry binary payloads, the `download`
mutation returns a short-lived **token** and the produced MP3/ZIP bytes stream from
the one non-GraphQL route, `GET /files/{token}`.

```
POST /graphql        -> queries + mutations (see operations below)
GET  /graphql        -> GraphiQL explorer
GET  /files/{token}  -> stream a produced MP3 / ZIP bundle   [auth-protected]
GET  /health         -> {"status":"ok"}
```

Operations: `config`, `me`, `vips`, `users` (queries) and
`download`, `add_vip`, `update_vip`, `remove_vip`, `sync_users` (mutations).
The `download` mutation requires a Firebase ID token (`Authorization: Bearer <token>`)
**when the backend is configured with Firebase credentials**; otherwise it stays
open. See [Authentication](#authentication).

```bash
# 1. Kick off a download -> get a token (+ any quality warnings)
curl -s localhost:5000/graphql -H 'content-type: application/json' \
  -d '{"query":"mutation($l:String!){download(links:$l){token filename warnings}}","variables":{"l":"https://youtu.be/<id>"}}'
# 2. Stream the file
curl -OJ "localhost:5000/files/<token>"
```

Quality warnings are returned on the `download` mutation's `warnings` field.

### Shared API contract

The code-first GraphQL schema in `backend/clazzziks/schema.py` (Strawberry) is the
**single source of truth**. Its emitted SDL, `backend/clazzziks/schema.graphql`, is the
committed contract: the frontend client (`frontend/src/api.ts`) builds against those
exact types/fields, and `backend/tests/test_contract.py` fails if the code drifts from
the committed SDL, so the two halves can't silently diverge.

## Authentication

Auth is **optional and off by default** — with no Firebase config, both halves run
open so you can develop without secrets. When configured, the frontend gates behind
**Google sign-in** and sends the user's Firebase ID token as a bearer token; the
backend verifies it on the `download` mutation (and admin operations) and can
restrict access to an email allowlist.

**Enable it (both halves must be configured):**

1. **Frontend** — copy `frontend/.env.example` → `frontend/.env.local` and fill in
   the Firebase web config (Console → Project settings → General → *Your apps*).
2. **Backend** — download a service-account key (Console → Project settings →
   *Service accounts* → Generate new private key) to
   `backend/firebase-service-account.json`, then set the env vars in
   `backend/.env` (template in `backend/.env.example`):

   | Variable | Purpose |
   |---|---|
   | `CLAZZZIKS_FIREBASE_CREDENTIALS` | Path to the service-account JSON (enables auth) |
   | `CLAZZZIKS_ALLOWED_EMAILS` | Optional comma-separated allowlist; others get `403`. Unset = any signed-in user |

3. In the Firebase Console, enable **Authentication → Sign-in method → Google**.

> **Note:** `uv run api` auto-loads `backend/.env` (existing environment
> variables win, so nothing exported or preset is clobbered). Run it from
> `backend/` so the relative `CLAZZZIKS_FIREBASE_CREDENTIALS` path resolves:
> ```bash
> cd backend && uv run api --port 5000
> ```
> Other entry points (`uvicorn clazzziks.api:app`, the test suite) do **not**
> auto-load `.env` — export the vars yourself there.

Token verification lives in `backend/clazzziks/auth.py` (`require_user`
dependency); the frontend auth flow is in `frontend/src/auth/AuthContext.tsx` and
`frontend/src/firebase.ts`. Secrets (`*.env`, `firebase-service-account*.json`)
are gitignored. The web config in `.env.local` is **not** secret — Firebase web
keys are meant to ship in client bundles; access is controlled by Auth rules.

## Formats & quality

The web utility and HTTP API always serve **320kbps MP3** — there is no format or
bitrate selection (FLAC bundles were far too large). The CLI keeps the full set
for power users:

| Format | Lossless | Notes                                         |
|--------|----------|-----------------------------------------------|
| WAV    | yes      | uncompressed PCM                              |
| FLAC   | yes      | default for bundles; recommended for quality  |
| MP3    | no       | 320kbps default; warns below 320              |

MP3 requests below 320kbps, and sources whose real bitrate can't reach 320kbps,
produce warnings (CLI output / the `download` mutation's `warnings` field).

**Quality ceiling:** YouTube serves audio at ~160kbps Opus. Requesting 320kbps
MP3 sets the *encoding target* — re-encoding a 160kbps source does not recover
quality. From the CLI, use FLAC to preserve the source without a second lossy
transcode.

## Tests

```bash
cd backend
uv run pytest                # offline: unit, web API, and contract tests
uv run pytest -m e2e -v      # real-network end-to-end tests (requires ffmpeg + network)
```

The e2e suite has two layers: `test_e2e.py` exercises the downloader directly;
`test_api_e2e.py` runs the same real downloads through the full HTTP API stack.

## Deploy to AWS

The `infra/` directory is a Pulumi (TypeScript) project that provisions the
stack: EC2 (Amazon Linux 2023, Docker + nginx), Elastic IP, 50 GiB EBS scratch
volume, S3 + CloudFront for the React SPA, and an ECR repository for the backend
image. Staging uses a t3.micro; production uses a t3.small.

Prerequisites: Docker, Node.js 18+, AWS CLI configured, Pulumi CLI
(see https://www.pulumi.com/docs/install/).

```bash
cd frontend && pnpm install && pnpm build   # build React first
cd infra && npm install
pulumi stack select production
pulumi up
```

See `infra/README.md` for the full command reference and stack outputs.
