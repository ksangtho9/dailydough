from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.api.auth import get_current_user
from app.ml.forecast_service import ForecastService
from app.schemas import sales_record


router = APIRouter(
    prefix="/forecast",
    tags=["forecast"],
)


@router.post(
    "/product/{product_id}",
    response_model=sales_record.ProductForecastOut,
    status_code=status.HTTP_200_OK,
)
def forecast_product_sales(
    product_id: int,
    horizon_days: int = 14,  # can override via query param
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """
    Generate a Prophet-based forecast for a single product.

    - Loads historical SalesRecord rows
    - Fills missing days
    - Trains Prophet
    - Returns next `horizon_days` predictions
    """

    # You might later enforce "product belongs to this user"
    # using current_user + bakery ownership. For now, ForecastService
    # just validates product existence & sales data.

    service = ForecastService()

    # Handle Prophet not installed
    try:
        forecast_result = service.generate_prophet_forecast_for_product(
            db=db,
            product_id=product_id,
            horizon_days=horizon_days,
        )
    except ImportError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Prophet is not installed. Install it with `pip install prophet`.",
        ) from e
    except ValueError as e:
        msg = str(e)
        if "Product not found" in msg:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found.",
            ) from e
        if "No sales data" in msg:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No sales data available for this product.",
            ) from e
        # Unknown ValueError
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=msg,
        ) from e

    # Map dataclass → Pydantic response model
    points = [
        sales_record.ForecastPointOut(
            date=p.date,
            yhat=p.yhat,
            yhat_lower=p.yhat_lower,
            yhat_upper=p.yhat_upper,
        )
        for p in forecast_result.points
    ]

    return sales_record.ProductForecastOut(
        product_id=forecast_result.product_id,
        product_name=forecast_result.product_name,
        horizon_days=forecast_result.horizon_days,
        points=points,
    )
