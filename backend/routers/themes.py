"""Themes — link commodities, news, and Polymarket markets into topics.

Two endpoints:

- ``GET /api/themes/``: aggregates the three data sources per topic. Cheap,
  deterministic, runs on every page load.
- ``POST /api/themes/analyze``: streams an LLM narrative that ties the three
  sources together for one topic. Routes to Anthropic / OpenAI / Ollama based
  on the model id (handled by :func:`services.llm_service.stream_llm`).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database import get_db
from services.commodity_service import get_latest_commodities
from services.llm_service import stream_llm
from services.news_service import display_language_name, get_latest_news, normalize_display_language
from services.polymarket_service import get_latest_polymarket
from services.topic_service import all_topics, classify_text, topic_meta

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/themes", tags=["themes"])
settings = get_settings()


# -------------------- analyse cache --------------------
# Keyed by (topic_id, model, language) so flipping provider/language doesn't return stale text.
# Each entry is (created_at_epoch, full_text). Kept in-process — fine for a
# single-uvicorn-worker dev setup. For multi-worker we'd promote to Redis.
_ANALYSIS_CACHE: dict[tuple[str, str, str], tuple[float, str]] = {}
_ANALYSIS_LOCK = asyncio.Lock()


def _cache_ttl_seconds() -> int:
    return max(0, int(settings.theme_analysis_cache_minutes) * 60)


def _cache_get(key: tuple[str, str, str]) -> str | None:
    entry = _ANALYSIS_CACHE.get(key)
    if not entry:
        return None
    created, text = entry
    ttl = _cache_ttl_seconds()
    if ttl == 0 or time.time() - created > ttl:
        _ANALYSIS_CACHE.pop(key, None)
        return None
    return text


def _cache_set(key: tuple[str, str, str], text: str) -> None:
    if _cache_ttl_seconds() == 0 or not text.strip():
        return
    _ANALYSIS_CACHE[key] = (time.time(), text)

# Per-theme display caps — keep payload small for the dashboard grid.
MAX_NEWS_PER_THEME = 8
MAX_MARKETS_PER_THEME = 6

# Larger caps for the LLM context window.
LLM_MAX_NEWS = 15
LLM_MAX_MARKETS = 10


@router.get("/topics")
async def topic_definitions() -> list[dict[str, Any]]:
    """Return the static topic catalogue (id, label, icon, color)."""
    return [
        {"id": t["id"], "label": t["label"], "icon": t["icon"], "color": t["color"]}
        for t in all_topics()
    ]


def _bucket_by_topic(items: list[dict], text_fn) -> dict[str, list[dict]]:
    """Group items into ``{topic_id: [items...]}`` using a text-extractor."""
    out: dict[str, list[dict]] = {}
    for item in items:
        tid = classify_text(text_fn(item))
        out.setdefault(tid, []).append({**item, "topic": tid})
    return out


@router.get("/")
async def list_themes(
    language: str = Query("en", pattern="^(en|fr)$"),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Return every active theme with its linked commodities, news, and markets."""
    lang = normalize_display_language(language)
    news = await get_latest_news(db, limit=200, language=lang)
    markets = await get_latest_polymarket(db, language=lang)
    commodities = await get_latest_commodities(db)
    commodities_by_ticker = {c["ticker"]: c for c in commodities}

    news_by_topic = _bucket_by_topic(
        news,
        text_fn=lambda n: f"{n.get('title', '')} {n.get('description', '')}",
    )
    markets_by_topic = _bucket_by_topic(
        markets,
        text_fn=lambda m: m.get("question", ""),
    )

    out: list[dict[str, Any]] = []
    for topic in all_topics():
        tid = topic["id"]
        topic_news = news_by_topic.get(tid, [])
        topic_markets = markets_by_topic.get(tid, [])
        topic_commodities = [
            commodities_by_ticker[t]
            for t in topic.get("commodity_tickers", [])
            if t in commodities_by_ticker
        ]

        # Suppress empty buckets except for the "other" catch-all which we always show.
        if tid != "other" and not (topic_news or topic_markets or topic_commodities):
            continue

        avg_change = (
            sum((c.get("change_pct") or 0) for c in topic_commodities) / len(topic_commodities)
            if topic_commodities
            else 0.0
        )
        anomaly_count = sum(1 for m in topic_markets if m.get("is_anomaly"))

        out.append({
            "id": tid,
            "label": topic["label"],
            "icon": topic["icon"],
            "color": topic["color"],
            "commodities": topic_commodities,
            "news": topic_news[:MAX_NEWS_PER_THEME],
            "markets": topic_markets[:MAX_MARKETS_PER_THEME],
            "stats": {
                "news_count": len(topic_news),
                "market_count": len(topic_markets),
                "anomaly_count": anomaly_count,
                "avg_commodity_change_pct": round(avg_change, 3),
            },
        })
    return out


class AnalyzeRequest(BaseModel):
    topic_id: str
    model: str = ""
    language: str = "en"
    # When True the cache is bypassed and a fresh stream is generated. The
    # fresh result still updates the cache for subsequent reads.
    fresh: bool = False


def _format_news_block(news: list[dict]) -> str:
    if not news:
        return "(no recent articles)"
    return "\n".join(
        f"- [{n.get('source','?')}] {n.get('title','')}"
        + (f" — {n['description'][:160]}" if n.get("description") else "")
        for n in news
    )


