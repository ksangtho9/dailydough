from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.api.auth import get_current_user
from app.forecasting.service import ForecastService
from app.schemas.forecast import ProductForecastResponse, ProductForecastPoint
from app.crud import product as crud_product


router = APIRouter(prefix="/forecast", tags=["forecast"])


@router.get("/product/{product_id}", response_model=ProductForecastResponse)
def get_product_forecast(
    product_id: int,
    horizon: int = Query(7, ge=1, le=30),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    bakery_id = current_user.bakery_id

    # Ensure product belongs to this bakery
    product = crud_product.get_product(
        db, bakery_id=bakery_id, product_id=product_id
    )
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    service = ForecastService(db)
    raw_forecast = service.forecast_product(
        bakery_id=bakery_id,
        product_id=product_id,
        horizon_days=horizon,
    )

    points = [
        ProductForecastPoint(date=item["date"], quantity=item["quantity"])
        for item in raw_forecast
    ]

    return ProductForecastResponse(product_id=product_id, points=points)
