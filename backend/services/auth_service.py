"""Supabase JWT authentication for the geopo API.

Supabase issues JWTs after a successful Google OAuth handshake. New
projects (post the *JWT Signing Keys* rollout) sign with **ES256** by
default and publish the public key at
``${SUPABASE_URL}/auth/v1/.well-known/jwks.json``. Older projects still
use **HS256** with a shared secret. This module supports both:

* If ``SUPABASE_URL`` is set we use :class:`PyJWKClient` against the
  JWKS endpoint — that covers ES256 / RS256 / HS256 alike and adapts
  automatically if Supabase rotates its keys.
* Otherwise we fall back to verifying HS256 with
  ``SUPABASE_JWT_SECRET``.

Design notes
------------
* **Dev fallback.** When *both* ``SUPABASE_URL`` and ``SUPABASE_JWT_SECRET``
  are empty the verifier is disabled and every request is treated as the
  local ``dev`` user. This keeps ``./start.sh`` working on a fresh checkout
  without any Supabase setup. The startup log line makes the mode obvious.
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
from jwt import PyJWKClient, PyJWKClientError

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
    s = get_settings()
    return bool(s.supabase_url or s.supabase_jwt_secret)


# All Supabase user-facing tokens carry ``aud=authenticated``.
_AUDIENCE = "authenticated"
# Algorithms we accept. Listing all three lets a single deployment serve
# both legacy HS256 projects and modern ES256/RS256 projects without
# config changes.
_ALGORITHMS = ["ES256", "RS256", "HS256"]


@lru_cache(maxsize=1)
def _jwks_client() -> PyJWKClient | None:
    """Return a cached :class:`PyJWKClient` pointed at Supabase's JWKS.

    Returns ``None`` when no ``SUPABASE_URL`` is configured — in that
    case the verifier falls back to HS256 with the static secret.
    PyJWT's client maintains its own ~5-minute in-memory key cache, so
    we only hit Supabase on cold start and when keys rotate.
    """
    base = (get_settings().supabase_url or "").strip().rstrip("/")
    if not base:
        return None
    jwks_url = f"{base}/auth/v1/.well-known/jwks.json"
    logger.info("JWT verifier: using JWKS at %s", jwks_url)
    return PyJWKClient(jwks_url, cache_keys=True, lifespan=300)


def _decode(token: str) -> dict:
    """Verify and decode a Supabase JWT.

    Strategy:
        * If a JWKS client is configured (``SUPABASE_URL`` set), look up
          the signing key by the token's ``kid`` and verify against the
          algorithm in the token header. This handles ES256/RS256 from
          new Supabase projects and HS256 from legacy ones (provided
          Supabase exposes it on JWKS).
        * Otherwise fall back to HS256 with the static
          ``SUPABASE_JWT_SECRET``.

    Raises:
        HTTPException: 401 with the underlying error reason for invalid,
            expired, or wrong-audience tokens. The reason is also logged
            server-side so Railway logs surface the root cause without
            the operator having to read response bodies in devtools.
    """
    try:
        client = _jwks_client()
        if client is not None:
            signing_key = client.get_signing_key_from_jwt(token).key
            return jwt.decode(
                token,
                signing_key,
                algorithms=_ALGORITHMS,
                audience=_AUDIENCE,
                options={"require": ["exp", "sub"]},
            )
        return jwt.decode(
            token,
            get_settings().supabase_jwt_secret,
            algorithms=["HS256"],
            audience=_AUDIENCE,
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        logger.warning("JWT rejected: expired (%s)", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired — please sign in again.",
        ) from exc
    except (jwt.InvalidTokenError, PyJWKClientError) as exc:
        # ``PyJWKClientError`` is what gets raised when the JWKS fetch
        # itself fails (network blip, missing ``kid``, unreachable JWKS
        # endpoint) — it does NOT inherit from ``InvalidTokenError`` so
        # we must catch it explicitly. Without this branch the exception
        # propagates as a 500, exactly the bug we hit on first deploy.
        hint = ""
        try:
            header = jwt.get_unverified_header(token)
            claims = jwt.decode(token, options={"verify_signature": False})
            hint = (
                f" | token alg={header.get('alg')} kid={header.get('kid')} "
                f"aud={claims.get('aud')} iss={claims.get('iss')}"
            )
        except Exception:  # noqa: BLE001 — best-effort diagnostic only
            pass
        logger.warning("JWT rejected (%s): %s%s", type(exc).__name__, exc, hint)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid auth token: {exc}",
        ) from exc
    except Exception as exc:  # noqa: BLE001
        # Catch-all so any future PyJWT/cryptography surprise still ends
        # up as a clean 401 with a server-side log entry, never a 500.
        logger.exception("JWT verification crashed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Auth check failed: {type(exc).__name__}",
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
        mode = "JWKS (asymmetric)" if _jwks_client() is not None else "HS256 (legacy shared secret)"
        n = len(_allowed_emails())
        if n:
            logger.info("Auth: Supabase JWT verification ENABLED via %s — %d allowed email(s)", mode, n)
        else:
            logger.warning(
                "Auth: Supabase JWT verification ENABLED via %s but ALLOWED_EMAILS is empty — "
                "any valid Supabase user can access this API.",
                mode,
            )
    else:
        logger.warning(
            "Auth: DISABLED (no SUPABASE_URL or SUPABASE_JWT_SECRET configured) — every request "
            "is treated as dev user. Do NOT expose this deployment to the internet."
        )


def log_provider_keys() -> None:
    """Log which external-API keys the process actually has at boot.

    We log presence only (never the secret itself) so the user can verify
    Railway/Supabase env vars landed in the container without leaking
    anything to log aggregators.
    """
    s = get_settings()
    flags = {
        "ANTHROPIC_API_KEY": bool(s.anthropic_api_key),
        "OPENAI_API_KEY": bool(s.openai_api_key),
        "NEWSDATA_API_KEY": bool(s.newsdata_api_key),
        "NEWSAPI_KEY": bool(s.newsapi_key),
        "GUARDIAN_API_KEY": bool(s.guardian_api_key),
        "NYT_API_KEY": bool(s.nyt_api_key),
    }
    summary = ", ".join(f"{k}={'set' if v else 'MISSING'}" for k, v in flags.items())
    logger.info("Provider keys: %s", summary)
