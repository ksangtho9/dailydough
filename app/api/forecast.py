import logging
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from app.database.database import get_db
from app.api.auth import get_current_user
from app.models import Profile
from app.ml.inference.forecast_service import get_forecast_for_product
from app.schemas import sales_record
from app.models.product import Product
from app.services.daily_forecast_service import upsert_product_daily_forecasts
from app.core.rate_limiter import limiter


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
@limiter.limit("30/minute")
def forecast_product_sales(
    request: Request,
    product_id: int,
    forecast_request: ForecastRequest,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    horizon_days = forecast_request.days or 14

    try:
        product = db.query(Product).filter(Product.id == product_id).first()
        result = get_forecast_for_product(
            product_id=product_id,
            days_ahead=horizon_days,
            db=db,
        )
        if product and result and result.points:
            try:
                upsert_product_daily_forecasts(db, product=product, forecast=result)
            except Exception:
                pass  # caching failure must not break the forecast response
        return result
    except ImportError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Prophet is not installed. Install it with `pip install prophet`.",
        ) from e
    except ValueError as e:
        msg = str(e)
        if "Product not found" in msg:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.") from e
        if "No sales data" in msg:
            product = db.query(Product).filter(Product.id == product_id).first()
            if product is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.") from e
            return sales_record.ProductForecastOut(
                product_id=product.id,
                product_name=product.name,
                horizon_days=horizon_days,
                points=[],
            )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg) from e
    except Exception as e:
        logger.exception("Forecast API error for product_id=%d: %s", product_id, str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating forecast: {str(e)}",
        ) from e
