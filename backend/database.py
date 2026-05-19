import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _resolve_async_db_url() -> str:
    """Return the async SQLAlchemy URL.

    Precedence:
        1. ``settings.database_url`` if set — normalized so a raw Supabase
           ``postgresql://`` URL works as-is (we inject ``+asyncpg`` and
           ``ssl=require``).
        2. Legacy local SQLite at ``settings.db_path`` — keeps dev boxes
           that haven't migrated to Postgres yet running unchanged.
    """
    raw = (settings.database_url or "").strip()
    if not raw:
        return f"sqlite+aiosqlite:///{settings.db_path}"

    url = raw
    # Supabase shows ``postgresql://`` — convert to the async driver.
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    elif url.startswith("postgres://"):  # heroku-style alias
        url = "postgresql+asyncpg://" + url[len("postgres://"):]

    # Force TLS for any Postgres connection. asyncpg uses ``ssl=`` (not
    # ``sslmode=`` like psycopg2). Both forms are tolerated here.
    if url.startswith("postgresql+asyncpg://") and "ssl=" not in url and "sslmode=" not in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}ssl=require"

    return url


ASYNC_DB_URL = _resolve_async_db_url()
_dialect = ASYNC_DB_URL.split(":", 1)[0]
logger.info("Database dialect=%s", _dialect)

engine = create_async_engine(ASYNC_DB_URL, echo=False, pool_pre_ping=True)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def _run_alembic_upgrade() -> None:
    """Run ``alembic upgrade head`` programmatically so dev/prod stay in sync.

    Falls back to ``Base.metadata.create_all`` if the alembic config can't be
    located (e.g. running tests from a stripped-down checkout). Logs but does
    not raise on migration errors — the caller still owns the engine.
    """
    from alembic import command
    from alembic.config import Config

    cfg_path = Path(__file__).resolve().parent / "alembic.ini"
    if not cfg_path.exists():
        logger.warning("alembic.ini not found at %s — skipping migrations", cfg_path)
        return
    cfg = Config(str(cfg_path))
    cfg.set_main_option("script_location", str(cfg_path.parent / "alembic"))
    # Make sure the URL matches the current settings even if alembic.ini
    # drifts. Convert the async URL we use at runtime to the sync form
    # Alembic expects (psycopg2 for Postgres, pysqlite for SQLite).
    cfg.set_main_option("sqlalchemy.url", _sync_url_for_alembic(ASYNC_DB_URL))
    command.upgrade(cfg, "head")
    logger.info("Alembic migrations up to date")


def _sync_url_for_alembic(async_url: str) -> str:
    """Map our runtime async URL to the sync driver Alembic needs.

    asyncpg → psycopg2 (Postgres) / aiosqlite → pysqlite (SQLite).
    """
    if async_url.startswith("postgresql+asyncpg://"):
        sync = "postgresql+psycopg2://" + async_url[len("postgresql+asyncpg://"):]
        # psycopg2 wants ``sslmode``, not ``ssl``.
        return sync.replace("ssl=require", "sslmode=require")
    if async_url.startswith("sqlite+aiosqlite:///"):
        return "sqlite+pysqlite:///" + async_url[len("sqlite+aiosqlite:///"):]
    return async_url


async def init_db():
    from models import commodity, news, polymarket, podcast  # noqa: F401

    # 1) Make sure the schema exists. ``create_all`` is a no-op for tables
    #    Alembic has already created, and is required for brand-new installs
    #    that have no DB yet (alembic's first run otherwise tries to ALTER
    #    a missing table on migration 0002).
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 2) Apply migrations. Alembic uses a sync engine internally — run it in
    #    a thread so we don't block the event loop.
    import asyncio

    try:
        await asyncio.to_thread(_run_alembic_upgrade)
    except Exception as exc:
        logger.exception("Alembic upgrade failed: %s", exc)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
