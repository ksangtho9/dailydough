# app/api/product.py

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..db import get_db
from ..user_models import Product, Bakery, User
from ..user_schemas import ProductCreate, ProductOut
from .auth import get_current_user

router = APIRouter(tags=["products"])


def _get_owned_bakery(db: Session, bakery_id: int, user_id: int) -> Bakery:
    bakery = db.query(Bakery).filter(Bakery.id == bakery_id).first()
    if bakery is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bakery not found",
        )
    if bakery.owner_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this bakery",
        )
    return bakery


@router.post("/", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(
    product_in: ProductCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Confirm bakery belongs to current user
    _get_owned_bakery(db, product_in.bakery_id, current_user.id)

    product = Product(
        bakery_id=product_in.bakery_id,
        name=product_in.name,
        sku=product_in.sku,
        category=product_in.category,
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@router.get("/by-bakery/{bakery_id}", response_model=List[ProductOut])
def list_products_for_bakery(
    bakery_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Confirm bakery belongs to current user
    _get_owned_bakery(db, bakery_id, current_user.id)

    products = (
        db.query(Product)
        .filter(Product.bakery_id == bakery_id, Product.is_active == 1)
        .order_by(Product.name.asc())
        .all()
    )
    return products
