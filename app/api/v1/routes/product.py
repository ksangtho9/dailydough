from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List

from app.database.database import get_db
from app.api.auth import get_current_user
from app.schemas.product import Product, ProductCreate, ProductUpdate
from app.crud import product as crud_product
from app.models import SalesRecord, Product as ProductModel, ForecastMetrics

router = APIRouter(prefix="/products", tags=["products"])


@router.put("/{product_id}", response_model=Product)
def update_product(
    product_id: int,
    payload: ProductUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    db_obj = db.query(ProductModel).filter(ProductModel.id == product_id).first()
    if not db_obj:
        raise HTTPException(status_code=404, detail="Product not found")
    db_obj = crud_product.update_product(
        db, bakery_id=db_obj.bakery_id, product_id=product_id, obj_in=payload
    )
    return db_obj


@router.delete("/{product_id}")
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    db_obj = db.query(ProductModel).filter(ProductModel.id == product_id).first()
    if not db_obj:
        raise HTTPException(status_code=404, detail="Product not found")
    ok = crud_product.delete_product(db, bakery_id=db_obj.bakery_id, product_id=product_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"success": True}


@router.delete("/", summary="Delete all products and related data for a bakery")
def delete_all_products_for_bakery(
    bakery_id: int = Query(..., description="Bakery ID to delete products for"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    product_ids = [
        p.id
        for p in db.query(ProductModel.id).filter(ProductModel.bakery_id == bakery_id).all()
    ]

    if not product_ids:
        return {"deleted_products": 0, "deleted_sales": 0, "deleted_metrics": 0}

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
