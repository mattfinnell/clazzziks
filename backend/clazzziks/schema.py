"""The GraphQL schema for CLAZZZIKS — the single source of truth for the API.

Strawberry (code-first) defines every query and mutation the React frontend
(``frontend/src/api.ts``) consumes. The emitted SDL (``clazzziks/schema.graphql``,
whose drift is caught by ``tests/test_contract.py``) is the committed contract that
keeps both halves honest — the GraphQL replacement for a hand-authored REST schema.

Auth is enforced **per resolver** (there is a single ``/graphql`` endpoint, so
there are no per-route dependencies): the :class:`IsUser` / :class:`IsAdmin`
permission classes wrap the existing Firebase logic in :mod:`clazzziks.auth` and,
on success, stash the resolved :class:`~clazzziks.auth.AuthUser` on the request
context for the resolver to read.

A bulk download runs as a background **job**: :meth:`Mutation.download` validates
the input, starts a :class:`~clazzziks.jobs.DownloadJob`, and returns its
``job_id``; the client then watches :meth:`Subscription.progress` for per-track
events. Binary payloads can't travel over GraphQL/JSON, so the terminal event
carries a short-lived **token** and the actual MP3/ZIP bytes are streamed by the
companion ``GET /files/{token}`` route in :mod:`clazzziks.api`.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Annotated, AsyncGenerator, Optional, Union

import strawberry
from fastapi import HTTPException, Request, WebSocket
from strawberry.permission import BasePermission
from strawberry.schema.config import StrawberryConfig

from .formats import AudioFormat, DEFAULT_MP3_BITRATE, BUNDLE_FORMAT
from .inputs import collect_urls
from .logging_config import log_event
from .auth import (
    AuthUser, require_user, require_admin, auth_configured,
    list_users as list_firebase_users,
)
from . import db, jobs

logger = logging.getLogger(__name__)

_TRACKS_DIR = Path(__file__).parents[2] / "tracks"


class RateLimitError(Exception):
    """Raised by the download mutation when the caller is over quota."""


# --- rate limiting ---------------------------------------------------------

def _over_rate_limit(user: AuthUser) -> tuple[bool, int, int]:
    """Whether ``user`` has hit their per-window quota.

    Returns ``(over, limit, window_seconds)``. A ``None`` effective limit
    (unlimited — VIPs by default) is never over. Open/dev mode is unlimited.
    """
    window = db.rate_window_seconds()
    if not auth_configured() or user.anonymous:
        return False, 0, window
    limit = db.effective_rate_limit(user.email)
    if limit is None:
        return False, 0, window
    used = db.count_recent_downloads(user.uid, window)
    return used >= limit, limit, window


# --- GraphQL types ---------------------------------------------------------
# auto_camel_case is disabled below, so these snake_case fields are exposed
# verbatim and match the shapes the React client already builds against.

@strawberry.type
class Config:
    formats: list[str]
    default_format: str
    bundle_format: str


@strawberry.type
class Me:
    email: Optional[str]
    is_vip: bool
    is_admin: bool
    anonymous: bool
    rate_limit: Optional[int]


@strawberry.type
class Vip:
    email: str
    is_admin: bool
    note: Optional[str]
    rate_limit: Optional[int]  # None == unlimited
    added_at: str  # ISO-8601


@strawberry.type
class User:
    email: Optional[str]
    name: Optional[str]
    email_verified: bool
    disabled: bool
    created_at: Optional[str]
    last_sign_in: Optional[str]
    provider: Optional[str]
    is_vip: bool
    is_admin: bool
    rate_limit: Optional[int]
    used_this_window: int


@strawberry.type
class UserList:
    users: list[User]
    window_seconds: int
    auth_configured: bool
    last_synced_at: Optional[str]


@strawberry.type
class DownloadStart:
    # Returned by the `download` mutation; feed job_id to the `progress` subscription.
    job_id: str
    count: int


@strawberry.type
class TrackProgress:
    """One track's live state within a running job."""
    url: str
    title: Optional[str]
    index: int
    total: int
    state: str  # queued | downloading | transcoding | done | failed
    pct: Optional[float]
    error: Optional[str]
    warnings: list[str]


@strawberry.type
class DownloadComplete:
    """Terminal progress event. `token` feeds GET /files/{token}; None if the job
    produced nothing downloadable."""
    token: Optional[str]
    filename: Optional[str]
    warnings: list[str]
    failures: list[str]


ProgressEvent = Annotated[
    Union[TrackProgress, DownloadComplete], strawberry.union("ProgressEvent")
]


