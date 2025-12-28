from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import relationship

from app.database.database import Base


class ForecastMetrics(Base):
    __tablename__ = "forecast_metrics"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(
        Integer,
        ForeignKey("products.id"),
        nullable=False,
        unique=True,
        index=True,
    )
    mape = Column(Float, nullable=True)
    rmse = Column(Float, nullable=True)
    wape = Column(Float, nullable=True)
    wape_adjusted = Column(Float, nullable=True)  # Censor-aware WAPE for supply-constrained days
    n_points = Column(Integer, nullable=False, default=0)
    model_type = Column(String, nullable=False, default="prophet")
    status = Column(String, nullable=False, default="ok")
    last_trained_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    product = relationship("Product", back_populates="forecast_metrics")




