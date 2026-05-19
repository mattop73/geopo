from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.sql import func

from database import Base


class PodcastChannel(Base):
    """A YouTube channel we subscribe to as a "podcast feed".

    We keep this generic (rather than locking to ``thinkerview`` / ``gsim``)
    so adding a channel later is a row insert, not a schema change.
    """

    __tablename__ = "podcast_channels"

    id = Column(Integer, primary_key=True, autoincrement=True)
    slug = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    # ISO 639-1 code of the channel's primary content language. Used when
    # picking the best caption track AND to instruct the LLM to mirror it
    # in the summary output.
    language = Column(String, default="en")
    youtube_channel_id = Column(String, nullable=True, index=True)
    description = Column(Text)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())


class PodcastEpisode(Base):
    __tablename__ = "podcast_episodes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(
        Integer, ForeignKey("podcast_channels.id"), nullable=False, index=True
    )
    youtube_video_id = Column(String, unique=True, nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(Text)
    published_at = Column(DateTime, index=True)
    duration_sec = Column(Integer, nullable=True)
    thumbnail_url = Column(String, nullable=True)
    # Populated lazily — the discovery job inserts the row first, the
    # processing job fills these in afterwards. Allows the UI to show "still
    # processing" placeholders.
    transcript = Column(Text, nullable=True)
    transcript_lang = Column(String, nullable=True)
    summary_json = Column(JSON, nullable=True)
    summary_model = Column(String, nullable=True)
    summary_at = Column(DateTime, nullable=True)
    error = Column(Text, nullable=True)
