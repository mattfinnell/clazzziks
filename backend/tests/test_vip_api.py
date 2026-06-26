"""API tests for the DB-backed features: track cache, rate limiting, VIP admin.

The ``isolated_db`` autouse fixture (conftest) gives each test fresh, isolated
Postgres tables. Downloads are mocked so nothing hits the network.
"""

# pylint: disable=missing-function-docstring,redefined-outer-name

from pathlib import Path

import pytest

from clazzziks import auth, db
from clazzziks.auth import AuthUser
from clazzziks.downloader import DownloadResult


def _fake_download_factory(tmp_path: Path, counter: list[int]):
    def fake_download_audio(url, *, fmt, outdir, bitrate):
        counter.append(1)
        audio = tmp_path / f"track-{len(counter)}.{fmt.value}"
        audio.write_bytes(b"audio-bytes")
        return DownloadResult(
            path=audio, title="Track", source="youtube", fmt=fmt, url=url,
        )

    return fake_download_audio


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("CLAZZZIKS_FIREBASE_PROJECT_ID", "test-project")
    monkeypatch.delenv("CLAZZZIKS_AUTH_DISABLED", raising=False)
    monkeypatch.delenv("CLAZZZIKS_ALLOWED_EMAILS", raising=False)
    assert auth.auth_configured() is True


def _signed_in_as(monkeypatch, *, uid: str, email: str):
    monkeypatch.setattr(
        "clazzziks.auth.verify_token", lambda _t: AuthUser(uid=uid, email=email)
    )


# --- track cache -----------------------------------------------------------

