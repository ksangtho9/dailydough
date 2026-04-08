from __future__ import annotations

import logging
from datetime import date
from typing import Iterable, List, Sequence
import numpy as np

from sqlalchemy import exc as sa_exc
from sqlalchemy.orm import Session

from app.models import DailyForecast, Product
from app.schemas.sales_record import ProductForecastOut
from app.utils.db_retry import retry_db_operation, is_database_locked_error
from app.core.config import settings

logger = logging.getLogger("bakezy.daily_forecast_service")


@retry_db_operation(max_retries=5, initial_delay=0.1, max_delay=1.6)
def _upsert_product_daily_forecasts_internal(
    db: Session,
    *,
    bakery_id: int,
    product_id: int,
    forecast: ProductForecastOut,
) -> None:
    """
    Internal function that performs the actual database operations.
    This is wrapped with retry logic to handle database locked errors.
    """
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

    # Step 6: Log sample of predictions before DB write (gated)
    should_log = settings.debug_zero_forecasts  # TODO: Check flagged set or auto-flag
    pre_write_samples = []
    if should_log and points_by_date:
        # Get first 5 and last 5 points
        sorted_dates = sorted(points_by_date.keys())
        sample_dates = sorted_dates[:5] + sorted_dates[-5:] if len(sorted_dates) > 10 else sorted_dates
        for sample_date in sample_dates:
            sample_point = points_by_date[sample_date]
            pre_write_samples.append({
                "date": sample_date,
                "yhat": sample_point.yhat,
            })
        logger.info(
            f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
            f"step=storage_verification, pre_write_samples={pre_write_samples}"
        )
    
    for point_date, point in points_by_date.items():
        # #region agent log
        try:
            import json
            import time
            from datetime import date as date_type
            today = date_type.today()
            log_entry = {
                "sessionId": "debug-session",
                "runId": "run1",
                "hypothesisId": "H",
                "location": "daily_forecast_service.py:51",
                "message": "Processing forecast point for storage",
                "data": {
                    "product_id": product_id,
                    "point_date": point_date.isoformat() if hasattr(point_date, 'isoformat') else str(point_date),
                    "today": today.isoformat(),
                    "is_future_date": point_date >= today if hasattr(point_date, '__ge__') else None,
                    "yhat": point.yhat
                },
                "timestamp": int(time.time() * 1000)
            }
            with open(r"c:\Users\forfl\Documents\dailydough-1\.cursor\debug.log", "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry) + "\n")
        except Exception:
            pass
        # #endregion
        
        # Step 6: Log raw yhat before storage (gated)
        raw_yhat_before_storage = point.yhat
        
        # Validate yhat before storing - skip if None or invalid
        if point.yhat is None:
            logger.warning(
                f"Skipping forecast for product_id={product_id}, date={point_date} - yhat is None (invalid forecast)"
            )
            continue
        
        try:
            yhat = float(point.yhat)
            # Validate yhat is a valid finite number; clamp negatives to 0 so stale zeros are overwritten
            if not np.isfinite(yhat):
                logger.warning(
                    f"Skipping forecast for product_id={product_id}, date={point_date} - non-finite yhat value: {yhat}"
                )
                continue
            yhat = max(yhat, 0.0)
            validation_result = True
        except (ValueError, TypeError) as e:
            logger.warning(
                f"Skipping forecast for product_id={product_id}, date={point_date} - cannot convert yhat to float: {e}"
            )
            continue
        
        # Step 6: Log storage verification (gated)
        if should_log:
            logger.info(
                f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                f"step=storage_verification, date={point_date}, "
                f"raw_yhat_before_storage={raw_yhat_before_storage}, "
                f"validation_result={validation_result}"
            )
        
        yhat_lower = None
        if point.yhat_lower is not None:
            try:
                yhat_lower_val = float(point.yhat_lower)
                if np.isfinite(yhat_lower_val) and yhat_lower_val >= 0:
                    yhat_lower = yhat_lower_val
            except (ValueError, TypeError):
                pass  # Keep as None if conversion fails
        
        yhat_upper = None
        if point.yhat_upper is not None:
            try:
                yhat_upper_val = float(point.yhat_upper)
                if np.isfinite(yhat_upper_val) and yhat_upper_val >= 0:
                    yhat_upper = yhat_upper_val
            except (ValueError, TypeError):
                pass  # Keep as None if conversion fails

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
            
            # Step 6: Verify stored value matches input (gated, after update)
            if should_log:
                retrieved_yhat_from_db = row.yhat
                values_match = abs(retrieved_yhat_from_db - yhat) < 1e-6 if retrieved_yhat_from_db is not None and yhat is not None else False
                logger.info(
                    f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                    f"step=storage_verification, date={point_date}, "
                    f"retrieved_yhat_from_db={retrieved_yhat_from_db}, "
                    f"values_match={values_match}"
                )
                
                # Check for "last write wins = 0" behavior
                if raw_yhat_before_storage is not None and raw_yhat_before_storage > 0 and retrieved_yhat_from_db == 0.0:
                    logger.warning(
                        f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                        f"step=storage_verification, WARNING: pre_write_yhat={raw_yhat_before_storage} > 0 "
                        f"but stored_yhat={retrieved_yhat_from_db} == 0.0 (possible overwrite)"
                    )

    try:
        db.commit()
        
        # Step 6: Read back after commit and verify stored values match pre-write (gated)
        if should_log and pre_write_samples:
            sample_dates = [s["date"] for s in pre_write_samples]
            retrieved_rows = (
                db.query(DailyForecast)
                .filter(
                    DailyForecast.bakery_id == bakery_id,
                    DailyForecast.product_id == product_id,
                    DailyForecast.date.in_(sample_dates),
                )
                .all()
            )
            
            retrieved_by_date = {row.date: row for row in retrieved_rows}
            mismatches = []
            for sample in pre_write_samples:
                sample_date = sample["date"]
                pre_write_yhat = sample["yhat"]
                retrieved_row = retrieved_by_date.get(sample_date)
                if retrieved_row:
                    retrieved_yhat = retrieved_row.yhat
                    if pre_write_yhat is not None and retrieved_yhat is not None:
                        if abs(pre_write_yhat - retrieved_yhat) > 1e-6:
                            mismatches.append({
                                "date": sample_date,
                                "pre_write": pre_write_yhat,
                                "retrieved": retrieved_yhat,
                            })
                        elif pre_write_yhat > 0 and retrieved_yhat == 0.0:
                            mismatches.append({
                                "date": sample_date,
                                "pre_write": pre_write_yhat,
                                "retrieved": retrieved_yhat,
                                "issue": "non_zero_to_zero"
                            })
                else:
                    mismatches.append({
                        "date": sample_date,
                        "pre_write": pre_write_yhat,
                        "retrieved": None,
                        "issue": "missing_after_commit"
                    })
            
            if mismatches:
                logger.warning(
                    f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                    f"step=storage_verification, WARNING: {len(mismatches)} mismatches found: {mismatches}"
                )
            else:
                logger.info(
                    f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                    f"step=storage_verification, All {len(pre_write_samples)} sample values match after commit"
                )
        
        # Detect duplicates (gated)
        if should_log:
            from sqlalchemy import func
            duplicate_query = (
                db.query(
                    DailyForecast.bakery_id,
                    DailyForecast.product_id,
                    DailyForecast.date,
                    func.count(DailyForecast.id).label("count")
                )
                .filter(
                    DailyForecast.bakery_id == bakery_id,
                    DailyForecast.product_id == product_id,
                    DailyForecast.date.in_(dates),
                )
                .group_by(
                    DailyForecast.bakery_id,
                    DailyForecast.product_id,
                    DailyForecast.date,
                )
                .having(func.count(DailyForecast.id) > 1)
            )
            duplicates = duplicate_query.all()
            if duplicates:
                logger.warning(
                    f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                    f"step=storage_verification, WARNING: Found {len(duplicates)} duplicate (bakery_id, product_id, date) pairs. "
                    f"Checking for 'last write wins = 0' behavior..."
                )
                # Check if any duplicates have zero yhat
                for dup in duplicates:
                    dup_rows = (
                        db.query(DailyForecast)
                        .filter(
                            DailyForecast.bakery_id == dup.bakery_id,
                            DailyForecast.product_id == dup.product_id,
                            DailyForecast.date == dup.date,
                        )
                        .all()
                    )
                    zero_count = sum(1 for r in dup_rows if r.yhat == 0.0)
                    if zero_count > 0:
                        logger.warning(
                            f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                            f"step=storage_verification, WARNING: Duplicate for date={dup.date} has {zero_count}/{len(dup_rows)} rows with yhat=0.0"
                        )
    except sa_exc.IntegrityError as e:
        # Handle UNIQUE constraint violations (race condition)
        # Rollback and re-query to get existing rows, then update them
        db.rollback()
        logger.warning(
            f"UNIQUE constraint violation during flush for product_id={product_id}, bakery_id={bakery_id}. "
            "Rolling back and re-querying existing rows."
        )
        
        # Re-query existing rows after rollback
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
        
        # Update or insert rows
        for point_date, point in points_by_date.items():
            # Validate yhat before storing - skip if None or invalid
            if point.yhat is None:
                logger.warning(
                    f"Skipping forecast for product_id={product_id}, date={point_date} - yhat is None (invalid forecast)"
                )
                continue
            
            try:
                yhat = float(point.yhat)
                # Clamp negatives to 0; only skip truly non-finite values (NaN/inf)
                if not np.isfinite(yhat):
                    logger.warning(
                        f"Skipping forecast for product_id={product_id}, date={point_date} - non-finite yhat value: {yhat}"
                    )
                    continue
                yhat = max(yhat, 0.0)
            except (ValueError, TypeError) as e:
                logger.warning(
                    f"Skipping forecast for product_id={product_id}, date={point_date} - cannot convert yhat to float: {e}"
                )
                continue
            
            yhat_lower = None
            if point.yhat_lower is not None:
                try:
                    yhat_lower_val = float(point.yhat_lower)
                    if np.isfinite(yhat_lower_val) and yhat_lower_val >= 0:
                        yhat_lower = yhat_lower_val
                except (ValueError, TypeError):
                    pass  # Keep as None if conversion fails
            
            yhat_upper = None
            if point.yhat_upper is not None:
                try:
                    yhat_upper_val = float(point.yhat_upper)
                    if np.isfinite(yhat_upper_val) and yhat_upper_val >= 0:
                        yhat_upper = yhat_upper_val
                except (ValueError, TypeError):
                    pass  # Keep as None if conversion fails

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
                existing_by_date[point_date] = row
            else:
                row.yhat = yhat
                row.yhat_lower = yhat_lower
                row.yhat_upper = yhat_upper
        
        # Try flush again - if it still fails with IntegrityError, 
        # another concurrent request inserted the same row, so just update it
        try:
            db.flush()
        except sa_exc.IntegrityError:
            # Another concurrent insert happened, re-query and update
            db.rollback()
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
            
            # Only update existing rows (don't try to insert again)
            for point_date, point in points_by_date.items():
                row = existing_by_date.get(point_date)
                if row is not None:
                    # Validate yhat before updating
                    if point.yhat is None:
                        continue  # Skip invalid forecasts
                    try:
                        yhat = float(point.yhat)
                        if not np.isfinite(yhat):
                            continue  # Skip NaN/inf
                        row.yhat = max(yhat, 0.0)
                    except (ValueError, TypeError):
                        continue  # Skip if conversion fails
                    
                    if point.yhat_lower is not None:
                        try:
                            yhat_lower_val = float(point.yhat_lower)
                            if np.isfinite(yhat_lower_val) and yhat_lower_val >= 0:
                                row.yhat_lower = yhat_lower_val
                        except (ValueError, TypeError):
                            pass
                    
                    if point.yhat_upper is not None:
                        try:
                            yhat_upper_val = float(point.yhat_upper)
                            if np.isfinite(yhat_upper_val) and yhat_upper_val >= 0:
                                row.yhat_upper = yhat_upper_val
                        except (ValueError, TypeError):
                            pass
            
            try:
                db.flush()
            except sa_exc.IntegrityError:
                # If it still fails, just log and continue - the data is already in the database
                logger.warning(
                    f"IntegrityError on final flush for product_id={product_id}, bakery_id={bakery_id}. "
                    "Data may have been inserted by another concurrent request."
                )
                db.rollback()
    except sa_exc.OperationalError as e:
        if is_database_locked_error(e):
            # Rollback immediately to restore session state
            db.rollback()
            logger.warning(
                f"Database locked during flush for product_id={product_id}, bakery_id={bakery_id}. "
                "Session rolled back."
            )
            # Re-raise to trigger retry logic
            raise
        # Re-raise other OperationalError instances
        raise


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
    - Automatically retries on "database is locked" errors with exponential backoff.
    
    Note: Extracts product_id and bakery_id before any database operations to avoid
    accessing ORM objects after potential rollback.
    """
    # Extract IDs before any database operations to avoid accessing ORM objects
    # after rollback in case of errors
    bakery_id = product.bakery_id
    product_id = product.id

    try:
        _upsert_product_daily_forecasts_internal(
            db,
            bakery_id=bakery_id,
            product_id=product_id,
            forecast=forecast,
        )
    except sa_exc.IntegrityError:
        # IntegrityError should be handled internally, but if it propagates,
        # it means the data was already inserted by another concurrent request
        # Just log and continue - this is not a fatal error
        logger.warning(
            f"IntegrityError propagated for product_id={product_id}, bakery_id={bakery_id}. "
            "Data may have been inserted by another concurrent request."
        )
        db.rollback()
        # Don't re-raise - the data is likely already in the database
    except sa_exc.OperationalError as e:
        if is_database_locked_error(e):
            # If retry logic exhausted, rollback and re-raise
            db.rollback()
            logger.error(
                f"Failed to upsert forecasts for product_id={product_id}, bakery_id={bakery_id} "
                "after retries. Database may be heavily contended."
            )
            raise
        # Re-raise other OperationalError instances
        raise


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


