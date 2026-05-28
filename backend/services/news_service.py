import asyncio
import calendar
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import feedparser
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
GDELT_QUERY = (
    "(geopolitics OR war OR conflict OR sanctions OR diplomacy OR "
    "NATO OR Ukraine OR Russia OR China OR Iran OR Israel OR Gaza OR "
    "oil OR gas OR wheat OR inflation OR currency) sourcelang:english"
)
ENGLISH_MARKERS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "have",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "said",
    "says",
    "the",
    "to",
    "us",
    "with",
}
NON_LATIN_RE = re.compile(r"[\u0400-\u052f\u0590-\u05ff\u0600-\u06ff\u3040-\u30ff\u3400-\u9fff]")
WORD_RE = re.compile(r"[A-Za-z']+")
_translation_cache: dict[str, tuple[str, str | None]] = {}


def _configured_rss_feeds() -> list[str]:
    """Return the comma-separated RSS feed URLs configured in env."""
    return [url.strip() for url in settings.news_rss_feeds.split(",") if url.strip()]


def _looks_english(text: str | None) -> bool:
    """Return True when text is likely already English enough for display."""
    if not text:
        return True
    if NON_LATIN_RE.search(text):
        return False
    words = [word.lower() for word in WORD_RE.findall(text)]
    if not words:
        return True
    marker_count = sum(1 for word in words if word in ENGLISH_MARKERS)
    ascii_letters = sum(1 for char in text if char.isascii() and char.isalpha())
    letters = sum(1 for char in text if char.isalpha())
    ascii_ratio = ascii_letters / letters if letters else 1.0
    return marker_count >= 2 or (ascii_ratio > 0.97 and marker_count >= 1)


async def _translate_article_to_english(article: dict[str, Any]) -> dict[str, Any]:
    """Translate article display fields to English when they look non-English."""
    if not settings.news_translate_to_english:
        return article

    title = (article.get("title") or "").strip()
    description = (article.get("description") or "").strip()
    if _looks_english(f"{title} {description}"):
        return article

    cache_key = f"{title}\n---\n{description}"
    cached = _translation_cache.get(cache_key)
    if cached:
        return {**article, "title": cached[0], "description": cached[1]}

    if not settings.anthropic_api_key:
        logger.info("ANTHROPIC_API_KEY missing — cannot translate non-English news article")
        return article

    try:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model=settings.news_translation_model,
            max_tokens=600,
            system=(
                "You translate news article display text into clear, neutral English. "
                "Preserve names, places, numbers, and the factual meaning. Output JSON only."
            ),
            messages=[
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "title": title,
                            "description": description,
                            "schema": {
                                "title": "English title",
                                "description": "English description or null",
                            },
                        },
                        ensure_ascii=False,
                    ),
                }
            ],
        )
        raw = response.content[0].text if response.content else ""
        payload = json.loads(raw)
        translated_title = str(payload.get("title") or title).strip()
        translated_description = payload.get("description")
        if translated_description is not None:
            translated_description = str(translated_description).strip()
        _translation_cache[cache_key] = (translated_title, translated_description)
        return {
            **article,
            "title": translated_title,
            "description": translated_description,
        }
    except Exception as e:
        logger.error(f"News translation failed: {e}")
        return article


async def _fetch_newsdata(client: httpx.AsyncClient) -> list[dict]:
    """Fetch articles from NewsData.io's free-tier latest-news endpoint."""
    if not settings.newsdata_api_key:
        logger.info("NEWSDATA_API_KEY missing in env — skipping NewsData.io source")
        return []
    try:
        r = await client.get(
            "https://newsdata.io/api/1/latest",
            params={
                "apikey": settings.newsdata_api_key,
                "q": "geopolitics OR war OR sanctions OR diplomacy OR oil OR gas",
                "language": "en",
                "category": "world,business,politics",
                "size": 10,
            },
            timeout=15,
        )
        r.raise_for_status()
        articles = r.json().get("results", [])
        return [
            {
                "source": a.get("source_name") or "NewsData.io",
                "title": a.get("title", ""),
                "description": a.get("description") or a.get("content") or "",
                "url": a.get("link", ""),
                "image_url": a.get("image_url"),
                "published_at": _parse_dt(a.get("pubDate")),
            }
            for a in articles
            if a.get("title") and a.get("link")
        ]
    except Exception as e:
        logger.error(f"NewsData.io fetch failed: {e}")
        return []


