"""baseline — capture initial schema (idempotent for existing DBs)

Revision ID: 0001
Revises:
Create Date: 2026-05-14

This migration is intentionally permissive. Existing databases that were
created via :func:`Base.metadata.create_all` already contain these tables;
``checkfirst`` semantics let new installs build them from scratch without
breaking upgrades on already-populated DBs.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return name in insp.get_table_names()


def upgrade() -> None:
    if not _has_table("commodity_prices"):
        op.create_table(
            "commodity_prices",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("ticker", sa.String, nullable=False),
            sa.Column("name", sa.String, nullable=False),
            sa.Column("category", sa.String, nullable=False),
            sa.Column("price", sa.Float, nullable=False),
            sa.Column("previous_close", sa.Float),
            sa.Column("change_pct", sa.Float),
            sa.Column("volume", sa.Float),
            sa.Column("currency", sa.String, server_default="USD"),
            sa.Column(
                "fetched_at",
                sa.DateTime,
                server_default=sa.func.now(),
            ),
        )
        op.create_index("ix_commodity_prices_ticker", "commodity_prices", ["ticker"])
        op.create_index("ix_commodity_prices_fetched_at", "commodity_prices", ["fetched_at"])

    if not _has_table("news_articles"):
        op.create_table(
            "news_articles",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("source", sa.String, nullable=False),
            sa.Column("title", sa.String, nullable=False),
            sa.Column("description", sa.Text),
            sa.Column("url", sa.String, unique=True),
            sa.Column("image_url", sa.String),
            sa.Column("published_at", sa.DateTime),
            sa.Column(
                "fetched_at",
                sa.DateTime,
                server_default=sa.func.now(),
            ),
            sa.Column("category", sa.String, server_default="geopolitics"),
            sa.Column("sentiment_score", sa.String),
        )
        op.create_index("ix_news_articles_source", "news_articles", ["source"])
        op.create_index("ix_news_articles_published_at", "news_articles", ["published_at"])

    if not _has_table("polymarket_markets"):
        op.create_table(
            "polymarket_markets",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("condition_id", sa.String, unique=True, nullable=False),
            sa.Column("question", sa.String, nullable=False),
            sa.Column("category", sa.String),
            sa.Column("end_date", sa.DateTime),
            sa.Column("volume", sa.Float, server_default="0"),
            sa.Column("liquidity", sa.Float, server_default="0"),
            sa.Column("active", sa.Boolean, server_default=sa.true()),
            sa.Column("fetched_at", sa.DateTime, server_default=sa.func.now()),
        )
        op.create_index(
            "ix_polymarket_markets_condition_id", "polymarket_markets", ["condition_id"]
        )

    if not _has_table("polymarket_snapshots"):
        op.create_table(
            "polymarket_snapshots",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("condition_id", sa.String, nullable=False),
            sa.Column("yes_price", sa.Float),
            sa.Column("no_price", sa.Float),
            sa.Column("volume_24h", sa.Float, server_default="0"),
            sa.Column("price_change_1h", sa.Float, server_default="0"),
            sa.Column("price_change_24h", sa.Float, server_default="0"),
            sa.Column("is_anomaly", sa.Boolean, server_default=sa.false()),
            sa.Column("anomaly_reason", sa.Text),
            sa.Column("recorded_at", sa.DateTime, server_default=sa.func.now()),
        )
        op.create_index(
            "ix_polymarket_snapshots_condition_id", "polymarket_snapshots", ["condition_id"]
        )
        op.create_index(
            "ix_polymarket_snapshots_recorded_at", "polymarket_snapshots", ["recorded_at"]
        )


def downgrade() -> None:
    # Best-effort rollback: drop in reverse dependency order. Safe to no-op if
    # tables don't exist (caller responsibility on a partial DB).
    for tbl in ("polymarket_snapshots", "polymarket_markets", "news_articles", "commodity_prices"):
        op.execute(f"DROP TABLE IF EXISTS {tbl}")
