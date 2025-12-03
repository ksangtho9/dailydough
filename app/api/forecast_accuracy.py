from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from pydantic import BaseModel

from app.database.database import get_db
from app.api.auth import get_current_user
from app.models import Product, ForecastMetrics, Bakery


class ProductAccuracyOut(BaseModel):
    product_id: int
    product_name: str
    mape: Optional[float]
    rmse: Optional[float]
    n_points: int
    last_trained_at: Optional[datetime]


router = APIRouter(
    prefix="/forecast-accuracy",
    tags=["analytics"],
)


@router.get(
    "/bakery/{bakery_id}",
    response_model=List[ProductAccuracyOut],
    status_code=status.HTTP_200_OK,
)
def get_bakery_forecast_accuracy(
    bakery_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Return per-product forecast accuracy metrics for a bakery in a single call.

    This endpoint reads from the ForecastMetrics table, which is populated during
    training, so it does not need to call the heavy forecasting pipeline for each
    request. That keeps the dashboard Accuracy tab fast even for many products.
    """
    # Ensure bakery exists and belongs to the current user (if applicable)
    bakery = db.query(Bakery).filter(Bakery.id == bakery_id).first()
    if bakery is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bakery not found",
        )

    # Fetch products for this bakery and any associated forecast metrics
    rows = (
        db.query(Product, ForecastMetrics)
        .outerjoin(ForecastMetrics, ForecastMetrics.product_id == Product.id)
        .filter(Product.bakery_id == bakery_id)
        .order_by(Product.name.asc())
        .all()
    )

    results: List[ProductAccuracyOut] = []
    for product, metrics in rows:
        if metrics is not None:
            results.append(
                ProductAccuracyOut(
                    product_id=product.id,
                    product_name=product.name,
                    mape=metrics.mape,
                    rmse=metrics.rmse,
                    n_points=metrics.n_points or 0,
                    last_trained_at=metrics.last_trained_at,
                )
            )
        else:
            # No metrics yet – surface a placeholder entry so the UI can show
            # the product with “—” for accuracy and zero data points.
            results.append(
                ProductAccuracyOut(
                    product_id=product.id,
                    product_name=product.name,
                    mape=None,
                    rmse=None,
                    n_points=0,
                    last_trained_at=None,
                )
            )

    return results


