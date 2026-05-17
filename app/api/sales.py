from __future__ import annotations
from typing import List, Optional
import logging

from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models import SalesRecord, Product
from app.user_schemas import SalesRecordOut
from app.api.auth import get_current_user
from app.schemas import sales_record
from app.core.config import settings

logger = logging.getLogger("bakezy.api.sales")

router = APIRouter(
    prefix="/sales",
    tags=["sales"],
)


@router.get("/", response_model=List[SalesRecordOut])
def list_sales(
    bakery_id: int | None = None,
    product_id: int | None = None,
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(SalesRecord)
    if bakery_id is not None:
        query = query.filter(SalesRecord.bakery_id == bakery_id)
    if product_id is not None:
        query = query.filter(SalesRecord.product_id == product_id)
    if start_date is not None:
        query = query.filter(SalesRecord.date >= start_date)
    if end_date is not None:
        query = query.filter(SalesRecord.date <= end_date)
    return query.order_by(SalesRecord.date).all()


@router.get("/product/{product_id}", response_model=sales_record.ProductSalesSeries)
def get_product_sales_for_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")

    sales_rows = (
        db.query(SalesRecord)
        .filter(SalesRecord.product_id == product_id)
        .order_by(SalesRecord.date.asc())
        .all()
    )

    return sales_record.ProductSalesSeries(
        product_id=product.id,
        product_name=product.name,
        sales=[
            sales_record.ProductSalesPoint(date=row.date, quantity=row.quantity_sold)
            for row in sales_rows
        ],
    )
