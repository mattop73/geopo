from sqlalchemy import Column, String, Float, DateTime, Integer, Boolean, Text
from sqlalchemy.sql import func
from database import Base


class PolymarketMarket(Base):
    __tablename__ = "polymarket_markets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    condition_id = Column(String, unique=True, nullable=False, index=True)
    question = Column(String, nullable=False)
    category = Column(String)
    # Persisted Polymarket URL slug. Consumer URLs are slug-based
    # (`/event/<slug>`); condition_id-based URLs 404. Populated on ingest
    # from the Gamma payload; legacy rows backfill on the next refresh.
    slug = Column(String, nullable=True)
    end_date = Column(DateTime)
    volume = Column(Float, default=0)
    liquidity = Column(Float, default=0)
    active = Column(Boolean, default=True)
    fetched_at = Column(DateTime, server_default=func.now())


class PolymarketSnapshot(Base):
    __tablename__ = "polymarket_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    condition_id = Column(String, nullable=False, index=True)
    yes_price = Column(Float)
    no_price = Column(Float)
    volume_24h = Column(Float, default=0)
    price_change_1h = Column(Float, default=0)
    price_change_24h = Column(Float, default=0)
    is_anomaly = Column(Boolean, default=False)
    anomaly_reason = Column(Text)
    recorded_at = Column(DateTime, server_default=func.now(), index=True)