def _to_gql_event(event: jobs.Event) -> ProgressEvent:
    if isinstance(event, jobs.TrackEvent):
        return TrackProgress(
            url=event.url, title=event.title, index=event.index, total=event.total,
            state=event.state, pct=event.pct, error=event.error, warnings=list(event.warnings),
        )
    return DownloadComplete(
        token=event.token, filename=event.filename,
        warnings=list(event.warnings), failures=list(event.failures),
    )


# --- mappers ---------------------------------------------------------------

def _vip_type(v: db.Vip) -> Vip:
    return Vip(
        email=v.email, is_admin=v.is_admin, note=v.note,
        rate_limit=v.rate_limit, added_at=v.added_at.isoformat(),
    )


def _user_type(u: db.SyncedUser, vip: db.Vip | None, used: int) -> User:
    return User(
        email=u.email, name=u.name, email_verified=u.email_verified,
        disabled=u.disabled, created_at=u.created_at, last_sign_in=u.last_sign_in,
        provider=u.provider, is_vip=vip is not None,
        is_admin=bool(vip and vip.is_admin),
        rate_limit=vip.rate_limit if vip else None, used_this_window=used,
    )


def _sync_users_from_firebase() -> int:
    """Fetch all Firebase accounts and upsert them into the Postgres mirror."""
    return db.sync_users(list_firebase_users())


def _users_payload() -> UserList:
    """The admin users view: the Postgres mirror joined with VIP state + usage."""
    window = db.rate_window_seconds()
    vips = {v.email.lower(): v for v in db.list_vips()}
    usage = db.recent_download_counts(window)
    users = [
        _user_type(u, vips.get((u.email or "").lower()), usage.get(u.uid, 0))
        for u in db.list_synced_users()
    ]
    # Admins first, then VIPs, then everyone else by email.
    users.sort(key=lambda u: (not u.is_admin, not u.is_vip, (u.email or "").lower()))
    last_synced = db.last_synced_at()
    return UserList(
        users=users,
        window_seconds=window,
        auth_configured=auth_configured(),
        last_synced_at=last_synced.isoformat() if last_synced else None,
    )


def _parse_rate_limit(value: int | None) -> int | None:
    """Validate a rate-limit input. ``None`` means unlimited; raises on ``<= 0``."""
    if value is None:
        return None
    if value <= 0:
        raise ValueError("rate_limit must be a positive integer or null (unlimited).")
    return value


# --- permissions -----------------------------------------------------------

class IsUser(BasePermission):
    """Require a signed-in user (or the anonymous caller in open/dev mode).

    Reuses :func:`clazzziks.auth.require_user`; on success it stashes the resolved
    user on the request context so resolvers can read ``info.context["user"]``.
    On failure it borrows the underlying HTTP detail as the GraphQL error message.
    """
    message = "Authentication required."

    async def has_permission(self, source, info, **kwargs) -> bool:
        request: Request = info.context["request"]
        try:
            info.context["user"] = await require_user(request)
        except HTTPException as exc:
            self.message = exc.detail
            return False
        return True


class IsAdmin(BasePermission):
    message = "Admin access required."

    async def has_permission(self, source, info, **kwargs) -> bool:
        request: Request = info.context["request"]
        try:
            info.context["user"] = await require_admin(request)
        except HTTPException as exc:
            self.message = exc.detail
            return False
        return True


# --- root query / mutation -------------------------------------------------

@strawberry.type
class Query:
    @strawberry.field
    def config(self) -> Config:
        # Users no longer pick a format/bitrate — everything is 320kbps MP3. This
        # stays so the frontend can probe availability and discover the format.
        return Config(
            formats=[AudioFormat.MP3.value],
            default_format=AudioFormat.MP3.value,
            bundle_format=BUNDLE_FORMAT.value,
        )

    @strawberry.field(permission_classes=[IsUser])
    def me(self, info: strawberry.Info) -> Me:
        user: AuthUser = info.context["user"]
        # Open/dev mode has no identity — treat the anonymous caller as local admin.
        if user.anonymous:
            return Me(email=None, is_vip=True, is_admin=True, anonymous=True, rate_limit=None)
        return Me(
            email=user.email,
            is_vip=db.is_vip(user.email),
            is_admin=db.is_admin(user.email),
            anonymous=False,
            rate_limit=db.effective_rate_limit(user.email),
        )

    @strawberry.field(permission_classes=[IsAdmin])
    def vips(self) -> list[Vip]:
        return [_vip_type(v) for v in db.list_vips()]

    @strawberry.field(permission_classes=[IsAdmin])
    def users(self) -> UserList:
        # Bootstrap one sync if the mirror is empty so a fresh deploy isn't blank.
        if auth_configured() and db.synced_user_count() == 0:
            _sync_users_from_firebase()
        return _users_payload()


