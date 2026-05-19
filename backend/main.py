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
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from database import init_db
from routers import commodities, llm, news, podcasts, polymarket, themes
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

    # Catch-all that lets React Router own the URL space. Any GET that
    # isn't an /api/* call returns index.html so deep links work on
    # refresh. We intentionally register this *after* the routers so
    # API routes take precedence.
    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        # Serve real files at the root (e.g. favicon, robots.txt)
        candidate = _SPA_DIR / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_SPA_DIR / "index.html")
else:
    logger.info(
        "SPA dist not found at %s — running in API-only mode (use Vite dev server).",
        _SPA_DIR,
    )