async def _fetch_gdelt(client: httpx.AsyncClient) -> list[dict]:
    """Fetch recent global news from GDELT DOC 2.0. No API key required."""
    if not settings.gdelt_enabled:
        logger.info("GDELT_ENABLED=false — skipping GDELT source")
        return []
    try:
        r = await client.get(
            "https://api.gdeltproject.org/api/v2/doc/doc",
            params={
                "query": GDELT_QUERY,
                "mode": "artlist",
                "format": "json",
                "sort": "hybridrel",
                "maxrecords": 50,
                "timespan": "48h",
            },
            timeout=20,
        )
        r.raise_for_status()
        articles = r.json().get("articles", [])
        return [
            {
                "source": a.get("source") or a.get("domain") or "GDELT",
                "title": a.get("title", ""),
                "description": a.get("snippet") or "",
                "url": a.get("url", ""),
                "image_url": a.get("socialimage"),
                "published_at": _parse_dt(a.get("seendate")),
            }
            for a in articles
            if a.get("title") and a.get("url")
        ]
    except Exception as e:
        logger.error(f"GDELT fetch failed: {e}")
        return []


async def _fetch_single_rss(client: httpx.AsyncClient, feed_url: str) -> list[dict]:
    """Fetch and normalize one RSS/Atom feed."""
    try:
        r = await client.get(feed_url, timeout=15, follow_redirects=True)
        r.raise_for_status()
        parsed = feedparser.parse(r.content)
        source = (parsed.feed.get("title") or parsed.feed.get("link") or feed_url).strip()
        articles: list[dict] = []
        for entry in parsed.entries[:25]:
            url = entry.get("link", "")
            title = entry.get("title", "")
            if not title or not url:
                continue
            articles.append(
                {
                    "source": source,
                    "title": title,
                    "description": entry.get("summary") or entry.get("description") or "",
                    "url": url,
                    "image_url": _extract_rss_image(entry),
                    "published_at": _parse_rss_dt(entry),
                }
            )
        return articles
    except Exception as e:
        logger.error(f"RSS fetch failed for {feed_url}: {e}")
        return []


async def _fetch_rss_feeds(client: httpx.AsyncClient) -> list[dict]:
    """Fetch all configured RSS feeds. RSS is free and requires no API key."""
    feeds = _configured_rss_feeds()
    if not feeds:
        logger.info("NEWS_RSS_FEEDS is empty — skipping RSS sources")
        return []
    results = await asyncio.gather(*(_fetch_single_rss(client, url) for url in feeds))
    return [article for feed_articles in results for article in feed_articles]


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


def _extract_rss_image(entry: Any) -> str | None:
    """Best-effort image extraction from common RSS/Atom media extensions."""
    media_content = entry.get("media_content") or []
    if isinstance(media_content, list):
        for item in media_content:
            if isinstance(item, dict) and item.get("url"):
                return item["url"]
    media_thumbnail = entry.get("media_thumbnail") or []
    if isinstance(media_thumbnail, list) and media_thumbnail:
        thumb = media_thumbnail[0]
        if isinstance(thumb, dict):
            return thumb.get("url")
    links = entry.get("links") or []
    if isinstance(links, list):
        for item in links:
            if (
                isinstance(item, dict)
                and str(item.get("type", "")).startswith("image/")
                and item.get("href")
            ):
                return item["href"]
    return None


def _parse_rss_dt(entry: Any) -> datetime | None:
    """Parse feedparser's normalized time fields into naive UTC."""
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        parsed = entry.get(key)
        if parsed:
            return _to_naive_utc(datetime.fromtimestamp(calendar.timegm(parsed), timezone.utc))
    return _parse_dt(entry.get("published") or entry.get("updated") or entry.get("created"))


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
        "%Y%m%d%H%M%S",
        "%Y%m%dT%H%M%SZ",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M:%S %z",
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
        newsdata, gdelt, rss, newsapi, guardian, nyt = await asyncio.gather(
            _fetch_newsdata(client),
            _fetch_gdelt(client),
            _fetch_rss_feeds(client),
            _fetch_newsapi(client),
            _fetch_guardian(client),
            _fetch_nyt(client),
        )

    per_source = {
        "newsdata": len(newsdata),
        "gdelt": len(gdelt),
        "rss": len(rss),
        "newsapi": len(newsapi),
        "guardian": len(guardian),
        "nyt": len(nyt),
    }
    all_articles: list[dict] = [*newsdata, *gdelt, *rss, *newsapi, *guardian, *nyt]
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
        a = await _translate_article_to_english(a)
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
        article = await _translate_article_to_english(
            {
                "id": r.id,
                "source": r.source,
                "title": r.title,
                "description": r.description,
                "url": r.url,
                "image_url": r.image_url,
                "published_at": _iso_utc(r.published_at),
                "sentiment_score": r.sentiment_score,
            }
        )
        tid = r.topic or classify_text(
            f"{article.get('title') or ''} {article.get('description') or ''}"
        )
        items.append({
            "id": r.id,
            "source": r.source,
            "title": article["title"],
            "description": article["description"],
            "url": r.url,
            "image_url": r.image_url,
            "published_at": _iso_utc(r.published_at),
            "sentiment_score": r.sentiment_score,
            "topic": tid,
            "tags": extract_keywords_for_article(article["title"], article["description"]),
        })
    return items
