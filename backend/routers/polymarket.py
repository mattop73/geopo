from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from services.polymarket_service import (
    fetch_and_store_polymarket,
    get_latest_polymarket,
    get_polymarket_history,
)

router = APIRouter(prefix="/api/polymarket", tags=["polymarket"])


@router.get("/")
async def list_markets(
    anomalies_only: bool = Query(False),
    topic: str | None = Query(None, description="Filter by topic id, e.g. russia_ukraine"),
    sort: str = Query(
        "anomaly",
        description="Sort mode: recent | volume | volume_24h | anomaly",
    ),
    db: AsyncSession = Depends(get_db),
):
    return await get_latest_polymarket(
        db, anomalies_only=anomalies_only, topic=topic, sort=sort
    )


@router.post("/refresh")
async def refresh_polymarket(db: AsyncSession = Depends(get_db)):
    data = await fetch_and_store_polymarket(db)
    return {"refreshed": len(data)}


@router.get("/{condition_id}/history")
async def market_history(
    condition_id: str,
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
):
    return await get_polymarket_history(db, condition_id, limit=limit)
