from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.api.auth import get_current_user
from app.ml.inference.forecast_service import get_forecast_for_product
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
    """
    Returns forecast data for a single product.
    Uses the new ML engine (Prophet for now, pluggable for other models).
    """
    bakery_id = current_user.bakery_id

    # Ensure product belongs to this bakery
    product = crud_product.get_product(
        db, bakery_id=bakery_id, product_id=product_id
    )
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Get forecast using new ML engine
    try:
        forecast_result = get_forecast_for_product(
            db=db,
            product_id=product_id,
            horizon_days=horizon,
        )
    except ValueError as e:
        msg = str(e)
        if "Product not found" in msg or "No sales data" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Forecast error: {str(e)}")

    # Convert to v1 schema format (simpler - just quantity, no bounds)
    from datetime import date as date_type
    points = [
        ProductForecastPoint(
            date=date_type.fromisoformat(p.date) if isinstance(p.date, str) else p.date,
            quantity=p.yhat
        )
        for p in forecast_result.points
    ]

    return ProductForecastResponse(product_id=product_id, points=points)
