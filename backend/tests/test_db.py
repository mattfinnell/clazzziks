"""Unit tests for the SQLite store (``clazzziks.db``).

The ``isolated_db`` autouse fixture (conftest) points ``CLAZZZIKS_DB_PATH`` at a
fresh temp file per test, so these run with empty, isolated tables.
"""

# pylint: disable=missing-function-docstring

import pytest

from clazzziks import db


@pytest.fixture(autouse=True)
def known_admin(monkeypatch):
    # Pin the seeded admin so tests don't depend on the personal default.
    monkeypatch.setenv("CLAZZZIKS_ADMIN_EMAIL", "owner@example.com")


# --- track cache -----------------------------------------------------------

def test_cache_miss_then_hit(tmp_path):
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"x")

    assert db.get_cached_track("https://y/1", "mp3") is None

    db.cache_track("https://y/1", "mp3", path=str(audio), title="Song", source="youtube")
    hit = db.get_cached_track("https://y/1", "mp3")
    assert hit is not None
    assert hit.path == str(audio)
    assert hit.title == "Song"


def test_cache_is_keyed_by_format(tmp_path):
    audio = tmp_path / "song.flac"
    audio.write_bytes(b"x")
    db.cache_track("https://y/1", "flac", path=str(audio))
    assert db.get_cached_track("https://y/1", "flac") is not None
    # Different file type for the same source is a separate (missing) entry.
    assert db.get_cached_track("https://y/1", "mp3") is None


def test_cache_prunes_when_file_is_gone(tmp_path):
    audio = tmp_path / "gone.mp3"
    audio.write_bytes(b"x")
    db.cache_track("https://y/1", "mp3", path=str(audio))
    audio.unlink()
    # File deleted underneath us -> treated as a miss and the row is pruned.
    assert db.get_cached_track("https://y/1", "mp3") is None


# --- VIP group -------------------------------------------------------------

def test_owner_is_seeded_as_admin():
    assert db.is_admin("owner@example.com") is True
    assert db.is_vip("owner@example.com") is True


def test_add_remove_vip_is_case_insensitive():
    db.add_vip("Friend@Example.com", note="buddy")
    assert db.is_vip("friend@example.com") is True
    assert db.is_admin("friend@example.com") is False

    assert db.remove_vip("friend@example.com") is True
    assert db.is_vip("friend@example.com") is False
    assert db.remove_vip("friend@example.com") is False


def test_add_vip_can_grant_admin():
    db.add_vip("boss@example.com", is_admin=True)
    assert db.is_admin("boss@example.com") is True


def test_promoting_existing_vip_to_admin_is_preserved():
    db.add_vip("u@example.com")
    db.add_vip("u@example.com", is_admin=True)
    assert db.is_admin("u@example.com") is True
    # A later plain re-add must not silently demote an admin.
    db.add_vip("u@example.com", note="updated")
    assert db.is_admin("u@example.com") is True


def test_clearing_group_reseeds_owner():
    # Removing the only admin should never lock the owner out.
    db.remove_vip("owner@example.com")
    assert db.is_admin("owner@example.com") is True


def test_blank_email_is_never_vip():
    assert db.is_vip(None) is False
    assert db.is_admin("") is False


# --- per-user rate limit ---------------------------------------------------

def test_normal_user_gets_default_rate_limit(monkeypatch):
    monkeypatch.delenv("CLAZZZIKS_RATE_LIMIT", raising=False)
    # Default is 20 tracks/window for anyone not in the VIP group.
    assert db.effective_rate_limit("nobody@example.com") == 20


def test_default_rate_limit_is_env_overridable(monkeypatch):
    monkeypatch.setenv("CLAZZZIKS_RATE_LIMIT", "5")
    assert db.effective_rate_limit("nobody@example.com") == 5


def test_vip_is_unlimited_by_default():
    db.add_vip("vip@example.com")
    # None == unlimited; a VIP isn't capped unless an admin sets a number.
    assert db.effective_rate_limit("vip@example.com") is None


def test_vip_can_have_a_custom_rate_limit():
    db.add_vip("vip@example.com", rate_limit=100)
    assert db.effective_rate_limit("vip@example.com") == 100


def test_update_vip_changes_only_given_fields():
    db.add_vip("vip@example.com", note="orig", rate_limit=50)
    assert db.update_vip("vip@example.com", rate_limit=10) is True
    v = {x.email: x for x in db.list_vips()}["vip@example.com"]
    assert v.rate_limit == 10
    assert v.note == "orig"  # untouched

    # Explicitly clearing back to unlimited.
    db.update_vip("vip@example.com", rate_limit=None)
    assert db.effective_rate_limit("vip@example.com") is None


def test_update_vip_unknown_is_false():
    assert db.update_vip("ghost@example.com", rate_limit=5) is False


# --- rate-limit log --------------------------------------------------------

def test_count_recent_downloads_respects_window():
    db.log_download("u1", "u1@example.com", "https://y/1")
    db.log_download("u1", "u1@example.com", "https://y/2")
    db.log_download("u2", "u2@example.com", "https://y/3")

    assert db.count_recent_downloads("u1", 3600) == 2
    assert db.count_recent_downloads("u2", 3600) == 1
    assert db.count_recent_downloads("nobody", 3600) == 0
