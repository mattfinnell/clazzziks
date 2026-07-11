"""API tests for the GraphQL backend the frontend talks to (``/graphql``).

These exercise the contract the React client in ``frontend/`` depends on
(see ``frontend/src/api.ts``): the ``config`` query shape, the ``download``
mutation + ``/files/{token}`` stream, and the GraphQL error surface for bad
input. The downloaders are mocked so nothing hits the network.

The ``client`` fixture (FastAPI ``TestClient``) lives in ``conftest.py``.
"""

# pylint: disable=missing-function-docstring,redefined-outer-name

from pathlib import Path
from urllib.parse import unquote

from clazzziks.formats import AudioFormat
from clazzziks.downloader import DownloadResult, DownloadUnavailableError
from clazzziks.bundle import BundleResult

from .gql import gql, gql_data, do_download, download_error

# Origin headers used to exercise CORS the way a browser would.
_CORS = {"Origin": "http://localhost:5173"}


def mimetype(resp) -> str:
    return resp.headers["content-type"].split(";")[0].strip()


def _make_file(tmp_path: Path, name: str, data: bytes = b"audio-bytes") -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


# --- health / config -------------------------------------------------------

def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_config_shape_matches_frontend_contract(client):
    data = gql_data(client, "{ config { formats default_format bundle_format } }")
    # Fields the React client (Config) reads. Users no longer pick a format/bitrate;
    # everything served is MP3.
    cfg = data["config"]
    assert cfg["formats"] == ["mp3"]
    assert cfg["default_format"] == "mp3"
    assert cfg["bundle_format"] == "mp3"


# --- download: validation --------------------------------------------------

def test_download_requires_links(client):
    assert "No link" in download_error(client, "")


def test_download_rejects_input_with_no_valid_links(client):
    # "not a url" collects to zero valid links.
    assert download_error(client, "not a url")


# --- download: single file -------------------------------------------------

def test_download_single_returns_file_with_warnings(client, tmp_path, monkeypatch):
    audio = _make_file(tmp_path, "Song [id].mp3")

    def fake_download_audio(_url, **_kwargs):
        return DownloadResult(
            path=audio, title="Song", source="youtube",
            fmt=AudioFormat.MP3, warnings=["low bitrate"],
        )

    monkeypatch.setattr("clazzziks.schema.download_audio", fake_download_audio)

    resp, payload = do_download(client, "https://youtu.be/abc")
    assert resp.status_code == 200
    assert mimetype(resp) == "audio/mpeg"
    # Starlette encodes the filename as RFC 5987 filename*=; the frontend uses the
    # GraphQL-returned name, but the stream still carries a sensible disposition.
    assert "Song [id].mp3" in unquote(resp.headers["content-disposition"])
    assert resp.content == b"audio-bytes"
    assert payload["filename"] == "Song [id].mp3"
    assert payload["warnings"] == ["low bitrate"]
    assert payload["failures"] == []


def test_download_single_unicode_warning_is_preserved(client, tmp_path, monkeypatch):
    # Warnings now travel as JSON (not an ASCII HTTP header), so typographic
    # punctuation like an en-dash survives intact rather than needing sanitizing.
    audio = _make_file(tmp_path, "Song [id].mp3")

    def fake_download_audio(_url, **_kwargs):
        return DownloadResult(
            path=audio, title="Deadmau5 – Strobe", source="youtube",
            fmt=AudioFormat.MP3, warnings=["Deadmau5 – Strobe: low bitrate"],
        )

    monkeypatch.setattr("clazzziks.schema.download_audio", fake_download_audio)

    _resp, payload = do_download(client, "https://youtu.be/abc")
    assert payload["warnings"] == ["Deadmau5 – Strobe: low bitrate"]


def test_download_single_unavailable_is_error(client, monkeypatch):
    def boom(url, *, fmt, outdir, bitrate):
        raise DownloadUnavailableError("DRM protected")

    monkeypatch.setattr("clazzziks.schema.download_audio", boom)
    assert "DRM" in download_error(client, "https://youtu.be/abc")


def test_download_single_unexpected_error_is_wrapped(client, monkeypatch):
    def boom(url, *, fmt, outdir, bitrate):
        raise RuntimeError("ffmpeg exploded")

    monkeypatch.setattr("clazzziks.schema.download_audio", boom)
    assert "Download failed" in download_error(client, "https://youtu.be/abc")


# --- download: bundle ------------------------------------------------------

def test_download_bundle_returns_zip_with_failures(client, tmp_path, monkeypatch):
    archive = _make_file(tmp_path, "clazzziks_bundle.zip", b"PK\x03\x04zip")

    def fake_bundle(_urls, **_kwargs):
        return BundleResult(
            path=archive,
            warnings=["Track A: low bitrate"],
            failures=[("https://youtu.be/bad", "unavailable")],
        )

    monkeypatch.setattr("clazzziks.schema.download_bundle", fake_bundle)

    resp, payload = do_download(client, "https://youtu.be/a\nhttps://youtu.be/bad")
    assert resp.status_code == 200
    assert mimetype(resp) == "application/zip"
    assert "clazzziks_bundle.zip" in resp.headers["content-disposition"]
    assert payload["warnings"] == ["Track A: low bitrate"]
    assert payload["failures"] == ["failed: https://youtu.be/bad"]


# --- CORS so a cross-origin frontend can read the file response ------------

def test_files_response_exposes_content_disposition(client, tmp_path, monkeypatch):
    audio = _make_file(tmp_path, "Song [id].mp3")
    monkeypatch.setattr(
        "clazzziks.schema.download_audio",
        lambda _u, **_k: DownloadResult(
            path=audio, title="Song", source="youtube", fmt=AudioFormat.MP3,
        ),
    )
    resp, _payload = do_download(client, "https://youtu.be/abc", headers=_CORS)
    assert resp.headers["access-control-allow-origin"] == "*"
    assert "Content-Disposition" in resp.headers["access-control-expose-headers"]


def test_graphql_preflight_options_ok(client):
    resp = client.options(
        "/graphql",
        headers={**_CORS, "Access-Control-Request-Method": "POST"},
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-methods"]
