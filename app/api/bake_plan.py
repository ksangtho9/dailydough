from __future__ import annotations

from datetime import date, timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models import Bakery, Product
from app.ml.inference.forecast_service import get_forecast_for_product
from app.schemas.bake_plan import BakePlanItem, BakePlanResponse

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

    for product in products:
        try:
            forecast = get_forecast_for_product(
                product_id=product.id,
                days_ahead=14,
                db=db,
            )
        except Exception:
            continue

        points = forecast.points if hasattr(forecast, "points") else forecast.get("points", [])
        match = next(
            (
                p
                for p in points
                if str(getattr(p, "date", p.get("date"))) == plan_date.isoformat()
            ),
            None,
        )
        if match is None:
            continue

        qty = getattr(match, "yhat", match.get("yhat", 0))
        forecast_qty = max(0, int(round(qty)))
        if forecast_qty <= 0:
            continue

        items.append(
            BakePlanItem(
                product_id=product.id,
                product_name=product.name,
                forecast_quantity=forecast_qty,
            )
        )

    items.sort(key=lambda x: x.forecast_quantity, reverse=True)

    return BakePlanResponse(
        bakery_id=bakery.id,
        bakery_name=bakery.name,
        date=plan_date,
        items=items,
    )

