"""add predictions table

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-05

Stores next-hour commodity forecasts from both the quantitative baseline
and the semantic/LLM model in a single table (discriminated by ``model``).
The ``actual_*`` columns are populated by the scorer once each prediction's
target hour has elapsed, which is what powers the performance dashboard.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(table: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return insp.has_table(table)


def upgrade() -> None:
    if _has_table("predictions"):
        return
    op.create_table(
        "predictions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("model", sa.String, nullable=False),
        sa.Column("ticker", sa.String, nullable=False),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("category", sa.String, nullable=False),
        sa.Column("made_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("target_at", sa.DateTime, nullable=False),
        sa.Column("base_price", sa.Float, nullable=False),
        sa.Column("predicted_direction", sa.String),
        sa.Column("predicted_change_pct", sa.Float),
        sa.Column("predicted_price", sa.Float),
        sa.Column("predicted_low", sa.Float),
        sa.Column("predicted_high", sa.Float),
        sa.Column("confidence", sa.Float),
        sa.Column("rationale", sa.Text),
        sa.Column("actual_price", sa.Float),
        sa.Column("actual_change_pct", sa.Float),
        sa.Column("actual_direction", sa.String),
        sa.Column("direction_correct", sa.Boolean),
        sa.Column("abs_error_pct", sa.Float),
        sa.Column("in_band", sa.Boolean),
        sa.Column("scored_at", sa.DateTime),
    )
    op.create_index("ix_predictions_model", "predictions", ["model"])
    op.create_index("ix_predictions_ticker", "predictions", ["ticker"])
    op.create_index("ix_predictions_made_at", "predictions", ["made_at"])
    op.create_index("ix_predictions_target_at", "predictions", ["target_at"])


def downgrade() -> None:
    op.drop_index("ix_predictions_target_at", table_name="predictions")
    op.drop_index("ix_predictions_made_at", table_name="predictions")
    op.drop_index("ix_predictions_ticker", table_name="predictions")
    op.drop_index("ix_predictions_model", table_name="predictions")
    op.drop_table("predictions")
