import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from models.news import NewsArticle
from config import get_settings
from services.topic_service import classify_text
from services.keyword_service import extract_keywords_for_article

logger = logging.getLogger(__name__)
settings = get_settings()

GEOPOLITICS_KEYWORDS = (
    "geopolitics OR war OR conflict OR sanctions OR diplomacy OR "
    "NATO OR Ukraine OR Russia OR China OR Iran OR Israel OR "
    "commodity OR oil OR gas OR wheat OR inflation OR currency"
)


async def _fetch_newsapi(client: httpx.AsyncClient) -> list[dict]:
    if not settings.newsapi_key:
        logger.warning("NEWSAPI_KEY missing in env — skipping NewsAPI source")
        return []
    try:
        r = await client.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": GEOPOLITICS_KEYWORDS,
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": 30,
                "apiKey": settings.newsapi_key,
            },
            timeout=15,
        )
        r.raise_for_status()
        articles = r.json().get("articles", [])
        return [
            {
                "source": a.get("source", {}).get("name", "NewsAPI"),
                "title": a.get("title", ""),
                "description": a.get("description", ""),
                "url": a.get("url", ""),
                "image_url": a.get("urlToImage"),
                "published_at": _parse_dt(a.get("publishedAt")),
            }
            for a in articles
            if a.get("title") and a.get("url")
        ]
    except Exception as e:
        logger.error(f"NewsAPI fetch failed: {e}")
        return []


async def _fetch_guardian(client: httpx.AsyncClient) -> list[dict]:
    # Guardian's free tier is real-time (no embargo, unlike NewsAPI's 24h
    # delay on the Developer plan). The literal key ``test`` is the public
    # demo key — heavily rate-limited but enough for dev. Users should
    # register a free key at https://open-platform.theguardian.com/access/
    # and set GUARDIAN_API_KEY in .env for production-grade quota.
    api_key = settings.guardian_api_key or "test"
    if api_key == "test":
        logger.info("Using Guardian demo key 'test' — register your own at "
                    "https://open-platform.theguardian.com/access/ for higher limits")
    try:
        r = await client.get(
            "https://content.guardianapis.com/search",
            params={
                "q": ("geopolitics OR war OR ceasefire OR sanctions OR NATO OR "
                      "Ukraine OR Russia OR China OR Taiwan OR Iran OR Israel OR "
                      "Gaza OR diplomacy OR election OR Trump"),
                "api-key": api_key,
                "show-fields": "thumbnail,trailText",
                "page-size": 50,
                "order-by": "newest",
            },
            timeout=15,
        )
        r.raise_for_status()
        results = r.json().get("response", {}).get("results", [])
        return [
            {
                "source": "The Guardian",
                "title": a.get("webTitle", ""),
                "description": a.get("fields", {}).get("trailText", ""),
                "url": a.get("webUrl", ""),
                "image_url": a.get("fields", {}).get("thumbnail"),
                "published_at": _parse_dt(a.get("webPublicationDate")),
            }
            for a in results
            if a.get("webTitle") and a.get("webUrl")
        ]
    except Exception as e:
        logger.error(f"Guardian fetch failed: {e}")
        return []


async def _fetch_nyt(client: httpx.AsyncClient) -> list[dict]:
    if not settings.nyt_api_key:
        logger.warning("NYT_API_KEY missing in env — skipping NYT source")
        return []
    # NYT's articlesearch is an archive index — its "newest" can still trail
    # by several days. Constrain to the last 48h so we never bury fresher
    # Guardian rows under stale NYT hits.
    begin = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y%m%d")
    try:
        r = await client.get(
            "https://api.nytimes.com/svc/search/v2/articlesearch.json",
            params={
                "q": "geopolitics war Ukraine China Russia sanctions oil",
                "sort": "newest",
                "begin_date": begin,
                "api-key": settings.nyt_api_key,
                "fl": "headline,abstract,web_url,pub_date,multimedia",
            },
            timeout=15,
        )
        r.raise_for_status()
        docs = r.json().get("response", {}).get("docs", [])
        results = []
        for a in docs:
            results.append({
                "source": "New York Times",
                "title": a.get("headline", {}).get("main", ""),
                "description": a.get("abstract", ""),
                "url": a.get("web_url", ""),
                "image_url": _extract_nyt_image(a.get("multimedia")),
                "published_at": _parse_dt(a.get("pub_date")),
            })
        return [r for r in results if r["title"] and r["url"]]
    except Exception as e:
        logger.error(f"NYT fetch failed: {e}")
        return []


