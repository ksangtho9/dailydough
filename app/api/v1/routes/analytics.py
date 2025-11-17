from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
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
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # 1) Make sure the bakery exists
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
    d7 = today - timedelta(days=7)
    d30 = today - timedelta(days=30)

    # 2) Total units last 7 days
    total_7 = (
        db.query(func.coalesce(func.sum(SalesRecord.quantity_sold), 0.0))
        .filter(SalesRecord.bakery_id == bakery_id)
        .filter(SalesRecord.date >= d7)
        .filter(SalesRecord.date <= today)
        .scalar()
    )

    # 3) Total units last 30 days
    total_30 = (
        db.query(func.coalesce(func.sum(SalesRecord.quantity_sold), 0.0))
        .filter(SalesRecord.bakery_id == bakery_id)
        .filter(SalesRecord.date >= d30)
        .filter(SalesRecord.date <= today)
        .scalar()
    )

    # 4) Top 5 products by units in last 30 days
    top_rows = (
        db.query(
            SalesRecord.product_id,
            func.coalesce(func.sum(SalesRecord.quantity_sold), 0.0).label("units"),
            Product.name,
        )
        .join(Product, Product.id == SalesRecord.product_id)
        .filter(SalesRecord.bakery_id == bakery_id)
        .filter(SalesRecord.date >= d30)
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

    # 5) Return summary INCLUDING bakery_name
    return BakerySummary(
        bakery_id=bakery_id,
        bakery_name=bakery.name,   # 👈 this was missing before
        as_of=today,
        total_units_last_7_days=float(total_7 or 0),
        total_units_last_30_days=float(total_30 or 0),
        top_products_last_30_days=top_products,
    )


