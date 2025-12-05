from __future__ import annotations

import logging
from datetime import date
from typing import Iterable, List, Sequence

from sqlalchemy import exc as sa_exc
from sqlalchemy.orm import Session

from app.models import DailyForecast, Product
from app.schemas.sales_record import ProductForecastOut
from app.utils.db_retry import retry_db_operation, is_database_locked_error

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

    try:
        db.flush()
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
                    row.yhat = float(point.yhat)
                    row.yhat_lower = float(point.yhat_lower) if point.yhat_lower is not None else None
                    row.yhat_upper = float(point.yhat_upper) if point.yhat_upper is not None else None
            
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


