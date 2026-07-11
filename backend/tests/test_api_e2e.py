"""E2e tests for the HTTP API with real network downloads.

These cover the full stack — GraphQL routing, real downloader, ``/files`` stream —
with no mocking. Everything served is MP3. Complement to ``test_e2e.py``
(downloader layer) and ``test_web.py`` (GraphQL layer, mocked downloads).

Run with:  pytest -m e2e -v
Skip with: pytest -m "not e2e"   (the default CI run)
"""

# pylint: disable=redefined-outer-name

import pytest
from fastapi.testclient import TestClient

from clazzziks.api import create_app

from .gql import do_download, download_error

_YT          = "https://www.youtube.com/watch?v=ijo-otbV0Dw&list=RDIxFQ9aUAAJM&index=2"
_SC          = "https://soundcloud.com/mattfinnell/lockyear"
_SC_DRM      = "https://soundcloud.com/valante-music/ramo"
_SPREADSHEET = "https://docs.google.com/spreadsheets/d/10RrB0I_0g7bZGTjGCqo7X72BXoLrjRBcLLwmvTOD5bg/edit?gid=0#gid=0"


@pytest.fixture(scope="module")
def live_client():
    # Generous timeout: real downloads can take tens of seconds. TestClient
    # doesn't accept a timeout kwarg, so set it on the underlying httpx client.
    client = TestClient(create_app())
    client.timeout = 300.0
    return client


# --- single file ------------------------------------------------------------

@pytest.mark.e2e
def test_api_youtube_returns_mp3(live_client):
    resp, _ = do_download(live_client, _YT)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("audio/mpeg")
    assert len(resp.content) > 0


@pytest.mark.e2e
def test_api_soundcloud_returns_mp3(live_client):
    resp, _ = do_download(live_client, _SC)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("audio/mpeg")
    assert len(resp.content) > 0


@pytest.mark.e2e
def test_api_soundcloud_drm_is_error(live_client):
    assert download_error(live_client, _SC_DRM)


# --- bundle -----------------------------------------------------------------

@pytest.mark.e2e
def test_api_bundle_returns_zip(live_client):
    resp, _ = do_download(live_client, f"{_YT}\n{_SC}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    assert resp.content[:2] == b"PK"


# --- spreadsheet ------------------------------------------------------------

@pytest.mark.e2e
def test_api_spreadsheet_returns_zip(live_client):
    from .gql import gql
    body = gql(live_client, "mutation ($l: String!) { download(links: $l) { token } }", {"l": _SPREADSHEET})
    if body.get("errors"):
        err = body["errors"][0]["message"]
        if "401" in err or "Unauthorized" in err or "403" in err:
            pytest.skip("Sheet is not publicly shared — set sharing to 'anyone with the link'")
        raise AssertionError(err)
    token = body["data"]["download"]["token"]
    resp = live_client.get(f"/files/{token}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    assert resp.content[:2] == b"PK"
