import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from app.database.database import get_db
from app.api.auth import get_current_user
from app.ml.inference.forecast_service import get_forecast_for_product
from app.schemas import sales_record
from app.models.product import Product
from app.core.config import settings


class ForecastRequest(BaseModel):
    days: Optional[int] = 14

# Logger configuration is centralized in app/main.py
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
    
    # POST_RETRIEVAL_ENTRY: Log entry point
    # Get bakery_id from product (User model doesn't have bakery_id)
    product_check = db.query(Product).filter(Product.id == product_id).first()
    bakery_id = product_check.bakery_id if product_check else None
    horizon_days = request.days or 14
    logger.info(
        f"POST_RETRIEVAL_ENTRY: product_id={product_id}, horizon_days={horizon_days}, bakery_id={bakery_id}"
    )

    try:
        forecast_result = get_forecast_for_product(
            product_id=product_id,
            days_ahead=horizon_days,
            db=db,
        )
        
        # POST_RESULT_RAW: Log from forecast_result (after get_forecast_for_product call)
        if forecast_result.points:
            zero_count_raw = sum(1 for p in forecast_result.points if p.yhat == 0.0)
            first_3_raw = [p.yhat for p in forecast_result.points[:3]]
            last_3_raw = [p.yhat for p in forecast_result.points[-3:]]
            logger.info(
                f"POST_RESULT_RAW: product_id={product_id}, points_count={len(forecast_result.points)}, "
                f"zero_count={zero_count_raw}, first_3_yhat={first_3_raw}, last_3_yhat={last_3_raw}, "
                f"debug_forecast_run_id={forecast_result.debug_forecast_run_id}, debug_source={forecast_result.debug_source}"
            )
        else:
            logger.warning(
                f"POST_RESULT_RAW: product_id={product_id}, points_count=0 (empty forecast)"
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
            # Instead of returning a 400 error for expected "no data yet" cases,
            # respond with an empty forecast so clients can render a graceful
            # "no forecast available" state without treating it as a failure.
            product = (
                db.query(Product)
                .filter(Product.id == product_id)
                .first()
            )

            if product is None:
                # Defensive fallback: if the product truly does not exist,
                # surface a 404 rather than an empty forecast.
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Product not found.",
                ) from e

            logger.info(
                "Forecast API: returning empty forecast for product_id=%d due to missing sales data",
                product_id,
            )

            empty_forecast = sales_record.ProductForecastOut(
                product_id=product.id,
                product_name=product.name,
                horizon_days=horizon_days,
                points=[],
            )
            return empty_forecast

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

    # POST_RESULT_RESPONSE: Log from response object before return
    # (After any schema conversion, but before FastAPI serialization)
    if forecast_result.points:
        zero_count_resp = sum(1 for p in forecast_result.points if p.yhat == 0.0)
        first_3_resp = [p.yhat for p in forecast_result.points[:3]]
        last_3_resp = [p.yhat for p in forecast_result.points[-3:]]
        logger.info(
            f"POST_RESULT_RESPONSE: product_id={product_id}, points_count={len(forecast_result.points)}, "
            f"zero_count={zero_count_resp}, first_3_yhat={first_3_resp}, last_3_yhat={last_3_resp}, "
            f"debug_forecast_run_id={forecast_result.debug_forecast_run_id}, debug_source={forecast_result.debug_source}"
        )
    else:
        logger.warning(
            f"POST_RESULT_RESPONSE: product_id={product_id}, points_count=0 (empty forecast)"
        )

    return forecast_result
