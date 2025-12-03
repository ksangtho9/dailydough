from datetime import date, datetime, UTC

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    UniqueConstraint,
)

from app.database.database import Base


class DailyForecast(Base):
    """
    Precomputed daily forecasts for each product and bakery.

    This table is populated by background jobs (e.g. after training) so that
    API endpoints serving dashboards/history can read forecasts quickly
    without triggering heavy on-demand forecasting.
    """

    __tablename__ = "daily_forecasts"

    id = Column(Integer, primary_key=True, index=True)

    bakery_id = Column(Integer, ForeignKey("bakeries.id"), index=True, nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), index=True, nullable=False)

    date = Column(Date, nullable=False, index=True)

    # Point forecast and optional bounds
    yhat = Column(Float, nullable=False)
    yhat_lower = Column(Float, nullable=True)
    yhat_upper = Column(Float, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        UniqueConstraint(
            "bakery_id",
            "product_id",
            "date",
            name="uq_daily_forecast_bakery_product_date",
        ),
    )


