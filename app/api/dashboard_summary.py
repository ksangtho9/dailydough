from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional, Tuple
import logging

import numpy as np

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.ml.inference.forecast_service import get_forecast_for_product
from app.ml.metrics import calculate_wape
from app.models import Bakery, Product, ForecastMetrics, SalesRecord, DailyForecast
from app.schemas.dashboard_summary import DashboardSummaryResponse
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["dashboard-summary"])


def calculate_post_training_wape(
    bakery_id: int,
    db: Session,
    as_of_date: Optional[date] = None,
) -> Optional[float]:
    """
    Calculate WAPE for a bakery using totals-based approach over the last 7 days.
    
    Uses a fixed window: last 7 days (from as_of_date - 7 days to as_of_date - 1 day).
    If as_of_date is None, uses today.
    Computes WAPE from raw totals: sum(|forecast - actual|) / sum(actual) * 100
    
    Returns WAPE as percentage (0-100+), or None if insufficient data.
    """
    # Step 1: Define date window (last 7 days, excluding as_of_date since we need actual sales)
    reference_date = as_of_date if as_of_date is not None else date.today()
    end_date = reference_date - timedelta(days=1)  # Day before reference (most recent day with complete sales data)
    start_date = reference_date - timedelta(days=7)  # 7 days ago (7 days total: from 7 days ago to end_date, inclusive)
    
    logger.debug(f"calculate_post_training_wape: bakery_id={bakery_id}, date_range={start_date} to {end_date}")
    
    # Step 2: Get all product IDs for this bakery
    products = (
        db.query(Product.id)
        .filter(Product.bakery_id == bakery_id)
        .all()
    )
    
    if not products:
        return None
    
    product_ids = [p.id for p in products]
    
    # Step 3: Batch query all forecasts in the last 7 days
    forecast_rows = (
        db.query(
            DailyForecast.product_id,
            DailyForecast.date,
            DailyForecast.yhat,
        )
        .filter(
            DailyForecast.bakery_id == bakery_id,
            DailyForecast.product_id.in_(product_ids),
            DailyForecast.date >= start_date,
            DailyForecast.date <= end_date,
            DailyForecast.yhat.isnot(None),
        )
        .all()
    )
    logger.debug(
        f"calculate_post_training_wape: Found {len(forecast_rows)} forecast rows "
        f"in date range {start_date} to {end_date}"
    )
    
    # Step 4: Batch query all sales in the last 7 days (aggregated by product_id, date)
    # Note: func.sum() handles None values and multiple rows per day correctly
    sales_rows = (
        db.query(
            SalesRecord.product_id,
            SalesRecord.date.label("day"),
            func.sum(SalesRecord.quantity_sold).label("qty"),
        )
        .filter(
            SalesRecord.bakery_id == bakery_id,
            SalesRecord.product_id.in_(product_ids),
            SalesRecord.date >= start_date,
            SalesRecord.date <= end_date,
        )
        .group_by(SalesRecord.product_id, SalesRecord.date)
        .all()
    )
    logger.debug(f"calculate_post_training_wape: Found {len(sales_rows)} sales rows in date range {start_date} to {end_date}")
    
    # Step 5: Build maps for efficient lookup
    # Group forecasts by (product_id, date) -> yhat
    # Note: DailyForecast has UniqueConstraint on (bakery_id, product_id, date),
    # so there's only one forecast per product/date - no need to filter for "latest"
    forecasts_by_key: dict[tuple[int, date], float] = {}
    for row in forecast_rows:
        if row.yhat is not None:
            forecasts_by_key[(row.product_id, row.date)] = float(row.yhat)
    
    # Group sales by (product_id, date) -> quantity
    # Note: func.sum() may return None if all values are None, so we handle that explicitly
    # Also note: quantity_sold can be negative (refunds/adjustments), but we include them
    # in the calculation as-is for consistency with Accuracy tab
    actuals_by_key: dict[tuple[int, date], float] = {}
    for row in sales_rows:
        qty = row.qty
        if qty is not None:
            actuals_by_key[(row.product_id, row.day)] = float(qty)
    
    # Step 6: Join forecasts and actuals, compute totals
    # Only include dates where both forecast and actual exist (and are not None)
    # This ensures we only compute WAPE on valid data points
    valid_keys = set(forecasts_by_key.keys()) & set(actuals_by_key.keys())
    
    if not valid_keys:
        # No overlapping data points
        logger.warning(
            f"calculate_post_training_wape: No overlapping dates for bakery_id={bakery_id}. "
            f"Forecasts: {len(forecasts_by_key)} dates, Sales: {len(actuals_by_key)} dates. "
            f"Date range: {start_date} to {end_date}. "
            f"Sample forecast dates: {sorted(list(forecasts_by_key.keys()))[:5] if forecasts_by_key else []}. "
            f"Sample sales dates: {sorted(list(actuals_by_key.keys()))[:5] if actuals_by_key else []}"
        )
        return None
    
    logger.info(f"calculate_post_training_wape: Found {len(valid_keys)} overlapping dates for bakery_id={bakery_id}")
    
    # Collect all valid forecast and actual values
    # Both forecast and actual are guaranteed to be non-None at this point
    valid_forecasts = []
    valid_actuals = []
    
    for key in valid_keys:
        forecast_val = forecasts_by_key[key]
        actual_val = actuals_by_key[key]
        # Both values are already validated (non-None) from the maps
        valid_forecasts.append(forecast_val)
        valid_actuals.append(actual_val)
    
    # Step 7: Calculate WAPE from totals using calculate_wape()
    # Check that we have data and sum of actuals is not zero (division by zero protection)
    if not valid_actuals:
        logger.warning(f"calculate_post_training_wape: No valid actuals for bakery_id={bakery_id}")
        return None
    
    # Calculate sum of absolute actuals to check for zero denominator
    # Note: calculate_wape() handles this internally, but we check here for clarity
    total_actual = sum(abs(a) for a in valid_actuals)
    total_abs_error = sum(abs(f - a) for f, a in zip(valid_forecasts, valid_actuals))
    
    logger.info(
        f"calculate_post_training_wape: bakery_id={bakery_id}, "
        f"valid_points={len(valid_actuals)}, total_actual={total_actual:.2f}, total_abs_error={total_abs_error:.2f}"
    )
    
    if total_actual == 0:
        # All actuals are zero - cannot compute WAPE
        logger.warning(f"calculate_post_training_wape: Sum of actuals is zero for bakery_id={bakery_id}")
        return None
    
    try:
        wape_result = calculate_wape(
            np.array(valid_actuals),
            np.array(valid_forecasts)
        )
        
        if wape_result is None or np.isnan(wape_result):
            logger.warning(
                f"calculate_post_training_wape: calculate_wape returned None or NaN for bakery_id={bakery_id}. "
                f"valid_actuals count={len(valid_actuals)}, total_actual={total_actual}"
            )
            return None
        
        # Convert to percentage (calculate_wape returns 0-1 range)
        wape_pct = float(wape_result) * 100
        logger.info(f"calculate_post_training_wape: Calculated WAPE={wape_pct:.2f}% for bakery_id={bakery_id}")
        return wape_pct
        
    except Exception as e:
        # If calculation fails, return None
        logger.error(f"calculate_post_training_wape: Error calculating WAPE for bakery_id={bakery_id}: {e}", exc_info=True)
        return None


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
    as_of_date: Optional[date] = None,  # Optional date for dev mode / testing
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

    # Use as_of_date if provided (for dev mode), otherwise use today
    # The forecast date is the day after the reference date
    reference_date = as_of_date if as_of_date is not None else date.today()
    target_forecast_date = reference_date + timedelta(days=1)  # Day after reference date

    # First choice: use precomputed daily forecasts so we don't need to run
    # heavy forecasting logic on dashboard requests.
    daily_rows = (
        db.query(DailyForecast)
        .filter(
            DailyForecast.bakery_id == bakery_id,
            DailyForecast.date == target_forecast_date,
        )
        .all()
    )

    if daily_rows:
        recommended_bake = sum(
            max(0, int(round(float(row.yhat or 0.0)))) for row in daily_rows
        )
    else:
        # No precomputed forecasts available - return None instead of generating
        # on-demand forecasts. This prevents connection pool exhaustion from
        # generating forecasts for many products sequentially.
        # Precomputed forecasts should be generated via training/background jobs.
        recommended_bake = 0

    if recommended_bake == 0:
        recommended_bake_value = None
    else:
        recommended_bake_value = recommended_bake

    # Lookback window: last 7 days ending the day before the forecast date
    # This gives us historical sales data to compare against the forecast
    lookback_days = 7
    lookback_end = target_forecast_date - timedelta(days=1)  # Day before forecast date
    lookback_start = lookback_end - timedelta(days=lookback_days - 1)  # 7 days total, inclusive
    
    # Query sales data: groups by date and sums quantity_sold across all products per day
    # This query returns one row per day, where each row contains the total units sold
    # across all products for that day. Then we average those daily totals.
    # avg_actual is computed as: for each day in the lookback window, sum quantity_sold
    # across all products; then average those daily totals (average computed over available days).
    actual_rows = (
        db.query(
            SalesRecord.date.label("day"),
            func.sum(SalesRecord.quantity_sold).label("qty"),
        )
        .filter(
            SalesRecord.bakery_id == bakery_id,
            SalesRecord.date >= lookback_start,
            SalesRecord.date <= lookback_end,
        )
        .group_by(SalesRecord.date)
        .all()
    )

    # Initialize date window fields for API response (populate even if calculation returns None)
    expected_waste_forecast_date = target_forecast_date
    expected_waste_lookback_start = lookback_start
    expected_waste_lookback_end = lookback_end

    expected_waste_pct = None
    if recommended_bake_value and actual_rows:
        # Require minimum 4 days of data to ensure metric is based on sufficient historical data
        # Average computed over available days (minimum 4 days required)
        if len(actual_rows) < 4:
            logger.warning(
                f"Expected waste: Insufficient data for bakery_id={bakery_id}. "
                f"Only {len(actual_rows)} days of sales data in lookback window "
                f"({lookback_start} to {lookback_end}), minimum 4 days required."
            )
        else:
            total_actual = sum(float(row.qty or 0.0) for row in actual_rows)
            avg_actual = total_actual / len(actual_rows)  # Average computed over available days
            logger.debug(
                f"Expected waste calculation: bakery_id={bakery_id}, "
                f"recommended_bake={recommended_bake_value}, "
                f"avg_actual={avg_actual:.2f}, "
                f"lookback_days={len(actual_rows)}, "
                f"lookback_range={lookback_start} to {lookback_end}, "
                f"forecast_date={target_forecast_date}"
            )
            if avg_actual > 0:
                surplus = max(recommended_bake_value - avg_actual, 0)
                if recommended_bake_value > 0:
                    expected_waste_pct = surplus / recommended_bake_value
                    logger.debug(
                        f"Expected waste result: surplus={surplus:.2f}, "
                        f"expected_waste_pct={expected_waste_pct:.4f} ({expected_waste_pct * 100:.2f}%)"
                    )
            else:
                logger.warning(
                    f"Expected waste: avg_actual is 0 or negative for bakery_id={bakery_id}"
                )
    else:
        logger.warning(
            f"Expected waste: Missing data for bakery_id={bakery_id}. "
            f"recommended_bake_value={recommended_bake_value}, actual_rows_count={len(actual_rows) if actual_rows else 0}"
        )

    # Calculate post-training accuracy for each product
    # OPTIMIZATION: Use more efficient query - only select needed columns
    metrics_rows = (
        db.query(
            ForecastMetrics.product_id,
            ForecastMetrics.mape,
            ForecastMetrics.last_trained_at,
        )
        .join(Product, ForecastMetrics.product_id == Product.id)
        .filter(Product.bakery_id == bakery_id)
        .all()
    )

    post_training_mape_values = []
    high_risk_count = 0

    # OPTIMIZATION: Use MAPE directly from ForecastMetrics instead of recalculating
    # Recalculating would call get_forecast_for_product for each product, which is
    # extremely slow and causes connection pool exhaustion.
    for metrics_row in metrics_rows:
        # Use the MAPE from ForecastMetrics directly (already in percentage form)
        mape_value = metrics_row.mape
        
        if mape_value is not None:
            post_training_mape_values.append(mape_value)
            # High risk: MAPE > 25%
            if mape_value > 25.0:
                high_risk_count += 1

    # Calculate average post-training MAPE (already in percentage form)
    forecast_accuracy_pct = (
        sum(post_training_mape_values) / len(post_training_mape_values)
        if post_training_mape_values
        else None
    )

    high_risk_items = high_risk_count

    # Calculate post-training WAPE (use as_of_date if provided, otherwise today)
    reference_date = as_of_date if as_of_date is not None else date.today()
    post_training_wape = calculate_post_training_wape(bakery_id, db, as_of_date=reference_date)

    return DashboardSummaryResponse(
        bakery_id=bakery.id,
        bakery_name=bakery.name,
        as_of=reference_date,
        recommended_bake=recommended_bake_value,
        expected_waste_pct=expected_waste_pct,
        forecast_accuracy_pct=forecast_accuracy_pct,
        post_training_wape=post_training_wape,
        high_risk_items=high_risk_items,
        expected_waste_forecast_date=expected_waste_forecast_date,
        expected_waste_lookback_start=expected_waste_lookback_start,
        expected_waste_lookback_end=expected_waste_lookback_end,
    )




