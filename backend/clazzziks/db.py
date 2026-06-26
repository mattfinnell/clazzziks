"""The CLAZZZIKS data layer — SQLAlchemy ORM over Postgres.

Three tables:

* ``track_cache``  — tracks already downloaded, keyed by ``(url, fmt)`` (download
  source + file type), so a repeat request re-serves the existing file instead of
  paying for a second fetch/transcode.
* ``vip``          — the VIP group: rate-limit-exempt users, an ``is_admin`` flag
  for those who may manage the group, and an optional per-VIP ``rate_limit``
  (``NULL`` = unlimited; the default for a VIP).
* ``download_log`` — one row per served download, used to enforce the per-user
  rate limit (count rows inside a sliding window).

Connection comes from ``CLAZZZIKS_DATABASE_URL`` (default points at the local
docker-compose Postgres). The engine is built lazily and cached per-URL, so the
test suite can point it at a separate database via the environment. Public
functions return small frozen dataclasses (not ORM rows) so callers never deal
with sessions or detached-instance surprises.

On first use of a database (an empty ``vip`` table) the owner from
``CLAZZZIKS_ADMIN_EMAIL`` is seeded as an admin, so the owner can never be locked
out of the dashboard. There is no built-in default — when the variable is unset
no owner is seeded (dev/open mode treats the local caller as admin anyway).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    String,
    Text,
    create_engine,
    func,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

DEFAULT_DATABASE_URL = "postgresql+psycopg://clazzziks:clazzziks@localhost:5432/clazzziks"
DEFAULT_ADMIN_EMAIL = ""  # no personal default — configure via CLAZZZIKS_ADMIN_EMAIL
DEFAULT_RATE_LIMIT = 20  # tracks per window for a normal (non-VIP) user
DEFAULT_RATE_WINDOW_SECONDS = 3600  # one hour

# Sentinel so partial updates can tell "leave unchanged" from "set to NULL".
_UNSET = object()


class Base(DeclarativeBase):
    pass


class TrackCacheRow(Base):
    __tablename__ = "track_cache"

    url: Mapped[str] = mapped_column(Text, primary_key=True)
    fmt: Mapped[str] = mapped_column(String(16), primary_key=True)
    path: Mapped[str] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class VipRow(Base):
    __tablename__ = "vip"

    email: Mapped[str] = mapped_column(String(320), primary_key=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # NULL -> unlimited (the default for a VIP); an integer caps tracks/window.
    rate_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DownloadLogRow(Base):
    __tablename__ = "download_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uid: Mapped[str] = mapped_column(String(128), index=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    url: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class UserRow(Base):
    """A Firebase Auth account mirrored into Postgres by the admin user sync.

    Keyed by Firebase ``uid``. Identity fields are a local snapshot refreshed by
    :func:`sync_users`; the VIP/throttle policy lives in :class:`VipRow` and is
    joined by email at read time, so this table stays a pure identity mirror.
    """

    __tablename__ = "users"

    uid: Mapped[str] = mapped_column(String(128), primary_key=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    name: Mapped[str | None] = mapped_column(String(320), nullable=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_sign_in: Mapped[str | None] = mapped_column(String(40), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


@dataclass(frozen=True)
class CachedTrack:
    url: str
    fmt: str
    path: str
    title: str | None
    source: str | None
    created_at: datetime


@dataclass(frozen=True)
class Vip:
    email: str
    is_admin: bool
    note: str | None
    rate_limit: int | None  # None == unlimited
    added_at: datetime


@dataclass(frozen=True)
class SyncedUser:
    """A Firebase account as mirrored in Postgres (identity only, no VIP policy)."""

    uid: str
    email: str | None
    name: str | None
    email_verified: bool
    disabled: bool
    created_at: str | None
    last_sign_in: str | None
    provider: str | None
    synced_at: datetime


# --- engine / session ------------------------------------------------------

_engines: dict[str, Engine] = {}


def database_url() -> str:
    return os.environ.get("CLAZZZIKS_DATABASE_URL") or DEFAULT_DATABASE_URL


def _engine() -> Engine:
    """Return a cached engine for the current URL, creating schema + seed once."""
    url = database_url()
    engine = _engines.get(url)
    if engine is None:
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        engine = create_engine(url, future=True, pool_pre_ping=True, connect_args=connect_args)
        Base.metadata.create_all(engine)
        _engines[url] = engine
        _seed_admin(engine)
    return engine


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _seed_admin(engine: Engine) -> None:
    """Ensure the owner (``CLAZZZIKS_ADMIN_EMAIL``) is always a VIP **and** admin.

    Runs on every startup/deploy and is idempotent: the owner is upserted into the
    VIP group with ``is_admin=True`` so they are both VIP (a row exists) and admin,
    and can never be locked out — even on a database that already has other VIPs.
    An existing owner row keeps its configured ``rate_limit`` (unlimited by default)
    and is only promoted to admin if needed. No-op when no admin email is set.
    """
    email = _admin_seed_email()
    if not email:
        return
    with Session(engine) as s:
        row = s.get(VipRow, email)
        if row is None:
            s.add(VipRow(
                email=email, is_admin=True,
                note="seeded owner", rate_limit=None, added_at=_now(),
            ))
            s.commit()
        elif not row.is_admin:
            row.is_admin = True
            s.commit()


def _admin_seed_email() -> str:
    return (os.environ.get("CLAZZZIKS_ADMIN_EMAIL") or DEFAULT_ADMIN_EMAIL).strip().lower()


def init_db() -> None:
    """Create the schema (and admin seed) for the configured database."""
    _engine()


def default_rate_limit() -> int:
    try:
        return int(os.environ.get("CLAZZZIKS_RATE_LIMIT", str(DEFAULT_RATE_LIMIT)))
    except ValueError:
        return DEFAULT_RATE_LIMIT


def rate_window_seconds() -> int:
    try:
        return int(os.environ.get("CLAZZZIKS_RATE_WINDOW_SECONDS", str(DEFAULT_RATE_WINDOW_SECONDS)))
    except ValueError:
        return DEFAULT_RATE_WINDOW_SECONDS


# --- track cache -----------------------------------------------------------

def get_cached_track(url: str, fmt: str) -> CachedTrack | None:
    """Return a prior download for ``(url, fmt)`` if its file still exists.

    A stale row whose file has since been deleted is pruned and treated as a miss.
    """
    with Session(_engine()) as s:
        row = s.get(TrackCacheRow, (url, fmt))
        if row is None:
            return None
        if not Path(row.path).exists():
            s.delete(row)
            s.commit()
            return None
        return CachedTrack(
            url=row.url, fmt=row.fmt, path=row.path,
            title=row.title, source=row.source, created_at=row.created_at,
        )


def cache_track(
    url: str,
    fmt: str,
    *,
    path: str,
    title: str | None = None,
    source: str | None = None,
) -> None:
    with Session(_engine()) as s:
        row = s.get(TrackCacheRow, (url, fmt))
        if row is None:
            s.add(TrackCacheRow(
                url=url, fmt=fmt, path=path, title=title,
                source=source, created_at=_now(),
            ))
        else:
            row.path, row.title, row.source, row.created_at = path, title, source, _now()
        s.commit()


# --- VIP group -------------------------------------------------------------

def add_vip(
    email: str,
    *,
    note: str | None = None,
    is_admin: bool = False,
    rate_limit: int | None = None,
) -> None:
    """Add or update a VIP. An existing admin is never silently demoted."""
    email = email.strip().lower()
    with Session(_engine()) as s:
        row = s.get(VipRow, email)
        if row is None:
            s.add(VipRow(
                email=email, is_admin=is_admin, note=note,
                rate_limit=rate_limit, added_at=_now(),
            ))
        else:
            row.is_admin = row.is_admin or is_admin
            row.note = note
            row.rate_limit = rate_limit
        s.commit()


def update_vip(
    email: str,
    *,
    note=_UNSET,
    is_admin=_UNSET,
    rate_limit=_UNSET,
) -> bool:
    """Apply a partial update to a VIP. Returns False if no such VIP.

    Only fields explicitly passed are changed, so ``rate_limit=None`` means
    "set to unlimited" while omitting it leaves the current value untouched.
    """
    with Session(_engine()) as s:
        row = s.get(VipRow, email.strip().lower())
        if row is None:
            return False
        if note is not _UNSET:
            row.note = note
        if is_admin is not _UNSET:
            row.is_admin = bool(is_admin)
        if rate_limit is not _UNSET:
            row.rate_limit = rate_limit
        s.commit()
        return True


def remove_vip(email: str) -> bool:
    with Session(_engine()) as s:
        row = s.get(VipRow, email.strip().lower())
        if row is None:
            return False
        s.delete(row)
        s.flush()
        # Anti-lockout: never let the group go fully empty — re-seed the owner
        # (only when an admin email is configured; otherwise allow empty).
        seed = _admin_seed_email()
        if seed and s.scalar(select(func.count()).select_from(VipRow)) == 0:
            s.add(VipRow(
                email=seed, is_admin=True,
                note="seeded owner", rate_limit=None, added_at=_now(),
            ))
        s.commit()
        return True


def list_vips() -> list[Vip]:
    with Session(_engine()) as s:
        rows = s.scalars(select(VipRow).order_by(VipRow.email)).all()
        return [
            Vip(email=r.email, is_admin=r.is_admin, note=r.note,
                rate_limit=r.rate_limit, added_at=r.added_at)
            for r in rows
        ]


def _get_vip(email: str | None) -> VipRow | None:
    if not email:
        return None
    with Session(_engine()) as s:
        return s.get(VipRow, email.strip().lower())


def is_vip(email: str | None) -> bool:
    return _get_vip(email) is not None


def is_admin(email: str | None) -> bool:
    row = _get_vip(email)
    return bool(row and row.is_admin)


def effective_rate_limit(email: str | None) -> int | None:
    """The caller's tracks-per-window cap. ``None`` means unlimited.

    Normal users get :func:`default_rate_limit` (20). A VIP gets their configured
    ``rate_limit``, which is ``None`` (unlimited) unless an admin set a number.
    """
    row = _get_vip(email)
    if row is not None:
        return row.rate_limit
    return default_rate_limit()


# --- rate-limit log --------------------------------------------------------

def log_download(uid: str, email: str | None, url: str) -> None:
    with Session(_engine()) as s:
        s.add(DownloadLogRow(uid=uid, email=email, url=url, created_at=_now()))
        s.commit()


def count_recent_downloads(uid: str, window_seconds: int) -> int:
    cutoff = _now() - timedelta(seconds=window_seconds)
    with Session(_engine()) as s:
        return int(
            s.scalar(
                select(func.count())
                .select_from(DownloadLogRow)
                .where(DownloadLogRow.uid == uid, DownloadLogRow.created_at >= cutoff)
            )
            or 0
        )


def recent_download_counts(window_seconds: int) -> dict[str, int]:
    """Downloads per ``uid`` within the window, as ``{uid: count}``.

    One grouped query so the admin dashboard can show every user's current usage
    without an N-query fan-out. Users with no recent downloads are simply absent.
    """
    cutoff = _now() - timedelta(seconds=window_seconds)
    with Session(_engine()) as s:
        rows = s.execute(
            select(DownloadLogRow.uid, func.count())
            .where(DownloadLogRow.created_at >= cutoff)
            .group_by(DownloadLogRow.uid)
        ).all()
    return {uid: int(count) for uid, count in rows}


# --- user mirror (Firebase -> Postgres sync) -------------------------------

def _to_synced_user(row: UserRow) -> SyncedUser:
    return SyncedUser(
        uid=row.uid, email=row.email, name=row.name,
        email_verified=row.email_verified, disabled=row.disabled,
        created_at=row.created_at, last_sign_in=row.last_sign_in,
        provider=row.provider, synced_at=row.synced_at,
    )


def sync_users(users) -> int:
    """Upsert a batch of Firebase accounts into the local mirror; returns the count.

    ``users`` is any iterable of objects carrying the identity attributes (the
    ``auth.FirebaseUser`` shape). Each is matched by ``uid`` and fully overwritten
    with the latest snapshot, stamping ``synced_at``. Upsert-only — accounts that
    have disappeared from Firebase are left in place rather than risking deletion
    on a partial listing.
    """
    now = _now()
    count = 0
    with Session(_engine()) as s:
        for u in users:
            row = s.get(UserRow, u.uid)
            if row is None:
                row = UserRow(uid=u.uid)
                s.add(row)
            row.email = u.email
            row.name = u.name
            row.email_verified = bool(u.email_verified)
            row.disabled = bool(u.disabled)
            row.created_at = u.created_at
            row.last_sign_in = u.last_sign_in
            row.provider = u.provider
            row.synced_at = now
            count += 1
        s.commit()
    return count


def list_synced_users() -> list[SyncedUser]:
    with Session(_engine()) as s:
        rows = s.scalars(select(UserRow)).all()
    return [_to_synced_user(r) for r in rows]


def synced_user_count() -> int:
    with Session(_engine()) as s:
        return int(s.scalar(select(func.count()).select_from(UserRow)) or 0)


def last_synced_at() -> datetime | None:
    """Timestamp of the most recent user sync, or ``None`` if never synced."""
    with Session(_engine()) as s:
        return s.scalar(select(func.max(UserRow.synced_at)))
