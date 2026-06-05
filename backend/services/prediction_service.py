"""Next-hour commodity prediction: generation, scoring, and metrics.

Two models write into the single ``predictions`` table:

- ``quant``: a lightweight statistical baseline. For each commodity we take
  the recent hourly close series, model the next-hour log return with an
  EWMA of recent returns (the "drift"), and size an uncertainty band from
  the EWMA volatility. Intentionally simple and dependency-free (numpy /
  pandas only) so a real ML model can later replace :func:`_quant_forecast`
  without touching scheduling, scoring, or the UI.

- ``semantic``: one LLM call per hour. We assemble the same per-theme news
  + Polymarket context the Themes tab uses, then ask the model to output a
  strict-JSON array of ``{ticker, direction, expected_change_pct,
  confidence, rationale}`` for every open commodity.

Both models only forecast commodities whose market is currently open (the
latest hourly bar is fresh). The scorer fills the ``actual_*`` columns once
a prediction's target hour has elapsed, which powers the dashboard.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models.prediction import Prediction
from services.commodity_service import (
    COMMODITIES,
    get_all_commodity_histories,
    get_latest_commodities,
)
from services.llm_service import stream_llm
from services.news_service import get_latest_news
from services.polymarket_service import get_latest_polymarket
from services.topic_service import all_topics, classify_text

logger = logging.getLogger(__name__)
settings = get_settings()

# A market counts as "open" if its most recent hourly bar is younger than
# this. yfinance hourly bars lag a little, so we allow ~1.5 bars of slack.
FRESH_BAR_MAX_AGE_SEC = 90 * 60

# Moves smaller than this (in %) are treated as "flat" rather than up/down,
# both for the quant direction call and when labelling the realized move.
FLAT_THRESHOLD_PCT = 0.02

# Half-life-ish smoothing window (in hourly bars) for the EWMA drift/vol.
EWMA_SPAN = 12

# Band half-width in EWMA standard deviations (~68% nominal coverage).
Z_BAND = 1.0

MODEL_QUANT = "quant"
MODEL_SEMANTIC = "semantic"

# Per-theme context caps for the LLM prompt — keep the call cheap.
LLM_MAX_NEWS_PER_THEME = 6
LLM_MAX_MARKETS_PER_THEME = 4


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #
def _utcnow() -> datetime:
    """Naive UTC ``datetime`` matching how rows are stored in the DB."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_utc_epoch(dt: datetime) -> float:
    """Interpret a naive DB datetime as UTC and return epoch seconds."""
    return dt.replace(tzinfo=timezone.utc).timestamp()


def _classify_direction(change_pct: float) -> str:
    if change_pct > FLAT_THRESHOLD_PCT:
        return "up"
    if change_pct < -FLAT_THRESHOLD_PCT:
        return "down"
    return "flat"


def _closes(points: list[dict]) -> list[tuple[int, float]]:
    """Extract ``(epoch, close)`` tuples, dropping non-finite values."""
    out: list[tuple[int, float]] = []
    for p in points:
        t = p.get("time")
        c = p.get("close")
        if t is None or c is None:
            continue
        try:
            cf = float(c)
        except (TypeError, ValueError):
            continue
        if np.isfinite(cf):
            out.append((int(t), cf))
    return out


def _is_open(closes: list[tuple[int, float]], now_epoch: float) -> bool:
    if not closes:
        return False
    return (now_epoch - closes[-1][0]) <= FRESH_BAR_MAX_AGE_SEC


async def _fetch_hourly_histories() -> dict[str, list[tuple[int, float]]]:
    """Return ``{ticker: [(epoch, close), ...]}`` for all commodities.

    Uses a single batched yfinance download (``1mo`` of ``1h`` bars), which
    gives the quant model enough history for a stable EWMA while staying to
    one network round-trip per run.
    """
    payload = await get_all_commodity_histories(period="1mo", interval="1h")
    out: dict[str, list[tuple[int, float]]] = {}
    for c in payload.get("commodities", []):
        out[c["ticker"]] = _closes(c.get("points", []))
    return out


