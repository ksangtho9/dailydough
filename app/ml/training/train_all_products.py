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
                # Only precompute if training was successful
                if result.get("status") not in ("skipped_no_data", "failed", None):
                    forecast_attempts = 0
                    max_forecast_attempts = 3
                    forecast_success = False
                    
                    while forecast_attempts < max_forecast_attempts and not forecast_success:
                        try:
                            forecast_attempts += 1
                            forecast_out = get_forecast_for_product(
                                product_id=product.id,
                                days_ahead=60,
                                db=db,
                            )
                            
                            # Validate that we got a forecast with points
                            if not forecast_out or not forecast_out.points:
                                raise ValueError(f"Forecast returned empty points for product_id={product.id}")
                            
                            upsert_product_daily_forecasts(
                                db,
                                product=product,
                                forecast=forecast_out,
                            )
                            forecast_success = True
                            logger.info(
                                f"Successfully precomputed forecasts for product_id={product.id}, product_name={product.name} "
                                f"(attempt {forecast_attempts}/{max_forecast_attempts})"
                            )
                        except Exception as e:
                            if forecast_attempts >= max_forecast_attempts:
                                # Final attempt failed - log as error and mark in result
                                logger.error(
                                    f"Failed to precompute forecasts for product_id={product.id}, "
                                    f"product_name={product.name} after {max_forecast_attempts} attempts: {e}",
                                    exc_info=True
                                )
                                result["forecast_precomputation_failed"] = True
                                result["forecast_error"] = str(e)
                                # #region agent log
                                try:
                                    import json
                                    import time
                                    log_entry = {
                                        "sessionId": "debug-session",
                                        "runId": "run1",
                                        "hypothesisId": "H",
                                        "location": "train_all_products.py:52",
                                        "message": "Forecast precomputation failed after retries",
                                        "data": {
                                            "product_id": product.id,
                                            "product_name": product.name,
                                            "error": str(e),
                                            "error_type": type(e).__name__,
                                            "attempts": forecast_attempts
                                        },
                                        "timestamp": int(time.time() * 1000)
                                    }
                                    with open(r"c:\Users\forfl\Documents\dailydough-1\.cursor\debug.log", "a", encoding="utf-8") as f:
                                        f.write(json.dumps(log_entry) + "\n")
                                except Exception:
                                    pass
                                # #endregion
                            else:
                                # Retry - log warning but continue
                                logger.warning(
                                    f"Forecast precomputation attempt {forecast_attempts}/{max_forecast_attempts} "
                                    f"failed for product_id={product.id}, product_name={product.name}: {e}. Retrying...",
                                    exc_info=True
                                )
                                # #region agent log
                                try:
                                    import json
                                    import time
                                    log_entry = {
                                        "sessionId": "debug-session",
                                        "runId": "run1",
                                        "hypothesisId": "H",
                                        "location": "train_all_products.py:52",
                                        "message": "Forecast precomputation attempt failed, retrying",
                                        "data": {
                                            "product_id": product.id,
                                            "product_name": product.name,
                                            "error": str(e),
                                            "error_type": type(e).__name__,
                                            "attempt": forecast_attempts,
                                            "max_attempts": max_forecast_attempts
                                        },
                                        "timestamp": int(time.time() * 1000)
                                    }
                                    with open(r"c:\Users\forfl\Documents\dailydough-1\.cursor\debug.log", "a", encoding="utf-8") as f:
                                        f.write(json.dumps(log_entry) + "\n")
                                except Exception:
                                    pass
                                # #endregion
                else:
                    logger.warning(
                        f"Skipping forecast precomputation for product_id={product.id}, product_name={product.name} "
                        f"because training status was: {result.get('status')}"
                    )
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



