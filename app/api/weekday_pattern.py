from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models import Product, SalesRecord
from app.schemas.weekday_pattern import WeekdayPatternResponse, WeekdayValue

router = APIRouter(tags=["weekday-pattern"])


@router.get(
    "/products/{product_id}/weekday-pattern",
    response_model=WeekdayPatternResponse,
)
def get_weekday_pattern(
    product_id: int,
    window_days: int = Query(90, ge=7, le=365),
    db: Session = Depends(get_db),
):
    product = db.query(Product).filter(Product.id == product_id).one_or_none()
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    end_date = date.today()
    start_date = end_date - timedelta(days=window_days)

    rows = (
        db.query(
            func.strftime("%w", SalesRecord.date).label("dow"),
            func.avg(SalesRecord.quantity_sold).label("avg_quantity"),
        )
        .filter(
            SalesRecord.product_id == product_id,
            SalesRecord.date >= start_date,
            SalesRecord.date <= end_date,
        )
        .group_by("dow")
        .all()
    )

    weekday_map = {
        "0": 6,
        "1": 0,
        "2": 1,
        "3": 2,
        "4": 3,
        "5": 4,
        "6": 5,
    }
    labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    raw: dict[int, float] = {}
    for row in rows:
        python_dow = weekday_map.get(row.dow)
        if python_dow is None:
            continue
        raw[python_dow] = float(row.avg_quantity or 0.0)

    points = [
        WeekdayValue(
            weekday=w,
            label=labels[w],
            avg_quantity=raw.get(w, 0.0),
        )
        for w in range(7)
    ]

    return WeekdayPatternResponse(
        product_id=product.id,
        window_days=window_days,
        points=points,
    )