def _format_market_block(markets: list[dict]) -> str:
    if not markets:
        return "(no relevant markets)"
    lines = []
    for m in markets:
        yes_pct = (m.get("yes_price") or 0) * 100
        d24 = (m.get("price_change_24h") or 0) * 100
        vol = m.get("volume", 0) or 0
        line = (
            f"- {m.get('question','')} — YES {yes_pct:.0f}% "
            f"({d24:+.1f}pts/24h, vol ${vol/1000:.0f}k)"
        )
        if m.get("is_anomaly") and m.get("anomaly_reason"):
            line += f"  ⚠️ {m['anomaly_reason']}"
        lines.append(line)
    return "\n".join(lines)


def _format_commodity_block(commodities: list[dict]) -> str:
    if not commodities:
        return "(no tied commodities)"
    return "\n".join(
        f"- {c.get('name','?')} ({c.get('ticker','?')}): "
        f"${(c.get('price') or 0):.4f} ({(c.get('change_pct') or 0):+.2f}%)"
        for c in commodities
    )


SYSTEM_PROMPT = (
    "You are a senior geopolitical analyst. You will receive live commodity prices, "
    "news headlines, and prediction-market odds for a single theme. Be precise, "
    "reference specific figures, and avoid hedging language. Stay under 400 words."
)


@router.post("/analyze")
async def analyze_theme(
    req: AnalyzeRequest,
    db: AsyncSession = Depends(get_db),
):
    """Stream an LLM analysis linking commodities + news + markets for one theme."""
    topic = topic_meta(req.topic_id)
    model = req.model or settings.default_llm_model
    lang = normalize_display_language(req.language)
    language_name = display_language_name(lang)

    news = await get_latest_news(db, limit=200, language=lang)
    markets = await get_latest_polymarket(db, language=lang)
    commodities = await get_latest_commodities(db)
    commodities_by_ticker = {c["ticker"]: c for c in commodities}

    related_news = [
        n for n in news
        if classify_text(f"{n.get('title','')} {n.get('description','')}") == req.topic_id
    ][:LLM_MAX_NEWS]
    related_markets = [
        m for m in markets
        if classify_text(m.get("question", "")) == req.topic_id
    ][:LLM_MAX_MARKETS]
    topic_commodities = [
        commodities_by_ticker[t]
        for t in topic.get("commodity_tickers", [])
        if t in commodities_by_ticker
    ]

    cache_key = (req.topic_id, model, lang)

    # Fast path: serve fully-formed cached analysis as a single response. We
    # still return it via StreamingResponse so the frontend reading code is
    # uniform — but it lands in one chunk and X-Cache=HIT signals reuse.
    if not req.fresh:
        cached = _cache_get(cache_key)
        if cached is not None:
            logger.info("Theme analysis cache HIT for %s / %s", req.topic_id, model)

            async def replay():
                yield cached

            return StreamingResponse(
                replay(),
                media_type="text/plain",
                headers={"X-Cache": "HIT"},
            )

    prompt = f"""Theme: **{topic['label']}**

Write a 4-6 paragraph brief that **explicitly links** the three sources below:
what the news flow says, how prediction markets are pricing it, and what the
commodity moves confirm or contradict. Cite specific numbers.
Write the entire brief in {language_name}.

End with:
1. The most likely scenario for the next 2 weeks.
2. One divergence or anomaly worth watching (e.g., commodity move not yet
   priced into Polymarket, or vice-versa).

## COMMODITIES
{_format_commodity_block(topic_commodities)}

## NEWS HEADLINES
{_format_news_block(related_news)}

## POLYMARKET ODDS
{_format_market_block(related_markets)}
"""

    async def generate():
        # Tee the stream: yield to client AND accumulate into a buffer so we
        # can populate the cache atomically once the stream completes
        # successfully. If the stream errors mid-way we deliberately do NOT
        # cache the truncated result.
        buf: list[str] = []
        had_error = False
        try:
            system = f"{SYSTEM_PROMPT} Write the entire response in {language_name}."
            async for chunk in stream_llm(prompt, model, system=system):
                buf.append(chunk)
                yield chunk
        except Exception as exc:
            had_error = True
            logger.exception("Theme analysis stream failed: %s", exc)
            raise
        finally:
            if not had_error and buf:
                # Stream provider error strings ("[Anthropic error: ...]")
                # come through as normal chunks — don't cache those.
                full = "".join(buf)
                if "[Anthropic error" not in full and "[Ollama error" not in full and "[OpenAI error" not in full:
                    async with _ANALYSIS_LOCK:
                        _cache_set(cache_key, full)

    return StreamingResponse(
        generate(),
        media_type="text/plain",
        headers={"X-Cache": "MISS"},
    )


@router.post("/cache/clear")
async def clear_analysis_cache() -> dict[str, Any]:
    """Drop all cached theme analyses (handy for dev)."""
    async with _ANALYSIS_LOCK:
        n = len(_ANALYSIS_CACHE)
        _ANALYSIS_CACHE.clear()
    return {"cleared": n}


@router.get("/cache/status")
async def cache_status() -> dict[str, Any]:
    """Return current cache contents (debug helper)."""
    ttl = _cache_ttl_seconds()
    now = time.time()
    return {
        "ttl_seconds": ttl,
        "entries": [
            {
                "topic_id": k[0],
                "model": k[1],
                "age_seconds": int(now - created),
                "size_chars": len(text),
            }
            for k, (created, text) in _ANALYSIS_CACHE.items()
        ],
    }
