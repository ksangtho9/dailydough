from __future__ import annotations

from typing import List, Dict, Any, Optional

from sqlalchemy.orm import Session

from app.database.database import SessionLocal
from app.models import Product, ModelRun
from app.ml.inference.forecast_service import get_forecast_for_product
from app.ml.forecast_service import ForecastService
from app.services.daily_forecast_service import upsert_product_daily_forecasts
from .train_product import train_product, _compute_raw_prediction_stats_future
import logging
import numpy as np

logger = logging.getLogger(__name__)


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
                            
                            # Call forecast service directly to get raw predictions for future stats
                            forecast_service = ForecastService()
                            forecast_result = forecast_service.generate_prophet_forecast_for_product(
                                db=db,
                                product_id=product.id,
                                horizon_days=60,
                            )
                            
                            # Validate that we got a forecast with points
                            if not forecast_result or not forecast_result.points:
                                raise ValueError(f"Forecast returned empty points for product_id={product.id}")
                            
                            # Convert to ProductForecastOut for upsert
                            from app.schemas.sales_record import ForecastPointOut, ProductForecastOut
                            from datetime import date as date_type
                            forecast_out = ProductForecastOut(
                                product_id=forecast_result.product_id,
                                product_name=forecast_result.product_name,
                                horizon_days=forecast_result.horizon_days,
                                points=[
                                    ForecastPointOut(
                                        date=date_type.fromisoformat(point.date),
                                        yhat=point.yhat,
                                        yhat_lower=point.yhat_lower,
                                        yhat_upper=point.yhat_upper,
                                        revenue=getattr(point, "revenue", None),
                                        cost=getattr(point, "cost", None),
                                        waste_cost=getattr(point, "waste_cost", None),
                                        profit=getattr(point, "profit", None),
                                        waste_quantity=getattr(point, "waste_quantity", None),
                                        optimal_quantity=getattr(point, "optimal_quantity", None),
                                        expected_stockout_cost=getattr(point, "expected_stockout_cost", None),
                                        expected_waste_cost=getattr(point, "expected_waste_cost", None),
                                        expected_total_cost=getattr(point, "expected_total_cost", None),
                                        is_predicted_spike=getattr(point, "is_predicted_spike", False),
                                        spike_probability=getattr(point, "spike_probability", None),
                                        spike_magnitude=getattr(point, "spike_magnitude", None),
                                        spike_confidence=getattr(point, "spike_confidence", None),
                                    )
                                    for point in forecast_result.points
                                ],
                            )
                            
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
                            
                            # Phase 1b: Compute and store future slice raw prediction stats
                            if forecast_result.raw_yhat_values is not None and len(forecast_result.raw_yhat_values) > 0:
                                try:
                                    # Get the active ModelRun for this product
                                    model_run = (
                                        db.query(ModelRun)
                                        .filter(
                                            ModelRun.product_id == product.id,
                                            ModelRun.is_active == True
                                        )
                                        .order_by(ModelRun.created_at.desc())
                                        .first()
                                    )
                                    
                                    if model_run:
                                        # Get feature_version from ModelRun
                                        feature_version = model_run.feature_version
                                        # Use a local variable to avoid shadowing the outer model_name parameter
                                        result_model_name = forecast_result.model_name or model_run.selected_model_type

                                        # Compute future slice stats
                                        raw_prediction_stats_future = _compute_raw_prediction_stats_future(
                                            forecast_result.raw_yhat_values,
                                            result_model_name,
                                            feature_version,
                                        )
                                        
                                        if raw_prediction_stats_future is not None:
                                            # Update ModelRun.metrics_json with future stats
                                            if model_run.metrics_json is None:
                                                model_run.metrics_json = {}
                                            
                                            model_run.metrics_json["raw_prediction_summary_future"] = raw_prediction_stats_future
                                            db.commit()
                                            
                                            logger.info(
                                                f"Updated ModelRun for product_id={product.id} with future slice raw prediction stats: "
                                                f"raw_neg_pct={raw_prediction_stats_future.get('raw_neg_pct', 0):.1f}%, "
                                                f"clamped_zero_pct={raw_prediction_stats_future.get('clamped_zero_pct', 0):.1f}%"
                                            )
                                            
                                            # Phase 5: Dense product sanity warning for future slice
                                            training_data_summary = model_run.metrics_json.get("training_data_summary", {})
                                            mean_y_train = training_data_summary.get("mean_y", 0.0)
                                            zero_rate_train = training_data_summary.get("zero_rate", 100.0)
                                            clamped_zero_pct_future = raw_prediction_stats_future.get("clamped_zero_pct", 0.0)
                                            
                                            if (mean_y_train > 10 and 
                                                zero_rate_train < 30.0 and 
                                                clamped_zero_pct_future > 50.0):
                                                logger.warning(
                                                    f"DENSE_PRODUCT_ZERO_FORECAST: Product {product.id} has healthy training data "
                                                    f"(mean_y={mean_y_train:.2f}, zero_rate={zero_rate_train:.1f}%) but "
                                                    f"{clamped_zero_pct_future:.1f}% of future forecasts are clamped to zero. "
                                                    f"Likely negative clamp or future feature/regressor issue."
                                                )
                                        else:
                                            logger.warning(
                                                f"Failed to compute future slice stats for product_id={product.id}"
                                            )
                                    else:
                                        logger.warning(
                                            f"No active ModelRun found for product_id={product.id} to update with future stats"
                                        )
                                except Exception as stats_error:
                                    logger.warning(
                                        f"Failed to compute/store future slice stats for product_id={product.id}: {stats_error}",
                                        exc_info=True
                                    )
                            else:
                                logger.debug(
                                    f"No raw predictions available for product_id={product.id} to compute future stats"
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
                            else:
                                # Retry - log warning but continue
                                logger.warning(
                                    f"Forecast precomputation attempt {forecast_attempts}/{max_forecast_attempts} "
                                    f"failed for product_id={product.id}, product_name={product.name}: {e}. Retrying...",
                                    exc_info=True
                                )
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



