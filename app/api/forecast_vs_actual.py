from __future__ import annotations

from datetime import date, timedelta
from typing import Optional
import logging

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
from app.core.config import settings
from app.schemas.forecast_vs_actual import (
    ForecastVsActualPoint,
    ForecastVsActualResponse,
)

logger = logging.getLogger(__name__)

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
    is_single_date_mode = False
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
        # Detect single-date mode
        if start_date == end_date:
            is_single_date_mode = True
            logger.info(
                f"SINGLE-DATE MODE DETECTED for product {product_id}: "
                f"start_date={start_date}, end_date={end_date}, "
                f"querying exactly one calendar date"
            )

    # Get actual sales for date range
    # First, get raw SalesRecord rows before aggregation (for single-date investigation)
    raw_sales_rows = []
    if is_single_date_mode:
        raw_sales_rows = (
            db.query(SalesRecord)
            .filter(
                SalesRecord.product_id == product_id,
                SalesRecord.date == start_date,  # Single date only
            )
            .order_by(SalesRecord.id)
            .all()
        )
        logger.debug(
            f"SINGLE-DATE: Raw SalesRecord rows for product {product_id}, date {start_date}: "
            f"count={len(raw_sales_rows)}, "
            f"rows={[{'id': r.id, 'date': str(r.date), 'quantity_sold': r.quantity_sold, 'product_id': r.product_id} for r in raw_sales_rows]}"
        )
    
    # Now get aggregated sales
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
    
    # Verify aggregation for single-date mode
    if is_single_date_mode and raw_sales_rows:
        aggregated_qty = actuals_by_date.get(start_date, 0.0)
        raw_sum = sum(float(r.quantity_sold or 0.0) for r in raw_sales_rows)
        logger.debug(
            f"SINGLE-DATE: Sales aggregation verification for product {product_id}, date {start_date}: "
            f"raw_rows_count={len(raw_sales_rows)}, "
            f"raw_sum={raw_sum:.4f}, "
            f"aggregated_value={aggregated_qty:.4f}, "
            f"match={abs(raw_sum - aggregated_qty) < 0.001}"
        )

    # Generate all dates in range
    dates = []
    current = start_date
    while current <= end_date:
        dates.append(current)
        current += timedelta(days=1)
    
    # Verify single-date mode produces exactly one date
    if is_single_date_mode:
        if len(dates) != 1:
            logger.warning(
                f"SINGLE-DATE MODE: Expected 1 date but got {len(dates)} dates. "
                f"start_date={start_date}, end_date={end_date}, dates={dates}"
            )
        else:
            logger.debug(
                f"SINGLE-DATE MODE: Confirmed exactly 1 date in range: {dates[0]}"
            )

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
            # Use settings.debug_zero_forecasts for non-authenticated endpoints
            include_debug = settings.debug_zero_forecasts
            forecast_out = get_forecast_for_product(
                product_id=product_id,
                days_ahead=days_ahead,
                db=db,
                include_debug=include_debug,
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

    # Log raw DailyForecast rows for single-date mode
    raw_forecast_rows = []
    if is_single_date_mode:
        raw_forecast_rows = [
            r for r in daily_rows if r.date == start_date
        ]
        logger.debug(
            f"SINGLE-DATE: Raw DailyForecast rows for product {product_id}, date {start_date}: "
            f"count={len(raw_forecast_rows)}, "
            f"rows={[{'id': getattr(r, 'id', None), 'date': str(r.date), 'yhat': r.yhat, 'product_id': getattr(r, 'product_id', None)} for r in raw_forecast_rows]}"
        )
    
    # Build forecast_by_date dictionary (last one wins if duplicates)
    forecast_by_date = {}
    for row in daily_rows:
        forecast_by_date[row.date] = float(row.yhat or 0.0) if row.yhat is not None else None
    
    # Verify forecast aggregation for single-date mode
    if is_single_date_mode and raw_forecast_rows:
        forecast_value = forecast_by_date.get(start_date)
        logger.debug(
            f"SINGLE-DATE: Forecast aggregation verification for product {product_id}, date {start_date}: "
            f"raw_rows_count={len(raw_forecast_rows)}, "
            f"final_forecast_value={forecast_value}, "
            f"duplicate_handling={'last_one_wins' if len(raw_forecast_rows) > 1 else 'single_row'}"
        )

    # Verify date alignment: check for off-by-one errors
    actual_dates = set(actuals_by_date.keys())
    forecast_dates = set(forecast_by_date.keys())
    overlapping_dates = actual_dates & forecast_dates
    
    # Enhanced date alignment logging for single-date mode
    if is_single_date_mode:
        logger.info(
            f"SINGLE-DATE: Date alignment check for product {product_id}, date {start_date}: "
            f"actual_dates={sorted([str(d) for d in actual_dates])}, "
            f"forecast_dates={sorted([str(d) for d in forecast_dates])}, "
            f"overlapping_dates={sorted([str(d) for d in overlapping_dates])}, "
            f"only_actual={sorted([str(d) for d in (actual_dates - forecast_dates)])}, "
            f"only_forecast={sorted([str(d) for d in (forecast_dates - actual_dates)])}, "
            f"all_dates_are_date_objects={all(isinstance(d, date) for d in list(actual_dates) + list(forecast_dates))}"
        )
        
        # Verify date object types (not datetime)
        actual_date_types = [type(d).__name__ for d in actual_dates]
        forecast_date_types = [type(d).__name__ for d in forecast_dates]
        if not all(t == 'date' for t in actual_date_types + forecast_date_types):
            logger.warning(
                f"SINGLE-DATE: Date type mismatch detected. "
                f"Actual date types: {set(actual_date_types)}, "
                f"Forecast date types: {set(forecast_date_types)}"
            )
        
        # Check for off-by-one issues
        if start_date not in actual_dates and start_date not in forecast_dates:
            logger.warning(
                f"SINGLE-DATE: Query date {start_date} not found in either actuals or forecasts. "
                f"This may indicate a date alignment issue."
            )
        elif start_date in actual_dates and start_date not in forecast_dates:
            logger.warning(
                f"SINGLE-DATE: Query date {start_date} has actual but no forecast. "
                f"This may indicate an off-by-one error or missing forecast data."
            )
        elif start_date not in actual_dates and start_date in forecast_dates:
            logger.warning(
                f"SINGLE-DATE: Query date {start_date} has forecast but no actual. "
                f"This may indicate an off-by-one error or missing sales data."
            )
    
    logger.debug(
        f"Date alignment check for product {product_id}: "
        f"actual_dates_count={len(actual_dates)}, "
        f"forecast_dates_count={len(forecast_dates)}, "
        f"overlapping_dates_count={len(overlapping_dates)}, "
        f"date_range={start_date} to {end_date}"
    )
    
    # Check for potential off-by-one issues (dates that exist in one but not the other)
    only_actual = actual_dates - forecast_dates
    only_forecast = forecast_dates - actual_dates
    if only_actual:
        logger.debug(
            f"Dates with actual but no forecast (first 5): "
            f"{sorted(list(only_actual))[:5]}"
        )
    if only_forecast:
        logger.debug(
            f"Dates with forecast but no actual (first 5): "
            f"{sorted(list(only_forecast))[:5]}"
        )

    # Build rows with error calculations
    rows_data = []
    valid_forecasts = []
    valid_actuals = []
    valid_count = 0
    
    # Track all data points for single-date mode logging
    wape_data_points = []

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
            
            # Track data point for logging
            wape_data_points.append({
                "date": str(d),
                "product_id": product_id,
                "raw_actual": actual_val,
                "raw_forecast": forecast_val,
                "absolute_error": abs_error,
            })
        
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
    
    # Log all data points for single-date mode
    if is_single_date_mode:
        logger.info(
            f"SINGLE-DATE: WAPE data points for product {product_id}, date {start_date}: "
            f"valid_points_count={valid_count}, "
            f"data_points={wape_data_points}"
        )
        
        # Log precision comparison for single date
        if len(wape_data_points) == 1:
            point = wape_data_points[0]
            raw_actual = point["raw_actual"]
            raw_forecast = point["raw_forecast"]
            rounded_actual = round(raw_actual, 1)
            rounded_forecast = round(raw_forecast, 1)
            rounded_match = rounded_actual == rounded_forecast
            raw_match = abs(raw_actual - raw_forecast) < 0.001
            
            logger.info(
                f"SINGLE-DATE: Precision analysis for product {product_id}, date {start_date}: "
                f"raw_actual={raw_actual:.10f}, "
                f"raw_forecast={raw_forecast:.10f}, "
                f"rounded_actual={rounded_actual:.1f}, "
                f"rounded_forecast={rounded_forecast:.1f}, "
                f"rounded_values_match={rounded_match}, "
                f"raw_values_match={raw_match}, "
                f"absolute_error={point['absolute_error']:.10f}"
            )
            
            if rounded_match and not raw_match:
                logger.warning(
                    f"SINGLE-DATE PRECISION ISSUE: Rounded values match ({rounded_actual:.1f}) "
                    f"but raw values differ (actual={raw_actual:.10f}, forecast={raw_forecast:.10f}). "
                    f"This explains non-zero WAPE when UI shows matching values."
                )

    # Calculate WAPE
    wape = None
    if valid_count > 0 and len(valid_actuals) > 0:
        try:
            # Log WAPE calculation details for debugging
            actuals_array = np.array(valid_actuals)
            forecasts_array = np.array(valid_forecasts)
            
            # Calculate components for logging
            abs_errors = np.abs(forecasts_array - actuals_array)
            numerator = np.sum(abs_errors)
            denominator = np.sum(np.abs(actuals_array))
            
            # Enhanced logging for single-date mode
            if is_single_date_mode:
                logger.info(
                    f"SINGLE-DATE: WAPE calculation details for product {product_id}, date {start_date}: "
                    f"valid_points_count={valid_count}, "
                    f"numerator={numerator:.10f}, "
                    f"denominator={denominator:.10f}, "
                    f"all_data_points={wape_data_points}"
                )
                
                if valid_count > 1:
                    logger.warning(
                        f"SINGLE-DATE ISSUE: valid_points_count={valid_count} > 1 for single date {start_date}. "
                        f"This suggests multiple data points are being included. "
                        f"Data points: {wape_data_points}"
                    )
            
            # Log per-date contributions (first 5 and last 5 dates for brevity)
            per_date_details = []
            for i, d in enumerate(dates):
                if d in actuals_by_date and forecast_by_date.get(d) is not None:
                    actual_val = actuals_by_date[d]
                    forecast_val = forecast_by_date[d]
                    error = abs(forecast_val - actual_val)
                    per_date_details.append({
                        "date": str(d),
                        "forecast": forecast_val,
                        "actual": actual_val,
                        "abs_error": error,
                    })
            
            logger.debug(
                f"WAPE calculation for product {product_id}: "
                f"valid_dates={valid_count}, "
                f"date_range={start_date} to {end_date}, "
                f"numerator={numerator:.4f}, "
                f"denominator={denominator:.4f}, "
                f"sample_dates={len(per_date_details)} dates with both forecast and actual"
            )
            
            # Log sample of per-date errors (first 3 and last 3)
            # Note: UI displays values with .toFixed(1), but WAPE uses full precision
            if len(per_date_details) > 0:
                sample_size = min(3, len(per_date_details))
                logger.debug(
                    f"WAPE sample per-date errors (first {sample_size}, full precision): "
                    f"{per_date_details[:sample_size]}"
                )
                if len(per_date_details) > sample_size * 2:
                    logger.debug(
                        f"WAPE sample per-date errors (last {sample_size}, full precision): "
                        f"{per_date_details[-sample_size:]}"
                    )
                
                # Check for precision differences (values that appear same when rounded)
                precision_matches = []
                for detail in per_date_details:
                    forecast_rounded = round(detail["forecast"], 1)
                    actual_rounded = round(detail["actual"], 1)
                    if forecast_rounded == actual_rounded and detail["abs_error"] > 0.001:
                        precision_matches.append({
                            "date": detail["date"],
                            "forecast_raw": detail["forecast"],
                            "actual_raw": detail["actual"],
                            "forecast_rounded": forecast_rounded,
                            "actual_rounded": actual_rounded,
                            "abs_error": detail["abs_error"],
                        })
                
                if precision_matches:
                    logger.debug(
                        f"WAPE precision note: {len(precision_matches)} dates where rounded values match "
                        f"but raw values differ (contributing to WAPE): {precision_matches[:3]}"
                    )
            
            wape_result = calculate_wape(actuals_array, forecasts_array)
            if wape_result is not None and not np.isnan(wape_result):
                wape = float(wape_result) * 100  # Convert to percentage
                logger.debug(
                    f"WAPE calculation result for product {product_id}: "
                    f"WAPE={wape:.2f}% (calculated over {valid_count} dates)"
                )
                
                # Enhanced logging for single-date mode
                if is_single_date_mode:
                    logger.info(
                        f"SINGLE-DATE: Final WAPE result for product {product_id}, date {start_date}: "
                        f"WAPE={wape:.2f}%, "
                        f"valid_points_count={valid_count}, "
                        f"numerator={numerator:.10f}, "
                        f"denominator={denominator:.10f}"
                    )
        except Exception as e:
            logger.error(f"Error calculating WAPE for product {product_id}: {e}", exc_info=True)
            wape = None

    return ForecastVsActualResponse(
        product_id=product.id,
        rows=rows_data,
        wape=wape,
        valid_points_count=valid_count,
        start_date=start_date,
        end_date=end_date,
    )




