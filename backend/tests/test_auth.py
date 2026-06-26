"""Auth tests for the FastAPI backend.

These don't need firebase-admin or the network: ``auth_configured()`` is made
true via env, and token verification is monkeypatched. They cover the dependency
behaviour (anonymous pass-through, 401 on missing/invalid token, 403 allowlist).
"""

# pylint: disable=missing-function-docstring,redefined-outer-name

from pathlib import Path

import pytest

from clazzziks import auth
from clazzziks.auth import AuthUser
from clazzziks.formats import AudioFormat
from clazzziks.downloader import DownloadResult


@pytest.fixture
def configured(monkeypatch):
    """Make the app behave as if Firebase credentials are configured."""
    monkeypatch.setenv("CLAZZZIKS_FIREBASE_PROJECT_ID", "test-project")
    monkeypatch.delenv("CLAZZZIKS_AUTH_DISABLED", raising=False)
    monkeypatch.delenv("CLAZZZIKS_ALLOWED_EMAILS", raising=False)
    assert auth.auth_configured() is True


def _fake_audio(tmp_path: Path):
    audio = tmp_path / "Song [id].mp3"
    audio.write_bytes(b"audio-bytes")

    def fake_download_audio(_url, **_kwargs):
        return DownloadResult(
            path=audio, title="Song", source="youtube",
            fmt=AudioFormat.MP3, warnings=[],
        )

    return fake_download_audio


# --- dependency behaviour --------------------------------------------------

def test_download_open_when_auth_not_configured(client, tmp_path, monkeypatch):
    # No Firebase creds -> anonymous pass-through (keeps local dev frictionless).
    monkeypatch.delenv("CLAZZZIKS_FIREBASE_PROJECT_ID", raising=False)
    monkeypatch.setattr("clazzziks.api.download_audio", _fake_audio(tmp_path))
    resp = client.post("/api/download", data={"links": "https://youtu.be/abc"})
    assert resp.status_code == 200


def test_download_requires_token_when_configured(client, configured):
    resp = client.post("/api/download", data={"links": "https://youtu.be/abc"})
    assert resp.status_code == 401
    # Error contract shape, not FastAPI's default {"detail": ...}.
    assert "error" in resp.json()


def test_download_rejects_invalid_token(client, configured, monkeypatch):
    def boom(_token):
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    monkeypatch.setattr("clazzziks.auth.verify_token", boom)
    resp = client.post(
        "/api/download",
        data={"links": "https://youtu.be/abc"},
        headers={"Authorization": "Bearer bad-token"},
    )
    assert resp.status_code == 401
    assert "error" in resp.json()


def test_download_succeeds_with_valid_token(client, configured, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "clazzziks.auth.verify_token",
        lambda _t: AuthUser(uid="u1", email="ok@example.com", name="OK", email_verified=True),
    )
    monkeypatch.setattr("clazzziks.api.download_audio", _fake_audio(tmp_path))

    resp = client.post(
        "/api/download",
        data={"links": "https://youtu.be/abc", "format": "mp3"},
        headers={"Authorization": "Bearer good-token"},
    )
    assert resp.status_code == 200
    assert resp.content == b"audio-bytes"


def test_allowlist_blocks_unapproved_email(client, configured, monkeypatch):
    monkeypatch.setenv("CLAZZZIKS_ALLOWED_EMAILS", "vip@example.com")
    monkeypatch.setattr(
        "clazzziks.auth.verify_token",
        lambda _t: AuthUser(uid="u2", email="stranger@example.com", email_verified=True),
    )
    resp = client.post(
        "/api/download",
        data={"links": "https://youtu.be/abc"},
        headers={"Authorization": "Bearer good-token"},
    )
    assert resp.status_code == 403
    assert "error" in resp.json()


def test_allowlist_allows_approved_email(client, configured, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAZZZIKS_ALLOWED_EMAILS", "vip@example.com, other@example.com")
    monkeypatch.setattr(
        "clazzziks.auth.verify_token",
        lambda _t: AuthUser(uid="u3", email="VIP@example.com", email_verified=True),  # case-insensitive
    )
    monkeypatch.setattr("clazzziks.api.download_audio", _fake_audio(tmp_path))
    resp = client.post(
        "/api/download",
        data={"links": "https://youtu.be/abc"},
        headers={"Authorization": "Bearer good-token"},
    )
    assert resp.status_code == 200


# --- unverified email is never honoured (account-takeover guard) ------------

def test_unverified_email_is_rejected_on_protected_route(client, configured, tmp_path, monkeypatch):
    # email/password signup yields email_verified=false; it must not be trusted.
    monkeypatch.setattr(
        "clazzziks.auth.verify_token",
        lambda _t: AuthUser(uid="u9", email="spoof@example.com", email_verified=False),
    )
    monkeypatch.setattr("clazzziks.api.download_audio", _fake_audio(tmp_path))
    resp = client.post(
        "/api/download",
        data={"links": "https://youtu.be/abc"},
        headers={"Authorization": "Bearer good-token"},
    )
    assert resp.status_code == 403
    assert "verify" in resp.json()["error"].lower()


def test_unverified_email_cannot_escalate_to_admin(client, configured, monkeypatch):
    # Exploit scenario: attacker registers the admin's address via password signup
    # (unverified) and tries to inherit the seeded admin row. Must be blocked.
    monkeypatch.setenv("CLAZZZIKS_ADMIN_EMAIL", "boss@example.com")
    monkeypatch.setattr(
        "clazzziks.auth.verify_token",
        lambda _t: AuthUser(uid="attacker", email="boss@example.com", email_verified=False),
    )
    resp = client.get("/api/admin/users", headers={"Authorization": "Bearer good-token"})
    assert resp.status_code == 403
    assert "verify" in resp.json()["error"].lower()
