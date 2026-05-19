import asyncio
import logging
import math
from datetime import datetime, timezone
from typing import Any

import yfinance as yf
from curl_cffi import requests as curl_requests
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from models.commodity import CommodityPrice


def _safe_float(v: Any) -> float | None:
    """Return ``float(v)`` if finite, else ``None`` (yfinance often returns NaN)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f

logger = logging.getLogger(__name__)


def _yf_session():
    """yfinance now requires browser impersonation to bypass Yahoo's bot detection."""
    return curl_requests.Session(impersonate="chrome")

COMMODITIES: list[dict[str, str]] = [
    # Energy
    {"ticker": "CL=F",       "name": "Crude Oil (WTI)",     "category": "energy"},
    {"ticker": "BZ=F",       "name": "Brent Crude",          "category": "energy"},
    {"ticker": "NG=F",       "name": "Natural Gas",          "category": "energy"},
    {"ticker": "RB=F",       "name": "Gasoline",             "category": "energy"},
    {"ticker": "HO=F",       "name": "Heating Oil",          "category": "energy"},
    # Metals
    {"ticker": "GC=F",       "name": "Gold",                 "category": "metals"},
    {"ticker": "SI=F",       "name": "Silver",               "category": "metals"},
    {"ticker": "HG=F",       "name": "Copper",               "category": "metals"},
    {"ticker": "PL=F",       "name": "Platinum",             "category": "metals"},
    {"ticker": "PA=F",       "name": "Palladium",            "category": "metals"},
    # Agriculture
    {"ticker": "ZW=F",       "name": "Wheat",                "category": "agriculture"},
    {"ticker": "ZC=F",       "name": "Corn",                 "category": "agriculture"},
    {"ticker": "ZS=F",       "name": "Soybeans",             "category": "agriculture"},
    {"ticker": "CC=F",       "name": "Cocoa",                "category": "agriculture"},
    {"ticker": "KC=F",       "name": "Coffee",               "category": "agriculture"},
    {"ticker": "SB=F",       "name": "Sugar",                "category": "agriculture"},
    {"ticker": "CT=F",       "name": "Cotton",               "category": "agriculture"},
    # Forex / Dollar index
    {"ticker": "DX-Y.NYB",  "name": "US Dollar Index",      "category": "forex"},
    {"ticker": "EURUSD=X",  "name": "EUR/USD",              "category": "forex"},
    {"ticker": "USDJPY=X",  "name": "USD/JPY",              "category": "forex"},
    {"ticker": "GBPUSD=X",  "name": "GBP/USD",              "category": "forex"},
]


def _fetch_quotes_sync() -> list[dict[str, Any]]:
    tickers = [c["ticker"] for c in COMMODITIES]
    meta = {c["ticker"]: c for c in COMMODITIES}
    results = []
    try:
        data = yf.download(
            tickers,
            period="2d",
            interval="1d",
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=False,
            session=_yf_session(),
        )
        for ticker, info in meta.items():
            try:
                if len(tickers) == 1:
                    df = data
                else:
                    df = data[ticker]
                if df.empty or len(df) < 1:
                    continue
                last = df.iloc[-1]
                prev = df.iloc[-2] if len(df) >= 2 else df.iloc[-1]
                price = _safe_float(last["Close"])
                prev_close = _safe_float(prev["Close"])
                # Skip if the most recent close itself is unusable — yfinance
                # occasionally returns NaN for FX tickers when the market is
                # mid-rollover; we'd rather keep the previous DB row than
                # insert garbage that breaks the NOT NULL constraint.
                if price is None:
                    logger.warning("Skipping %s — no valid close from yfinance", ticker)
                    continue
                change_pct = (
                    ((price - prev_close) / prev_close * 100)
                    if prev_close
                    else 0.0
                )
                results.append({
                    "ticker": ticker,
                    "name": info["name"],
                    "category": info["category"],
                    "price": round(price, 4),
                    "previous_close": round(prev_close, 4) if prev_close is not None else None,
                    "change_pct": round(change_pct, 4),
                    "volume": _safe_float(last.get("Volume", 0)) or 0.0,
                })
            except Exception as e:
                logger.warning(f"Failed to parse {ticker}: {e}")
    except Exception as e:
        logger.error(f"yfinance batch download failed: {e}")
    return results


async def fetch_and_store_commodities(db: AsyncSession) -> list[dict]:
    loop = asyncio.get_event_loop()
    quotes = await loop.run_in_executor(None, _fetch_quotes_sync)
    for q in quotes:
        row = CommodityPrice(**q)
        db.add(row)
    await db.commit()
    logger.info(f"Stored {len(quotes)} commodity prices")
    return quotes


