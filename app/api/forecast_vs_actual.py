from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models import Product, SalesRecord
from app.ml.inference.forecast_service import get_forecast_for_product
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

    try:
        forecast = get_forecast_for_product(
            product_id=product_id,
            days_ahead=window_days,
            db=db,
        )
    except Exception:
        forecast = None

    forecast_points = []
    if forecast is not None:
        forecast_points = getattr(forecast, "points", forecast.get("points", []))
    forecast_by_date_str = {}
    for p in forecast_points:
        point_date = getattr(p, "date", p.get("date"))
        yhat = getattr(p, "yhat", p.get("yhat"))
        if point_date and yhat is not None:
            forecast_by_date_str[str(point_date)] = float(yhat)

    points = [
        ForecastVsActualPoint(
            date=d.isoformat(),
            actual=actuals_by_date.get(d),
            forecast=forecast_by_date_str.get(d.isoformat()),
        )
        for d in dates
    ]

    return ForecastVsActualResponse(
        product_id=product.id,
        window_days=window_days,
        points=points,
    )




