"""API tests for the FastAPI backend the frontend talks to (``/api/*``).

These exercise the HTTP contract the React client in ``frontend/`` depends on
(see ``frontend/src/api.js``): the JSON shape of ``/api/formats``, the file +
header responses of ``/api/download``, and the ``{"error": ...}`` + status-code
contract for failures. The downloaders are mocked so nothing hits the network.

The ``client`` fixture (FastAPI ``TestClient``) lives in ``conftest.py``.
"""

# pylint: disable=missing-function-docstring,redefined-outer-name

from pathlib import Path
from urllib.parse import unquote

from clazzziks.formats import AudioFormat
from clazzziks.downloader import DownloadResult, DownloadUnavailableError
from clazzziks.bundle import BundleResult


def mimetype(resp) -> str:
    return resp.headers["content-type"].split(";")[0].strip()

# Origin headers used to exercise CORS the way a browser would.
_CORS = {"Origin": "http://localhost:5173"}


def _make_file(tmp_path: Path, name: str, data: bytes = b"audio-bytes") -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


# --- health / formats ------------------------------------------------------

def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_formats_shape_matches_frontend_contract(client):
    resp = client.get("/api/formats")
    assert resp.status_code == 200
    data = resp.json()
    # Keys the React client (Config) reads. Users no longer pick a format/bitrate;
    # everything served is MP3.
    assert set(data) >= {"formats", "default_format", "bundle_format"}
    assert data["formats"] == ["mp3"]
    assert data["default_format"] == "mp3"
    assert data["bundle_format"] == "mp3"


# --- download: validation --------------------------------------------------

def test_download_requires_links(client):
    resp = client.post("/api/download", data={"links": ""})
    assert resp.status_code == 400
    assert "error" in resp.json()


def test_download_rejects_input_with_no_valid_links(client):
    resp = client.post("/api/download", data={"links": "not a url"})
    assert resp.status_code == 400
    assert "error" in resp.json()


# --- download: single file -------------------------------------------------

def test_download_single_returns_file_with_headers(client, tmp_path, monkeypatch):
    audio = _make_file(tmp_path, "Song [id].mp3")

    def fake_download_audio(_url, **_kwargs):
        return DownloadResult(
            path=audio, title="Song", source="youtube",
            fmt=AudioFormat.MP3, warnings=["low bitrate"],
        )

    monkeypatch.setattr("clazzziks.api.download_audio", fake_download_audio)

    resp = client.post("/api/download", data={"links": "https://youtu.be/abc"})
    assert resp.status_code == 200
    assert mimetype(resp) == "audio/mpeg"
    # Starlette encodes the filename as RFC 5987 filename*=; the frontend decodes
    # it (decodeURIComponent), so assert on the decoded value the client sees.
    assert "Song [id].mp3" in unquote(resp.headers["content-disposition"])
    assert resp.headers["x-clazzziks-warnings"] == "low bitrate"
    assert resp.content == b"audio-bytes"


def test_download_single_non_latin1_warning_does_not_500(client, tmp_path, monkeypatch):
    # A warning built from a title with typographic punctuation (an en-dash, the
    # exact U+2013 from the field report) is not latin-1 encodable. Starlette
    # encodes header values as latin-1, so an unsanitized warning header used to
    # 500 the whole request even though the file downloaded fine.
    audio = _make_file(tmp_path, "Song [id].mp3")

    def fake_download_audio(_url, **_kwargs):
        return DownloadResult(
            path=audio, title="Deadmau5 – Strobe", source="youtube",
            fmt=AudioFormat.MP3, warnings=["Deadmau5 – Strobe: low bitrate"],
        )

    monkeypatch.setattr("clazzziks.api.download_audio", fake_download_audio)

    resp = client.post("/api/download", data={"links": "https://youtu.be/abc"})
    assert resp.status_code == 200
    assert resp.content == b"audio-bytes"
    # The en-dash is transliterated to ASCII so the header still reads sensibly.
    assert resp.headers["x-clazzziks-warnings"] == "Deadmau5 - Strobe: low bitrate"


def test_download_single_unavailable_is_422(client, monkeypatch):
    def boom(url, *, fmt, outdir, bitrate):
        raise DownloadUnavailableError("DRM protected")

    monkeypatch.setattr("clazzziks.api.download_audio", boom)

    resp = client.post("/api/download", data={"links": "https://youtu.be/abc"})
    assert resp.status_code == 422
    assert "DRM" in resp.json()["error"]


def test_download_single_unexpected_error_is_502(client, monkeypatch):
    def boom(url, *, fmt, outdir, bitrate):
        raise RuntimeError("ffmpeg exploded")

    monkeypatch.setattr("clazzziks.api.download_audio", boom)

    resp = client.post("/api/download", data={"links": "https://youtu.be/abc"})
    assert resp.status_code == 502
    assert "error" in resp.json()


# --- download: bundle ------------------------------------------------------

def test_download_bundle_returns_zip_with_failure_warnings(client, tmp_path, monkeypatch):
    archive = _make_file(tmp_path, "clazzziks_bundle.zip", b"PK\x03\x04zip")

    def fake_bundle(_urls, **_kwargs):
        return BundleResult(
            path=archive,
            warnings=["Track A: low bitrate"],
            failures=[("https://youtu.be/bad", "unavailable")],
        )

    monkeypatch.setattr("clazzziks.api.download_bundle", fake_bundle)

    resp = client.post(
        "/api/download",
        data={"links": "https://youtu.be/a\nhttps://youtu.be/bad"},
    )
    assert resp.status_code == 200
    assert mimetype(resp) == "application/zip"
    assert "clazzziks_bundle.zip" in resp.headers["content-disposition"]
    warnings = resp.headers["x-clazzziks-warnings"]
    assert "Track A: low bitrate" in warnings
    assert "failed: https://youtu.be/bad" in warnings


def test_download_bundle_non_latin1_warning_does_not_500(client, tmp_path, monkeypatch):
    # Same latin-1 hazard on the batch path: a warning drawn from a track title
    # with an en-dash must not sink a bundle whose files already downloaded.
    archive = _make_file(tmp_path, "clazzziks_bundle.zip", b"PK\x03\x04zip")

    def fake_bundle(_urls, **_kwargs):
        return BundleResult(
            path=archive,
            warnings=["Motörhead – Ace of Spades: low bitrate"],
            failures=[("https://youtu.be/bad", "unavailable")],
        )

    monkeypatch.setattr("clazzziks.api.download_bundle", fake_bundle)

    resp = client.post(
        "/api/download",
        data={"links": "https://youtu.be/a\nhttps://youtu.be/bad"},
    )
    assert resp.status_code == 200
    assert mimetype(resp) == "application/zip"
    warnings = resp.headers["x-clazzziks-warnings"]
    # Header text is flattened to ASCII (umlaut -> base letter, en-dash -> "-")
    # so every client decodes it identically.
    assert "Motorhead - Ace of Spades: low bitrate" in warnings
    assert "failed: https://youtu.be/bad" in warnings


# --- CORS so a cross-origin frontend can read headers ----------------------

def test_responses_expose_cors_and_warning_headers(client):
    resp = client.get("/api/formats", headers=_CORS)
    assert resp.headers["access-control-allow-origin"] == "*"
    expose = resp.headers["access-control-expose-headers"]
    assert "X-Clazzziks-Warnings" in expose
    assert "Content-Disposition" in expose


def test_download_preflight_options_ok(client):
    resp = client.options(
        "/api/download",
        headers={**_CORS, "Access-Control-Request-Method": "POST"},
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-methods"]
