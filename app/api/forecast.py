import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from app.database.database import get_db
from app.api.auth import get_current_user
from app.ml.inference.forecast_service import get_forecast_for_product
from app.schemas import sales_record


class ForecastRequest(BaseModel):
    days: Optional[int] = 14

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
    request: ForecastRequest,
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
    # using current_user + bakery ownership. For now, the ML layer
    # just validates product existence & sales data.

    try:
        horizon_days = request.days or 14
        
        forecast_result = get_forecast_for_product(
            product_id=product_id,
            days_ahead=horizon_days,
            db=db,
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
    except Exception as e:
        # Catch any other exceptions (RuntimeError, AttributeError, etc.)
        # that might occur during forecast generation
        logger.exception(
            "Forecast API: unexpected error for product_id=%d: %s", product_id, str(e)
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating forecast: {str(e)}",
        ) from e

    return forecast_result
