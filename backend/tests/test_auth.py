"""Auth tests for the GraphQL backend.

These don't need firebase-admin or the network: ``auth_configured()`` is made
true via env, and token verification is monkeypatched. They cover the permission
behaviour (anonymous pass-through, error on missing/invalid token, allowlist).
GraphQL surfaces authz failures as ``errors`` (the download mutation fails before
a job starts), so these assert on the error message rather than a status code.
"""

# pylint: disable=missing-function-docstring,redefined-outer-name

from pathlib import Path

import pytest

from clazzziks import auth
from clazzziks.auth import AuthUser
from clazzziks.formats import AudioFormat
from clazzziks.downloader import DownloadResult

from .gql import do_download, download_error, gql_error


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


# --- permission behaviour --------------------------------------------------

def test_download_open_when_auth_not_configured(client, tmp_path, monkeypatch):
    # No Firebase creds -> anonymous pass-through (keeps local dev frictionless).
    monkeypatch.delenv("CLAZZZIKS_FIREBASE_PROJECT_ID", raising=False)
    monkeypatch.setattr("clazzziks.jobs.download_audio", _fake_audio(tmp_path))
    resp, _complete, _events = do_download(client, "https://youtu.be/abc")
    assert resp.status_code == 200
    assert resp.content == b"audio-bytes"


def test_download_requires_token_when_configured(client, configured):
    assert "token" in download_error("https://youtu.be/abc").lower()


def test_download_rejects_invalid_token(client, configured, monkeypatch):
    def boom(_token):
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    monkeypatch.setattr("clazzziks.auth.verify_token", boom)
    headers = {"Authorization": "Bearer bad-token"}
    assert "Invalid or expired" in download_error("https://youtu.be/abc", headers)


def test_download_succeeds_with_valid_token(client, configured, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "clazzziks.auth.verify_token",
        lambda _t: AuthUser(uid="u1", email="ok@example.com", name="OK", email_verified=True),
    )
    monkeypatch.setattr("clazzziks.jobs.download_audio", _fake_audio(tmp_path))

    resp, _complete, _events = do_download(
        client, "https://youtu.be/abc", headers={"Authorization": "Bearer good-token"}
    )
    assert resp.status_code == 200
    assert resp.content == b"audio-bytes"


def test_allowlist_blocks_unapproved_email(client, configured, monkeypatch):
    monkeypatch.setenv("CLAZZZIKS_ALLOWED_EMAILS", "vip@example.com")
    monkeypatch.setattr(
        "clazzziks.auth.verify_token",
        lambda _t: AuthUser(uid="u2", email="stranger@example.com", email_verified=True),
    )
    msg = download_error("https://youtu.be/abc", {"Authorization": "Bearer good-token"})
    assert "pending approval" in msg.lower()


def test_allowlist_allows_approved_email(client, configured, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAZZZIKS_ALLOWED_EMAILS", "vip@example.com, other@example.com")
    monkeypatch.setattr(
        "clazzziks.auth.verify_token",
        lambda _t: AuthUser(uid="u3", email="VIP@example.com", email_verified=True),  # case-insensitive
    )
    monkeypatch.setattr("clazzziks.jobs.download_audio", _fake_audio(tmp_path))
    resp, _complete, _events = do_download(
        client, "https://youtu.be/abc", headers={"Authorization": "Bearer good-token"}
    )
    assert resp.status_code == 200


# --- unverified email is never honoured (account-takeover guard) ------------

def test_unverified_email_is_rejected_on_protected_route(client, configured, tmp_path, monkeypatch):
    # email/password signup yields email_verified=false; it must not be trusted.
    monkeypatch.setattr(
        "clazzziks.auth.verify_token",
        lambda _t: AuthUser(uid="u9", email="spoof@example.com", email_verified=False),
    )
    monkeypatch.setattr("clazzziks.jobs.download_audio", _fake_audio(tmp_path))
    msg = download_error("https://youtu.be/abc", {"Authorization": "Bearer good-token"})
    assert "verify" in msg.lower()


def test_unverified_email_cannot_escalate_to_admin(client, configured, monkeypatch):
    # Exploit scenario: attacker registers the admin's address via password signup
    # (unverified) and tries to inherit the seeded admin row. Must be blocked.
    monkeypatch.setenv("CLAZZZIKS_ADMIN_EMAIL", "boss@example.com")
    monkeypatch.setattr(
        "clazzziks.auth.verify_token",
        lambda _t: AuthUser(uid="attacker", email="boss@example.com", email_verified=False),
    )
    msg = gql_error(
        client,
        "{ users { window_seconds } }",
        headers={"Authorization": "Bearer good-token"},
    )
    assert "verify" in msg.lower()