@strawberry.type
class Mutation:
    @strawberry.mutation(permission_classes=[IsAdmin])
    def add_vip(
        self,
        email: str,
        note: Optional[str] = None,
        is_admin: bool = False,
        rate_limit: Optional[int] = None,
    ) -> list[Vip]:
        email = (email or "").strip()
        if "@" not in email:
            raise ValueError("A valid email is required.")
        db.add_vip(email, note=note, is_admin=is_admin, rate_limit=_parse_rate_limit(rate_limit))
        return [_vip_type(v) for v in db.list_vips()]

    @strawberry.mutation(permission_classes=[IsAdmin])
    def update_vip(
        self,
        email: str,
        note: Optional[str] = strawberry.UNSET,
        is_admin: Optional[bool] = strawberry.UNSET,
        rate_limit: Optional[int] = strawberry.UNSET,
    ) -> list[Vip]:
        changes: dict = {}
        if note is not strawberry.UNSET:
            changes["note"] = note
        if is_admin is not strawberry.UNSET:
            changes["is_admin"] = bool(is_admin)
        if rate_limit is not strawberry.UNSET:
            changes["rate_limit"] = _parse_rate_limit(rate_limit)
        if not db.update_vip(email, **changes):
            raise ValueError(f"{email} is not a VIP.")
        return [_vip_type(v) for v in db.list_vips()]

    @strawberry.mutation(permission_classes=[IsAdmin])
    def remove_vip(self, email: str) -> list[Vip]:
        if not db.remove_vip(email):
            raise ValueError(f"{email} is not a VIP.")
        return [_vip_type(v) for v in db.list_vips()]

    @strawberry.mutation(permission_classes=[IsAdmin])
    def sync_users(self) -> UserList:
        synced = _sync_users_from_firebase()
        log_event(logger, logging.INFO, "users.sync", synced=synced)
        return _users_payload()

    @strawberry.mutation(permission_classes=[IsUser])
    async def download(self, info: strawberry.Info, links: str) -> DownloadStart:
        """Validate input, start a background download job, return its id.

        Per-track progress and the final ``/files`` token stream from the
        ``progress(job_id)`` subscription — this only kicks the job off.
        """
        request: Request = info.context["request"]
        user: AuthUser = info.context["user"]

        raw_input = (links or "").strip()
        if not raw_input:
            raise ValueError("No link(s) provided.")

        # Enforce the quota before any work begins (VIPs / open mode are unlimited).
        over, limit, window = _over_rate_limit(user)
        if over:
            minutes = max(window // 60, 1)
            log_event(
                logger, logging.WARNING, "rate_limit.blocked",
                uid=user.uid, limit=limit, window_seconds=window,
            )
            raise RateLimitError(
                f"Rate limit reached ({limit} tracks per {minutes} min). "
                "Ask an admin for VIP access."
            )

        # Input expansion (spreadsheet fetch, ytsearch) can do network I/O, so run
        # it off the event loop. ValueError surfaces as a GraphQL error.
        loop = asyncio.get_running_loop()
        urls = await loop.run_in_executor(None, collect_urls, raw_input)
        if not urls:
            raise ValueError("No valid links found in the input.")

        request_id = getattr(request.state, "request_id", None)
        outdir = _TRACKS_DIR / (request_id or uuid.uuid4().hex[:8])
        job = jobs.broker.create(
            urls, uid=user.uid, email=user.email, outdir=outdir, loop=loop,
        )
        job.start()
        log_event(
            logger, logging.INFO, "download.request",
            request_id=request_id, job_id=job.id, links=len(urls),
            uid=user.uid, vip=db.is_vip(user.email),
        )
        return DownloadStart(job_id=job.id, count=len(urls))


@strawberry.type
class Subscription:
    @strawberry.subscription
    async def progress(self, job_id: str) -> AsyncGenerator[ProgressEvent, None]:
        """Stream a download job's per-track progress, ending with the terminal
        DownloadComplete event.

        Ungated by design: a ``job_id`` is an unguessable handle only an authorized
        caller (who passed the ``download`` mutation's IsUser check) can obtain.
        An unknown id yields an empty stream.
        """
        job = jobs.broker.get(job_id)
        if job is None:
            return
        async for event in job.subscribe():
            yield _to_gql_event(event)


async def get_context(request: Request = None, websocket: WebSocket = None) -> dict:
    """GraphQL context: carries the connection (HTTP Request for queries/mutations,
    WebSocket for subscriptions) so permissions can read auth headers and stash the
    resolved user for resolvers. Request/WebSocket are special-injected by FastAPI,
    whichever the transport provides."""
    return {"request": request or websocket}


schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    subscription=Subscription,
    # Keep field names snake_case so the emitted shapes match what the React
    # client already builds against (Me.is_vip, Vip.rate_limit, ...).
    config=StrawberryConfig(auto_camel_case=False),
)
