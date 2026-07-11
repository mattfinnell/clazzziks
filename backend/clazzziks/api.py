"""FastAPI host for the CLAZZZIKS GraphQL API.

The entire API surface consumed by the React frontend (``frontend/src/api.ts``)
is GraphQL, served at ``POST /graphql`` (with GraphiQL on ``GET /graphql``). The
schema in ``clazzziks/schema.py`` is the single source of truth — its emitted SDL
(``clazzziks/schema.graphql``) is the shared contract validated by
``tests/test_contract.py``.

GraphQL/JSON can't carry binary payloads, so the one non-GraphQL route is
``GET /files/{token}``: the ``download`` mutation performs the fetch/transcode and
returns a token, and this route streams the produced MP3 or ZIP bytes.

Routes:
    POST /graphql        -> the GraphQL API (queries + mutations)
    GET  /graphql        -> GraphiQL explorer
    GET  /files/{token}  -> stream a produced audio file / ZIP bundle (auth-gated)
    GET  /health         -> {"status": "ok"}
    GET  /               -> a pointer to the GraphQL endpoint
"""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from strawberry.fastapi import GraphQLRouter

from .logging_config import configure_logging, log_event
from .auth import AuthUser, require_user
from .schema import schema, get_context, get_file

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="CLAZZZIKS API", openapi_url=None)

    # Allow the React dev server (and standalone API clients) to call us and to
    # read the Content-Disposition filename on the /files download response.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )

    @app.middleware("http")
    async def _observability(request: Request, call_next):
        # Tag every request so its log lines can be correlated end to end. The
        # download resolver reads this id to name its output directory.
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
        # Render aborts (e.g. the /files route's auth 401/403) in the project's
        # {"error": ...} shape so clients get a consistent error body.
        return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})

    graphql_router = GraphQLRouter(schema, context_getter=get_context)
    app.include_router(graphql_router, prefix="/graphql")

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/files/{token}")
    async def files(token: str, _user: AuthUser = Depends(require_user)):
        # Streams a file produced by the `download` mutation. Auth-gated the same
        # way the mutation is; the token is an unguessable per-download handle.
        entry = get_file(token)
        if entry is None:
            raise HTTPException(status_code=404, detail="File not found or expired.")
        path, media_type = entry
        if not path.exists():
            raise HTTPException(status_code=404, detail="File no longer available.")
        return FileResponse(path, filename=path.name, media_type=media_type)

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return (
            "<h1>CLAZZZIKS API</h1>"
            '<p>The API is GraphQL — explore it at <a href="/graphql">/graphql</a>.</p>'
        )

    return app


# Allow `uvicorn clazzziks.api:app` and `python -m clazzziks.api`.
app = create_app()


def _load_dotenv() -> None:
    """Dev convenience: load ``backend/.env`` into the environment for ``uv run api``.

    Only the CLI entry point calls this — production runs ``uvicorn clazzziks.api:app``
    and tests import the app directly, so neither auto-loads a ``.env``. Existing
    environment variables win over the file (``override=False``), so devcontainer
    presets (e.g. ``CLAZZZIKS_DATABASE_URL``) and anything you exported are never
    clobbered. No-op when python-dotenv isn't installed (the lean prod image).
    """
    from pathlib import Path

    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    env_path = Path(__file__).resolve().parents[1] / ".env"  # backend/.env
    if env_path.is_file():
        load_dotenv(env_path)
        logger.info("loaded environment from %s", env_path)


def main() -> None:
    import argparse

    import uvicorn

    _load_dotenv()
    parser = argparse.ArgumentParser(description="Run the CLAZZZIKS API server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    uvicorn.run(
        "clazzziks.api:app", host=args.host, port=args.port, reload=args.reload
    )


if __name__ == "__main__":
    main()
