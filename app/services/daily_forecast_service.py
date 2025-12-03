from __future__ import annotations

from datetime import date
from typing import Iterable, List, Sequence

from sqlalchemy.orm import Session

from app.models import DailyForecast, Product
from app.schemas.sales_record import ProductForecastOut


def upsert_product_daily_forecasts(
    db: Session,
    *,
    product: Product,
    forecast: ProductForecastOut,
) -> None:
    """
    Upsert daily forecast rows for a single product based on a ProductForecastOut.

    - Only future dates (>= today) are written.
    - Existing rows for (bakery_id, product_id, date) are updated in-place.
    """
    bakery_id = product.bakery_id
    product_id = product.id

    if not forecast.points:
        return

    # Normalize forecast points so we have at most one point per date.
    # If multiple points share the same date, the last one wins.
    points_by_date = {}
    for p in forecast.points:
        points_by_date[p.date] = p

    dates = list(points_by_date.keys())
    existing_rows: List[DailyForecast] = (
        db.query(DailyForecast)
        .filter(
            DailyForecast.bakery_id == bakery_id,
            DailyForecast.product_id == product_id,
            DailyForecast.date.in_(dates),
        )
        .all()
    )
    existing_by_date = {row.date: row for row in existing_rows}

    for point_date, point in points_by_date.items():
        yhat = float(point.yhat)
        yhat_lower = float(point.yhat_lower) if point.yhat_lower is not None else None
        yhat_upper = float(point.yhat_upper) if point.yhat_upper is not None else None

        row = existing_by_date.get(point_date)
        if row is None:
            row = DailyForecast(
                bakery_id=bakery_id,
                product_id=product_id,
                date=point_date,
                yhat=yhat,
                yhat_lower=yhat_lower,
                yhat_upper=yhat_upper,
            )
            db.add(row)
            # Ensure subsequent points for the same date (if any) update
            # this row instead of attempting a second INSERT.
            existing_by_date[point_date] = row
        else:
            row.yhat = yhat
            row.yhat_lower = yhat_lower
            row.yhat_upper = yhat_upper

    db.flush()


def get_product_daily_forecasts(
    db: Session,
    *,
    bakery_id: int,
    product_id: int,
    start_date: date,
    end_date: date,
) -> List[DailyForecast]:
    """
    Fetch daily forecasts for a product over a date range.
    """
    return (
        db.query(DailyForecast)
        .filter(
            DailyForecast.bakery_id == bakery_id,
            DailyForecast.product_id == product_id,
            DailyForecast.date >= start_date,
            DailyForecast.date <= end_date,
        )
        .order_by(DailyForecast.date.asc())
        .all()
    )