def _extract_nyt_image(mm: Any) -> str | None:
    """NYT changed `multimedia` from list[dict] to a single dict with sub-keys
    (`default`, `thumbnail`, ...). Handle both shapes defensively."""
    if not mm:
        return None
    if isinstance(mm, dict):
        for key in ("default", "thumbnail"):
            node = mm.get(key)
            if isinstance(node, dict) and node.get("url"):
                return node["url"]
        return None
    if isinstance(mm, list):
        for item in mm:
            if isinstance(item, dict) and item.get("type") == "image" and item.get("url"):
                u = item["url"]
                return u if u.startswith("http") else f"https://www.nytimes.com/{u}"
    return None


def _to_naive_utc(dt: datetime) -> datetime:
    """Normalize any datetime to a naive UTC datetime.

    The DB column is a naive ``DateTime``; we store all timestamps as UTC so
    downstream serialization can unambiguously tag them with ``+00:00``.
    A naive input is assumed to already be UTC (the upstream news APIs we
    consume publish UTC timestamps).
    """
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.replace(tzinfo=None)


def _parse_dt(s: str | None) -> datetime | None:
    """Robust ISO-8601 parser. Always returns naive UTC."""
    if not s:
        return None
    try:
        return _to_naive_utc(datetime.fromisoformat(s.replace("Z", "+00:00")))
    except ValueError:
        pass
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S.%f%z",
    ):
        try:
            return _to_naive_utc(datetime.strptime(s, fmt))
        except ValueError:
            continue
    logger.debug("Unparseable date: %r", s)
    return None


def _iso_utc(dt: datetime | None) -> str | None:
    """Serialize a naive (UTC) DB timestamp as a fully-qualified ISO-8601
    string with explicit ``+00:00`` offset, so JS ``new Date(...)`` cannot
    silently interpret it as local time."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).isoformat()


async def fetch_and_store_news(db: AsyncSession) -> dict[str, Any]:
    """Fetch news from all configured sources, persist new rows, return counts."""
    async with httpx.AsyncClient() as client:
        newsapi, guardian, nyt = await asyncio.gather(
            _fetch_newsapi(client),
            _fetch_guardian(client),
            _fetch_nyt(client),
        )

    per_source = {"newsapi": len(newsapi), "guardian": len(guardian), "nyt": len(nyt)}
    all_articles: list[dict] = [*newsapi, *guardian, *nyt]
    fetched = len(all_articles)
    logger.info("Fetched %d articles (per source: %s)", fetched, per_source)

    stored = 0
    skipped_dup = 0
    for a in all_articles:
        if not a.get("url"):
            continue
        existing = await db.execute(
            select(NewsArticle.id).where(NewsArticle.url == a["url"])
        )
        if existing.scalar_one_or_none():
            skipped_dup += 1
            continue
        # Classify once at ingest time so subsequent reads can use SQL filters
        # on the `topic` column instead of recomputing.
        topic = classify_text(f"{a.get('title','')} {a.get('description','')}")
        db.add(NewsArticle(**a, topic=topic))
        stored += 1
    await db.commit()
    logger.info("Stored %d new articles (duplicates skipped: %d)", stored, skipped_dup)
    return {
        "fetched": fetched,
        "stored": stored,
        "duplicates_skipped": skipped_dup,
        "per_source": per_source,
    }


async def get_latest_news(
    db: AsyncSession,
    limit: int = 60,
    source: str | None = None,
    topic: str | None = None,
) -> list[dict]:
    """Return latest news rows. Filters topic at the SQL layer.

    Topic is now persisted on every row (see migration 0002). For legacy rows
    where the column is still NULL we fall back to the in-memory classifier
    so the UI never gets ``None``.
    """
    q = select(NewsArticle).order_by(desc(NewsArticle.published_at)).limit(limit)
    if source:
        q = q.where(NewsArticle.source == source)
    if topic:
        q = q.where(NewsArticle.topic == topic)
    result = await db.execute(q)
    rows = result.scalars().all()

    items: list[dict] = []
    for r in rows:
        tid = r.topic or classify_text(f"{r.title or ''} {r.description or ''}")
        items.append({
            "id": r.id,
            "source": r.source,
            "title": r.title,
            "description": r.description,
            "url": r.url,
            "image_url": r.image_url,
            "published_at": _iso_utc(r.published_at),
            "sentiment_score": r.sentiment_score,
            "topic": tid,
            "tags": extract_keywords_for_article(r.title, r.description),
        })
    return items
