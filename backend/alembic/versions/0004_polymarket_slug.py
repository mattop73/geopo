"""add slug column to polymarket_markets

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-18

The frontend builds market URLs as ``https://polymarket.com/event/<slug>``,
but Polymarket's consumer site does not resolve those by ``condition_id``
(hex hash) — it 404s. The slug *is* present in the Gamma API payload but
was previously only kept in the transient response dict, never persisted.
This migration adds the column. Existing rows are nullable until the next
scheduler tick fills them in.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return any(c["name"] == column for c in insp.get_columns(table))


def upgrade() -> None:
    if not _has_column("polymarket_markets", "slug"):
        with op.batch_alter_table("polymarket_markets", recreate="auto") as batch:
            batch.add_column(sa.Column("slug", sa.String, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("polymarket_markets", recreate="auto") as batch:
        batch.drop_column("slug")
