from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models import Bakery, Product
from app.ml.inference.forecast_service import get_forecast_for_product
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

    for product in products:
        try:
            forecast = get_forecast_for_product(
                product_id=product.id,
                days_ahead=14,
                db=db,
            )
            logger.debug(
                "Forecast generated successfully for product_id=%d, product_name=%s",
                product.id,
                product.name,
            )
        except Exception as e:
            logger.warning(
                "Failed to generate forecast for product_id=%d, product_name=%s: %s",
                product.id,
                product.name,
                str(e),
                exc_info=True,
            )
            continue

        # Validate forecast response structure
        if not hasattr(forecast, "points"):
            logger.warning(
                "Forecast response missing 'points' attribute for product_id=%d",
                product.id,
            )
            continue
        
        points = forecast.points
        if not points or len(points) == 0:
            logger.warning(
                "Forecast returned empty points list for product_id=%d",
                product.id,
            )
            continue

        # Find matching forecast point for the plan date
        # Compare date objects directly instead of string conversion
        match = None
        for p in points:
            point_date = getattr(p, "date", None)
            if point_date is None:
                continue
            # Handle both date objects and date strings
            if isinstance(point_date, date):
                if point_date == plan_date:
                    match = p
                    break
            elif isinstance(point_date, str):
                try:
                    parsed_date = date.fromisoformat(point_date)
                    if parsed_date == plan_date:
                        match = p
                        break
                except (ValueError, TypeError):
                    logger.debug(
                        "Could not parse date string '%s' for product_id=%d",
                        point_date,
                        product.id,
                    )
                    continue

        if match is None:
            # Log available dates for debugging
            available_dates = [
                getattr(p, "date", None) for p in points[:5]  # First 5 dates
            ]
            logger.debug(
                "No forecast match found for product_id=%d, plan_date=%s. "
                "Available forecast dates (first 5): %s",
                product.id,
                plan_date.isoformat(),
                available_dates,
            )
            continue

        qty = getattr(match, "yhat", 0)
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




