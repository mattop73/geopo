from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from services.news_service import fetch_and_store_news, get_latest_news

router = APIRouter(prefix="/api/news", tags=["news"])


@router.get("/")
async def list_news(
    limit: int = Query(60, le=200),
    source: str | None = Query(None),
    topic: str | None = Query(None, description="Filter by topic id, e.g. russia_ukraine"),
    language: str = Query("en", pattern="^(en|fr)$"),
    db: AsyncSession = Depends(get_db),
):
    return await get_latest_news(db, limit=limit, source=source, topic=topic, language=language)


@router.post("/refresh")
async def refresh_news(db: AsyncSession = Depends(get_db)):
    return await fetch_and_store_news(db)
