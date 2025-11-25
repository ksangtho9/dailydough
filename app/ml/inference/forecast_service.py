from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app.ml.forecast_service import ForecastService
from app.schemas.sales_record import ForecastPointOut, ProductForecastOut


def _iso_to_date(value: str) -> date:
    """Convert ISO-8601 strings coming from the ML layer into date objects."""
    return date.fromisoformat(value)


def get_forecast_for_product(
    *,
    product_id: int,
    days_ahead: int = 14,
    db: Optional[Session] = None,
) -> ProductForecastOut:
    """
    Entry point used by the FastAPI layer.

    Delegates to the refactored ML ForecastService and adapts the result into
    the Pydantic schema expected by the routes.
    """
    if db is None:
        raise ValueError("Database session is required to forecast a product.")

    service = ForecastService()
    result = service.generate_prophet_forecast_for_product(
        db=db,
        product_id=product_id,
        horizon_days=days_ahead,
    )

    points = [
        ForecastPointOut(
            date=_iso_to_date(point.date),
            yhat=point.yhat,
            yhat_lower=point.yhat_lower,
            yhat_upper=point.yhat_upper,
        )
        for point in result.points
    ]

    return ProductForecastOut(
        product_id=result.product_id,
        product_name=result.product_name,
        horizon_days=result.horizon_days,
        points=points,
    )


