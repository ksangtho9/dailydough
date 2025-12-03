from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import exc as sa_exc
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models import Bakery, Product, DailyForecast
from app.ml.inference.forecast_service import get_forecast_for_product
from app.services.daily_forecast_service import upsert_product_daily_forecasts
from app.core.config import settings
from app.schemas.bake_plan import BakePlanItem, BakePlanResponse

logger = logging.getLogger("bakezy.bake_plan")

router = APIRouter(tags=["bake-plan"])


@router.get(
    "/bakeries/{bakery_id}/bake-plan",
    response_model=BakePlanResponse,
)
def get_bake_plan(
    bakery_id: int,
    target_date: date | None = Query(
        default=None,
        description="ISO date. Defaults to tomorrow.",
    ),
    db: Session = Depends(get_db),
):
    bakery = db.query(Bakery).filter(Bakery.id == bakery_id).one_or_none()
    if bakery is None:
        raise HTTPException(status_code=404, detail="Bakery not found")

    plan_date = target_date or (date.today() + timedelta(days=1))

    products = (
        db.query(Product)
        .filter(Product.bakery_id == bakery_id)
        .order_by(Product.name.asc())
        .all()
    )

    items: List[BakePlanItem] = []
    
    logger.info(
        "Generating bake plan for bakery_id=%d, plan_date=%s, products_count=%d",
        bakery_id,
        plan_date.isoformat(),
        len(products),
    )

    # Try to use precomputed daily forecasts for the plan date, falling back
    # to on-demand forecasting only for products that are missing rows.
    precomputed_rows = (
        db.query(DailyForecast)
        .filter(
            DailyForecast.bakery_id == bakery_id,
            DailyForecast.date == plan_date,
        )
        .all()
    )
    precomputed_by_product = {row.product_id: row for row in precomputed_rows}

    for product in products:
        row = precomputed_by_product.get(product.id)

        if row is None and not settings.disable_on_demand_analytics_forecasts:
            # Fallback: run a single on-demand forecast for this product,
            # then store its daily points for future requests.
            try:
                forecast = get_forecast_for_product(
                    product_id=product.id,
                    days_ahead=14,
                    db=db,
                )
                upsert_product_daily_forecasts(
                    db,
                    product=product,
                    forecast=forecast,
                )
                row = (
                    db.query(DailyForecast)
                    .filter(
                        DailyForecast.bakery_id == bakery_id,
                        DailyForecast.product_id == product.id,
                        DailyForecast.date == plan_date,
                    )
                    .one_or_none()
                )
            except sa_exc.OperationalError as e:
                # Handle SQLite \"database is locked\" errors gracefully by rolling
                # back the current transaction and skipping this product.
                msg = str(e.orig) if getattr(e, "orig", None) is not None else str(e)
                if "database is locked" in msg:
                    logger.warning(
                        "Bake plan: database is locked while upserting daily forecasts for "
                        "product_id=%d, skipping this product for bakery_id=%d, plan_date=%s",
                        product.id,
                        bakery_id,
                        plan_date.isoformat(),
                        exc_info=True,
                    )
                    db.rollback()
                    continue
                # Re-raise other OperationalError instances
                raise
            except Exception as e:
                logger.warning(
                    "Failed to generate forecast for product_id=%d, product_name=%s: %s",
                    product.id,
                    product.name,
                    str(e),
                    exc_info=True,
                )
                db.rollback()
                continue

        if row is None:
            continue

        qty = float(row.yhat or 0.0)
        forecast_qty = max(0, int(round(qty)))
        if forecast_qty <= 0:
            logger.debug(
                "Forecast quantity is zero or negative for product_id=%d (yhat=%.2f)",
                product.id,
                qty,
            )
            continue

        logger.debug(
            "Adding product to bake plan: product_id=%d, forecast_quantity=%d",
            product.id,
            forecast_qty,
        )
        items.append(
            BakePlanItem(
                product_id=product.id,
                product_name=product.name,
                forecast_quantity=forecast_qty,
                sku=product.sku,
            )
        )

    items.sort(key=lambda x: x.forecast_quantity, reverse=True)

    logger.info(
        "Bake plan generated successfully: bakery_id=%d, plan_date=%s, items_count=%d",
        bakery.id,
        plan_date.isoformat(),
        len(items),
    )

    return BakePlanResponse(
        bakery_id=bakery.id,
        bakery_name=bakery.name,
        date=plan_date,
        items=items,
    )




