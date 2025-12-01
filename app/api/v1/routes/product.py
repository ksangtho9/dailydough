from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List

from app.database.database import get_db
from app.api.auth import get_current_user
from app.schemas.product import Product, ProductCreate, ProductUpdate
from app.crud import product as crud_product
from app.models import SalesRecord, Product as ProductModel, ForecastMetrics

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


@router.delete("/", summary="Delete all products and related data for a bakery")
def delete_all_products_for_bakery(
    bakery_id: int = Query(..., description="Bakery ID to delete products for"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Delete all products for the given bakery, along with their sales records
    and forecast metrics.
    """

    # Collect product IDs for this bakery
    product_ids = [
        p.id
        for p in db.query(ProductModel.id).filter(
            ProductModel.bakery_id == bakery_id
        ).all()
    ]

    if not product_ids:
        return {
            "deleted_products": 0,
            "deleted_sales": 0,
            "deleted_metrics": 0,
        }

    # Delete related sales and metrics first to avoid dangling references
    deleted_sales = (
        db.query(SalesRecord)
        .filter(SalesRecord.bakery_id == bakery_id)
        .delete(synchronize_session=False)
    )

    deleted_metrics = (
        db.query(ForecastMetrics)
        .filter(ForecastMetrics.product_id.in_(product_ids))
        .delete(synchronize_session=False)
    )

    deleted_products = (
        db.query(ProductModel)
        .filter(ProductModel.bakery_id == bakery_id)
        .delete(synchronize_session=False)
    )

    db.commit()

    return {
        "deleted_products": deleted_products,
        "deleted_sales": deleted_sales,
        "deleted_metrics": deleted_metrics,
    }
