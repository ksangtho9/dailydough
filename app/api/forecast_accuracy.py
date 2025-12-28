from __future__ import annotations

import json
import time
from collections import defaultdict
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database.database import get_db
from app.api.auth import get_current_user
from app.models import Product, ForecastMetrics, Bakery, SalesRecord, DailyForecast
from app.schemas.forecast_accuracy import ProductAccuracyOut
from app.ml.metrics import calculate_wape, calculate_adjusted_wape
from app.services.daily_forecast_service import get_product_daily_forecasts

# #region agent log
def _debug_log(location: str, message: str, data: dict, hypothesis_id: str = ""):
    try:
        import os
        log_path = r"c:\Users\forfl\Documents\dailydough-1\.cursor\debug.log"
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        log_entry = {
            "sessionId": "debug-session",
            "runId": "run1",
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000)
        }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")
    except Exception as e:
        # Log to stderr so we can see if there's an issue
        import sys
        print(f"DEBUG LOG ERROR: {e}", file=sys.stderr)
# #endregion


router = APIRouter(
    prefix="/forecast-accuracy",
    tags=["analytics"],
)


@router.get(
    "/bakery/{bakery_id}",
    response_model=List[ProductAccuracyOut],
    status_code=status.HTTP_200_OK,
)
def get_bakery_forecast_accuracy(
    bakery_id: int,
    start_date: Optional[date] = Query(None, description="Start date for date-filtered accuracy calculation (or single date if end_date not provided)"),
    end_date: Optional[date] = Query(None, description="End date for date-filtered accuracy calculation (if not provided, uses start_date as single date)"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Return per-product forecast accuracy metrics for a bakery in a single call.

    If start_date and end_date are provided, recalculates accuracy metrics for the
    selected date range using daily forecast vs actual data. Otherwise, returns
    metrics from the ForecastMetrics table (populated during training).
    """
    # #region agent log
    try:
        _debug_log("forecast_accuracy.py:51", "Endpoint called", {
            "bakery_id": bakery_id,
            "start_date": str(start_date) if start_date else None,
            "end_date": str(end_date) if end_date else None
        }, "ENTRY")
    except Exception as log_err:
        import sys
        print(f"DEBUG LOG ERROR at entry: {log_err}", file=sys.stderr)
    # #endregion
    
    # Ensure bakery exists and belongs to the current user (if applicable)
    bakery = db.query(Bakery).filter(Bakery.id == bakery_id).first()
    if bakery is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bakery not found",
        )

    # If date(s) are provided, recalculate metrics from daily forecasts vs actuals
    # Support both single date (start_date only) and date range (start_date + end_date)
    if start_date is not None:
        # #region agent log
        _debug_log("forecast_accuracy.py:53", "Function entry with date filter", {
            "bakery_id": bakery_id,
            "start_date": str(start_date) if start_date else None,
            "end_date": str(end_date) if end_date else None
        }, "A")
        # #endregion
        
        # If only start_date provided, use it as single date
        if end_date is None:
            end_date = start_date
        elif start_date > end_date:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="start_date must be <= end_date",
            )
        
        # #region agent log
        query_start = time.time()
        # #endregion
        
        # Fetch products for this bakery
        products = (
            db.query(Product)
            .filter(Product.bakery_id == bakery_id)
            .order_by(Product.name.asc())
            .all()
        )
        
        # #region agent log
        query_time = time.time() - query_start
        _debug_log("forecast_accuracy.py:69", "Products query completed", {
            "product_count": len(products),
            "query_time_ms": round(query_time * 1000, 2)
        }, "A")
        # #endregion
        
        if not products:
            return []
        
        product_ids = [p.id for p in products]
        
        # OPTIMIZATION: Batch fetch all sales records in one query
        # Use more efficient query with explicit column selection
        # Also fetch quantity_delivered for supply-cap detection
        # #region agent log
        query_start = time.time()
        # #endregion
        try:
            sales_rows = (
                db.query(
                    SalesRecord.product_id,
                    SalesRecord.date.label("day"),
                    func.sum(SalesRecord.quantity_sold).label("qty"),
                    func.sum(SalesRecord.quantity_delivered).label("delivery"),
                )
                .filter(
                    SalesRecord.product_id.in_(product_ids),
                    SalesRecord.date >= start_date,
                    SalesRecord.date <= end_date,
                )
                .group_by(SalesRecord.product_id, SalesRecord.date)
                .all()
            )
        except Exception as e:
            # #region agent log
            _debug_log("forecast_accuracy.py:90", "Sales query error", {"error": str(e)}, "ERROR")
            # #endregion
            db.rollback()
            raise
        # #region agent log
        query_time = time.time() - query_start
        _debug_log("forecast_accuracy.py:90", "Sales records query completed", {
            "row_count": len(sales_rows),
            "product_ids_count": len(product_ids),
            "date_range_days": (end_date - start_date).days + 1,
            "query_time_ms": round(query_time * 1000, 2)
        }, "B")
        # #endregion
        
        # Group sales by product_id -> date -> quantity and delivery (use defaultdict for efficiency)
        # Also compute is_supply_capped_day for each date
        # #region agent log
        process_start = time.time()
        # #endregion
        actuals_by_product: dict[int, dict[date, float]] = defaultdict(dict)
        delivery_by_product: dict[int, dict[date, float]] = defaultdict(dict)
        supply_capped_by_product: dict[int, dict[date, int]] = defaultdict(dict)
        for row in sales_rows:
            product_id = row.product_id
            day = row.day
            qty = float(row.qty or 0.0)
            delivery = float(row.delivery or 0.0)
            actuals_by_product[product_id][day] = qty
            delivery_by_product[product_id][day] = delivery
            # Compute is_supply_capped_day: delivery > 0 AND sales >= 0.95 * delivery
            # Only on valid days (delivery > 0 or sales > 0)
            is_valid = (delivery > 0) or (qty > 0)
            is_capped = is_valid and (delivery > 0) and (qty >= 0.95 * delivery)
            supply_capped_by_product[product_id][day] = 1 if is_capped else 0
        # #region agent log
        process_time = time.time() - process_start
        _debug_log("forecast_accuracy.py:96", "Sales grouping completed", {
            "processing_time_ms": round(process_time * 1000, 2),
            "products_with_sales": len(actuals_by_product)
        }, "B")
        # #endregion
        
        # OPTIMIZATION: Batch fetch all daily forecasts in one query
        # Only select needed columns to reduce memory usage
        # #region agent log
        query_start = time.time()
        # #endregion
        try:
            daily_rows = (
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
                    DailyForecast.yhat.isnot(None),  # Only get rows with valid forecasts
                )
                .all()
            )
        except Exception as e:
            # #region agent log
            _debug_log("forecast_accuracy.py:113", "Forecasts query error", {"error": str(e)}, "ERROR")
            # #endregion
            db.rollback()
            raise
        # #region agent log
        query_time = time.time() - query_start
        _debug_log("forecast_accuracy.py:113", "Daily forecasts query completed", {
            "row_count": len(daily_rows),
            "query_time_ms": round(query_time * 1000, 2)
        }, "C")
        # #endregion
        
        # Group forecasts by product_id -> date -> yhat (use defaultdict for efficiency)
        # #region agent log
        process_start = time.time()
        # #endregion
        forecasts_by_product: dict[int, dict[date, float]] = defaultdict(dict)
        for row in daily_rows:
            if row.yhat is not None:
                forecasts_by_product[row.product_id][row.date] = float(row.yhat)
        # #region agent log
        process_time = time.time() - process_start
        _debug_log("forecast_accuracy.py:120", "Forecasts grouping completed", {
            "processing_time_ms": round(process_time * 1000, 2),
            "products_with_forecasts": len(forecasts_by_product)
        }, "C")
        # #endregion
        
        # Batch fetch all ForecastMetrics in one query
        metrics_rows = (
            db.query(ForecastMetrics)
            .filter(ForecastMetrics.product_id.in_(product_ids))
            .all()
        )
        metrics_by_product = {m.product_id: m for m in metrics_rows}
        
        # Calculate WAPE for each product
        results: List[ProductAccuracyOut] = []
        import numpy as np
        
        # #region agent log
        wape_start = time.time()
        products_processed = 0
        # #endregion
        
        for product in products:
            # #region agent log
            product_start = time.time()
            # #endregion
            product_id = product.id
            actuals_by_date = actuals_by_product.get(product_id, {})
            forecasts_by_date = forecasts_by_product.get(product_id, {})
            
            # Calculate WAPE for valid points (both forecast and actual exist)
            valid_forecasts = []
            valid_actuals = []
            valid_is_supply_capped = []
            valid_count = 0
            zero_forecast_count = 0  # Track how many forecasts are 0
            delivery_by_date = delivery_by_product.get(product_id, {})
            supply_capped_by_date = supply_capped_by_product.get(product_id, {})
            
            # OPTIMIZATION: Only check dates that have both actual and forecast
            # This is more efficient than checking all dates
            dates_with_both = set(actuals_by_date.keys()) & set(forecasts_by_date.keys())
            
            # #region agent log
            today = date.today()
            sample_actual_dates = [str(d) for d in sorted(actuals_by_date.keys())[:5]] if actuals_by_date else []
            sample_forecast_dates = [str(d) for d in sorted(forecasts_by_date.keys())[:5]] if forecasts_by_date else []
            actual_date_range = None
            forecast_date_range = None
            if actuals_by_date:
                actual_dates_sorted = sorted(actuals_by_date.keys())
                actual_date_range = f"{actual_dates_sorted[0]} to {actual_dates_sorted[-1]}" if actual_dates_sorted else None
            if forecasts_by_date:
                forecast_dates_sorted = sorted(forecasts_by_date.keys())
                forecast_date_range = f"{forecast_dates_sorted[0]} to {forecast_dates_sorted[-1]}" if forecast_dates_sorted else None
            
            _debug_log("forecast_accuracy.py:220", "Date matching analysis", {
                "product_id": product_id,
                "product_name": product.name,
                "query_start_date": str(start_date),
                "query_end_date": str(end_date),
                "today": str(today),
                "actuals_dates_count": len(actuals_by_date),
                "forecasts_dates_count": len(forecasts_by_date),
                "dates_with_both_count": len(dates_with_both),
                "actual_date_range": actual_date_range,
                "forecast_date_range": forecast_date_range,
                "sample_actual_dates": sample_actual_dates,
                "sample_forecast_dates": sample_forecast_dates,
                "querying_past_dates": start_date < today,
            }, "E")
            # #endregion
            
            for d in dates_with_both:
                forecast_val = forecasts_by_date[d]  # Direct access since we know it exists
                actual_val = actuals_by_date[d]  # Direct access since we know it exists
                
                # #region agent log
                if len(valid_forecasts) < 3:  # Log first few matches for debugging
                    _debug_log("forecast_accuracy.py:235", "Date match details", {
                        "product_id": product_id,
                        "date": str(d),
                        "forecast_val": forecast_val,
                        "actual_val": actual_val
                    }, "E")
                # #endregion
                
                # Include ALL forecasts in WAPE calculation, including 0.0 forecasts
                # 0.0 is a valid model output and should be factored into accuracy metrics
                # Only exclude if forecast is None (truly missing), which is already filtered
                # by the query (DailyForecast.yhat.isnot(None))
                valid_forecasts.append(forecast_val)
                valid_actuals.append(actual_val)
                # Get supply-capped flag for this date
                is_capped = supply_capped_by_date.get(d, 0)
                valid_is_supply_capped.append(is_capped)
                valid_count += 1
                if forecast_val == 0.0:
                    zero_forecast_count += 1
            
            # Calculate WAPE (raw)
            wape = None
            if valid_count > 0 and len(valid_actuals) > 0:
                try:
                    wape_result = calculate_wape(
                        np.array(valid_actuals),
                        np.array(valid_forecasts)
                    )
                    if wape_result is not None and not np.isnan(wape_result):
                        wape = float(wape_result) * 100  # Convert to percentage
                        
                        # Log warning if all forecasts are 0 and actuals exist (may indicate training issue)
                        # Note: 0.0 forecasts are now included in WAPE calculation as valid model outputs
                        if zero_forecast_count == valid_count and valid_count > 0:
                            import logging
                            logger = logging.getLogger(__name__)
                            # Only warn if there are actuals > 0 (indicating model may be incorrectly predicting zero)
                            if any(a > 0 for a in valid_actuals):
                                logger.debug(
                                    f"Product {product_id}: All {valid_count} forecasts are 0.0 but actuals > 0 exist. "
                                    f"This may indicate a training issue (model incorrectly predicting zero). WAPE={wape:.2f}%"
                                )
                except Exception as e:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f"Error calculating WAPE for product {product_id}: {e}")
                    wape = None
            
            # Calculate Adjusted WAPE (censor-aware)
            wape_adjusted = None
            if valid_count > 0 and len(valid_actuals) > 0 and len(valid_is_supply_capped) > 0:
                try:
                    wape_adjusted_result = calculate_adjusted_wape(
                        np.array(valid_actuals),
                        np.array(valid_forecasts),
                        np.array(valid_is_supply_capped),
                        capped_overpred_penalty=0.2,  # Default soft censor
                    )
                    if wape_adjusted_result is not None and not np.isnan(wape_adjusted_result):
                        wape_adjusted = float(wape_adjusted_result) * 100  # Convert to percentage
                        
                        # Validation: adjusted WAPE should be <= raw WAPE when supply-capped days exist
                        capped_count = sum(valid_is_supply_capped)
                        if capped_count > 0 and wape is not None and wape_adjusted > wape:
                            import logging
                            logger = logging.getLogger(__name__)
                            logger.warning(
                                f"Product {product_id}: Adjusted WAPE ({wape_adjusted:.2f}%) > Raw WAPE ({wape:.2f}%) "
                                f"despite {capped_count} supply-capped days. This may indicate an issue."
                            )
                except Exception as e:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f"Error calculating Adjusted WAPE for product {product_id}: {e}")
                    wape_adjusted = None
            
            # Get base metrics from ForecastMetrics if available
            metrics = metrics_by_product.get(product_id)
            
            # #region agent log
            product_time = time.time() - product_start
            products_processed += 1
            if products_processed % 10 == 0 or products_processed == len(products):
                _debug_log("forecast_accuracy.py:193", "Product processing progress", {
                    "products_processed": products_processed,
                    "total_products": len(products),
                    "last_product_time_ms": round(product_time * 1000, 2),
                    "valid_count": valid_count
                }, "D")
            # #endregion
            
            results.append(
                ProductAccuracyOut(
                    product_id=product.id,
                    product_name=product.name,
                    mape=metrics.mape if metrics else None,
                    rmse=metrics.rmse if metrics else None,
                    wape=wape,
                    wape_adjusted=wape_adjusted,
                    n_points=metrics.n_points or 0 if metrics else 0,
                    valid_points_count=valid_count,
                    last_trained_at=metrics.last_trained_at if metrics else None,
                    start_date=start_date,
                    end_date=end_date,
                )
            )
        
        # #region agent log
        wape_time = time.time() - wape_start
        _debug_log("forecast_accuracy.py:207", "WAPE calculation completed", {
            "total_products": len(products),
            "total_time_ms": round(wape_time * 1000, 2),
            "avg_time_per_product_ms": round((wape_time / len(products)) * 1000, 2) if products else 0,
            "results_count": len(results)
        }, "D")
        # #endregion
        
        return results
    
    # Default behavior: use ForecastMetrics table
    # Fetch products for this bakery and any associated forecast metrics
    rows = (
        db.query(Product, ForecastMetrics)
        .outerjoin(ForecastMetrics, ForecastMetrics.product_id == Product.id)
        .filter(Product.bakery_id == bakery_id)
        .order_by(Product.name.asc())
        .all()
    )

    results: List[ProductAccuracyOut] = []
    for product, metrics in rows:
        if metrics is not None:
            results.append(
                ProductAccuracyOut(
                    product_id=product.id,
                    product_name=product.name,
                    mape=metrics.mape,
                    rmse=metrics.rmse,
                    wape=metrics.wape,  # Include WAPE from metrics
                    wape_adjusted=metrics.wape_adjusted,  # Include Adjusted WAPE from metrics
                    n_points=metrics.n_points or 0,
                    valid_points_count=None,
                    last_trained_at=metrics.last_trained_at,
                    start_date=None,
                    end_date=None,
                )
            )
        else:
            # No metrics yet – surface a placeholder entry so the UI can show
            # the product with "—" for accuracy and zero data points.
            results.append(
                ProductAccuracyOut(
                    product_id=product.id,
                    product_name=product.name,
                    mape=None,
                    rmse=None,
                    wape=None,
                    wape_adjusted=None,
                    n_points=0,
                    valid_points_count=None,
                    last_trained_at=None,
                    start_date=None,
                    end_date=None,
                )
            )

    return results


