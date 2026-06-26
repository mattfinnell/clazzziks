"""Firebase authentication for the CLAZZZIKS API.

Verifies Firebase ID tokens sent by the React frontend as
``Authorization: Bearer <token>`` and exposes a FastAPI dependency,
:func:`require_user`, that route handlers depend on to require a signed-in user.

Auth is **enforced only when Firebase is configured**. If no service-account
credential is available (the common case for local dev and the test suite),
``require_user`` lets requests through as an anonymous user and logs a warning,
so the app stays usable without secrets. In production, set the credential (and
optionally ``CLAZZZIKS_ALLOWED_EMAILS``) and every request to a protected route
must carry a valid token.

Configuration (environment variables):
    CLAZZZIKS_FIREBASE_CREDENTIALS  Path to a Firebase service-account JSON file.
    GOOGLE_APPLICATION_CREDENTIALS  Standard Google credential path (fallback).
    CLAZZZIKS_FIREBASE_PROJECT_ID   Project id (used with application-default creds).
    CLAZZZIKS_ALLOWED_EMAILS        Comma-separated allowlist. When set, only these
                                    emails may use protected routes; others get 403.
    CLAZZZIKS_AUTH_DISABLED         Set to 1/true to force auth off even if creds exist
                                    (used by tests).
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request

logger = logging.getLogger(__name__)

_TRUE = {"1", "true", "yes", "on"}

# Lazily-initialised firebase-admin app + a lock so concurrent first requests
# don't race to initialise it twice.
_init_lock = threading.Lock()
_firebase_app = None
_init_attempted = False


@dataclass(frozen=True)
class AuthUser:
    """The authenticated caller. ``anonymous`` is True in dev when auth is off."""

    uid: str
    email: str | None
    name: str | None = None
    anonymous: bool = False


@dataclass(frozen=True)
class FirebaseUser:
    """A Firebase Auth account as seen by the admin dashboard's user list."""

    uid: str
    email: str | None
    name: str | None
    email_verified: bool
    disabled: bool
    created_at: str | None  # ISO-8601 UTC, or None if Firebase didn't report it
    last_sign_in: str | None
    provider: str | None  # e.g. "google.com", "password"


def auth_disabled() -> bool:
    return os.environ.get("CLAZZZIKS_AUTH_DISABLED", "").lower() in _TRUE


def _credential_path() -> str | None:
    return (
        os.environ.get("CLAZZZIKS_FIREBASE_CREDENTIALS")
        or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        or None
    )


def auth_configured() -> bool:
    """True when a Firebase credential is available to verify tokens."""
    if auth_disabled():
        return False
    return _credential_path() is not None or bool(
        os.environ.get("CLAZZZIKS_FIREBASE_PROJECT_ID")
    )


