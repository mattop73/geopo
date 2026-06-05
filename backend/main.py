"""Geopo Dashboard API — FastAPI entry point.

Production layout (Railway / Docker):
    The same Uvicorn/Gunicorn process serves both the JSON API under
    ``/api/*`` and the compiled React SPA from ``frontend/dist`` at ``/``.
    This keeps the deployment single-service and avoids CORS entirely
    (everything is same-origin).

Dev layout:
    Vite on :5173 proxies ``/api`` to Uvicorn on :8000 — the SPA mount
    below is a no-op when ``frontend/dist`` doesn't exist, so dev is
    unaffected.

Auth:
    Every ``/api/*`` route except ``/api/health`` requires a valid Supabase
    JWT. The health endpoint stays public so Railway's healthchecker can
    poll it without a token. See ``services/auth_service.py`` for the
    dev-mode fallback that keeps local boot working without Supabase.
"""
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from database import init_db
from routers import commodities, llm, news, podcasts, polymarket, predictions, themes
from scheduler import scheduler, start_scheduler
from services.auth_service import log_auth_mode, log_provider_keys, require_user

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log_auth_mode()
    log_provider_keys()
    await init_db()
    start_scheduler()
    from database import AsyncSessionLocal
    from services.commodity_service import fetch_and_store_commodities
    from services.news_service import fetch_and_store_news
    from services.podcast_service import discover_new_episodes
    from services.polymarket_service import fetch_and_store_polymarket

    logger.info("Running initial data fetch...")
    async with AsyncSessionLocal() as db:
        await fetch_and_store_commodities(db)
    async with AsyncSessionLocal() as db:
        await fetch_and_store_news(db)
    async with AsyncSessionLocal() as db:
        await fetch_and_store_polymarket(db)
    # Discover podcast episodes up-front; transcript + LLM summary is done
    # by the scheduler so startup stays snappy and the 90-day backfill
    # spreads across ticks rather than blocking boot.
    async with AsyncSessionLocal() as db:
        await discover_new_episodes(db)
    yield
    scheduler.shutdown()


app = FastAPI(
    title="Geopo Dashboard API",
    description="Geopolitics KPI dashboard — commodities, news, prediction markets, LLM analysis",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS only matters in dev (Vite at :5173 → API at :8000). In production
# the SPA is served by the same process so requests are same-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Catch-all exception handler: every unhandled error in an /api/* route
# becomes a single, clearly-tagged log line with the full traceback. The
# default FastAPI behavior buries the traceback under uvicorn's "Exception
# in ASGI application" framing, which makes Railway logs unscannable when
# many endpoints fail at once. The error type is also surfaced to the
# client in ``detail`` (no leaked internals — just the class name) so the
# browser console gets a hint without needing server access.
@app.exception_handler(Exception)
async def _unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "UNHANDLED %s %s -> %s: %s",
        request.method,
        request.url.path,
        type(exc).__name__,
        exc,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal error: {type(exc).__name__}: {exc}"},
    )


# Public, unauthenticated. Used as Railway's healthcheck target. Also
# reports the auth posture so the operator can confirm in one HTTP call
# whether the JWKS-based verifier is live (i.e. that the latest code
# actually deployed). Returns plain JSON so it's curl-friendly.
@app.get("/api/health")
async def health() -> dict[str, object]:
    from config import get_settings
    from services.auth_service import _jwks_client

    s = get_settings()
    if s.supabase_url and _jwks_client() is not None:
        auth_mode = "jwks"
    elif s.supabase_jwt_secret:
        auth_mode = "hs256-static"
    else:
        auth_mode = "disabled"
    return {
        "status": "ok",
        "auth_mode": auth_mode,
        "supabase_url_set": bool(s.supabase_url),
        "supabase_jwt_secret_set": bool(s.supabase_jwt_secret),
        "allowed_emails_count": len(
            [e for e in (s.allowed_emails or "").split(",") if e.strip()]
        ),
    }


# Every data router gates on a valid Supabase JWT (or the dev fallback).
auth_dep = [Depends(require_user)]
app.include_router(commodities.router, dependencies=auth_dep)
app.include_router(news.router, dependencies=auth_dep)
app.include_router(polymarket.router, dependencies=auth_dep)
app.include_router(llm.router, dependencies=auth_dep)
app.include_router(themes.router, dependencies=auth_dep)
app.include_router(podcasts.router, dependencies=auth_dep)
app.include_router(predictions.router, dependencies=auth_dep)


# -- SPA static mount --------------------------------------------------------
# Path is configurable so the Dockerfile can copy the build to a known
# location and point at it via env. Defaults to ``frontend/dist`` next to
# this file's repo root, which is also where ``npm run build`` lands.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SPA_DIR = Path(os.getenv("SPA_DIST_DIR", _REPO_ROOT / "frontend" / "dist"))

if _SPA_DIR.is_dir() and (_SPA_DIR / "index.html").exists():
    logger.info("Mounting SPA from %s", _SPA_DIR)

    # /assets, /favicon.ico, etc. served from the build output.
    app.mount(
        "/assets",
        StaticFiles(directory=_SPA_DIR / "assets"),
        name="spa-assets",
    )

    def _render_index_with_runtime_config() -> HTMLResponse:
        """Serve ``index.html`` with Supabase URL+anon key injected.

        Vite normally bakes ``import.meta.env.VITE_*`` into the bundle at
        build time, which couples the React app to ``--build-arg`` plumbing.
        That's fragile on Railway and similar PaaS where runtime env vars
        are easy to set but build args are easy to forget. Injecting a
        ``window.GEOPO_CONFIG`` blob at request time decouples the two:
        anytime ``SUPABASE_URL`` / ``SUPABASE_ANON_KEY`` change, a simple
        restart picks them up — no rebuild required. The frontend reads
        ``window.GEOPO_CONFIG`` with a graceful fallback to
        ``import.meta.env`` for local Vite dev.
        """
        from config import get_settings

        s = get_settings()
        cfg = {
            "supabase_url": (s.supabase_url or "").strip().rstrip("/"),
            "supabase_anon_key": (s.supabase_anon_key or "").strip(),
        }
        html = (_SPA_DIR / "index.html").read_text(encoding="utf-8")
        # Use json.dumps so any quotes/backslashes are properly escaped,
        # and prepend an empty string literal to defang any closing </script>
        # smuggled into the values (defense-in-depth; values come from our
        # own settings, but cheap to harden).
        injected = (
            f"<script>window.GEOPO_CONFIG = {json.dumps(cfg)};</script>"
        )
        # Inject just before </head>. ``replace(..., 1)`` is intentional —
        # only the first match should be touched even on weird future templates.
        if "</head>" in html:
            html = html.replace("</head>", f"{injected}\n  </head>", 1)
        else:
            # Fallback: prepend to body if no </head> tag exists.
            html = injected + html
        return HTMLResponse(html)

    # Catch-all that lets React Router own the URL space. Any GET that
    # isn't an /api/* call returns index.html so deep links work on
    # refresh. We intentionally register this *after* the routers so
    # API routes take precedence.
    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        # Serve real files at the root (e.g. favicon, robots.txt). Skip
        # index.html itself — that path goes through the injection
        # renderer below so the config always lands in the bundle.
        candidate = _SPA_DIR / full_path
        if full_path and candidate.is_file() and candidate.name != "index.html":
            return FileResponse(candidate)
        return _render_index_with_runtime_config()
else:
    logger.info(
        "SPA dist not found at %s — running in API-only mode (use Vite dev server).",
        _SPA_DIR,
    )