def test_repeat_download_is_served_from_cache(client, tmp_path, monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(
        "clazzziks.api.download_audio", _fake_download_factory(tmp_path, calls)
    )

    payload = {"links": "https://youtu.be/abc"}
    first = client.post("/api/download", data=payload)
    second = client.post("/api/download", data=payload)

    assert first.status_code == second.status_code == 200
    assert first.content == second.content == b"audio-bytes"
    # The download/transcode happened exactly once; the repeat hit the cache.
    assert len(calls) == 1


def test_distinct_sources_are_cached_separately(client, tmp_path, monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(
        "clazzziks.api.download_audio", _fake_download_factory(tmp_path, calls)
    )
    client.post("/api/download", data={"links": "https://youtu.be/abc"})
    client.post("/api/download", data={"links": "https://youtu.be/xyz"})
    # Different source URLs are independent cache entries -> two fetches.
    assert len(calls) == 2


# --- rate limiting ---------------------------------------------------------

def test_non_vip_is_rate_limited(client, configured, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAZZZIKS_RATE_LIMIT", "2")
    _signed_in_as(monkeypatch, uid="u1", email="user@example.com")
    monkeypatch.setattr("clazzziks.api.download_audio", _fake_download_factory(tmp_path, []))
    headers = {"Authorization": "Bearer t"}

    data = {"links": "https://youtu.be/abc"}
    assert client.post("/api/download", data=data, headers=headers).status_code == 200
    assert client.post("/api/download", data=data, headers=headers).status_code == 200
    third = client.post("/api/download", data=data, headers=headers)
    assert third.status_code == 429
    assert "error" in third.json()


def test_vip_with_custom_limit_is_capped(client, configured, tmp_path, monkeypatch):
    # A VIP can be given a finite per-user limit by an admin.
    db.add_vip("vip@example.com", rate_limit=1)
    _signed_in_as(monkeypatch, uid="v1", email="vip@example.com")
    monkeypatch.setattr("clazzziks.api.download_audio", _fake_download_factory(tmp_path, []))
    headers = {"Authorization": "Bearer t"}

    data = {"links": "https://youtu.be/abc"}
    assert client.post("/api/download", data=data, headers=headers).status_code == 200
    assert client.post("/api/download", data=data, headers=headers).status_code == 429


def test_vip_bypasses_rate_limit(client, configured, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAZZZIKS_RATE_LIMIT", "1")
    db.add_vip("vip@example.com")
    _signed_in_as(monkeypatch, uid="v1", email="vip@example.com")
    monkeypatch.setattr("clazzziks.api.download_audio", _fake_download_factory(tmp_path, []))
    headers = {"Authorization": "Bearer t"}

    data = {"links": "https://youtu.be/abc"}
    for _ in range(3):
        assert client.post("/api/download", data=data, headers=headers).status_code == 200


def test_no_rate_limit_in_open_mode(client, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAZZZIKS_RATE_LIMIT", "1")
    monkeypatch.setattr("clazzziks.api.download_audio", _fake_download_factory(tmp_path, []))
    # Auth not configured -> anonymous, never rate limited (dev stays frictionless).
    data = {"links": "https://youtu.be/abc"}
    assert client.post("/api/download", data=data).status_code == 200
    assert client.post("/api/download", data=data).status_code == 200


# --- /me -------------------------------------------------------------------

def test_me_reports_local_admin_in_open_mode(client):
    body = client.get("/api/me").json()
    assert body == {
        "email": None, "is_vip": True, "is_admin": True,
        "anonymous": True, "rate_limit": None,
    }


def test_me_reflects_vip_and_admin_when_configured(client, configured, monkeypatch):
    db.add_vip("vip@example.com")
    _signed_in_as(monkeypatch, uid="v1", email="vip@example.com")
    body = client.get("/api/me", headers={"Authorization": "Bearer t"}).json()
    assert body["is_vip"] is True
    assert body["is_admin"] is False
    assert body["email"] == "vip@example.com"


# --- admin VIP management --------------------------------------------------

def test_admin_can_add_and_remove_vip_open_mode(client):
    # Open mode: the local caller is treated as admin.
    added = client.post("/api/admin/vips", json={"email": "new@example.com", "note": "pal"})
    assert added.status_code == 200
    emails = [v["email"] for v in added.json()["vips"]]
    assert "new@example.com" in emails

    removed = client.delete("/api/admin/vips/new@example.com")
    assert removed.status_code == 200
    assert "new@example.com" not in [v["email"] for v in removed.json()["vips"]]


def test_add_vip_with_rate_limit(client):
    resp = client.post(
        "/api/admin/vips", json={"email": "capped@example.com", "rate_limit": 7}
    )
    assert resp.status_code == 200
    row = {v["email"]: v for v in resp.json()["vips"]}["capped@example.com"]
    assert row["rate_limit"] == 7


def test_patch_configures_vip_rate_limit(client):
    client.post("/api/admin/vips", json={"email": "vip@example.com"})
    patched = client.patch("/api/admin/vips/vip@example.com", json={"rate_limit": 42})
    assert patched.status_code == 200
    row = {v["email"]: v for v in patched.json()["vips"]}["vip@example.com"]
    assert row["rate_limit"] == 42

    # null clears it back to unlimited.
    cleared = client.patch("/api/admin/vips/vip@example.com", json={"rate_limit": None})
    row = {v["email"]: v for v in cleared.json()["vips"]}["vip@example.com"]
    assert row["rate_limit"] is None


def test_patch_unknown_vip_is_404(client):
    resp = client.patch("/api/admin/vips/ghost@example.com", json={"rate_limit": 5})
    assert resp.status_code == 404


def test_add_vip_rejects_bad_email(client):
    resp = client.post("/api/admin/vips", json={"email": "not-an-email"})
    assert resp.status_code == 400
    assert "error" in resp.json()


def test_add_vip_rejects_bad_rate_limit(client):
    resp = client.post(
        "/api/admin/vips", json={"email": "x@example.com", "rate_limit": -3}
    )
    assert resp.status_code == 400
    assert "error" in resp.json()


def test_remove_unknown_vip_is_404(client):
    resp = client.delete("/api/admin/vips/ghost@example.com")
    assert resp.status_code == 404


def test_admin_api_forbidden_for_non_admin(client, configured, monkeypatch):
    _signed_in_as(monkeypatch, uid="u1", email="stranger@example.com")
    resp = client.get("/api/admin/vips", headers={"Authorization": "Bearer t"})
    assert resp.status_code == 403
    assert "error" in resp.json()


def test_admin_api_allowed_for_seeded_admin(client, configured, monkeypatch):
    monkeypatch.setenv("CLAZZZIKS_ADMIN_EMAIL", "boss@example.com")
    # First DB touch seeds boss@ as admin (group starts empty).
    assert db.is_admin("boss@example.com") is True
    _signed_in_as(monkeypatch, uid="a1", email="boss@example.com")
    resp = client.get("/api/admin/vips", headers={"Authorization": "Bearer t"})
    assert resp.status_code == 200
    assert "boss@example.com" in [v["email"] for v in resp.json()["vips"]]
