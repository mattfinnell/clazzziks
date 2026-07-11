"""API tests for the DB-backed features: track cache, rate limiting, VIP admin.

The ``isolated_db`` autouse fixture (conftest) gives each test fresh, isolated
Postgres tables. Downloads are mocked so nothing hits the network. Everything
goes through the GraphQL API (queries/mutations) + the ``/files`` stream.
"""

# pylint: disable=missing-function-docstring,redefined-outer-name

from pathlib import Path

import pytest

from clazzziks import auth, db
from clazzziks.auth import AuthUser
from clazzziks.downloader import DownloadResult

from .gql import gql_data, gql_error, do_download, download_error

_AUTH = {"Authorization": "Bearer t"}


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


def _signed_in_as(monkeypatch, *, uid: str, email: str, verified: bool = True):
    monkeypatch.setattr(
        "clazzziks.auth.verify_token",
        lambda _t: AuthUser(uid=uid, email=email, email_verified=verified),
    )


# --- VIP admin GraphQL helpers ---------------------------------------------

ADD_VIP = "mutation ($e: String!, $n: String, $rl: Int) { add_vip(email: $e, note: $n, rate_limit: $rl) { email is_admin note rate_limit } }"
UPDATE_VIP = "mutation ($e: String!, $rl: Int) { update_vip(email: $e, rate_limit: $rl) { email rate_limit } }"
REMOVE_VIP = "mutation ($e: String!) { remove_vip(email: $e) { email } }"
VIPS = "{ vips { email is_admin note rate_limit } }"
ME = "{ me { email is_vip is_admin anonymous rate_limit } }"
USERS = "{ users { users { email name is_vip is_admin rate_limit used_this_window provider } window_seconds auth_configured last_synced_at } }"
SYNC_USERS = "mutation { sync_users { users { email } last_synced_at } }"


# --- track cache -----------------------------------------------------------

