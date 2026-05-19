from sqlalchemy import Column, String, DateTime, Integer, Text
from sqlalchemy.sql import func
from database import Base


class NewsArticle(Base):
    __tablename__ = "news_articles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(Text)
    url = Column(String, unique=True)
    image_url = Column(String)
    published_at = Column(DateTime, index=True)
    fetched_at = Column(DateTime, server_default=func.now())
    category = Column(String, default="geopolitics")
    sentiment_score = Column(String)
    # Persisted thematic bucket. Computed via services.topic_service.classify_text
    # at ingestion time so SQL filtering / per-topic aggregations don't pay the
    # classifier cost on read. Nullable for back-compat with legacy rows the
    # migration backfills.
    topic = Column(String, index=True)
