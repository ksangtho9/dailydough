from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
import numpy as np

from app.database.database import get_db
from app.models import Product, SalesRecord, DailyForecast
from app.ml.inference.forecast_service import get_forecast_for_product
from app.ml.metrics import calculate_wape
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
    start_date: Optional[date] = Query(None, description="Start date (inclusive)"),
    end_date: Optional[date] = Query(None, description="End date (inclusive)"),
    db: Session = Depends(get_db),
):
    """
    Get forecast vs actual comparison for a product.
    
    If start_date and end_date are provided, uses those dates.
    Otherwise defaults to last 60 days.
    """
    product = db.query(Product).filter(Product.id == product_id).one_or_none()
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    # Determine date range
    if start_date is None or end_date is None:
        # Default to last 60 days
        end_date = date.today() - timedelta(days=1)
        start_date = end_date - timedelta(days=59)
    else:
        if start_date > end_date:
            raise HTTPException(
                status_code=400,
                detail="start_date must be <= end_date",
            )

    # Get actual sales for date range
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

    # Generate all dates in range
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
            # Calculate days_ahead for on-demand forecast
            days_ahead = (end_date - start_date).days + 1
            forecast_out = get_forecast_for_product(
                product_id=product_id,
                days_ahead=days_ahead,
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

    forecast_by_date = {row.date: float(row.yhat or 0.0) if row.yhat is not None else None for row in daily_rows}

    # Build rows with error calculations
    rows_data = []
    valid_forecasts = []
    valid_actuals = []
    valid_count = 0

    for d in dates:
        forecast_val = forecast_by_date.get(d)
        actual_val = actuals_by_date.get(d) if d in actuals_by_date else None
        
        # Calculate error fields
        error = None
        abs_error = None
        pct_error = None
        
        if forecast_val is not None and actual_val is not None:
            error = forecast_val - actual_val
            abs_error = abs(error)
            if actual_val > 0:
                pct_error = (abs_error / abs(actual_val)) * 100  # Convert to percentage
            
            # Collect for WAPE calculation
            valid_forecasts.append(forecast_val)
            valid_actuals.append(actual_val)
            valid_count += 1
        
        rows_data.append(
            ForecastVsActualPoint(
                date=d.isoformat(),
                actual=actual_val,
                forecast=forecast_val,
                error=error,
                abs_error=abs_error,
                pct_error=pct_error,
            )
        )

    # Calculate WAPE
    wape = None
    if valid_count > 0 and len(valid_actuals) > 0:
        try:
            wape_result = calculate_wape(
                np.array(valid_actuals),
                np.array(valid_forecasts)
            )
            if wape_result is not None and not np.isnan(wape_result):
                wape = float(wape_result) * 100  # Convert to percentage
        except Exception:
            wape = None

    return ForecastVsActualResponse(
        product_id=product.id,
        rows=rows_data,
        wape=wape,
        valid_points_count=valid_count,
        start_date=start_date,
        end_date=end_date,
    )




