"""Predictions API — recent forecasts, performance metrics, manual run.

Both models (quant + semantic) are surfaced through one set of endpoints.
The hourly scheduler job normally drives generation and scoring; ``POST
/run`` exists so the dashboard can be seeded/verified on demand without
waiting for the next tick.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from services.prediction_service import (
    get_performance,
    get_predictions,
    run_quant_predictions,
    run_semantic_predictions,
    score_due_predictions,
)

router = APIRouter(prefix="/api/predictions", tags=["predictions"])


@router.get("/")
async def list_predictions(
    model: str | None = Query(None, description="Filter by model: quant | semantic"),
    ticker: str | None = Query(None, description="Filter by commodity ticker"),
    scored_only: bool = Query(False, description="Only return resolved predictions"),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    return await get_predictions(
        db, model=model, ticker=ticker, scored_only=scored_only, limit=limit
    )


@router.get("/performance")
async def performance(
    window_days: int = Query(7, ge=1, le=90),
    ticker: str | None = Query(None, description="Optional commodity ticker filter"),
    db: AsyncSession = Depends(get_db),
):
    return await get_performance(db, window_days=window_days, ticker=ticker)


@router.post("/run")
async def run_predictions(db: AsyncSession = Depends(get_db)):
    """Score any due predictions, then generate a fresh batch from both models."""
    scored = await score_due_predictions(db)
    quant = await run_quant_predictions(db)
    semantic = await run_semantic_predictions(db)
    return {"scored": scored, "quant": quant, "semantic": semantic}