# --------------------------------------------------------------------------- #
# Quant model
# --------------------------------------------------------------------------- #
def _quant_forecast(closes: list[tuple[int, float]]) -> dict[str, Any] | None:
    """EWMA-drift + volatility-band next-hour forecast from a close series.

    Returns ``None`` when there isn't enough data to fit. The returned dict
    carries the fields the :class:`Prediction` row needs.
    """
    if len(closes) < EWMA_SPAN + 2:
        return None

    prices = pd.Series([c for _, c in closes], dtype="float64")
    last_price = float(prices.iloc[-1])
    if last_price <= 0:
        return None

    log_ret = np.log(prices / prices.shift(1)).dropna()
    if log_ret.empty:
        return None

    mu = float(log_ret.ewm(span=EWMA_SPAN).mean().iloc[-1])
    sigma = float(log_ret.ewm(span=EWMA_SPAN).std().iloc[-1])
    if not np.isfinite(mu):
        mu = 0.0
    if not np.isfinite(sigma) or sigma < 0:
        sigma = 0.0

    predicted_price = last_price * float(np.exp(mu))
    change_pct = (predicted_price - last_price) / last_price * 100.0
    half_width = last_price * float(np.exp(Z_BAND * sigma) - 1.0)

    return {
        "base_price": round(last_price, 6),
        "predicted_price": round(predicted_price, 6),
        "predicted_change_pct": round(change_pct, 4),
        "predicted_direction": _classify_direction(change_pct),
        "predicted_low": round(predicted_price - half_width, 6),
        "predicted_high": round(predicted_price + half_width, 6),
    }


async def run_quant_predictions(db: AsyncSession) -> int:
    """Generate and persist quant forecasts for every open commodity."""
    histories = await _fetch_hourly_histories()
    now = _utcnow()
    now_epoch = _as_utc_epoch(now)
    target_at = now + timedelta(minutes=settings.prediction_horizon_minutes)
    meta = {c["ticker"]: c for c in COMMODITIES}

    inserted = 0
    for ticker, closes in histories.items():
        if not _is_open(closes, now_epoch):
            continue
        forecast = _quant_forecast(closes)
        if forecast is None:
            continue
        info = meta.get(ticker, {})
        db.add(
            Prediction(
                model=MODEL_QUANT,
                ticker=ticker,
                name=info.get("name", ticker),
                category=info.get("category", "unknown"),
                made_at=now,
                target_at=target_at,
                **forecast,
            )
        )
        inserted += 1

    await db.commit()
    logger.info("Quant predictions: stored %d forecasts", inserted)
    return inserted


# --------------------------------------------------------------------------- #
# Semantic model
# --------------------------------------------------------------------------- #
SEMANTIC_SYSTEM = (
    "You are a commodities strategist. Given geopolitical news flow and "
    "prediction-market odds, you estimate the very-short-term (next hour) "
    "direction and magnitude of commodity futures prices. You are calibrated "
    "and concise. You ALWAYS reply with valid JSON only — no prose, no "
    "markdown fences."
)


def _build_theme_context(
    news: list[dict],
    markets: list[dict],
) -> str:
    """Bucket news + markets by theme and render a compact text context."""
    blocks: list[str] = []
    for topic in all_topics():
        tid = topic["id"]
        topic_news = [
            n for n in news
            if classify_text(f"{n.get('title', '')} {n.get('description', '')}") == tid
        ][:LLM_MAX_NEWS_PER_THEME]
        topic_markets = [
            m for m in markets
            if classify_text(m.get("question", "")) == tid
        ][:LLM_MAX_MARKETS_PER_THEME]
        if not topic_news and not topic_markets:
            continue

        lines = [f"### {topic['label']}"]
        if topic.get("commodity_tickers"):
            lines.append(f"linked tickers: {', '.join(topic['commodity_tickers'])}")
        for n in topic_news:
            lines.append(f"- NEWS [{n.get('source', '?')}] {n.get('title', '')}")
        for m in topic_markets:
            yes = (m.get("yes_price") or 0) * 100
            d24 = (m.get("price_change_24h") or 0) * 100
            lines.append(
                f"- MARKET {m.get('question', '')} — YES {yes:.0f}% ({d24:+.1f}pts/24h)"
            )
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks) if blocks else "(no notable news or markets)"


async def _collect_llm(prompt: str, model: str, system: str) -> str:
    chunks: list[str] = []
    async for chunk in stream_llm(prompt, model, system=system):
        chunks.append(chunk)
    return "".join(chunks)


def _extract_json_array(text: str) -> list[dict] | None:
    """Best-effort extraction of a JSON array from an LLM response."""
    if not text:
        return None
    # Provider error strings come through as plain chunks — never parse those.
    for marker in ("[Anthropic error", "[OpenAI error", "[Ollama error", "[No "):
        if marker in text:
            logger.warning("Semantic LLM returned an error/empty response: %s", text[:200])
            return None
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        logger.warning("Semantic LLM response had no JSON array: %s", text[:200])
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        logger.warning("Semantic LLM JSON parse failed (%s): %s", exc, text[:200])
        return None
    return parsed if isinstance(parsed, list) else None


