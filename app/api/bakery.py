# app/api/bakery.py

from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ..db import get_db
from ..user_models import Bakery, User
from ..user_schemas import BakeryCreate, BakeryOut
from .auth import get_current_user

router = APIRouter(tags=["bakeries"])


@router.post("/", response_model=BakeryOut, status_code=status.HTTP_201_CREATED)
def create_bakery(
    bakery_in: BakeryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    bakery = Bakery(
        name=bakery_in.name,
        location=bakery_in.location,
        owner_id=current_user.id,
    )
    db.add(bakery)
    db.commit()
    db.refresh(bakery)
    return bakery


@router.get("/", response_model=List[BakeryOut])
def list_my_bakeries(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    bakeries = (
        db.query(Bakery)
        .filter(Bakery.owner_id == current_user.id)
        .order_by(Bakery.created_at.desc())
        .all()
    )
    return bakeries
