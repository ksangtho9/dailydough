from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import List, Optional
import logging

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.api.auth import get_current_user
from app.models import Product, ForecastMetrics, Bakery, SalesRecord, DailyForecast
from app.schemas.forecast_accuracy import ProductAccuracyOut
from app.ml.metrics import calculate_wape, calculate_adjusted_wape

logger = logging.getLogger(__name__)

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
    start_date: Optional[date] = Query(None, description="Start date for date-range accuracy"),
    end_date: Optional[date] = Query(None, description="End date (defaults to start_date if omitted)"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    bakery = db.query(Bakery).filter(Bakery.id == bakery_id).first()
    if bakery is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bakery not found")

    if start_date is not None:
        if end_date is None:
            end_date = start_date
        elif start_date > end_date:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="start_date must be <= end_date",
            )

        products = (
            db.query(Product)
            .filter(Product.bakery_id == bakery_id)
            .order_by(Product.name.asc())
            .all()
        )
        if not products:
            return []

        product_ids = [p.id for p in products]

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

        actuals_by_product: dict[int, dict[date, float]] = defaultdict(dict)
        supply_capped_by_product: dict[int, dict[date, int]] = defaultdict(dict)
        for row in sales_rows:
            qty = float(row.qty or 0.0)
            delivery = float(row.delivery or 0.0)
            actuals_by_product[row.product_id][row.day] = qty
            is_capped = (delivery > 0) and (qty >= 0.95 * delivery)
            supply_capped_by_product[row.product_id][row.day] = 1 if is_capped else 0

        daily_rows = (
            db.query(DailyForecast.product_id, DailyForecast.date, DailyForecast.yhat)
            .filter(
                DailyForecast.bakery_id == bakery_id,
                DailyForecast.product_id.in_(product_ids),
                DailyForecast.date >= start_date,
                DailyForecast.date <= end_date,
                DailyForecast.yhat.isnot(None),
            )
            .all()
        )

        forecasts_by_product: dict[int, dict[date, float]] = defaultdict(dict)
        for row in daily_rows:
            if row.yhat is not None:
                forecasts_by_product[row.product_id][row.date] = float(row.yhat)

        metrics_by_product = {
            m.product_id: m
            for m in db.query(ForecastMetrics)
            .filter(ForecastMetrics.product_id.in_(product_ids))
            .all()
        }

        results: List[ProductAccuracyOut] = []
        for product in products:
            actuals_by_date = actuals_by_product.get(product.id, {})
            forecasts_by_date = forecasts_by_product.get(product.id, {})
            supply_capped_by_date = supply_capped_by_product.get(product.id, {})

            dates_with_both = set(actuals_by_date.keys()) & set(forecasts_by_date.keys())
            valid_forecasts, valid_actuals, valid_is_supply_capped = [], [], []
            for d in dates_with_both:
                valid_forecasts.append(forecasts_by_date[d])
                valid_actuals.append(actuals_by_date[d])
                valid_is_supply_capped.append(supply_capped_by_date.get(d, 0))

            wape = None
            wape_adjusted = None
            mape = None
            rmse = None
            valid_count = len(valid_forecasts)

            if valid_count > 0:
                arr_actual = np.array(valid_actuals)
                arr_forecast = np.array(valid_forecasts)

                try:
                    wape_result = calculate_wape(arr_actual, arr_forecast)
                    if wape_result is not None and not np.isnan(wape_result):
                        wape = float(wape_result) * 100
                except Exception as e:
                    logger.error("Error calculating WAPE for product %d: %s", product.id, e)

                try:
                    adj_result = calculate_adjusted_wape(
                        arr_actual,
                        arr_forecast,
                        np.array(valid_is_supply_capped),
                        capped_overpred_penalty=0.2,
                    )
                    if adj_result is not None and not np.isnan(adj_result):
                        wape_adjusted = float(adj_result) * 100
                except Exception as e:
                    logger.error("Error calculating Adjusted WAPE for product %d: %s", product.id, e)

                try:
                    rmse_val = float(np.sqrt(np.mean((arr_forecast - arr_actual) ** 2)))
                    if not np.isnan(rmse_val):
                        rmse = rmse_val
                except Exception as e:
                    logger.error("Error calculating RMSE for product %d: %s", product.id, e)

                try:
                    nonzero = arr_actual > 0
                    if nonzero.any():
                        mape_val = float(np.mean(np.abs((arr_actual[nonzero] - arr_forecast[nonzero]) / arr_actual[nonzero])) * 100)
                        if not np.isnan(mape_val):
                            mape = mape_val
                except Exception as e:
                    logger.error("Error calculating MAPE for product %d: %s", product.id, e)

            metrics = metrics_by_product.get(product.id)
            results.append(
                ProductAccuracyOut(
                    product_id=product.id,
                    product_name=product.name,
                    mape=mape,
                    rmse=rmse,
                    wape=wape,
                    wape_adjusted=wape_adjusted,
                    n_points=metrics.n_points or 0 if metrics else 0,
                    valid_points_count=valid_count,
                    last_trained_at=metrics.last_trained_at if metrics else None,
                    start_date=start_date,
                    end_date=end_date,
                )
            )
        return results

    # Default: return precomputed ForecastMetrics
    rows = (
        db.query(Product, ForecastMetrics)
        .outerjoin(ForecastMetrics, ForecastMetrics.product_id == Product.id)
        .filter(Product.bakery_id == bakery_id)
        .order_by(Product.name.asc())
        .all()
    )

    return [
        ProductAccuracyOut(
            product_id=product.id,
            product_name=product.name,
            mape=None,
            rmse=None,
            wape=None,
            wape_adjusted=None,
            n_points=metrics.n_points or 0 if metrics else 0,
            valid_points_count=None,
            last_trained_at=metrics.last_trained_at if metrics else None,
            start_date=None,
            end_date=None,
        )
        for product, metrics in rows
    ]
