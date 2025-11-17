from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

from app.database.database import get_db
from app.api.auth import get_current_user
from app.schemas.sales_record import SalesRecord, SalesRecordCreate
from app.crud import sales as crud_sales

router = APIRouter(prefix="/sales", tags=["sales"])


@router.post("/", response_model=SalesRecord)
def create_sales_record(
    payload: SalesRecordCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    bakery_id = current_user.bakery_id
    return crud_sales.create_sales_record(
        db, bakery_id=bakery_id, obj_in=payload
    )


@router.post("/bulk", response_model=List[SalesRecord])
def create_sales_records_bulk(
    payload: List[SalesRecordCreate],
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    bakery_id = current_user.bakery_id
    return crud_sales.create_sales_records_bulk(
        db, bakery_id=bakery_id, objs_in=payload
    )
