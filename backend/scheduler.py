import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from database import AsyncSessionLocal
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()
scheduler = AsyncIOScheduler()


async def _job_commodities():
    async with AsyncSessionLocal() as db:
        from services.commodity_service import fetch_and_store_commodities
        try:
            await fetch_and_store_commodities(db)
        except Exception as e:
            logger.error(f"Commodity scheduler error: {e}")


async def _job_news():
    async with AsyncSessionLocal() as db:
        from services.news_service import fetch_and_store_news
        try:
            await fetch_and_store_news(db)
        except Exception as e:
            logger.error(f"News scheduler error: {e}")


async def _job_polymarket():
    async with AsyncSessionLocal() as db:
        from services.polymarket_service import fetch_and_store_polymarket
        try:
            await fetch_and_store_polymarket(db)
        except Exception as e:
            logger.error(f"Polymarket scheduler error: {e}")


async def _job_predictions():
    """Score forecasts whose target hour passed, then generate new ones.

    Scoring runs first so the freshly-elapsed predictions get resolved
    against actuals before we add the next batch. Each step uses its own
    session and is guarded so a failure in one model doesn't block the
    other.
    """
    from services.prediction_service import (
        run_quant_predictions,
        run_semantic_predictions,
        score_due_predictions,
    )

    async with AsyncSessionLocal() as db:
        try:
            await score_due_predictions(db)
        except Exception as e:
            logger.error(f"Prediction scoring error: {e}")
    async with AsyncSessionLocal() as db:
        try:
            await run_quant_predictions(db)
        except Exception as e:
            logger.error(f"Quant prediction error: {e}")
    async with AsyncSessionLocal() as db:
        try:
            await run_semantic_predictions(db)
        except Exception as e:
            logger.error(f"Semantic prediction error: {e}")


async def _job_podcasts():
    """Discover new episodes then process a handful of pending ones.

    Two separate sessions so a failed discovery doesn't block processing
    and vice-versa. The per-tick processing cap is intentionally small so
    a long initial backfill spreads over several ticks without starving
    the event loop or running up Anthropic costs in one burst.
    """
    from services.podcast_service import discover_new_episodes, process_pending
    async with AsyncSessionLocal() as db:
        try:
            await discover_new_episodes(db)
        except Exception as e:
            logger.error(f"Podcast discovery error: {e}")
    async with AsyncSessionLocal() as db:
        try:
            await process_pending(db, max_episodes=3)
        except Exception as e:
            logger.error(f"Podcast processing error: {e}")


def start_scheduler():
    scheduler.add_job(
        _job_commodities,
        trigger=IntervalTrigger(minutes=settings.commodity_refresh_minutes),
        id="commodities",
        replace_existing=True,
    )
    scheduler.add_job(
        _job_news,
        trigger=IntervalTrigger(minutes=settings.news_refresh_minutes),
        id="news",
        replace_existing=True,
    )
    scheduler.add_job(
        _job_polymarket,
        trigger=IntervalTrigger(minutes=settings.polymarket_refresh_minutes),
        id="polymarket",
        replace_existing=True,
    )
    scheduler.add_job(
        _job_podcasts,
        trigger=IntervalTrigger(minutes=settings.podcast_refresh_minutes),
        id="podcasts",
        replace_existing=True,
    )
    scheduler.add_job(
        _job_predictions,
        trigger=IntervalTrigger(minutes=settings.prediction_refresh_minutes),
        id="predictions",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started")
