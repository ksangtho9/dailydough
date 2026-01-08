from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models import Bakery, Product, SalesRecord
from app.schemas.top_products import TopProductsResponse, TopProductItem

router = APIRouter(tags=["top-products"])


@router.get(
    "/bakeries/{bakery_id}/top-products",
    response_model=TopProductsResponse,
)
def get_top_products(
    bakery_id: int,
    window_days: int = Query(30, ge=1, le=365),
    limit: int = Query(5, ge=1, le=50),
    db: Session = Depends(get_db),
):
    bakery = db.query(Bakery).filter(Bakery.id == bakery_id).one_or_none()
    if bakery is None:
        raise HTTPException(status_code=404, detail="Bakery not found")

    end_date = date.today()
    start_date = end_date - timedelta(days=window_days)

    rows = (
        db.query(
            SalesRecord.product_id,
            Product.name.label("product_name"),
            func.sum(SalesRecord.quantity_sold).label("total_quantity"),
        )
        .join(Product, Product.id == SalesRecord.product_id)
        .filter(
            SalesRecord.bakery_id == bakery_id,
            SalesRecord.date >= start_date,
            SalesRecord.date <= end_date,
        )
        .group_by(SalesRecord.product_id, Product.name)
        .order_by(func.sum(SalesRecord.quantity_sold).desc())
        .limit(limit)
        .all()
    )

    items = [
        TopProductItem(
            product_id=row.product_id,
            product_name=row.product_name,
            total_quantity=float(row.total_quantity or 0.0),
        )
        for row in rows
    ]

    return TopProductsResponse(
        bakery_id=bakery.id,
        window_days=window_days,
        items=items,
    )