async def get_latest_commodities(db: AsyncSession) -> list[dict]:
    subq = (
        select(CommodityPrice.ticker, CommodityPrice.fetched_at)
        .order_by(desc(CommodityPrice.fetched_at))
        .limit(len(COMMODITIES) * 2)
        .subquery()
    )
    result = await db.execute(
        select(CommodityPrice).order_by(desc(CommodityPrice.fetched_at)).limit(len(COMMODITIES) * 2)
    )
    rows = result.scalars().all()
    seen: set[str] = set()
    latest = []
    for row in rows:
        if row.ticker not in seen:
            seen.add(row.ticker)
            latest.append({
                "ticker": row.ticker,
                "name": row.name,
                "category": row.category,
                "price": row.price,
                "previous_close": row.previous_close,
                "change_pct": row.change_pct,
                "volume": row.volume,
                "currency": row.currency,
                "fetched_at": row.fetched_at.isoformat() if row.fetched_at else None,
            })
    return latest


def _fetch_history_sync(ticker: str, period: str, interval: str) -> list[dict]:
    try:
        df = yf.download(
            ticker,
            period=period,
            interval=interval,
            auto_adjust=True,
            progress=False,
            session=_yf_session(),
        )
        if df.empty:
            return []
        # yfinance 1.3 returns MultiIndex columns even for single ticker
        if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
            df = df.droplevel(1, axis=1)
        records = []
        for ts, row in df.iterrows():
            try:
                records.append({
                    "time": int(ts.timestamp()),
                    "open": round(float(row["Open"]), 4),
                    "high": round(float(row["High"]), 4),
                    "low": round(float(row["Low"]), 4),
                    "close": round(float(row["Close"]), 4),
                    "volume": float(row.get("Volume", 0) or 0),
                })
            except (KeyError, ValueError, TypeError):
                continue
        return records
    except Exception as e:
        logger.error(f"History fetch failed for {ticker}: {e}")
        return []


async def get_commodity_history(ticker: str, period: str = "3mo", interval: str = "1d") -> list[dict]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch_history_sync, ticker, period, interval)


def _fetch_all_histories_sync(
    period: str, interval: str, tickers: list[str] | None = None
) -> dict[str, list[dict]]:
    """Batch-download history for selected commodities in a single yfinance call.

    Returns a mapping ``ticker -> [{time, close}, ...]`` suitable for overlay charts.
    When ``tickers`` is provided, only those are downloaded — useful for the
    per-theme mini-chart. Unknown tickers are silently dropped.
    """
    all_tickers = [c["ticker"] for c in COMMODITIES]
    selected = [t for t in (tickers or all_tickers) if t in set(all_tickers)] or all_tickers
    out: dict[str, list[dict]] = {t: [] for t in selected}
    try:
        data = yf.download(
            selected,
            period=period,
            interval=interval,
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=False,
            session=_yf_session(),
        )
    except Exception as e:
        logger.error("Batch history fetch failed: %s", e)
        return out

    for ticker in selected:
        try:
            df = data[ticker] if len(selected) > 1 else data
            if df is None or df.empty:
                continue
            # Some yfinance responses return MultiIndex even after group_by
            if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
                df = df.droplevel(0, axis=1)
            series = df["Close"].dropna()
            out[ticker] = [
                {"time": int(ts.timestamp()), "close": round(float(v), 6)}
                for ts, v in series.items()
            ]
        except Exception as e:
            logger.warning("Failed to extract history for %s: %s", ticker, e)
    return out


async def get_all_commodity_histories(
    period: str = "1mo",
    interval: str = "1d",
    tickers: list[str] | None = None,
) -> dict[str, Any]:
    """Async wrapper around the batch yfinance download.

    The response includes the commodity metadata so the frontend can render a
    legend without an extra round-trip. When ``tickers`` is supplied the
    response is filtered to that subset, in the same order they were given.
    """
    loop = asyncio.get_event_loop()
    histories = await loop.run_in_executor(
        None, _fetch_all_histories_sync, period, interval, tickers
    )

    if tickers:
        wanted = set(tickers)
        commodities_by_ticker = {c["ticker"]: c for c in COMMODITIES}
        ordered_meta = [
            commodities_by_ticker[t] for t in tickers if t in commodities_by_ticker
        ]
    else:
        wanted = None
        ordered_meta = list(COMMODITIES)

    return {
        "period": period,
        "interval": interval,
        "commodities": [
            {
                "ticker": c["ticker"],
                "name": c["name"],
                "category": c["category"],
                "points": histories.get(c["ticker"], []),
            }
            for c in ordered_meta
            if wanted is None or c["ticker"] in wanted
        ],
    }
