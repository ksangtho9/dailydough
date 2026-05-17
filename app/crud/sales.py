from __future__ import annotations
from typing import List
from sqlalchemy.orm import Session
from datetime import date

from app.models.sales_record import SalesRecord
from app.schemas.sales_record import SalesRecordCreate


def create_sales_record(
    db: Session,
    *,
    bakery_id: int,
    obj_in: SalesRecordCreate,
) -> SalesRecord:
    db_obj = SalesRecord(
        bakery_id=bakery_id,
        product_id=obj_in.product_id,
        date=obj_in.date,
        quantity_sold=obj_in.quantity_sold,
    )
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj


def create_sales_records_bulk(
    db: Session,
    *,
    bakery_id: int,
    objs_in: List[SalesRecordCreate],
) -> List[SalesRecord]:
    db_objs: List[SalesRecord] = []
    for obj_in in objs_in:
        db_obj = SalesRecord(
            bakery_id=bakery_id,
            product_id=obj_in.product_id,
            date=obj_in.date,
            quantity_sold=obj_in.quantity_sold,
        )
        db.add(db_obj)
        db_objs.append(db_obj)

    db.commit()
    for obj in db_objs:
        db.refresh(obj)
    return db_objs


def list_sales_for_product(
    db: Session,
    *,
    bakery_id: int,
    product_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
) -> List[SalesRecord]:
    q = db.query(SalesRecord).filter(
        SalesRecord.bakery_id == bakery_id,
        SalesRecord.product_id == product_id,
    )
    if start_date:
        q = q.filter(SalesRecord.date >= start_date)
    if end_date:
        q = q.filter(SalesRecord.date <= end_date)
    return q.order_by(SalesRecord.date).all()
