import json
import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from models.polymarket import PolymarketMarket, PolymarketSnapshot
from services.news_service import _translate_articles_for_display
from services.topic_service import classify_text

logger = logging.getLogger(__name__)

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"

GEOPOLITICS_KEYWORDS = [
    "war", "ceasefire", "nato", "ukraine", "russia", "putin", "zelensky",
    "china", "xi", "taiwan", "iran", "israel", "gaza", "hezbollah", "houthi",
    "north korea", "venezuela", "election", "president", "prime minister",
    "sanction", "tariff", "trump", "biden", "macron", "merz",
    "fed", "rate", "inflation", "recession", "gdp",
    "oil", "opec", "energy", "gas",
    "treaty", "summit", "diplomat", "ambassador", "coup", "regime",
    "european union", "brexit", "border", "immigration",
]

ANOMALY_PRICE_JUMP = 0.10           # 10pt move since last snapshot
ANOMALY_DAILY_CHANGE = 0.08         # 8pt 24h move
ANOMALY_HIGH_VOL_CHANGE = 0.04      # 4pt 24h move IF volume > threshold
ANOMALY_VOLUME_MIN = 100_000        # vol-amplifier threshold


def _iso_utc(dt: datetime | None) -> str | None:
    """Tag a naive (UTC) DB timestamp with explicit ``+00:00`` so JS clients
    don't interpret it as local time. See note in ``news_service``."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).isoformat()


def _parse_json_array(s: Any) -> list:
    if isinstance(s, list):
        return s
    if isinstance(s, str):
        try:
            return json.loads(s)
        except (json.JSONDecodeError, ValueError):
            return []
    return []


async def _fetch_markets(client: httpx.AsyncClient) -> list[dict]:
    """Fetch top-volume active markets. Paginated to get a useful pool to filter."""
    all_markets: list[dict] = []
    for offset in (0, 100, 200, 300):
        try:
            r = await client.get(
                f"{GAMMA_BASE}/markets",
                params={
                    "active": "true",
                    "closed": "false",
                    "limit": 100,
                    "offset": offset,
                    "order": "volume24hr",
                    "ascending": "false",
                },
                timeout=20,
            )
            r.raise_for_status()
            batch = r.json()
            if not batch:
                break
            all_markets.extend(batch)
        except Exception as e:
            logger.error(f"Polymarket markets fetch failed (offset {offset}): {e}")
            break
    return all_markets


async def _fetch_prices(client: httpx.AsyncClient, token_ids: list[str]) -> dict[str, float]:
    if not token_ids:
        return {}
    try:
        r = await client.get(
            f"{CLOB_BASE}/prices",
            params={"token_id": token_ids[0], "side": "BUY"},
            timeout=10,
        )
        r.raise_for_status()
        return {}
    except Exception:
        return {}


def _is_geopolitics(market: dict) -> bool:
    text = (
        (market.get("question") or "") + " " +
        (market.get("description") or "") + " " +
        (market.get("slug") or "")
    ).lower()
    return any(kw in text for kw in GEOPOLITICS_KEYWORDS)


def _detect_anomaly(yes_price: float, vol_24h: float, one_day_change: float, previous_yes: float | None) -> tuple[bool, str]:
    reasons = []
    if previous_yes is not None:
        delta = abs(yes_price - previous_yes)
        if delta >= ANOMALY_PRICE_JUMP:
            reasons.append(f"Price moved {delta*100:+.1f}pts since last check")
    abs_day = abs(one_day_change)
    if abs_day >= ANOMALY_DAILY_CHANGE:
        reasons.append(f"24h change {one_day_change*100:+.1f}pts")
    elif abs_day >= ANOMALY_HIGH_VOL_CHANGE and vol_24h >= ANOMALY_VOLUME_MIN:
        reasons.append(f"24h change {one_day_change*100:+.1f}pts on ${vol_24h:,.0f} volume")
    return bool(reasons), "; ".join(reasons)


async def fetch_and_store_polymarket(db: AsyncSession) -> list[dict]:
    async with httpx.AsyncClient() as client:
        raw_markets = await _fetch_markets(client)

    geo_markets = [m for m in raw_markets if _is_geopolitics(m)]
    logger.info(f"Found {len(geo_markets)} geopolitics Polymarket markets")

    previous_snaps: dict[str, float] = {}
    existing = await db.execute(
        select(PolymarketSnapshot).order_by(desc(PolymarketSnapshot.recorded_at)).limit(500)
    )
    for row in existing.scalars().all():
        if row.condition_id not in previous_snaps and row.yes_price is not None:
            previous_snaps[row.condition_id] = row.yes_price

    results = []
    for m in geo_markets:
        cid = m.get("conditionId") or str(m.get("id", ""))
        if not cid:
            continue

        outcomes = _parse_json_array(m.get("outcomes"))
        prices = _parse_json_array(m.get("outcomePrices"))
        if len(prices) < 2:
            continue
        try:
            yes_price = float(prices[0])
            no_price = float(prices[1])
        except (ValueError, TypeError):
            continue
        # Skip markets with no real trading
        if yes_price <= 0 or yes_price >= 1:
            continue

        vol_24h = float(m.get("volume24hr", 0) or 0)
        vol_total = float(m.get("volume", 0) or 0)
        one_day_change = float(m.get("oneDayPriceChange", 0) or 0)
        liquidity = float(m.get("liquidityNum", m.get("liquidity", 0)) or 0)

        end_date = None
        if m.get("endDate"):
            try:
                parsed = datetime.fromisoformat(m["endDate"].replace("Z", "+00:00"))
                if parsed.tzinfo is not None:
                    parsed = parsed.astimezone(timezone.utc)
                end_date = parsed.replace(tzinfo=None)
            except Exception:
                pass

        # Upsert market metadata.
        # Polymarket distinguishes "markets" (a single yes/no question) from
        # "events" (a container, e.g. "2028 Presidential Election" holding
        # all candidates). Consumer URLs resolve only the event slug —
        # the market's own slug usually 404s on the website. We persist the
        # event slug as our canonical ``slug``, falling back to the market
        # slug if no event is attached (rare; mostly orphan markets).
        events = m.get("events") or []
        event_slug = None
        if isinstance(events, list) and events:
            event_slug = events[0].get("slug")
        slug = event_slug or m.get("slug") or None
        existing_market = await db.execute(
            select(PolymarketMarket).where(PolymarketMarket.condition_id == cid)
        )
        market_row = existing_market.scalar_one_or_none()
        if not market_row:
            market_row = PolymarketMarket(
                condition_id=cid,
                question=m.get("question", ""),
                category="",
                slug=slug,
                end_date=end_date,
                volume=vol_total,
                liquidity=liquidity,
            )
            db.add(market_row)
        else:
            market_row.volume = vol_total
            market_row.liquidity = liquidity
            # Backfill slug on legacy rows (and keep it fresh if Polymarket
            # ever changes one). Skip overwrite-with-None so a transient API
            # hiccup doesn't wipe a known-good slug.
            if slug and market_row.slug != slug:
                market_row.slug = slug

        is_anomaly, anomaly_reason = _detect_anomaly(
            yes_price, vol_24h, one_day_change, previous_snaps.get(cid)
        )

        snap = PolymarketSnapshot(
            condition_id=cid,
            yes_price=yes_price,
            no_price=no_price,
            volume_24h=vol_24h,
            price_change_24h=one_day_change,
            is_anomaly=is_anomaly,
            anomaly_reason=anomaly_reason if is_anomaly else None,
        )
        db.add(snap)

        results.append({
            "condition_id": cid,
            "question": m.get("question", ""),
            "category": outcomes[0] + "/" + outcomes[1] if len(outcomes) >= 2 else "",
            "yes_price": yes_price,
            "no_price": no_price,
            "volume": vol_total,
            "volume_24h": vol_24h,
            "liquidity": liquidity,
            "end_date": m.get("endDate"),
            "price_change_24h": one_day_change,
            "is_anomaly": is_anomaly,
            "anomaly_reason": anomaly_reason if is_anomaly else None,
            "url": (
                f"https://polymarket.com/event/{slug}"
                if slug
                else f"https://polymarket.com/markets?_q={quote_plus(m.get('question', ''))}"
            ),
        })

    await db.commit()
    return results


_VALID_SORTS = {"recent", "volume", "volume_24h", "anomaly"}


async def get_latest_polymarket(
    db: AsyncSession,
    anomalies_only: bool = False,
    topic: str | None = None,
    sort: str = "anomaly",
    language: str | None = "en",
) -> list[dict]:
    """Return latest market snapshots with topic classification and sortable output.

    Args:
        anomalies_only: keep only markets flagged as anomalies.
        topic: filter results to a single topic id (see services.topic_service).
        sort: one of ``recent`` (recorded_at desc), ``volume`` (total vol desc),
            ``volume_24h`` (24h vol desc), or ``anomaly`` (anomalies first then
            volume desc — the historical default).
    """
    if sort not in _VALID_SORTS:
        sort = "anomaly"

    snap_q = select(PolymarketSnapshot).order_by(desc(PolymarketSnapshot.recorded_at)).limit(1000)
    if anomalies_only:
        snap_q = snap_q.where(PolymarketSnapshot.is_anomaly == True)  # noqa: E712
    snaps = (await db.execute(snap_q)).scalars().all()

    seen: set[str] = set()
    latest_snaps: dict[str, PolymarketSnapshot] = {}
    for s in snaps:
        if s.condition_id not in seen:
            seen.add(s.condition_id)
            latest_snaps[s.condition_id] = s

    if not latest_snaps:
        return []

    markets_q = select(PolymarketMarket).where(
        PolymarketMarket.condition_id.in_(list(latest_snaps.keys()))
    )
    markets = {m.condition_id: m for m in (await db.execute(markets_q)).scalars().all()}

    results = []
    for cid, snap in latest_snaps.items():
        market = markets.get(cid)
        question = market.question if market else cid
        # Topic is computed on the fly. ~200 markets at most; classifier is
        # cheap. If this ever becomes hot we can persist + index it (mirror
        # what we did for news_articles).
        tid = classify_text(question)
        if topic and tid != topic:
            continue
        results.append({
            "condition_id": cid,
            "question": question,
            "category": market.category if market else "",
            "topic": tid,
            "yes_price": snap.yes_price,
            "no_price": snap.no_price,
            "volume": market.volume if market else 0,
            "volume_24h": snap.volume_24h,
            "price_change_24h": snap.price_change_24h or 0,
            "is_anomaly": snap.is_anomaly,
            "anomaly_reason": snap.anomaly_reason,
            "recorded_at": _iso_utc(snap.recorded_at),
            "end_date": _iso_utc(market.end_date) if market else None,
            # Polymarket consumer URLs are slug-based; the condition_id-based
            # form 404s. Fall back to a search query if the slug isn't yet
            # backfilled (covers the brief window between deploy and the
            # next scheduler tick).
            "url": (
                f"https://polymarket.com/event/{market.slug}"
                if market and market.slug
                else f"https://polymarket.com/markets?_q={quote_plus(question)}"
            ),
        })

    # Sort key per requested mode. Using negatives instead of reverse=True so
    # the secondary key (volume) keeps a consistent direction for ties.
    if sort == "recent":
        results.sort(key=lambda x: x.get("recorded_at") or "", reverse=True)
    elif sort == "volume":
        results.sort(key=lambda x: -(x.get("volume") or 0))
    elif sort == "volume_24h":
        results.sort(key=lambda x: -(x.get("volume_24h") or 0))
    else:  # "anomaly" (default)
        results.sort(key=lambda x: (not x["is_anomaly"], -(x["volume"] or 0)))

    translation_items = [
        {"title": item["question"], "description": item.get("anomaly_reason")}
        for item in results
    ]
    translated_items = await _translate_articles_for_display(translation_items, language)
    for item, translated in zip(results, translated_items, strict=False):
        item["question"] = translated.get("title") or item["question"]
        if item.get("anomaly_reason"):
            item["anomaly_reason"] = translated.get("description") or item["anomaly_reason"]
    return results


async def get_polymarket_history(db: AsyncSession, condition_id: str, limit: int = 100) -> list[dict]:
    result = await db.execute(
        select(PolymarketSnapshot)
        .where(PolymarketSnapshot.condition_id == condition_id)
        .order_by(PolymarketSnapshot.recorded_at)
        .limit(limit)
    )
    return [
        {
            "yes_price": r.yes_price,
            "no_price": r.no_price,
            "volume_24h": r.volume_24h,
            "is_anomaly": r.is_anomaly,
            "recorded_at": _iso_utc(r.recorded_at),
        }
        for r in result.scalars().all()
    ]
