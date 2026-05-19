"""Supabase JWT authentication for the geopo API.

Supabase issues HS256-signed JWTs after a successful Google OAuth handshake.
This module verifies those tokens server-side and exposes a FastAPI
dependency, :func:`require_user`, that every protected endpoint can declare.

Design notes
------------
* **Dev fallback.** When :pyattr:`Settings.supabase_jwt_secret` is empty the
  verifier is disabled and every request is treated as the local ``dev``
  user. This keeps ``./start.sh`` working on a fresh checkout without any
  Supabase setup. The startup log line makes the mode obvious.
* **Allowlist.** :pyattr:`Settings.allowed_emails` is a comma-separated list.
  If non-empty, the email on the validated JWT must match (case-insensitive)
  or the request is rejected with 403. Empty allowlist → anyone with a
  valid Supabase JWT is admitted (only safe for private projects).
* **No DB lookup.** We trust Supabase as the identity source of truth and
  do not persist a users table — fewer moving parts, less to migrate.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config import get_settings

logger = logging.getLogger(__name__)

# ``auto_error=False`` so we can produce our own 401 with a useful body
# instead of FastAPI's terse default when no Authorization header is sent.
_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthUser:
    """Authenticated principal extracted from a verified Supabase JWT.

    Attributes:
        sub: Supabase user id (UUID string).
        email: User email (lowercased).
        is_dev: ``True`` when auth is disabled and we returned the synthetic
            dev user — useful for endpoints that want to flag dev mode in
            telemetry / logs.
    """

    sub: str
    email: str
    is_dev: bool = False


@lru_cache(maxsize=1)
def _allowed_emails() -> frozenset[str]:
    raw = get_settings().allowed_emails or ""
    return frozenset(
        e.strip().lower() for e in raw.split(",") if e.strip()
    )


def _auth_enabled() -> bool:
    return bool(get_settings().supabase_jwt_secret)


def _decode(token: str) -> dict:
    """Verify and decode a Supabase HS256 JWT.

    Raises:
        HTTPException: 401 with the underlying error reason for invalid,
            expired, or wrong-audience tokens.
    """
    try:
        return jwt.decode(
            token,
            get_settings().supabase_jwt_secret,
            algorithms=["HS256"],
            # All user-facing Supabase JWTs carry ``aud=authenticated``.
            audience="authenticated",
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired — please sign in again.",
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid auth token: {exc}",
        ) from exc


async def require_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthUser:
    """FastAPI dependency: return the authenticated user or raise 401/403.

    Behavior matrix:
        * Auth disabled (no JWT secret configured) → synthetic dev user.
        * Auth enabled + no Authorization header → 401.
        * Auth enabled + valid JWT + email not on allowlist → 403.
        * Auth enabled + valid JWT + allowlist OK (or empty) → AuthUser.
    """
    if not _auth_enabled():
        # Dev mode: stamp it on the request so downstream middleware can
        # surface it in logs if useful.
        request.state.auth_dev_mode = True
        return AuthUser(sub="dev", email="dev@local", is_dev=True)

    if creds is None or creds.scheme.lower() != "bearer" or not creds.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = _decode(creds.credentials)
    email = (payload.get("email") or "").lower()
    sub = payload["sub"]

    allow = _allowed_emails()
    if allow and email not in allow:
        # 403 (not 401) — token is valid, user is just not authorized.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not authorized for this app.",
        )

    return AuthUser(sub=sub, email=email)


def log_auth_mode() -> None:
    """Log a single startup banner so the auth posture is unambiguous."""
    if _auth_enabled():
        n = len(_allowed_emails())
        if n:
            logger.info("Auth: Supabase JWT verification ENABLED — %d allowed email(s)", n)
        else:
            logger.warning(
                "Auth: Supabase JWT verification ENABLED but ALLOWED_EMAILS is empty — "
                "any valid Supabase user can access this API."
            )
    else:
        logger.warning(
            "Auth: DISABLED (SUPABASE_JWT_SECRET unset) — every request is treated as dev user. "
            "Do NOT expose this deployment to the internet."
        )