async def run_semantic_predictions(db: AsyncSession) -> int:
    """Generate and persist LLM-based forecasts for every open commodity."""
    histories = await _fetch_hourly_histories()
    now = _utcnow()
    now_epoch = _as_utc_epoch(now)
    target_at = now + timedelta(minutes=settings.prediction_horizon_minutes)
    meta = {c["ticker"]: c for c in COMMODITIES}

    open_tickers = {
        t: closes[-1][1]
        for t, closes in histories.items()
        if _is_open(closes, now_epoch)
    }
    if not open_tickers:
        logger.info("Semantic predictions: no open markets, skipping")
        return 0

    news = await get_latest_news(db, limit=200)
    markets = await get_latest_polymarket(db)
    context = _build_theme_context(news, markets)

    ticker_lines = "\n".join(
        f"- {t} ({meta.get(t, {}).get('name', t)}): last {price:.4f}"
        for t, price in open_tickers.items()
    )

    prompt = f"""Based on the geopolitical context below, forecast the NEXT HOUR
move for each commodity listed. Consider how the news flow and prediction-market
odds should move each commodity over the next 60 minutes.

For EVERY ticker in the COMMODITIES list, return one object with:
- "ticker": the exact ticker string
- "direction": one of "up", "down", "flat"
- "expected_change_pct": signed number, the expected percent move over the hour (e.g. 0.15 or -0.30)
- "confidence": number from 0 to 1
- "rationale": one short sentence (max 25 words)

Reply with ONLY a JSON array of these objects, nothing else.

## CONTEXT
{context}

## COMMODITIES
{ticker_lines}
"""

    model = settings.default_llm_model
    raw = await _collect_llm(prompt, model, SEMANTIC_SYSTEM)
    items = _extract_json_array(raw)
    if not items:
        return 0

    inserted = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        ticker = item.get("ticker")
        if ticker not in open_tickers:
            continue
        base_price = open_tickers[ticker]
        try:
            change_pct = float(item.get("expected_change_pct", 0.0))
        except (TypeError, ValueError):
            change_pct = 0.0
        direction = str(item.get("direction", "")).lower().strip()
        if direction not in ("up", "down", "flat"):
            direction = _classify_direction(change_pct)
        try:
            confidence = float(item.get("confidence"))
        except (TypeError, ValueError):
            confidence = None
        if confidence is not None:
            confidence = max(0.0, min(1.0, confidence))

        info = meta.get(ticker, {})
        db.add(
            Prediction(
                model=MODEL_SEMANTIC,
                ticker=ticker,
                name=info.get("name", ticker),
                category=info.get("category", "unknown"),
                made_at=now,
                target_at=target_at,
                base_price=round(base_price, 6),
                predicted_direction=direction,
                predicted_change_pct=round(change_pct, 4),
                confidence=confidence,
                rationale=str(item.get("rationale", ""))[:500] or None,
            )
        )
        inserted += 1

    await db.commit()
    logger.info("Semantic predictions: stored %d forecasts", inserted)
    return inserted


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #
def _actual_close_at(closes: list[tuple[int, float]], target_epoch: float) -> float | None:
    """Pick the close of the first bar at/after ``target_epoch``.

    Falls back to the most recent available bar so a slightly-late scorer
    run still resolves. Returns ``None`` if there's no usable data.
    """
    if not closes:
        return None
    for ts, close in closes:
        if ts >= target_epoch:
            return close
    return closes[-1][1]


async def score_due_predictions(db: AsyncSession) -> int:
    """Fill actuals + metrics for predictions whose target hour has passed."""
    now = _utcnow()
    result = await db.execute(
        select(Prediction).where(
            Prediction.target_at <= now,
            Prediction.actual_price.is_(None),
        )
    )
    due = list(result.scalars().all())
    if not due:
        return 0

    histories = await _fetch_hourly_histories()
    scored = 0
    for pred in due:
        closes = histories.get(pred.ticker, [])
        target_epoch = _as_utc_epoch(pred.target_at)
        actual = _actual_close_at(closes, target_epoch)
        if actual is None or not pred.base_price:
            continue

        actual_change_pct = (actual - pred.base_price) / pred.base_price * 100.0
        actual_direction = _classify_direction(actual_change_pct)

        pred.actual_price = round(actual, 6)
        pred.actual_change_pct = round(actual_change_pct, 4)
        pred.actual_direction = actual_direction
        pred.direction_correct = pred.predicted_direction == actual_direction
        if pred.predicted_change_pct is not None:
            pred.abs_error_pct = round(
                abs(pred.predicted_change_pct - actual_change_pct), 4
            )
        if pred.predicted_low is not None and pred.predicted_high is not None:
            pred.in_band = pred.predicted_low <= actual <= pred.predicted_high
        pred.scored_at = now
        scored += 1

    await db.commit()
    logger.info("Scored %d due predictions", scored)
    return scored


