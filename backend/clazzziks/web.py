"""Flask backend for CLAZZZIKS.

Exposes a small JSON/file API under ``/api`` consumed by the React frontend
(and any other client). In dev the Vite server proxies ``/api`` here; in prod
you can serve the built frontend from any static host pointed at this API.

Routes:
    GET  /api/health    -> {"status": "ok"}
    GET  /api/formats   -> supported formats + defaults (drives the UI)
    POST /api/download  -> one audio file (1 link) or a ZIP bundle (many links)
    GET  /              -> legacy server-rendered fallback form
"""

from __future__ import annotations

import tempfile

from flask import Blueprint, Flask, request, render_template, send_file, jsonify

from .formats import AudioFormat, SUPPORTED_FORMATS, DEFAULT_MP3_BITRATE, BUNDLE_FORMAT
from .downloader import download_audio, DownloadUnavailableError
from .bundle import download_bundle
from .inputs import collect_urls

api = Blueprint("api", __name__, url_prefix="/api")


@api.get("/health")
def health():
    return jsonify(status="ok")


@api.get("/formats")
def formats():
    return jsonify(
        formats=SUPPORTED_FORMATS,
        default_format=AudioFormat.MP3.value,
        bundle_format=BUNDLE_FORMAT.value,
        default_bitrate=DEFAULT_MP3_BITRATE,
        bitrates=[320, 256, 192],
    )


@api.post("/download")
def download():
    payload = _read_payload()
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

    try:
        if len(urls) == 1:
            fmt = _parse_format(payload.get("format"), default=AudioFormat.MP3)
            return _serve_single(urls[0], fmt, bitrate)
        fmt = _parse_format(payload.get("format"), default=BUNDLE_FORMAT)
        return _serve_bundle(urls, fmt, bitrate)
    except ValueError as exc:
        return _error(str(exc), 400)
    except DownloadUnavailableError as exc:
        # The track exists but can't be downloaded (DRM, geo-block, removed).
        return _error(str(exc), 422)
    except Exception as exc:  # noqa: BLE001
        return _error(f"Download failed: {exc}", 502)


def create_app() -> Flask:
    app = Flask(__name__)
    app.register_blueprint(api)

    @app.after_request
    def add_cors_headers(response):
        # Allow the React dev server (and standalone API clients) to call us and
        # to read the custom warnings/filename headers from JS.
        response.headers.setdefault("Access-Control-Allow-Origin", "*")
        response.headers.setdefault("Access-Control-Allow-Headers", "Content-Type")
        response.headers.setdefault("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        response.headers.setdefault(
            "Access-Control-Expose-Headers",
            "X-Clazzziks-Warnings, Content-Disposition",
        )
        return response

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            formats=SUPPORTED_FORMATS,
            default_format=AudioFormat.MP3.value,
        )

    return app


def _read_payload() -> dict:
    if request.is_json:
        return request.get_json(silent=True) or {}
    return {k: v for k, v in request.form.items()}


def _parse_format(value, *, default: AudioFormat) -> AudioFormat:
    if not value:
        return default
    return AudioFormat.parse(value)


def _parse_bitrate(value) -> int:
    try:
        return int(value) if value else DEFAULT_MP3_BITRATE
    except (TypeError, ValueError):
        return DEFAULT_MP3_BITRATE


def _serve_single(url: str, fmt: AudioFormat, bitrate: int):
    tmp = tempfile.mkdtemp(prefix="clazzziks_web_")
    result = download_audio(url, fmt=fmt, outdir=tmp, bitrate=bitrate)
    response = send_file(
        result.path,
        as_attachment=True,
        download_name=result.path.name,
    )
    if result.warnings:
        response.headers["X-Clazzziks-Warnings"] = " | ".join(result.warnings)
    return response


def _serve_bundle(urls: list[str], fmt: AudioFormat, bitrate: int):
    tmp = tempfile.mkdtemp(prefix="clazzziks_web_")
    result = download_bundle(urls, fmt=fmt, outdir=tmp, bitrate=bitrate)
    response = send_file(
        result.path,
        as_attachment=True,
        download_name=result.path.name,
        mimetype="application/zip",
    )
    notes = list(result.warnings) + [f"failed: {u}" for u, _ in result.failures]
    if notes:
        response.headers["X-Clazzziks-Warnings"] = " | ".join(notes)
    return response


def _error(message: str, status: int):
    return jsonify(error=message), status


# Allow `flask --app clazzziks.web run` and `python -m clazzziks.web`.
app = create_app()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run the CLAZZZIKS web server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
