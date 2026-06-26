# Project Root - CLAZZZIKS

Audio downloader supporting YouTube and SoundCloud. Outputs MP3, WAV, or FLAC via a CLI, web UI, or HTTP API.

## Layout

```
backend/    Python core (yt-dlp + ffmpeg), FastAPI API, CLI
frontend/   React + Vite web utility
infra/      Pulumi (TypeScript) — staging and production stacks
Dockerfile  Container image for the FastAPI backend (built/pushed by Pulumi)
```

All backend work lives in `backend/` and uses `uv`. See `backend/CLAUDE.md` for conventions.
All infrastructure work lives in `infra/`. See `infra/CLAUDE.md` for conventions.

## Auth

Optional **Firebase** auth gates `POST /api/download`: the React app signs in with
Google and sends the ID token; the backend (`clazzziks/auth.py`) verifies it.
Enforced only when Firebase credentials are configured — otherwise both halves run
open (keeps dev and tests secret-free). See the Authentication sections of the
root `README.md` and `backend/CLAUDE.md`.

## Persistence

State lives in **Postgres** via a SQLAlchemy ORM (`backend/clazzziks/db.py`): a
download **cache** (keyed by source URL + file type), a **VIP** group, and a
download log. Inside the devcontainer Postgres runs automatically as the `db`
service (`CLAZZZIKS_DATABASE_URL` is pre-set); outside it, `docker compose up -d db`.
In the deployed staging/production environments Postgres is **RDS**, provisioned
by Pulumi (`infra/`); the EC2 instance reads its credentials from Secrets Manager
at boot. The test suite runs against the same local Postgres. Rate limiting is FastAPI middleware —
normal users get 20 tracks/hour, VIPs are unlimited (or an admin-set per-VIP cap).
Admins manage the group via the React `#/admin` dashboard or the `clazzziks-db` CLI.
See the Database section of `backend/CLAUDE.md`.

## Audio formats

The **web utility and HTTP API always output 320kbps MP3** — single files and batch
ZIP bundles alike. There is no user-facing format/bitrate selection (FLAC bundles
were far too large). FLAC/WAV remain in the `AudioFormat` enum for **CLI use only**
(`clazzziks -f flac`).

- **MP3** — 320kbps; the default everywhere; warns if the source bitrate is below 320
- **WAV** — lossless PCM; CLI only (`-f wav`)
- **FLAC** — lossless compressed; CLI only (`-f flac`)

**Quality ceiling:** YouTube's best audio is ~160kbps Opus. Re-encoding to 320kbps MP3 does not recover quality. From the CLI, use FLAC to avoid a second lossy transcode.

## Platforms

- **YouTube** — direct yt-dlp download; CDN returns 403 in cookie-less environments
- **SoundCloud** — direct yt-dlp download; many tracks are DRM-encrypted

Bulk input also accepts a public Google Sheets URL; URL-less rows (song + artist)
are resolved via a `ytsearch1:` YouTube query.
