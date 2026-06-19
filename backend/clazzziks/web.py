"""FastAPI backend for CLAZZZIKS.

Exposes a small JSON/file API under ``/api`` consumed by the React frontend
(and any other client). In dev the Vite server proxies ``/api`` here; in prod
you can serve the built frontend from any static host pointed at this API.

The request/response shapes are defined by the shared API contract in
``clazzziks/openapi.json`` (served at ``/api/openapi.json``), which is the single
source of truth for both backend and frontend. ``tests/test_contract.py``
validates these responses against it. FastAPI's own schema generation is
disabled (``openapi_url=None``) so that hand-authored contract stays the one
source of truth.

Routes:
    GET  /api/health        -> {"status": "ok"}
    GET  /api/openapi.json  -> the shared OpenAPI contract document
    GET  /api/formats       -> supported formats + defaults (drives the UI)
    POST /api/download      -> one audio file (1 link) or a ZIP bundle (many links)
    GET  /                  -> legacy server-rendered fallback form
"""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from .formats import AudioFormat, SUPPORTED_FORMATS, DEFAULT_MP3_BITRATE, BUNDLE_FORMAT
from .downloader import download_audio, DownloadUnavailableError
from .bundle import download_bundle
from .inputs import collect_urls
from .contract import load_contract
from .logging_config import configure_logging, log_event

logger = logging.getLogger(__name__)

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).with_name("templates")))
_TRACKS_DIR = Path(__file__).parents[2] / "tracks"

api = APIRouter(prefix="/api")


@api.get("/health")
async def health():
    return {"status": "ok"}


@api.get("/openapi.json")
async def openapi():
    # The shared backend/frontend contract; served so any client can discover it.
    return load_contract()


@api.get("/formats")
async def formats():
    return {
        "formats": SUPPORTED_FORMATS,
        "default_format": AudioFormat.MP3.value,
        "bundle_format": BUNDLE_FORMAT.value,
        "default_bitrate": DEFAULT_MP3_BITRATE,
        "bitrates": [320, 256, 192],
    }


@api.post("/download")
async def download(request: Request):
    payload = await _read_payload(request)
    raw_input = (payload.get("links") or "").strip()
    if not raw_input:
        return _error("No link(s) provided.", 400)

    bitrate = _parse_bitrate(payload.get("bitrate"))

    try:
        urls = collect_urls(raw_input)
    except ValueError as exc:
        return _error(str(exc), 400)

    if not urls:
        return _error("No valid links found in the input.", 400)

    request_id = getattr(request.state, "request_id", None)
    log_event(
        logger, logging.INFO, "download.request",
        request_id=request_id, links=len(urls), bitrate=bitrate,
    )

    try:
        if len(urls) == 1:
            fmt = _parse_format(payload.get("format"), default=AudioFormat.MP3)
            return _serve_single(urls[0], fmt, bitrate, request_id)
        fmt = _parse_format(payload.get("format"), default=BUNDLE_FORMAT)
        return _serve_bundle(urls, fmt, bitrate, request_id)
    except ValueError as exc:
        return _error(str(exc), 400)
    except DownloadUnavailableError as exc:
        # The track exists but can't be downloaded (DRM, geo-block, removed).
        return _error(str(exc), 422)
    except Exception as exc:  # noqa: BLE001
        log_event(
            logger, logging.ERROR, "download.failed",
            request_id=request_id, error=str(exc), exc_info=True,
        )
        return _error(f"Download failed: {exc}", 502)


def create_app() -> FastAPI:
    configure_logging()
    # openapi_url=None: the hand-authored clazzziks/openapi.json is the single
    # source of truth, so FastAPI's auto-generated schema/docs stay disabled.
    app = FastAPI(title="CLAZZZIKS API", openapi_url=None)

    # Allow the React dev server (and standalone API clients) to call us and to
    # read the custom warnings/filename headers from JS.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Clazzziks-Warnings", "Content-Disposition"],
    )

    @app.middleware("http")
    async def _observability(request: Request, call_next):
        # Tag every request so its log lines can be correlated end to end.
        request.state.request_id = uuid.uuid4().hex[:8]
        started = time.perf_counter()
        response = await call_next(request)
        log_event(
            logger, logging.INFO, "http.request",
            request_id=request.state.request_id,
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
        return response

    app.include_router(api)

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return _TEMPLATES.TemplateResponse(
            request,
            "index.html",
            {"formats": SUPPORTED_FORMATS, "default_format": AudioFormat.MP3.value},
        )

    return app


async def _read_payload(request: Request) -> dict:
    if request.headers.get("content-type", "").startswith("application/json"):
        try:
            data = await request.json()
        except Exception:  # noqa: BLE001 - malformed JSON body
            return {}
        return data if isinstance(data, dict) else {}
    form = await request.form()
    return {k: v for k, v in form.items()}


def _parse_format(value, *, default: AudioFormat) -> AudioFormat:
    if not value:
        return default
    return AudioFormat.parse(value)


def _parse_bitrate(value) -> int:
    try:
        return int(value) if value else DEFAULT_MP3_BITRATE
    except (TypeError, ValueError):
        return DEFAULT_MP3_BITRATE


def _serve_single(url: str, fmt: AudioFormat, bitrate: int, request_id: str = ""):
    outdir = _TRACKS_DIR / (request_id or uuid.uuid4().hex[:8])
    result = download_audio(url, fmt=fmt, outdir=outdir, bitrate=bitrate)
    headers = {}
    if result.warnings:
        headers["X-Clazzziks-Warnings"] = " | ".join(result.warnings)
    return FileResponse(
        result.path,
        filename=result.path.name,
        headers=headers,
    )


def _serve_bundle(urls: list[str], fmt: AudioFormat, bitrate: int, request_id: str = ""):
    outdir = _TRACKS_DIR / (request_id or uuid.uuid4().hex[:8])
    result = download_bundle(urls, fmt=fmt, outdir=outdir, bitrate=bitrate)
    notes = list(result.warnings) + [f"failed: {u}" for u, _ in result.failures]
    headers = {}
    if notes:
        headers["X-Clazzziks-Warnings"] = " | ".join(notes)
    return FileResponse(
        result.path,
        filename=result.path.name,
        media_type="application/zip",
        headers=headers,
    )


def _error(message: str, status: int):
    return JSONResponse(status_code=status, content={"error": message})


# Allow `uvicorn clazzziks.web:app` and `python -m clazzziks.web`.
app = create_app()


def main() -> None:
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="Run the CLAZZZIKS web server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    uvicorn.run(
        "clazzziks.web:app", host=args.host, port=args.port, reload=args.reload
    )


if __name__ == "__main__":
    main()
