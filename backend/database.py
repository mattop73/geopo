import logging
import socket
from pathlib import Path

from sqlalchemy.engine.url import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _resolve_async_db_url() -> URL:
    """Return the async SQLAlchemy URL as a :class:`URL` object.

    Precedence:
        1. ``settings.database_url`` if set — normalized via SQLAlchemy's
           ``make_url`` parser (which handles percent-encoded passwords,
           IPv6 brackets, etc.) and rewritten to use the asyncpg driver
           with ``ssl=require``.
        2. Legacy local SQLite at ``settings.db_path`` — keeps dev boxes
           that haven't migrated to Postgres yet running unchanged.
    """
    raw = (settings.database_url or "").strip()
    if not raw:
        return make_url(f"sqlite+aiosqlite:///{settings.db_path}")

    url = make_url(raw)

    # Force the asyncpg driver. ``postgres://`` is the Heroku-style alias.
    if url.drivername in ("postgres", "postgresql"):
        url = url.set(drivername="postgresql+asyncpg")

    # Force TLS for any Postgres connection. asyncpg expects ``ssl=`` in
    # the query string (psycopg2 uses ``sslmode=``). Don't overwrite if
    # the user already set one explicitly.
    if url.drivername == "postgresql+asyncpg":
        q = dict(url.query)
        if "ssl" not in q and "sslmode" not in q:
            q["ssl"] = "require"
            url = url.set(query=q)

    return url


ASYNC_DB_URL_OBJ: URL = _resolve_async_db_url()
# String form is what create_async_engine wants, but we keep the URL object
# around so the diagnostic below can read host/port/user without re-parsing.
ASYNC_DB_URL: str = ASYNC_DB_URL_OBJ.render_as_string(hide_password=False)


def _log_db_target(url: URL) -> None:
    """Print a redacted summary of where we're connecting + DNS sanity check.

    The single most common reason a Supabase+Railway boot fails is that the
    hostname stored in ``DATABASE_URL`` is not what the operator thinks it
    is (typo, wrong region, copy-paste lost a char, env var has trailing
    whitespace, etc.). Logging it explicitly — alongside a ``getaddrinfo``
    probe — turns a cryptic ``gaierror`` traceback into a one-line answer.
    """
    if url.drivername.startswith("sqlite"):
        logger.info("DB target: sqlite at %s", url.database)
        return

    host = url.host or "<none>"
    port = url.port or "<default>"
    user = url.username or "<none>"
    logger.info(
        "DB target: driver=%s host=%s port=%s user=%s db=%s query=%s",
        url.drivername, host, port, user, url.database, dict(url.query),
    )

    if not url.host:
        logger.error(
            "DB target has NO host — the DATABASE_URL likely has an unencoded "
            "special character in the password that broke URL parsing. "
            "Percent-encode @ # ? & = / : + $ %% in the password, or "
            "regenerate the Supabase password to be purely alphanumeric."
        )
        return

    try:
        infos = socket.getaddrinfo(url.host, url.port or 5432, type=socket.SOCK_STREAM)
        addrs = sorted({info[4][0] for info in infos})
        logger.info("DNS: %s resolves to %s", url.host, addrs)
    except socket.gaierror as exc:
        logger.error(
            "DNS lookup FAILED for %s: %s. The hostname is either wrong or "
            "unreachable from this container. Re-copy the Session pooler URI "
            "from Supabase Dashboard → Project Settings → Database → "
            "Connection string (tab 'Session pooler', port 5432).",
            url.host, exc,
        )


_log_db_target(ASYNC_DB_URL_OBJ)

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

    asyncpg → psycopg2 (Postgres) / aiosqlite → pysqlite (SQLite). Uses
    :func:`make_url` so the password's percent-encoding and any query
    params (e.g. ``ssl=require``) survive the rewrite cleanly.
    """
    url = make_url(async_url)
    if url.drivername == "postgresql+asyncpg":
        url = url.set(drivername="postgresql+psycopg2")
        # psycopg2 wants ``sslmode``, not ``ssl``.
        q = dict(url.query)
        if "ssl" in q and "sslmode" not in q:
            q["sslmode"] = q.pop("ssl")
            url = url.set(query=q)
    elif url.drivername == "sqlite+aiosqlite":
        url = url.set(drivername="sqlite+pysqlite")
    return url.render_as_string(hide_password=False)


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
