from __future__ import annotations
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from app.database.database import get_db
from app.models import SalesRecord, Product, Bakery
from app.api.auth import get_current_user
from app.schemas.analytics import BakerySummary, TopProductSummary

router = APIRouter(
    prefix="/bakeries",
    tags=["analytics"],
)


@router.get("/{bakery_id}/summary", response_model=BakerySummary)
def get_bakery_summary(
    bakery_id: int,
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Summary for a bakery over the last `days` days.

    - total_units: total units sold in that window
    - previous_total_units: total in the immediately preceding window
    - pct_change_vs_previous: % change vs previous window (None if no prev data)
    - top_products: top products in the current window
    """
    # 1) Check bakery exists
    bakery = (
        db.query(Bakery)
        .filter(Bakery.id == bakery_id)
        .first()
    )
    if not bakery:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bakery not found",
        )

    today = date.today()
    start_date = today - timedelta(days=days)

    # 2) Total units in current window
    total_units = (
        db.query(func.coalesce(func.sum(SalesRecord.quantity_sold), 0.0))
        .filter(SalesRecord.bakery_id == bakery_id)
        .filter(SalesRecord.date >= start_date)
        .filter(SalesRecord.date <= today)
        .scalar()
    )

    # 3) Total units in previous window (same length, immediately before)
    prev_end = start_date - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)

    previous_total_units = (
        db.query(func.coalesce(func.sum(SalesRecord.quantity_sold), 0.0))
        .filter(SalesRecord.bakery_id == bakery_id)
        .filter(SalesRecord.date >= prev_start)
        .filter(SalesRecord.date <= prev_end)
        .scalar()
    )

    # 4) Compute percent change vs previous window
    pct_change: float | None = None
    if previous_total_units and previous_total_units != 0:
        pct_change = float(
            (total_units - previous_total_units) / previous_total_units * 100.0
        )

    # 5) Top products in current window
    top_rows = (
        db.query(
            SalesRecord.product_id,
            func.coalesce(func.sum(SalesRecord.quantity_sold), 0.0).label("units"),
            Product.name,
        )
        .join(Product, Product.id == SalesRecord.product_id)
        .filter(SalesRecord.bakery_id == bakery_id)
        .filter(SalesRecord.date >= start_date)
        .filter(SalesRecord.date <= today)
        .group_by(SalesRecord.product_id, Product.name)
        .order_by(desc("units"))
        .limit(5)
        .all()
    )

    top_products = [
        TopProductSummary(
            product_id=row.product_id,
            product_name=row.name,
            units_sold=row.units,
        )
        for row in top_rows
    ]

    return BakerySummary(
        bakery_id=bakery_id,
        bakery_name=bakery.name,
        as_of=today,
        window_days=days,
        total_units=float(total_units or 0),
        previous_total_units=float(previous_total_units or 0),
        pct_change_vs_previous=pct_change,
        top_products=top_products,
    )


