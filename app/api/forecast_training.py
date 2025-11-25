from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.database.database import get_db
from app.ml.training.train_product import train_product
from app.ml.training.train_all_products import train_all_products
from app.models import Product
from app.schemas.forecast import (
    ProductTrainingResult,
    TrainAllProductsResult,
)

router = APIRouter(tags=["forecast-training"])


@router.post(
    "/products/{product_id}/train",
    response_model=ProductTrainingResult,
    status_code=status.HTTP_200_OK,
)
def train_single_product_endpoint(
    product_id: int,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    product = (
        db.query(Product)
        .filter(Product.id == product_id)
        .one_or_none()
    )
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    try:
        result = train_product(product_id=product_id, db=db)
        return result
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


@router.post(
    "/forecast/train-all",
    response_model=TrainAllProductsResult,
    status_code=status.HTTP_200_OK,
)
def train_all_products_endpoint(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        results = train_all_products(db=db)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    failed_products = [
        r["product_id"]
        for r in results
        if r.get("status") not in {"ok", "skipped_no_data", "skipped_no_timeseries"}
    ]
    mape_values = [
        r["mape"]
        for r in results
        if r.get("mape") is not None
    ]
    avg_mape: Optional[float] = (
        sum(mape_values) / len(mape_values) if mape_values else None
    )

    return {
        "trained_products": len(results),
        "failed_products": failed_products,
        "avg_mape": avg_mape,
        "results": results,
    }



