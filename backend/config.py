from pydantic_settings import BaseSettings
from functools import lru_cache
from pathlib import Path


ROOT_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    newsapi_key: str = ""
    newsdata_api_key: str = ""
    guardian_api_key: str = ""
    nyt_api_key: str = ""
    gdelt_enabled: bool = True
    news_rss_feeds: str = (
        "https://feeds.bbci.co.uk/news/world/rss.xml,"
        "https://www.aljazeera.com/xml/rss/all.xml,"
        "https://www.france24.com/en/rss"
    )
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"
    default_llm_model: str = "ollama:llama3.2"

    # --- Storage ---------------------------------------------------------
    # Full SQLAlchemy URL. If set, takes precedence over ``db_path``.
    # Accepts a plain Postgres URL (e.g. the one Supabase shows) — it gets
    # normalized to ``postgresql+asyncpg://...`` with SSL at runtime.
    # Empty → falls back to the legacy local SQLite file at ``db_path``,
    # so existing local dev keeps working unchanged.
    database_url: str = ""
    db_path: str = "geopo.db"

    # --- Auth (Supabase) -------------------------------------------------
    # When ``supabase_jwt_secret`` is empty, JWT verification is bypassed
    # and every request is treated as an anonymous local-dev user. This
    # lets the app boot on a fresh checkout without any Supabase setup.
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_jwt_secret: str = ""
    # Comma-separated allowlist of authorized email addresses. Empty means
    # any user with a valid Supabase JWT is admitted (NOT recommended
    # in production with a public Google OAuth provider).
    allowed_emails: str = ""
    commodity_refresh_minutes: int = 5
    news_refresh_minutes: int = 15
    polymarket_refresh_minutes: int = 5
    podcast_refresh_minutes: int = 30
    # Anthropic model used to summarize podcast episodes. Sonnet is the
    # default — it handles long French/English transcripts cleanly and costs
    # ~$0.06 per 1h episode / ~$0.15 per 3h Thinkerview.
    podcast_summary_model: str = "claude-sonnet-4-6"
    # How far back to backfill episodes on first run (and on every discovery
    # tick — older items are simply ignored).
    podcast_backfill_days: int = 90
    # In-memory cache TTL for /api/themes/analyze responses (per topic+model).
    # Set to 0 to disable caching entirely.
    theme_analysis_cache_minutes: int = 10

    class Config:
        env_file = ROOT_ENV_FILE
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
