from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import exc as sa_exc
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models import Bakery, Product, DailyForecast
from app.ml.inference.forecast_service import get_forecast_for_product
from app.services.daily_forecast_service import upsert_product_daily_forecasts
from app.services.risk_calculator import calculate_risk_metrics
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
    request_id = uuid.uuid4().hex[:8]

    products = (
        db.query(Product)
        .filter(Product.bakery_id == bakery_id)
        .order_by(Product.name.asc())
        .all()
    )

    items: List[BakePlanItem] = []

    logger.info(
        "Bake plan request: request_id=%s, bakery_id=%d, plan_date=%s, products_count=%d",
        request_id,
        bakery_id,
        plan_date.isoformat(),
        len(products),
    )

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
        product_id = product.id
        product_name = product.name
        product_sku = product.sku

        row = precomputed_by_product.get(product_id)

        if row is None and not settings.disable_on_demand_analytics_forecasts:
            # Fallback: run on-demand forecast and cache it for future requests.
            # Training ended months ago so we need a large enough horizon to cover plan_date.
            today = date.today()
            days_needed = max(180, (plan_date - today).days + 400)
            try:
                forecast = get_forecast_for_product(
                    product_id=product_id,
                    days_ahead=days_needed,
                    db=db,
                )

                if forecast and forecast.points:
                    try:
                        upsert_product_daily_forecasts(db, product=product, forecast=forecast)
                    except Exception as storage_error:
                        logger.error(
                            "Failed to store forecast for product_id=%d: %s",
                            product_id,
                            storage_error,
                            exc_info=True,
                        )

                    row = (
                        db.query(DailyForecast)
                        .filter(
                            DailyForecast.bakery_id == bakery_id,
                            DailyForecast.product_id == product_id,
                            DailyForecast.date == plan_date,
                        )
                        .one_or_none()
                    )

            except sa_exc.OperationalError as e:
                msg = str(e.orig) if getattr(e, "orig", None) is not None else str(e)
                if "database is locked" in msg.lower():
                    logger.warning(
                        "Bake plan: database is locked for product_id=%d, bakery_id=%d, plan_date=%s",
                        product_id,
                        bakery_id,
                        plan_date.isoformat(),
                        exc_info=True,
                    )
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    continue
                raise
            except sa_exc.PendingRollbackError as e:
                logger.warning(
                    "Session in bad state for product_id=%d, rolling back and skipping: %s",
                    product_id,
                    str(e),
                    exc_info=True,
                )
                try:
                    db.rollback()
                except Exception:
                    pass
                continue
            except Exception as e:
                logger.warning(
                    "Failed to generate forecast for product_id=%d, product_name=%s: %s",
                    product_id,
                    product_name,
                    str(e),
                    exc_info=True,
                )
                try:
                    db.rollback()
                except Exception:
                    pass
                continue

        forecast_qty = 0 if row is None else max(0, int(round(float(row.yhat or 0.0))))

        logger.debug(
            "Adding product to bake plan: product_id=%d, forecast_quantity=%d",
            product_id,
            forecast_qty,
        )

        risk_metrics = None
        if row is not None:
            yhat = float(row.yhat or 0.0)
            yhat_lower = float(row.yhat_lower) if row.yhat_lower is not None else None
            yhat_upper = float(row.yhat_upper) if row.yhat_upper is not None else None

            risk_metrics = calculate_risk_metrics(
                yhat=yhat,
                yhat_lower=yhat_lower,
                yhat_upper=yhat_upper,
                planned_qty=float(forecast_qty),
                interval_level=None,
            )

            logger.info(
                "Risk calculation: request_id=%s, bakery_id=%d, product_id=%d, date=%s, "
                "yhat=%.2f, lower=%s, upper=%s, planned_qty=%d, "
                "waste_risk_prob=%.4f, stockout_risk_prob=%.4f, risk_method=%s, "
                "interval_level_used=%s, risk_sigma=%.4f, sigma_clamped=%s",
                request_id,
                bakery_id,
                product_id,
                plan_date.isoformat(),
                yhat,
                f"{yhat_lower:.2f}" if yhat_lower is not None else "None",
                f"{yhat_upper:.2f}" if yhat_upper is not None else "None",
                forecast_qty,
                risk_metrics["waste_risk_prob"],
                risk_metrics["stockout_risk_prob"],
                risk_metrics["risk_method"],
                risk_metrics["interval_level_used"],
                risk_metrics["risk_sigma"],
                risk_metrics["sigma_clamped"],
            )
        else:
            logger.debug(
                "No forecast row for product_id=%d, date=%s - skipping risk calculation",
                product_id,
                plan_date.isoformat(),
            )

        items.append(
            BakePlanItem(
                product_id=product_id,
                product_name=product_name,
                forecast_quantity=forecast_qty,
                sku=product_sku,
                waste_risk_prob=risk_metrics["waste_risk_prob"] if risk_metrics else None,
                stockout_risk_prob=risk_metrics["stockout_risk_prob"] if risk_metrics else None,
                risk_sigma=risk_metrics["risk_sigma"] if risk_metrics else None,
                interval_level_used=risk_metrics["interval_level_used"] if risk_metrics else None,
                risk_method=risk_metrics["risk_method"] if risk_metrics else None,
                debug_source=risk_metrics["debug_source"] if risk_metrics else None,
                sigma_clamped=risk_metrics["sigma_clamped"] if risk_metrics else None,
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
