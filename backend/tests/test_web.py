"""API tests for the GraphQL backend the frontend talks to (``/graphql``).

Covers the contract the React client in ``frontend/`` depends on (see
``frontend/src/api.ts``): the ``config`` query, the ``download`` mutation +
``progress`` subscription job flow, the ``/files/{token}`` stream, and the
GraphQL error surface for bad input. Downloaders are mocked (no network); the
subscription is driven at the schema level by the ``tests/gql.py`` helpers.

The ``client`` fixture (FastAPI ``TestClient``) lives in ``conftest.py``.
"""

# pylint: disable=missing-function-docstring,redefined-outer-name

from pathlib import Path
from urllib.parse import unquote

from clazzziks.formats import AudioFormat
from clazzziks.downloader import DownloadResult, DownloadUnavailableError

from .gql import gql_data, do_download, run_download, download_error

# Origin headers used to exercise CORS the way a browser would.
_CORS = {"Origin": "http://localhost:5173"}


def mimetype(resp) -> str:
    return resp.headers["content-type"].split(";")[0].strip()


def _make_file(tmp_path: Path, name: str, data: bytes = b"audio-bytes") -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def _states(events, url_substr=None):
    return [
        e["state"] for e in events
        if e["__typename"] == "TrackProgress" and (url_substr is None or url_substr in e["url"])
    ]


# --- health / config -------------------------------------------------------

def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_config_shape_matches_frontend_contract(client):
    cfg = gql_data(client, "{ config { formats default_format bundle_format } }")["config"]
    # Users no longer pick a format/bitrate — everything served is MP3.
    assert cfg["formats"] == ["mp3"]
    assert cfg["default_format"] == "mp3"
    assert cfg["bundle_format"] == "mp3"


# --- download: validation (mutation-level errors) --------------------------

def test_download_requires_links(client):
    assert "No link" in download_error("")


def test_download_rejects_input_with_no_valid_links(client):
    assert download_error("not a url")


# --- download: single file -------------------------------------------------

def test_download_single_returns_file_with_warnings(client, tmp_path, monkeypatch):
    audio = _make_file(tmp_path, "Song [id].mp3")

    def fake_download_audio(_url, **_kwargs):
        return DownloadResult(
            path=audio, title="Song", source="youtube",
            fmt=AudioFormat.MP3, warnings=["low bitrate"],
        )

    monkeypatch.setattr("clazzziks.jobs.download_audio", fake_download_audio)

    resp, complete, events = do_download(client, "https://youtu.be/abc")
    assert resp.status_code == 200
    assert mimetype(resp) == "audio/mpeg"
    assert "Song [id].mp3" in unquote(resp.headers["content-disposition"])
    assert resp.content == b"audio-bytes"
    assert complete["filename"] == "Song [id].mp3"
    assert complete["warnings"] == ["low bitrate"]
    assert complete["failures"] == []
    # The track walked from queued -> ... -> done.
    assert _states(events)[0] == "queued"
    assert _states(events)[-1] == "done"


def test_download_single_unicode_warning_is_preserved(client, tmp_path, monkeypatch):
    # Warnings travel as JSON now, so typographic punctuation (an en-dash) survives
    # intact rather than needing the old ASCII HTTP-header sanitizing.
    audio = _make_file(tmp_path, "Song [id].mp3")

    def fake_download_audio(_url, **_kwargs):
        return DownloadResult(
            path=audio, title="Deadmau5 – Strobe", source="youtube",
            fmt=AudioFormat.MP3, warnings=["Deadmau5 – Strobe: low bitrate"],
        )

    monkeypatch.setattr("clazzziks.jobs.download_audio", fake_download_audio)

    _resp, complete, _events = do_download(client, "https://youtu.be/abc")
    assert complete["warnings"] == ["Deadmau5 – Strobe: low bitrate"]


def test_download_single_unavailable_is_a_failed_track(client, monkeypatch):
    def boom(url, *, fmt, outdir, bitrate, progress_hook=None):
        raise DownloadUnavailableError("DRM protected")

    monkeypatch.setattr("clazzziks.jobs.download_audio", boom)

    events = run_download("https://youtu.be/abc")
    failed = [e for e in events if e["__typename"] == "TrackProgress" and e["state"] == "failed"]
    assert failed and "DRM" in failed[0]["error"]
    # Nothing downloadable -> terminal event has no token.
    assert events[-1]["__typename"] == "DownloadComplete"
    assert events[-1]["token"] is None


def test_download_single_unexpected_error_is_a_failed_track(client, monkeypatch):
    def boom(url, *, fmt, outdir, bitrate, progress_hook=None):
        raise RuntimeError("ffmpeg exploded")

    monkeypatch.setattr("clazzziks.jobs.download_audio", boom)

    events = run_download("https://youtu.be/abc")
    failed = [e for e in events if e["__typename"] == "TrackProgress" and e["state"] == "failed"]
    assert failed and "ffmpeg" in failed[0]["error"]
    assert events[-1]["token"] is None


# --- download: bundle ------------------------------------------------------

def test_download_bundle_returns_zip_with_failures(client, tmp_path, monkeypatch):
    good = _make_file(tmp_path, "Track A [a].mp3")

    def fake_download_audio(url, *, fmt, outdir, bitrate, progress_hook=None):
        if "bad" in url:
            raise DownloadUnavailableError("unavailable")
        return DownloadResult(
            path=good, title="Track A", source="youtube",
            fmt=fmt, warnings=["low bitrate"], url=url,
        )

    monkeypatch.setattr("clazzziks.jobs.download_audio", fake_download_audio)

    resp, complete, events = do_download(client, "https://youtu.be/a\nhttps://youtu.be/bad")
    assert resp.status_code == 200
    assert mimetype(resp) == "application/zip"
    assert "clazzziks_bundle.zip" in resp.headers["content-disposition"]
    assert complete["failures"] == ["failed: https://youtu.be/bad"]
    assert any("Track A: low bitrate" in w for w in complete["warnings"])
    # The bad URL surfaced a failed track event; the good one completed.
    assert "failed" in _states(events, "bad")
    assert "done" in _states(events, "/a")


# --- CORS so a cross-origin frontend can read the file response ------------

def test_files_response_exposes_content_disposition(client, tmp_path, monkeypatch):
    audio = _make_file(tmp_path, "Song [id].mp3")
    monkeypatch.setattr(
        "clazzziks.jobs.download_audio",
        lambda _u, **_k: DownloadResult(
            path=audio, title="Song", source="youtube", fmt=AudioFormat.MP3,
        ),
    )
    resp, _complete, _events = do_download(client, "https://youtu.be/abc", headers=_CORS)
    assert resp.headers["access-control-allow-origin"] == "*"
    assert "Content-Disposition" in resp.headers["access-control-expose-headers"]


def test_graphql_preflight_options_ok(client):
    resp = client.options(
        "/graphql",
        headers={**_CORS, "Access-Control-Request-Method": "POST"},
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-methods"]
