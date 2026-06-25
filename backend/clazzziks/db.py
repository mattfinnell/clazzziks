"""A small SQLite store for CLAZZZIKS.

Three tables, all backed by a single file (stdlib :mod:`sqlite3` — no server, no
extra dependency, matching the project's "stay secret-free in dev/tests" stance):

* ``track_cache``  — tracks already downloaded, keyed by ``(url, fmt)`` (the
  download source + file type), so a repeat request can re-serve the existing
  file instead of paying for a second fetch/transcode.
* ``vip``          — the VIP group: emails allowed to use the tool without
  rate-limiting, plus an ``is_admin`` flag for those who may manage the group.
* ``download_log`` — one row per served download, used to enforce a simple
  per-user rate limit (count rows inside a sliding window).

The database path comes from ``CLAZZZIKS_DB_PATH`` (default ``backend/clazzziks.db``)
and is read on every call so tests can point it at a temp file via ``monkeypatch``.
Each operation opens its own short-lived connection, which keeps the module
trivially safe to call from FastAPI's threadpool without a shared-connection lock.

On first use (an empty ``vip`` table) the admin from ``CLAZZZIKS_ADMIN_EMAIL``
(default ``mattfinnell104@gmail.com``) is seeded so the owner can never be locked
out of the dashboard.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

DEFAULT_DB_PATH = Path(__file__).with_name("clazzziks.db")
DEFAULT_ADMIN_EMAIL = "mattfinnell104@gmail.com"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS track_cache (
    url        TEXT NOT NULL,
    fmt        TEXT NOT NULL,
    path       TEXT NOT NULL,
    title      TEXT,
    source     TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (url, fmt)
);

CREATE TABLE IF NOT EXISTS vip (
    email    TEXT PRIMARY KEY,
    is_admin INTEGER NOT NULL DEFAULT 0,
    note     TEXT,
    added_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS download_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    uid        TEXT NOT NULL,
    email      TEXT,
    url        TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_download_log_uid ON download_log (uid, created_at);
"""


@dataclass(frozen=True)
class CachedTrack:
    url: str
    fmt: str
    path: str
    title: str | None
    source: str | None
    created_at: str


@dataclass(frozen=True)
class Vip:
    email: str
    is_admin: bool
    note: str | None
    added_at: str


def db_path() -> Path:
    """Resolve the SQLite file path (env-overridable, read on every call)."""
    return Path(os.environ.get("CLAZZZIKS_DB_PATH") or DEFAULT_DB_PATH)


def _admin_seed_email() -> str:
    return (os.environ.get("CLAZZZIKS_ADMIN_EMAIL") or DEFAULT_ADMIN_EMAIL).strip().lower()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    """Open a connection, ensure the schema + admin seed, and commit on exit."""
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_SCHEMA)
        _seed_admin(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _seed_admin(conn: sqlite3.Connection) -> None:
    """Bootstrap the owner as an admin whenever the VIP group is empty.

    Seeding on "empty" rather than "missing" means clearing the group can never
    lock the owner out of the admin dashboard.
    """
    empty = conn.execute("SELECT 1 FROM vip LIMIT 1").fetchone() is None
    if empty:
        conn.execute(
            "INSERT OR IGNORE INTO vip (email, is_admin, note, added_at) "
            "VALUES (?, 1, 'seeded owner', ?)",
            (_admin_seed_email(), _iso(_now())),
        )


def init_db() -> None:
    """Create the database file, tables, and admin seed if they don't exist yet."""
    with _connect():
        pass


# --- track cache -----------------------------------------------------------

def get_cached_track(url: str, fmt: str) -> CachedTrack | None:
    """Return a prior download for ``(url, fmt)`` if its file still exists.

    A stale row whose file has since been deleted is pruned and treated as a miss,
    so the caller falls back to a fresh download.
    """
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM track_cache WHERE url = ? AND fmt = ?", (url, fmt)
        ).fetchone()
        if row is None:
            return None
        if not Path(row["path"]).exists():
            conn.execute("DELETE FROM track_cache WHERE url = ? AND fmt = ?", (url, fmt))
            return None
        return CachedTrack(**dict(row))


def cache_track(
    url: str,
    fmt: str,
    *,
    path: str,
    title: str | None = None,
    source: str | None = None,
) -> None:
    """Remember a freshly downloaded track so the next request can skip the work."""
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO track_cache "
            "(url, fmt, path, title, source, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (url, fmt, path, title, source, _iso(_now())),
        )


# --- VIP group -------------------------------------------------------------

def add_vip(email: str, *, note: str | None = None, is_admin: bool = False) -> None:
    """Add (or update) a VIP. Promoting an existing member to admin is preserved."""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO vip (email, is_admin, note, added_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(email) DO UPDATE SET "
            "is_admin = max(is_admin, excluded.is_admin), note = excluded.note",
            (email.strip().lower(), int(is_admin), note, _iso(_now())),
        )


def remove_vip(email: str) -> bool:
    """Remove a VIP; return True if a row was actually deleted."""
    with _connect() as conn:
        cur = conn.execute("DELETE FROM vip WHERE email = ?", (email.strip().lower(),))
        return cur.rowcount > 0


def list_vips() -> list[Vip]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT email, is_admin, note, added_at FROM vip ORDER BY email"
        ).fetchall()
        return [
            Vip(email=r["email"], is_admin=bool(r["is_admin"]),
                note=r["note"], added_at=r["added_at"])
            for r in rows
        ]


def is_vip(email: str | None) -> bool:
    if not email:
        return False
    with _connect() as conn:
        return conn.execute(
            "SELECT 1 FROM vip WHERE email = ?", (email.strip().lower(),)
        ).fetchone() is not None


def is_admin(email: str | None) -> bool:
    if not email:
        return False
    with _connect() as conn:
        row = conn.execute(
            "SELECT is_admin FROM vip WHERE email = ?", (email.strip().lower(),)
        ).fetchone()
        return bool(row and row["is_admin"])


# --- rate-limit log --------------------------------------------------------

def log_download(uid: str, email: str | None, url: str) -> None:
    """Record one served download (drives the per-user rate limit)."""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO download_log (uid, email, url, created_at) VALUES (?, ?, ?, ?)",
            (uid, email, url, _iso(_now())),
        )


def count_recent_downloads(uid: str, window_seconds: int) -> int:
    """How many downloads ``uid`` has made within the last ``window_seconds``."""
    cutoff = _iso(_now() - timedelta(seconds=window_seconds))
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM download_log WHERE uid = ? AND created_at >= ?",
            (uid, cutoff),
        ).fetchone()
        return int(row["n"])
