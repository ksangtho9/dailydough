from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.ml.inference.forecast_service import get_forecast_for_product
from app.models import Bakery, Product, ForecastMetrics, SalesRecord, DailyForecast
from app.schemas.dashboard_summary import DashboardSummaryResponse
from app.core.config import settings

router = APIRouter(tags=["dashboard-summary"])


def calculate_post_training_accuracy(
    product_id: int,
    last_trained_at: Optional[datetime],
    db: Session,
) -> Tuple[Optional[float], Optional[float]]:
    """
    Calculate post-training accuracy for a product by comparing sales with forecasts
    for dates after the last training date.
    
    Returns (mape, rmse) where MAPE is in percentage (0-100), or (None, None) if
    insufficient data or no training date.
    """
    if last_trained_at is None:
        return None, None
    
    # Extract date part from last_trained_at
    training_date = last_trained_at.date()
    
    try:
        # Get sales records after training date
        sales_rows = (
            db.query(SalesRecord)
            .filter(
                SalesRecord.product_id == product_id,
                SalesRecord.date > training_date,  # Only dates after training
            )
            .order_by(SalesRecord.date.asc())
            .all()
        )
        
        if not sales_rows:
            return None, None
        
        # Get forecast for a longer horizon to capture historical forecasts
        # Note: This will generate future forecasts, so we need to match against
        # sales data that exists. We'll look for any overlapping dates.
        try:
            forecast = get_forecast_for_product(
                product_id=product_id,
                days_ahead=60,  # Get enough days to potentially overlap with recent sales
                db=db,
            )
        except Exception:
            return None, None
        
        # Build sales map by date
        sales_map = {row.date: row.quantity_sold for row in sales_rows}
        
        # Calculate accuracy on overlapping dates after training
        sq_err_sum = 0.0
        abs_pct_sum = 0.0
        n_rmse = 0
        n_mape = 0
        
        for point in forecast.points:
            point_date = point.date if isinstance(point.date, date) else date.fromisoformat(str(point.date))
            
            # Only consider dates after training
            if point_date <= training_date:
                continue
            
            actual = sales_map.get(point_date)
            if actual is None:
                continue
            
            yhat = point.yhat
            err = yhat - actual
            
            # RMSE calculation
            sq_err_sum += err * err
            n_rmse += 1
            
            # MAPE calculation (skip zero actuals)
            if actual != 0:
                abs_pct_sum += abs(err / actual)
                n_mape += 1
        
        if n_rmse == 0:
            return None, None
        
        rmse = (sq_err_sum / n_rmse) ** 0.5
        mape = (abs_pct_sum / n_mape * 100) if n_mape > 0 else None
        
        return mape, rmse
        
    except Exception:
        # If any error occurs, return None
        return None, None


@router.get(
    "/bakeries/{bakery_id}/dashboard-summary",
    response_model=DashboardSummaryResponse,
)
def get_dashboard_summary(
    bakery_id: int,
    db: Session = Depends(get_db),
):
    bakery = db.query(Bakery).filter(Bakery.id == bakery_id).one_or_none()
    if bakery is None:
        raise HTTPException(status_code=404, detail="Bakery not found")

    products = (
        db.query(Product)
        .filter(Product.bakery_id == bakery_id)
        .all()
    )

    tomorrow = date.today() + timedelta(days=1)

    # First choice: use precomputed daily forecasts so we don't need to run
    # heavy forecasting logic on dashboard requests.
    daily_rows = (
        db.query(DailyForecast)
        .filter(
            DailyForecast.bakery_id == bakery_id,
            DailyForecast.date == tomorrow,
        )
        .all()
    )

    if daily_rows:
        recommended_bake = sum(
            max(0, int(round(float(row.yhat or 0.0)))) for row in daily_rows
        )
    elif not settings.disable_on_demand_analytics_forecasts:
        # Fallback: if no precomputed forecasts exist yet (e.g. before models
        # have been trained), fall back to on-demand forecasts so the dashboard
        # still shows something, at the cost of extra compute.
        recommended_bake = 0
        for product in products:
            try:
                forecast = get_forecast_for_product(
                    product_id=product.id,
                    days_ahead=14,
                    db=db,
                )
            except Exception:
                continue

            points = getattr(forecast, "points", [])
            match = next(
                (
                    p
                    for p in points
                    if str(getattr(p, "date", None)) == tomorrow.isoformat()
                ),
                None,
            )
            if match is None:
                continue
            yhat = getattr(match, "yhat", None)
            if yhat is None:
                continue
            recommended_bake += max(0, int(round(float(yhat))))

    if recommended_bake == 0:
        recommended_bake_value = None
    else:
        recommended_bake_value = recommended_bake

    lookback_days = 7
    lookback_start = date.today() - timedelta(days=lookback_days)
    actual_rows = (
        db.query(
            SalesRecord.date.label("day"),
            func.sum(SalesRecord.quantity_sold).label("qty"),
        )
        .filter(
            SalesRecord.bakery_id == bakery_id,
            SalesRecord.date >= lookback_start,
            SalesRecord.date <= date.today(),
        )
        .group_by(SalesRecord.date)
        .all()
    )

    expected_waste_pct = None
    if recommended_bake_value and actual_rows:
        total_actual = sum(float(row.qty or 0.0) for row in actual_rows)
        avg_actual = total_actual / len(actual_rows) if actual_rows else 0
        if avg_actual > 0:
            surplus = max(recommended_bake_value - avg_actual, 0)
            if recommended_bake_value > 0:
                expected_waste_pct = surplus / recommended_bake_value

    # Calculate post-training accuracy for each product
    metrics_rows = (
        db.query(ForecastMetrics)
        .join(Product, ForecastMetrics.product_id == Product.id)
        .filter(Product.bakery_id == bakery_id)
        .all()
    )

    post_training_mape_values = []
    high_risk_count = 0

    for metrics_row in metrics_rows:
        product_id = metrics_row.product_id
        last_trained_at = metrics_row.last_trained_at
        
        # Calculate post-training accuracy
        post_mape, _ = calculate_post_training_accuracy(
            product_id=product_id,
            last_trained_at=last_trained_at,
            db=db,
        )
        
        if post_mape is not None:
            post_training_mape_values.append(post_mape)
            # High risk: MAPE > 25%
            if post_mape > 25.0:
                high_risk_count += 1

    # Calculate average post-training MAPE (already in percentage form)
    forecast_accuracy_pct = (
        sum(post_training_mape_values) / len(post_training_mape_values)
        if post_training_mape_values
        else None
    )

    high_risk_items = high_risk_count

    return DashboardSummaryResponse(
        bakery_id=bakery.id,
        bakery_name=bakery.name,
        as_of=date.today(),
        recommended_bake=recommended_bake_value,
        expected_waste_pct=expected_waste_pct,
        forecast_accuracy_pct=forecast_accuracy_pct,
        high_risk_items=high_risk_items,
    )