def test_repeat_download_is_served_from_cache(client, tmp_path, monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(
        "clazzziks.schema.download_audio", _fake_download_factory(tmp_path, calls)
    )

    first, _ = do_download(client, "https://youtu.be/abc")
    second, _ = do_download(client, "https://youtu.be/abc")

    assert first.status_code == second.status_code == 200
    assert first.content == second.content == b"audio-bytes"
    # The download/transcode happened exactly once; the repeat hit the cache.
    assert len(calls) == 1


def test_distinct_sources_are_cached_separately(client, tmp_path, monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(
        "clazzziks.schema.download_audio", _fake_download_factory(tmp_path, calls)
    )
    do_download(client, "https://youtu.be/abc")
    do_download(client, "https://youtu.be/xyz")
    # Different source URLs are independent cache entries -> two fetches.
    assert len(calls) == 2


# --- rate limiting ---------------------------------------------------------

def test_non_vip_is_rate_limited(client, configured, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAZZZIKS_RATE_LIMIT", "2")
    _signed_in_as(monkeypatch, uid="u1", email="user@example.com")
    monkeypatch.setattr("clazzziks.schema.download_audio", _fake_download_factory(tmp_path, []))

    assert do_download(client, "https://youtu.be/abc", _AUTH)[0].status_code == 200
    assert do_download(client, "https://youtu.be/abc", _AUTH)[0].status_code == 200
    assert "Rate limit reached" in download_error(client, "https://youtu.be/abc", _AUTH)


def test_vip_with_custom_limit_is_capped(client, configured, tmp_path, monkeypatch):
    # A VIP can be given a finite per-user limit by an admin.
    db.add_vip("vip@example.com", rate_limit=1)
    _signed_in_as(monkeypatch, uid="v1", email="vip@example.com")
    monkeypatch.setattr("clazzziks.schema.download_audio", _fake_download_factory(tmp_path, []))

    assert do_download(client, "https://youtu.be/abc", _AUTH)[0].status_code == 200
    assert "Rate limit reached" in download_error(client, "https://youtu.be/abc", _AUTH)


def test_vip_bypasses_rate_limit(client, configured, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAZZZIKS_RATE_LIMIT", "1")
    db.add_vip("vip@example.com")
    _signed_in_as(monkeypatch, uid="v1", email="vip@example.com")
    monkeypatch.setattr("clazzziks.schema.download_audio", _fake_download_factory(tmp_path, []))

    for _ in range(3):
        assert do_download(client, "https://youtu.be/abc", _AUTH)[0].status_code == 200


def test_no_rate_limit_in_open_mode(client, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAZZZIKS_RATE_LIMIT", "1")
    monkeypatch.setattr("clazzziks.schema.download_audio", _fake_download_factory(tmp_path, []))
    # Auth not configured -> anonymous, never rate limited (dev stays frictionless).
    assert do_download(client, "https://youtu.be/abc")[0].status_code == 200
    assert do_download(client, "https://youtu.be/abc")[0].status_code == 200


# --- me --------------------------------------------------------------------

def test_me_reports_local_admin_in_open_mode(client):
    me = gql_data(client, ME)["me"]
    assert me == {
        "email": None, "is_vip": True, "is_admin": True,
        "anonymous": True, "rate_limit": None,
    }


def test_me_reflects_vip_and_admin_when_configured(client, configured, monkeypatch):
    db.add_vip("vip@example.com")
    _signed_in_as(monkeypatch, uid="v1", email="vip@example.com")
    me = gql_data(client, ME, headers=_AUTH)["me"]
    assert me["is_vip"] is True
    assert me["is_admin"] is False
    assert me["email"] == "vip@example.com"


# --- admin VIP management --------------------------------------------------

def test_admin_can_add_and_remove_vip_open_mode(client):
    # Open mode: the local caller is treated as admin.
    added = gql_data(client, ADD_VIP, {"e": "new@example.com", "n": "pal"})["add_vip"]
    assert "new@example.com" in [v["email"] for v in added]

    removed = gql_data(client, REMOVE_VIP, {"e": "new@example.com"})["remove_vip"]
    assert "new@example.com" not in [v["email"] for v in removed]


def test_add_vip_with_rate_limit(client):
    vips = gql_data(client, ADD_VIP, {"e": "capped@example.com", "rl": 7})["add_vip"]
    row = {v["email"]: v for v in vips}["capped@example.com"]
    assert row["rate_limit"] == 7


def test_update_configures_vip_rate_limit(client):
    gql_data(client, ADD_VIP, {"e": "vip@example.com"})
    patched = gql_data(client, UPDATE_VIP, {"e": "vip@example.com", "rl": 42})["update_vip"]
    assert {v["email"]: v for v in patched}["vip@example.com"]["rate_limit"] == 42

    # null clears it back to unlimited.
    cleared = gql_data(client, UPDATE_VIP, {"e": "vip@example.com", "rl": None})["update_vip"]
    assert {v["email"]: v for v in cleared}["vip@example.com"]["rate_limit"] is None


def test_update_unknown_vip_errors(client):
    assert "not a VIP" in gql_error(client, UPDATE_VIP, {"e": "ghost@example.com", "rl": 5})


def test_add_vip_rejects_bad_email(client):
    assert "valid email" in gql_error(client, ADD_VIP, {"e": "not-an-email"})


def test_add_vip_rejects_bad_rate_limit(client):
    assert "positive" in gql_error(client, ADD_VIP, {"e": "x@example.com", "rl": -3})


def test_remove_unknown_vip_errors(client):
    assert "not a VIP" in gql_error(client, REMOVE_VIP, {"e": "ghost@example.com"})


def test_admin_api_forbidden_for_non_admin(client, configured, monkeypatch):
    _signed_in_as(monkeypatch, uid="u1", email="stranger@example.com")
    assert "Admin access required" in gql_error(client, VIPS, headers=_AUTH)


def test_admin_api_allowed_for_seeded_admin(client, configured, monkeypatch):
    monkeypatch.setenv("CLAZZZIKS_ADMIN_EMAIL", "boss@example.com")
    # First DB touch seeds boss@ as admin (group starts empty).
    assert db.is_admin("boss@example.com") is True
    _signed_in_as(monkeypatch, uid="a1", email="boss@example.com")
    vips = gql_data(client, VIPS, headers=_AUTH)["vips"]
    assert "boss@example.com" in [v["email"] for v in vips]


# --- admin user list -------------------------------------------------------

def _fake_users():
    return [
        auth.FirebaseUser(
            uid="a1", email="boss@example.com", name="Boss",
            email_verified=True, disabled=False,
            created_at="2026-01-01T00:00:00+00:00",
            last_sign_in="2026-06-01T00:00:00+00:00", provider="google.com",
        ),
        auth.FirebaseUser(
            uid="u2", email="capped@example.com", name="Capped User",
            email_verified=False, disabled=False,
            created_at=None, last_sign_in=None, provider="password",
        ),
    ]


def test_admin_users_merges_vip_state_and_usage(client, configured, monkeypatch):
    monkeypatch.setenv("CLAZZZIKS_ADMIN_EMAIL", "boss@example.com")
    assert db.is_admin("boss@example.com") is True  # seeds boss@ as VIP + admin
    db.add_vip("capped@example.com", rate_limit=5)
    db.log_download("u2", "capped@example.com", "https://x/1")
    db.log_download("u2", "capped@example.com", "https://x/2")

    # The seam the resolver actually calls is the name bound into schema.py.
    monkeypatch.setattr("clazzziks.schema.list_firebase_users", _fake_users)
    _signed_in_as(monkeypatch, uid="a1", email="boss@example.com")

    body = gql_data(client, USERS, headers=_AUTH)["users"]
    assert body["window_seconds"] == db.rate_window_seconds()
    assert body["auth_configured"] is True

    users = {u["email"]: u for u in body["users"]}
    boss = users["boss@example.com"]
    assert boss["is_admin"] is True and boss["is_vip"] is True
    assert boss["name"] == "Boss" and boss["provider"] == "google.com"

    capped = users["capped@example.com"]
    assert capped["is_vip"] is True and capped["is_admin"] is False
    assert capped["rate_limit"] == 5
    assert capped["used_this_window"] == 2

    # Admins sort first.
    assert body["users"][0]["email"] == "boss@example.com"


def test_admin_users_forbidden_for_non_admin(client, configured, monkeypatch):
    _signed_in_as(monkeypatch, uid="u1", email="stranger@example.com")
    assert "Admin access required" in gql_error(client, USERS, headers=_AUTH)


def test_admin_users_sync_persists_firebase_users(client, monkeypatch):
    # Open mode: the local caller is admin. Sync pulls Firebase -> Postgres.
    monkeypatch.setattr("clazzziks.schema.list_firebase_users", _fake_users)
    body = gql_data(client, SYNC_USERS)["sync_users"]
    assert body["last_synced_at"] is not None
    assert {"boss@example.com", "capped@example.com"} <= {u["email"] for u in body["users"]}

    # The mirror is persistent: a later read returns them from Postgres even when
    # Firebase now lists nobody, proving the dashboard no longer hits Firebase live.
    monkeypatch.setattr("clazzziks.schema.list_firebase_users", list)
    again = gql_data(client, USERS)["users"]
    assert {"boss@example.com", "capped@example.com"} <= {u["email"] for u in again["users"]}
