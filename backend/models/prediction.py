from sqlalchemy import Column, String, Float, DateTime, Integer, Boolean, Text
from sqlalchemy.sql import func

from database import Base


class Prediction(Base):
    """A single next-hour forecast for one commodity from one model.

    Both the quantitative baseline (``model='quant'``) and the semantic /
    LLM model (``model='semantic'``) write rows into this one table. The
    ``actual_*`` columns stay NULL until the target hour passes and the
    scorer fills them in, which is what powers the performance dashboard.
    """

    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # Discriminator: 'quant' | 'semantic'.
    model = Column(String, nullable=False, index=True)
    ticker = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    category = Column(String, nullable=False)

    # When the forecast was generated, and the hour it forecasts for.
    made_at = Column(DateTime, server_default=func.now(), index=True)
    target_at = Column(DateTime, nullable=False, index=True)
    # Price at ``made_at`` — the anchor the change_pct is measured against.
    base_price = Column(Float, nullable=False)

    # --- Prediction ------------------------------------------------------
    predicted_direction = Column(String)            # 'up' | 'down' | 'flat'
    predicted_change_pct = Column(Float)            # expected % move over the hour
    predicted_price = Column(Float)                 # quant point forecast
    predicted_low = Column(Float)                   # quant uncertainty band (low)
    predicted_high = Column(Float)                  # quant uncertainty band (high)
    confidence = Column(Float)                      # semantic confidence 0-1
    rationale = Column(Text)                        # semantic explanation

    # --- Actuals (filled by the scorer once target_at passes) ------------
    actual_price = Column(Float)
    actual_change_pct = Column(Float)
    actual_direction = Column(String)
    direction_correct = Column(Boolean)
    abs_error_pct = Column(Float)                   # |predicted_change_pct - actual_change_pct|
    in_band = Column(Boolean)                       # quant: actual within [low, high]
    scored_at = Column(DateTime)
