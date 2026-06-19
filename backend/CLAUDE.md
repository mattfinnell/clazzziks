# Backend — Claude Instructions

## Running commands

Always prefix with `uv run` from `backend/`:

```bash
uv run pytest                  # unit + contract tests
uv run pytest -m e2e -v        # real-network e2e tests
uv run clazzziks-web --reload  # dev server
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

## Test patterns

- **Unit/contract tests** (`test_web.py`, `test_contract.py`, `test_units.py`): use `monkeypatch` to mock `download_audio` / `download_bundle`. No network. These run by default.
- **e2e tests** (`test_e2e.py`): hit real URLs. Mark with `@pytest.mark.e2e`. Use `tmp_path` as `outdir` — never write into `tracks/` from tests.

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
