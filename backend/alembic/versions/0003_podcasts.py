"""add podcast channels and episodes tables (seeded with two channels)

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-15

Creates two tables for the podcast tab:

* ``podcast_channels`` — registry of YouTube channels we subscribe to.
* ``podcast_episodes`` — discovered episodes with optional transcript + LLM
  summary populated lazily by the scheduler.

Seeds two channels by default:
* Thinkerview (French, long-form interviews — geopolitics, energy, economics)
* The Great Simplification by Nate Hagens (English — energy/ecology/economics)
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if not _has_table("podcast_channels"):
        op.create_table(
            "podcast_channels",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("slug", sa.String, nullable=False),
            sa.Column("name", sa.String, nullable=False),
            sa.Column("language", sa.String, server_default="en"),
            sa.Column("youtube_channel_id", sa.String, nullable=True),
            sa.Column("description", sa.Text),
            # ``sa.true()`` emits ``1`` on SQLite and ``TRUE`` on Postgres,
            # avoiding the dialect-specific ``sa.text("1")`` we used before.
            sa.Column("active", sa.Boolean, server_default=sa.true()),
            sa.Column(
                "created_at", sa.DateTime, server_default=sa.func.now()
            ),
            sa.UniqueConstraint("slug", name="uq_podcast_channels_slug"),
        )
        op.create_index(
            "ix_podcast_channels_slug", "podcast_channels", ["slug"]
        )
        op.create_index(
            "ix_podcast_channels_youtube_channel_id",
            "podcast_channels",
            ["youtube_channel_id"],
        )

    if not _has_table("podcast_episodes"):
        op.create_table(
            "podcast_episodes",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column(
                "channel_id",
                sa.Integer,
                sa.ForeignKey("podcast_channels.id"),
                nullable=False,
            ),
            sa.Column("youtube_video_id", sa.String, nullable=False),
            sa.Column("title", sa.String, nullable=False),
            sa.Column("description", sa.Text),
            sa.Column("published_at", sa.DateTime),
            sa.Column("duration_sec", sa.Integer, nullable=True),
            sa.Column("thumbnail_url", sa.String, nullable=True),
            sa.Column("transcript", sa.Text, nullable=True),
            sa.Column("transcript_lang", sa.String, nullable=True),
            sa.Column("summary_json", sa.JSON, nullable=True),
            sa.Column("summary_model", sa.String, nullable=True),
            sa.Column("summary_at", sa.DateTime, nullable=True),
            sa.Column("error", sa.Text, nullable=True),
            sa.UniqueConstraint(
                "youtube_video_id", name="uq_podcast_episodes_youtube_video_id"
            ),
        )
        op.create_index(
            "ix_podcast_episodes_channel_id",
            "podcast_episodes",
            ["channel_id"],
        )
        op.create_index(
            "ix_podcast_episodes_published_at",
            "podcast_episodes",
            ["published_at"],
        )
        op.create_index(
            "ix_podcast_episodes_youtube_video_id",
            "podcast_episodes",
            ["youtube_video_id"],
        )

    # Seed the two channels — dialect-agnostic: we check existence in Python
    # first rather than relying on SQLite's ``INSERT OR IGNORE`` or
    # Postgres's ``ON CONFLICT DO NOTHING``. Keeps the migration portable.
    seeds = [
        {
            "slug": "thinkerview",
            "name": "Thinkerview",
            "language": "fr",
            "youtube_channel_id": "UCQgWpmt02UtJkyO32HGUASQ",
            "description": "Interviews françaises de fond — politique, économie, géopolitique.",
            "active": True,
        },
        {
            "slug": "great_simplification",
            "name": "The Great Simplification",
            "language": "en",
            "youtube_channel_id": "UCWJOjGOpN8oSVr_OoJLzk9g",
            "description": "Nate Hagens on the human predicament — energy, ecology, economics.",
            "active": True,
        },
    ]
    bind = op.get_bind()
    for s in seeds:
        exists = bind.execute(
            sa.text("SELECT 1 FROM podcast_channels WHERE slug = :slug"),
            {"slug": s["slug"]},
        ).first()
        if exists:
            continue
        bind.execute(
            sa.text(
                "INSERT INTO podcast_channels "
                "(slug, name, language, youtube_channel_id, description, active) "
                "VALUES (:slug, :name, :language, :youtube_channel_id, "
                ":description, :active)"
            ),
            s,
        )


def downgrade() -> None:
    op.drop_index(
        "ix_podcast_episodes_youtube_video_id", table_name="podcast_episodes"
    )
    op.drop_index(
        "ix_podcast_episodes_published_at", table_name="podcast_episodes"
    )
    op.drop_index(
        "ix_podcast_episodes_channel_id", table_name="podcast_episodes"
    )
    op.drop_table("podcast_episodes")
    op.drop_index(
        "ix_podcast_channels_youtube_channel_id",
        table_name="podcast_channels",
    )
    op.drop_index(
        "ix_podcast_channels_slug", table_name="podcast_channels"
    )
    op.drop_table("podcast_channels")
