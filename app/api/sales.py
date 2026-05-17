from __future__ import annotations
from typing import List, Optional
import logging

from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func
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


MAX_SALES_ROWS = 10_000


class TopProductStat(BaseModel):
    name: str
    total: float


class SalesStats(BaseModel):
    total_quantity: float
    days_with_sales: int
    average_per_day: float
    unique_products: int
    top_products: List[TopProductStat]


@router.get("/stats", response_model=SalesStats)
def get_sales_stats(
    bakery_id: int,
    start_date: date | None = Query(None),
    db: Session = Depends(get_db),
):
    filters = [SalesRecord.bakery_id == bakery_id]
    if start_date is not None:
        filters.append(SalesRecord.date >= start_date)

    total_qty = db.query(func.sum(SalesRecord.quantity_sold)).filter(*filters).scalar() or 0
    days_with_sales = db.query(func.count(func.distinct(SalesRecord.date))).filter(*filters).scalar() or 0
    unique_products = db.query(func.count(func.distinct(SalesRecord.product_id))).filter(*filters).scalar() or 0

    top_rows = (
        db.query(Product.name, func.sum(SalesRecord.quantity_sold).label("total"))
        .join(Product, SalesRecord.product_id == Product.id)
        .filter(*filters)
        .group_by(Product.name)
        .order_by(func.sum(SalesRecord.quantity_sold).desc())
        .limit(3)
        .all()
    )

    return SalesStats(
        total_quantity=float(total_qty),
        days_with_sales=days_with_sales,
        average_per_day=float(total_qty) / days_with_sales if days_with_sales > 0 else 0.0,
        unique_products=unique_products,
        top_products=[TopProductStat(name=r.name, total=float(r.total)) for r in top_rows],
    )


@router.get("/", response_model=List[SalesRecordOut])
def list_sales(
    bakery_id: int | None = None,
    product_id: int | None = None,
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    limit: int = Query(MAX_SALES_ROWS, le=MAX_SALES_ROWS),
    offset: int = Query(0, ge=0),
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
    return query.order_by(SalesRecord.date.desc()).limit(limit).offset(offset).all()


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
