from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
import logging

from app.database.database import get_db
from app.api.auth import set_user_state, get_current_user
from app.models import User
from app.ml.inference.forecast_service import get_forecast_for_product
from app.core.config import settings
from app.schemas.forecast import ProductForecastResponse, ProductForecastPoint
from app.crud import product as crud_product
from app.core.rate_limiter import limiter

logger = logging.getLogger("bakezy.api")

router = APIRouter(prefix="/forecast", tags=["forecast"])


@router.get("/product/{product_id}", response_model=ProductForecastResponse)
@limiter.limit("30/minute")  # Rate limit: 30 requests per minute per authenticated user (IP fallback)
def get_product_forecast(
    request: Request,
    product_id: int,
    horizon: int = Query(7, ge=1, le=30),
    db: Session = Depends(get_db),
    current_user=Depends(set_user_state),
):
    bakery_id = current_user.bakery_id
    
    # Diagnostic: Log retrieval entry
    logger.info(
        f"RETRIEVAL_ENTRY: bakery_id={bakery_id}, product_id={product_id}, horizon={horizon}"
    )

    # Ensure product belongs to this bakery
    product = crud_product.get_product(
        db, bakery_id=bakery_id, product_id=product_id
    )
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Determine if debug fields should be included
    include_debug = current_user.is_admin or settings.debug_zero_forecasts
    
    forecast = get_forecast_for_product(
        product_id=product_id,
        days_ahead=horizon,
        db=db,
        include_debug=include_debug,
    )
    
    # Diagnostic: Log before serialization
    # Note: forecast_run_id and source are logged in INFERENCE_RESULT in inference/forecast_service.py
    if forecast.points:
        first_3_yhat = [p.yhat for p in forecast.points[:3]]
        last_3_yhat = [p.yhat for p in forecast.points[-3:]]
        # Check for zeros in the forecast
        zero_count = sum(1 for p in forecast.points if p.yhat == 0.0)
        logger.info(
            f"RETRIEVAL_BEFORE_SERIALIZATION: bakery_id={bakery_id}, product_id={product_id}, "
            f"points_count={len(forecast.points)}, zero_count={zero_count}, "
            f"first_3_yhat={first_3_yhat}, last_3_yhat={last_3_yhat}"
        )

    points = [
        ProductForecastPoint(date=point.date, quantity=point.yhat)
        for point in forecast.points
    ]
    
    # Diagnostic: Log retrieval result (always log, unconditional)
    if points:
        first_3_yhat = [p.quantity for p in points[:3]] if len(points) >= 3 else [p.quantity for p in points]
        last_3_yhat = [p.quantity for p in points[-3:]] if len(points) >= 3 else [p.quantity for p in points]
        zero_count = sum(1 for p in points if p.quantity == 0.0)
        date_range = f"{points[0].date} to {points[-1].date}" if len(points) > 1 else str(points[0].date)
        logger.info(
            f"RETRIEVAL_RESULT: bakery_id={bakery_id}, product_id={product_id}, "
            f"rows_returned={len(points)}, zero_count={zero_count}, date_range={date_range}, "
            f"first_3_yhat={first_3_yhat}, last_3_yhat={last_3_yhat}"
        )
    else:
        logger.warning(
            f"RETRIEVAL_RESULT: bakery_id={bakery_id}, product_id={product_id}, "
            f"WARNING: No points returned (empty forecast)"
        )

    return ProductForecastResponse(product_id=product_id, points=points)