# --------------------------------------------------------------------------- #
# Reads for the dashboard
# --------------------------------------------------------------------------- #
def _serialize(pred: Prediction) -> dict[str, Any]:
    return {
        "id": pred.id,
        "model": pred.model,
        "ticker": pred.ticker,
        "name": pred.name,
        "category": pred.category,
        "made_at": pred.made_at.isoformat() if pred.made_at else None,
        "target_at": pred.target_at.isoformat() if pred.target_at else None,
        "base_price": pred.base_price,
        "predicted_direction": pred.predicted_direction,
        "predicted_change_pct": pred.predicted_change_pct,
        "predicted_price": pred.predicted_price,
        "predicted_low": pred.predicted_low,
        "predicted_high": pred.predicted_high,
        "confidence": pred.confidence,
        "rationale": pred.rationale,
        "actual_price": pred.actual_price,
        "actual_change_pct": pred.actual_change_pct,
        "actual_direction": pred.actual_direction,
        "direction_correct": pred.direction_correct,
        "abs_error_pct": pred.abs_error_pct,
        "in_band": pred.in_band,
        "scored_at": pred.scored_at.isoformat() if pred.scored_at else None,
    }


async def get_predictions(
    db: AsyncSession,
    model: str | None = None,
    ticker: str | None = None,
    scored_only: bool = False,
    limit: int = 100,
) -> list[dict[str, Any]]:
    stmt = select(Prediction).order_by(Prediction.made_at.desc())
    if model:
        stmt = stmt.where(Prediction.model == model)
    if ticker:
        stmt = stmt.where(Prediction.ticker == ticker)
    if scored_only:
        stmt = stmt.where(Prediction.scored_at.is_not(None))
    stmt = stmt.limit(max(1, min(limit, 1000)))
    result = await db.execute(stmt)
    return [_serialize(p) for p in result.scalars().all()]


def _empty_metrics(model: str) -> dict[str, Any]:
    return {
        "model": model,
        "scored_count": 0,
        "direction_accuracy": None,
        "mean_abs_error_pct": None,
        "band_coverage": None,
    }


async def get_performance(
    db: AsyncSession,
    window_days: int = 7,
    ticker: str | None = None,
) -> dict[str, Any]:
    """Aggregate per-model accuracy plus a daily accuracy time series."""
    since = _utcnow() - timedelta(days=max(1, window_days))
    stmt = select(Prediction).where(
        Prediction.scored_at.is_not(None),
        Prediction.scored_at >= since,
    )
    if ticker:
        stmt = stmt.where(Prediction.ticker == ticker)
    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    models = [MODEL_QUANT, MODEL_SEMANTIC]
    metrics = {m: _empty_metrics(m) for m in models}
    # day -> model -> [correct, total]
    daily: dict[str, dict[str, list[int]]] = {}

    for m in models:
        subset = [r for r in rows if r.model == m]
        n = len(subset)
        if n == 0:
            continue
        correct = [1 if r.direction_correct else 0 for r in subset]
        errors = [r.abs_error_pct for r in subset if r.abs_error_pct is not None]
        coverage = [1 if r.in_band else 0 for r in subset if r.in_band is not None]
        metrics[m].update(
            scored_count=n,
            direction_accuracy=round(sum(correct) / n * 100, 2),
            mean_abs_error_pct=round(sum(errors) / len(errors), 4) if errors else None,
            band_coverage=round(sum(coverage) / len(coverage) * 100, 2) if coverage else None,
        )

    for r in rows:
        day = r.scored_at.date().isoformat()
        bucket = daily.setdefault(day, {m: [0, 0] for m in models})
        bucket[r.model][1] += 1
        if r.direction_correct:
            bucket[r.model][0] += 1

    series = []
    for day in sorted(daily.keys()):
        entry: dict[str, Any] = {"date": day}
        for m in models:
            correct, total = daily[day][m]
            entry[m] = round(correct / total * 100, 2) if total else None
        series.append(entry)

    return {
        "window_days": window_days,
        "models": [metrics[m] for m in models],
        "daily_accuracy": series,
    }
