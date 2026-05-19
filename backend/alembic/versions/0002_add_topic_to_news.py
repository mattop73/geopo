"""add topic column to news_articles + backfill via classifier

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-14

Adds a persisted ``topic`` column so we can run SQL filters / aggregations
per theme instead of classifying every row on read. Existing rows are
back-filled by running the same keyword classifier used at runtime.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return any(c["name"] == column for c in insp.get_columns(table))


def upgrade() -> None:
    # Make the classifier importable. The alembic env already prepends
    # backend/ to sys.path, but being defensive lets `alembic upgrade head`
    # work from any CWD.
    backend_dir = Path(__file__).resolve().parents[2]
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
    from services.topic_service import classify_text

    if not _has_column("news_articles", "topic"):
        with op.batch_alter_table("news_articles", recreate="auto") as batch:
            batch.add_column(sa.Column("topic", sa.String, nullable=True))
        op.create_index(
            "ix_news_articles_topic", "news_articles", ["topic"]
        )

    # Backfill existing rows. Doing this in Python (rather than pure SQL with a
    # massive CASE expression) keeps the topic logic in one place — the
    # classifier — so future keyword additions stay consistent.
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, title, description FROM news_articles WHERE topic IS NULL")
    ).fetchall()
    for row in rows:
        text = f"{row.title or ''} {row.description or ''}"
        tid = classify_text(text)
        bind.execute(
            sa.text("UPDATE news_articles SET topic = :tid WHERE id = :id"),
            {"tid": tid, "id": row.id},
        )


def downgrade() -> None:
    op.drop_index("ix_news_articles_topic", table_name="news_articles")
    with op.batch_alter_table("news_articles", recreate="auto") as batch:
        batch.drop_column("topic")
