from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models import Product, SalesRecord, DailyForecast
from app.ml.inference.forecast_service import get_forecast_for_product
from app.services.daily_forecast_service import (
    get_product_daily_forecasts,
    upsert_product_daily_forecasts,
)
from app.schemas.forecast_vs_actual import (
    ForecastVsActualPoint,
    ForecastVsActualResponse,
)

router = APIRouter(tags=["forecast-vs-actual"])


@router.get(
    "/products/{product_id}/forecast-vs-actual",
    response_model=ForecastVsActualResponse,
)
def get_forecast_vs_actual(
    product_id: int,
    window_days: int = Query(60, ge=7, le=365),
    db: Session = Depends(get_db),
):
    product = db.query(Product).filter(Product.id == product_id).one_or_none()
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    end_date = date.today() - timedelta(days=1)
    start_date = end_date - timedelta(days=window_days - 1)

    rows = (
        db.query(
            SalesRecord.date.label("day"),
            func.sum(SalesRecord.quantity_sold).label("qty"),
        )
        .filter(
            SalesRecord.product_id == product_id,
            SalesRecord.date >= start_date,
            SalesRecord.date <= end_date,
        )
        .group_by(SalesRecord.date)
        .order_by(SalesRecord.date)
        .all()
    )
    actuals_by_date = {row.day: float(row.qty or 0.0) for row in rows}

    dates = []
    current = start_date
    while current <= end_date:
        dates.append(current)
        current += timedelta(days=1)

    # Prefer precomputed daily forecasts; fall back to on-demand once if needed.
    daily_rows = get_product_daily_forecasts(
        db,
        bakery_id=product.bakery_id,
        product_id=product.id,
        start_date=start_date,
        end_date=end_date,
    )

    if not daily_rows:
        try:
            forecast_out = get_forecast_for_product(
                product_id=product_id,
                days_ahead=window_days,
                db=db,
            )
            upsert_product_daily_forecasts(
                db,
                product=product,
                forecast=forecast_out,
            )
            daily_rows = get_product_daily_forecasts(
                db,
                bakery_id=product.bakery_id,
                product_id=product.id,
                start_date=start_date,
                end_date=end_date,
            )
        except Exception:
            daily_rows = []

    forecast_by_date = {row.date: float(row.yhat or 0.0) for row in daily_rows}

    points = [
        ForecastVsActualPoint(
            date=d.isoformat(),
            actual=actuals_by_date.get(d),
            forecast=forecast_by_date.get(d),
        )
        for d in dates
    ]

    return ForecastVsActualResponse(
        product_id=product.id,
        window_days=window_days,
        points=points,
    )




