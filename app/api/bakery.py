from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.database.database import get_db
from app.models import Bakery
from app.user_schemas import BakeryCreate, BakeryOut

router = APIRouter(
    prefix="/bakeries",
    tags=["bakeries"],
)


@router.post("/", response_model=BakeryOut, status_code=status.HTTP_201_CREATED)
def create_bakery(
    bakery_in: BakeryCreate,
    db: Session = Depends(get_db),
):
    bakery = Bakery(
        name=bakery_in.name,
        location=bakery_in.location,
    )
    db.add(bakery)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # name is UNIQUE, so this happens if the name already exists
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A bakery with this name already exists",
        )
    db.refresh(bakery)
    return bakery



@router.get("/", response_model=list[BakeryOut])
def list_bakeries(db: Session = Depends(get_db)):
    return db.query(Bakery).all()