def _allowed_emails() -> set[str]:
    raw = os.environ.get("CLAZZZIKS_ALLOWED_EMAILS", "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def _get_firebase_app():
    """Initialise (once) and return the firebase-admin app, or None if it can't."""
    global _firebase_app, _init_attempted
    if _firebase_app is not None or _init_attempted:
        return _firebase_app
    with _init_lock:
        if _firebase_app is not None or _init_attempted:
            return _firebase_app
        _init_attempted = True
        try:
            import firebase_admin
            from firebase_admin import credentials

            # Reuse an already-initialised default app if present.
            try:
                _firebase_app = firebase_admin.get_app()
                return _firebase_app
            except ValueError:
                pass

            cred_path = _credential_path()
            project_id = os.environ.get("CLAZZZIKS_FIREBASE_PROJECT_ID")
            if cred_path:
                cred = credentials.Certificate(cred_path)
            else:
                # Application-default credentials (e.g. on GCP) keyed by project.
                cred = credentials.ApplicationDefault()
            options = {"projectId": project_id} if project_id else None
            _firebase_app = firebase_admin.initialize_app(cred, options)
        except Exception as exc:  # noqa: BLE001 - misconfig shouldn't crash boot
            logger.error("firebase init failed: %s", exc)
            _firebase_app = None
    return _firebase_app


def verify_token(id_token: str) -> AuthUser:
    """Verify a Firebase ID token and return the user. Raises HTTPException 401."""
    app = _get_firebase_app()
    if app is None:
        # Configured but unusable — fail closed rather than letting callers in.
        raise HTTPException(status_code=503, detail="Auth backend unavailable.")
    from firebase_admin import auth as fb_auth

    try:
        decoded = fb_auth.verify_id_token(id_token, app=app)
    except Exception as exc:  # noqa: BLE001 - any verify failure is a 401
        logger.info("token verification failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid or expired token.") from exc

    return AuthUser(
        uid=decoded["uid"],
        email=decoded.get("email"),
        name=decoded.get("name"),
    )


def _ms_to_iso(ms: int | None) -> str | None:
    """Firebase reports timestamps as epoch milliseconds; render them as ISO UTC."""
    if not ms:
        return None
    from datetime import datetime, timezone

    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def list_users() -> list[FirebaseUser]:
    """Return every Firebase Auth account, or ``[]`` when Firebase isn't usable.

    Pages through the Admin SDK (1000 rows/page via ``iterate_all``) and maps each
    record to a :class:`FirebaseUser`. Any failure (no credential, transient error)
    is logged and returns ``[]`` so the admin dashboard degrades gracefully instead
    of 500-ing. This is the single seam the tests monkeypatch.
    """
    app = _get_firebase_app()
    if app is None:
        return []
    try:
        from firebase_admin import auth as fb_auth

        users: list[FirebaseUser] = []
        for u in fb_auth.list_users(app=app).iterate_all():
            meta = u.user_metadata
            provider = u.provider_data[0].provider_id if u.provider_data else None
            users.append(
                FirebaseUser(
                    uid=u.uid,
                    email=u.email,
                    name=u.display_name,
                    email_verified=bool(u.email_verified),
                    disabled=bool(u.disabled),
                    created_at=_ms_to_iso(getattr(meta, "creation_timestamp", None)),
                    last_sign_in=_ms_to_iso(getattr(meta, "last_sign_in_timestamp", None)),
                    provider=provider,
                )
            )
        return users
    except Exception as exc:  # noqa: BLE001 - never let a listing error crash the dashboard
        logger.error("firebase list_users failed: %s", exc)
        return []


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization") or request.headers.get("Authorization")
    if not header:
        return None
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


async def require_user(request: Request) -> AuthUser:
    """FastAPI dependency: resolve the signed-in user for a protected route.

    - Auth not configured (dev/tests): returns an anonymous user, logs a warning.
    - Configured: requires a valid bearer token (401 if missing/invalid) and, when
      ``CLAZZZIKS_ALLOWED_EMAILS`` is set, that the email is allowlisted (403).
    """
    if not auth_configured():
        logger.warning("auth not configured — allowing anonymous request to %s", request.url.path)
        return AuthUser(uid="anonymous", email=None, anonymous=True)

    token = _bearer_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token.")

    user = verify_token(token)

    allowed = _allowed_emails()
    if allowed and (user.email or "").lower() not in allowed:
        # Known identity, but not yet granted access to the tool.
        raise HTTPException(status_code=403, detail="Access pending approval.")

    return user


def resolve_optional_user(request: Request) -> AuthUser | None:
    """Best-effort, non-raising user resolution for middleware.

    - Auth not configured (dev): returns the anonymous user.
    - Configured with a valid token: returns the verified user.
    - Configured but token missing/invalid: returns ``None`` (let the route's
      ``require_user`` dependency produce the proper 401).
    """
    if not auth_configured():
        return AuthUser(uid="anonymous", email=None, anonymous=True)
    token = _bearer_token(request)
    if not token:
        return None
    try:
        return verify_token(token)
    except HTTPException:
        return None


async def require_admin(request: Request) -> AuthUser:
    """FastAPI dependency: restrict a route to admins (VIP rows with ``is_admin``).

    In open/dev mode (auth not configured) there's no identity to check, so the
    anonymous caller is allowed — consistent with the rest of the app staying
    open without secrets. When configured, the caller must be a DB admin (403).
    """
    user = await require_user(request)
    if not auth_configured():
        return user

    from . import db  # local import to avoid a module-load cycle

    if not db.is_admin(user.email):
        raise HTTPException(status_code=403, detail="Admin access required.")
    return user


# Re-export so handlers can write `user: AuthUser = Depends(require_user)`.
__all__ = [
    "AuthUser", "FirebaseUser", "require_user", "require_admin",
    "resolve_optional_user", "verify_token", "list_users", "auth_configured",
    "Depends",
]
