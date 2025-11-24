import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.api.auth import get_current_user
from app.ml.inference.forecast_service import get_forecast_for_product
from app.schemas import sales_record

logger = logging.getLogger("bakezy.forecast.api")

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
    # using current_user + bakery ownership. For now, the service
    # just validates product existence & sales data.

    # Handle Prophet not installed
    try:
        forecast_result = get_forecast_for_product(
            db=db,
            product_id=product_id,
            horizon_days=horizon_days,
        )
    except ImportError as e:
        logger.exception("Prophet import error during forecast: product_id=%d", product_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Prophet is not installed. Install it with `pip install prophet`.",
        ) from e
    except ValueError as e:
        msg = str(e)
        if "Product not found" in msg:
            logger.warning(
                "Forecast API: product not found (product_id=%d)", product_id
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found.",
            ) from e
        if "No sales data" in msg:
            logger.warning(
                "Forecast API: no sales data (product_id=%d)", product_id
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No sales data available for this product.",
            ) from e

        logger.exception(
            "Forecast API: unexpected ValueError for product_id=%d", product_id
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=msg,
        ) from e

    # Map dataclass → Pydantic response model
    from datetime import date as date_type
    points = [
        sales_record.ForecastPointOut(
            date=date_type.fromisoformat(p.date) if isinstance(p.date, str) else p.date,
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
