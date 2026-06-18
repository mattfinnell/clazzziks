"""Minimal Flask web interface + JSON API for CLAZZZIKS.

Routes:
    GET  /                 -> the simple web form
    POST /download         -> form/JSON: download one link or a bundle, returns the file
    GET  /health           -> liveness probe

The same endpoint powers both single links (returns one audio file) and many
links (returns a ZIP bundle), matching the spec's two web use-cases.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from flask import Flask, request, render_template, send_file, jsonify

from .formats import AudioFormat, SUPPORTED_FORMATS, DEFAULT_MP3_BITRATE, BUNDLE_FORMAT
from .downloader import download_audio
from .bundle import download_bundle
from .inputs import collect_urls


def create_app() -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            formats=SUPPORTED_FORMATS,
            default_format=AudioFormat.MP3.value,
        )

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.post("/download")
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
        except Exception as exc:  # noqa: BLE001
            return _error(f"Download failed: {exc}", 502)

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
