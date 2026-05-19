from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from services.commodity_service import (
    fetch_and_store_commodities,
    get_latest_commodities,
    get_commodity_history,
    get_all_commodity_histories,
    COMMODITIES,
)

router = APIRouter(prefix="/api/commodities", tags=["commodities"])


@router.get("/")
async def list_commodities(db: AsyncSession = Depends(get_db)):
    return await get_latest_commodities(db)


@router.post("/refresh")
async def refresh_commodities(db: AsyncSession = Depends(get_db)):
    data = await fetch_and_store_commodities(db)
    return {"refreshed": len(data)}


@router.get("/tickers")
async def list_tickers():
    return COMMODITIES


# IMPORTANT: this static route must be declared BEFORE the dynamic
# /{ticker}/history one, otherwise FastAPI would match "history" as a ticker.
@router.get("/history/all")
async def all_histories(
    period: str = Query("1mo", description="1d,5d,1mo,3mo,6mo,1y,2y,5y"),
    interval: str = Query("1d", description="1m,5m,15m,1h,1d,1wk,1mo"),
    tickers: str | None = Query(
        None,
        description="Optional comma-separated ticker filter (e.g. CL=F,BZ=F,ZW=F)",
    ),
):
    """Close-price history for the selected commodities in a single batch.

    Intended for both the all-up overview chart and the per-theme mini chart
    (see ThemesTab). When ``tickers`` is omitted, every tracked commodity is
    returned.
    """
    ticker_list = (
        [t.strip() for t in tickers.split(",") if t.strip()]
        if tickers
        else None
    )
    return await get_all_commodity_histories(period, interval, tickers=ticker_list)


@router.get("/{ticker}/history")
async def commodity_history(
    ticker: str,
    period: str = Query("3mo", description="1d,5d,1mo,3mo,6mo,1y,2y,5y"),
    interval: str = Query("1d", description="1m,5m,15m,1h,1d,1wk,1mo"),
):
    return await get_commodity_history(ticker, period, interval)
