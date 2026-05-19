"""Podcast endpoints. The heavy work (RSS poll, transcript fetch, Sonnet
summary) happens in the scheduler — these endpoints expose reads and a
manual ``/refresh`` trigger that runs the pipeline out-of-band so the HTTP
call returns immediately."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal, get_db
from services.podcast_service import (
    discover_new_episodes,
    get_channels,
    get_episode,
    get_episodes,
    process_pending,
    reset_episode,
)

router = APIRouter(prefix="/api/podcasts", tags=["podcasts"])


@router.get("/channels")
async def list_channels(db: AsyncSession = Depends(get_db)):
    return await get_channels(db)


@router.get("/episodes")
async def list_episodes(
    channel: str | None = Query(
        None, description="Channel slug filter (e.g. 'thinkerview')"
    ),
    limit: int = Query(60, le=200),
    db: AsyncSession = Depends(get_db),
):
    return await get_episodes(db, channel_slug=channel, limit=limit)


@router.get("/episodes/{episode_id}")
async def episode_detail(
    episode_id: int, db: AsyncSession = Depends(get_db)
):
    ep = await get_episode(db, episode_id)
    if not ep:
        raise HTTPException(status_code=404, detail="Episode not found")
    return ep


@router.post("/refresh")
async def refresh(
    background: BackgroundTasks,
    max_process: int = Query(
        5, le=20, description="Cap on episodes to fully process this call"
    ),
):
    """Trigger discovery + processing in the background, return immediately.

    The cap prevents a manual refresh from blocking the worker on a long
    backfill. Subsequent scheduler ticks will catch the remaining queue.
    """

    async def _run() -> None:
        async with AsyncSessionLocal() as db:
            await discover_new_episodes(db)
        async with AsyncSessionLocal() as db:
            await process_pending(db, max_episodes=max_process)

    background.add_task(_run)
    return {"queued": True, "max_process": max_process}


@router.post("/episodes/{episode_id}/reprocess")
async def reprocess(
    episode_id: int, db: AsyncSession = Depends(get_db)
):
    """Wipe an episode's transcript+summary so the next scheduler tick
    redoes them. Useful if a summary came out bad or the model changed."""
    if not await reset_episode(db, episode_id):
        raise HTTPException(status_code=404, detail="Episode not found")
    return {"ok": True}
