from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List

from app.db.session import get_db
from app.api.deps import get_current_user  # adjust to your deps path
from app.schemas.product import Product, ProductCreate, ProductUpdate
from app.crud import product as crud_product

router = APIRouter(prefix="/products", tags=["products"])


@router.post("/", response_model=Product)
def create_product(
    payload: ProductCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    bakery_id = current_user.bakery_id
    return crud_product.create_product(db, bakery_id=bakery_id, obj_in=payload)


@router.get("/", response_model=List[Product])
def list_products(
    skip: int = 0,
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    bakery_id = current_user.bakery_id
    return crud_product.list_products(
        db, bakery_id=bakery_id, skip=skip, limit=limit
    )


@router.get("/{product_id}", response_model=Product)
def get_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    bakery_id = current_user.bakery_id
    db_obj = crud_product.get_product(
        db, bakery_id=bakery_id, product_id=product_id
    )
    if not db_obj:
        raise HTTPException(status_code=404, detail="Product not found")
    return db_obj


@router.put("/{product_id}", response_model=Product)
def update_product(
    product_id: int,
    payload: ProductUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    bakery_id = current_user.bakery_id
    db_obj = crud_product.update_product(
        db, bakery_id=bakery_id, product_id=product_id, obj_in=payload
    )
    if not db_obj:
        raise HTTPException(status_code=404, detail="Product not found")
    return db_obj


@router.delete("/{product_id}")
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    bakery_id = current_user.bakery_id
    ok = crud_product.delete_product(
        db, bakery_id=bakery_id, product_id=product_id
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"success": True}
