from sqlalchemy import Column, String, Float, DateTime, Integer
from sqlalchemy.sql import func
from database import Base


class CommodityPrice(Base):
    __tablename__ = "commodity_prices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    category = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    previous_close = Column(Float)
    change_pct = Column(Float)
    volume = Column(Float)
    currency = Column(String, default="USD")
    fetched_at = Column(DateTime, server_default=func.now(), index=True)
