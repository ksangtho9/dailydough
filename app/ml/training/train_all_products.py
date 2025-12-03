from __future__ import annotations

from typing import List, Dict, Any, Optional

from sqlalchemy.orm import Session

from app.database.database import SessionLocal
from app.models import Product
from app.ml.inference.forecast_service import get_forecast_for_product
from app.services.daily_forecast_service import upsert_product_daily_forecasts
from .train_product import train_product


def train_all_products(
    *,
    db: Optional[Session] = None,
    model_name: str = "prophet",
    bakery_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    owns_session = False
    if db is None:
        db = SessionLocal()
        owns_session = True

    results: List[Dict[str, Any]] = []
    try:
        query = db.query(Product).order_by(Product.id.asc())
        if bakery_id is not None:
            query = query.filter(Product.bakery_id == bakery_id)
        products = query.all()
        for product in products:
            try:
                result = train_product(
                    product_id=product.id,
                    db=db,
                    model_name=model_name,
                )
                # After successfully training a model for this product, precompute
                # and store daily forecasts so that dashboard/history endpoints can
                # serve data quickly without triggering heavy forecasting on demand.
                try:
                    forecast_out = get_forecast_for_product(
                        product_id=product.id,
                        days_ahead=60,
                        db=db,
                    )
                    upsert_product_daily_forecasts(
                        db,
                        product=product,
                        forecast=forecast_out,
                    )
                except Exception:
                    # Precomputing forecasts should never break training; any
                    # issues here will simply mean on-demand forecasting may be
                    # used as a fallback for this product.
                    pass
            except Exception as exc:
                result = {
                    "product_id": product.id,
                    "product_name": product.name,
                    "status": "failed",
                    "model_type": model_name,
                    "n_points": 0,
                    "mape": None,
                    "rmse": None,
                    "last_trained_at": None,
                    "error": str(exc),
                }
            results.append(result)
        return results
    finally:
        if owns_session:
            db.close()



