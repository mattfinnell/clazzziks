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
    GET    /api/health            -> {"status": "ok"}
    GET    /api/openapi.json      -> the shared OpenAPI contract document
    GET    /api/formats           -> the served format (always MP3); backend probe
    GET    /api/me                -> the caller's VIP/admin status
    GET    /api/admin/vips        -> list the VIP group (admin only)
    POST   /api/admin/vips        -> add/update a VIP (admin only)
    DELETE /api/admin/vips/{email}-> remove a VIP (admin only)
    POST   /api/download          -> one audio file (1 link) or a ZIP bundle (many)
    GET    /                      -> legacy server-rendered fallback form
"""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from .formats import AudioFormat, DEFAULT_MP3_BITRATE, BUNDLE_FORMAT
from .downloader import download_audio, DownloadUnavailableError
from .bundle import download_bundle
from .inputs import collect_urls
from .contract import load_contract
from .logging_config import configure_logging, log_event
from .auth import (
    AuthUser, require_user, require_admin, resolve_optional_user, auth_configured,
)
from . import db

logger = logging.getLogger(__name__)


def _over_rate_limit(user: AuthUser) -> tuple[bool, int, int]:
    """Whether ``user`` has hit their per-window quota.

    Returns ``(over, limit, window_seconds)``. A ``None`` effective limit
    (unlimited — VIPs by default) is never over. Open/dev mode is unlimited.
    """
    window = db.rate_window_seconds()
    if not auth_configured() or user.anonymous:
        return False, 0, window
    limit = db.effective_rate_limit(user.email)
    if limit is None:
        return False, 0, window
    used = db.count_recent_downloads(user.uid, window)
    return used >= limit, limit, window


_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).with_name("templates")))
_TRACKS_DIR = Path(__file__).parents[2] / "tracks"

api = APIRouter(prefix="/api")


@api.get("/", response_class=HTMLResponse)
async def docs():
    return get_swagger_ui_html(openapi_url="/api/openapi.json", title="CLAZZZIKS API")


@api.get("/health")
async def health():
    return {"status": "ok"}


@api.get("/openapi.json")
async def openapi():
    # The shared backend/frontend contract; served so any client can discover it.
    return load_contract()


@api.get("/formats")
async def formats():
    # Users no longer pick a format or bitrate — everything is 320kbps MP3. This
    # endpoint stays so the frontend can probe backend availability and discover
    # the single served format.
    return {
        "formats": [AudioFormat.MP3.value],
        "default_format": AudioFormat.MP3.value,
        "bundle_format": BUNDLE_FORMAT.value,
    }


@api.get("/me")
async def me(user: AuthUser = Depends(require_user)):
    # The caller's status, so the UI can show VIP state / reveal the admin link.
    # In open/dev mode there's no identity, so treat the anonymous caller as a
    # local admin (the app is intentionally unguarded without Firebase).
    if user.anonymous:
        return {
            "email": None, "is_vip": True, "is_admin": True,
            "anonymous": True, "rate_limit": None,
        }
    return {
        "email": user.email,
        "is_vip": db.is_vip(user.email),
        "is_admin": db.is_admin(user.email),
        "anonymous": False,
        "rate_limit": db.effective_rate_limit(user.email),
    }


@api.get("/admin/vips")
async def list_vips(_admin: AuthUser = Depends(require_admin)):
    return {"vips": [_vip_dict(v) for v in db.list_vips()]}


@api.post("/admin/vips")
async def add_vip(request: Request, _admin: AuthUser = Depends(require_admin)):
    payload = await _read_payload(request)
    email = (payload.get("email") or "").strip()
    if "@" not in email:
        return _error("A valid email is required.", 400)
    rate_limit, err = _parse_rate_limit(payload.get("rate_limit"))
    if err:
        return _error(err, 400)
    db.add_vip(
        email,
        note=payload.get("note"),
        is_admin=bool(payload.get("is_admin")),
        rate_limit=rate_limit,
    )
    return {"vips": [_vip_dict(v) for v in db.list_vips()]}


@api.patch("/admin/vips/{email}")
async def update_vip(email: str, request: Request, _admin: AuthUser = Depends(require_admin)):
    payload = await _read_payload(request)
    changes: dict = {}
    if "rate_limit" in payload:
        rate_limit, err = _parse_rate_limit(payload.get("rate_limit"))
        if err:
            return _error(err, 400)
        changes["rate_limit"] = rate_limit
    if "note" in payload:
        changes["note"] = payload.get("note")
    if "is_admin" in payload:
        changes["is_admin"] = bool(payload.get("is_admin"))
    if not db.update_vip(email, **changes):
        return _error(f"{email} is not a VIP.", 404)
    return {"vips": [_vip_dict(v) for v in db.list_vips()]}


@api.delete("/admin/vips/{email}")
async def remove_vip(email: str, _admin: AuthUser = Depends(require_admin)):
    if not db.remove_vip(email):
        return _error(f"{email} is not a VIP.", 404)
    return {"vips": [_vip_dict(v) for v in db.list_vips()]}


@api.post("/download")
async def download(
    request: Request,
    user: AuthUser = Depends(require_user),
):
    payload = await _read_payload(request)
    raw_input = (payload.get("links") or "").strip()
    if not raw_input:
        return _error("No link(s) provided.", 400)

    # Everything users download is 320kbps MP3 — there is no format/bitrate choice.
    fmt = AudioFormat.MP3
    bitrate = DEFAULT_MP3_BITRATE

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
        uid=user.uid, vip=db.is_vip(user.email),
    )

    try:
        if len(urls) == 1:
            return _serve_single(urls[0], fmt, bitrate, request_id, user)
        return _serve_bundle(urls, fmt, bitrate, request_id, user)
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
    async def _rate_limit(request: Request, call_next):
        # Per-user rate limiting lives in middleware so the quota is enforced
        # before any work begins. Only POST /api/download is gated; VIPs (and
        # open/dev mode) are unlimited. Recording each downloaded track happens
        # in the handler, so the count reflects what was actually served.
        if request.method == "POST" and request.url.path.rstrip("/") == "/api/download":
            user = resolve_optional_user(request)
            if user is not None and not user.anonymous:
                over, limit, window = _over_rate_limit(user)
                if over:
                    minutes = max(window // 60, 1)
                    log_event(
                        logger, logging.WARNING, "rate_limit.blocked",
                        uid=user.uid, limit=limit, window_seconds=window,
                    )
                    return JSONResponse(
                        status_code=429,
                        content={
                            "error": (
                                f"Rate limit reached ({limit} tracks per "
                                f"{minutes} min). Ask an admin for VIP access."
                            )
                        },
                    )
        return await call_next(request)

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

    @app.exception_handler(HTTPException)
    async def _http_exc(_request: Request, exc: HTTPException):
        # Render aborts (e.g. auth 401/403 from require_user) in the project's
        # {"error": ...} shape so they match the Error contract and the frontend.
        return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})

    app.include_router(api)

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return _TEMPLATES.TemplateResponse(request, "index.html", {})

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


def _serve_single(
    url: str, fmt: AudioFormat, bitrate: int, request_id: str, user: AuthUser
):
    # Cache hit: re-serve the existing file, skipping the fetch/transcode entirely.
    cached = db.get_cached_track(url, fmt.value)
    if cached:
        db.log_download(user.uid, user.email, url)
        log_event(logger, logging.INFO, "cache.hit", url=url, format=fmt.value)
        path = Path(cached.path)
        return FileResponse(path, filename=path.name)

    outdir = _TRACKS_DIR / (request_id or uuid.uuid4().hex[:8])
    result = download_audio(url, fmt=fmt, outdir=outdir, bitrate=bitrate)
    db.cache_track(
        url, fmt.value, path=str(result.path),
        title=result.title, source=result.source,
    )
    db.log_download(user.uid, user.email, url)

    headers = {}
    if result.warnings:
        headers["X-Clazzziks-Warnings"] = " | ".join(result.warnings)
    return FileResponse(
        result.path,
        filename=result.path.name,
        headers=headers,
    )


def _serve_bundle(
    urls: list[str], fmt: AudioFormat, bitrate: int, request_id: str, user: AuthUser
):
    outdir = _TRACKS_DIR / (request_id or uuid.uuid4().hex[:8])
    result = download_bundle(urls, fmt=fmt, outdir=outdir, bitrate=bitrate)
    # Cache and log each track that actually downloaded so a later single-link
    # request for the same source+format is a cache hit.
    for item in result.items:
        db.cache_track(
            item.url, fmt.value, path=str(item.path),
            title=item.title, source=item.source,
        )
        db.log_download(user.uid, user.email, item.url)

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


def _vip_dict(v: db.Vip) -> dict:
    return {
        "email": v.email,
        "is_admin": v.is_admin,
        "note": v.note,
        "rate_limit": v.rate_limit,
        "added_at": v.added_at,
    }


def _parse_rate_limit(value) -> tuple[int | None, str | None]:
    """Parse a rate-limit input. ``(limit, error)``; ``None`` limit = unlimited.

    Accepts null/""/"unlimited"/"inf" as unlimited, otherwise a positive integer.
    """
    if value is None:
        return None, None
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("", "unlimited", "inf", "infinite", "none", "null"):
            return None, None
        value = text
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return None, "rate_limit must be a positive integer or unlimited."
    if limit <= 0:
        return None, "rate_limit must be a positive integer or unlimited."
    return limit, None


def _error(message: str, status: int):
    return JSONResponse(status_code=status, content={"error": message})


# Allow `uvicorn clazzziks.api:app` and `python -m clazzziks.api`.
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
        "clazzziks.api:app", host=args.host, port=args.port, reload=args.reload
    )


if __name__ == "__main__":
    main()
