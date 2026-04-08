from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app.ml.forecast_service import ForecastService
from app.schemas.sales_record import ForecastPointOut, ProductForecastOut

logger = logging.getLogger("bakezy.inference")

# Startup banner to identify module
logger.info("INFERENCE_SERVICE_MODULE_LOADED: app/ml/inference/forecast_service.py - UUID: inference-service-v1")


def _iso_to_date(value: str) -> date:
    """Convert ISO-8601 strings coming from the ML layer into date objects."""
    return date.fromisoformat(value)


def get_forecast_for_product(
    *,
    product_id: int,
    days_ahead: int = 14,
    db: Optional[Session] = None,
) -> ProductForecastOut:
    """
    Entry point used by the FastAPI layer.

    Delegates to the refactored ML ForecastService and adapts the result into
    the Pydantic schema expected by the routes.
    """
    if db is None:
        raise ValueError("Database session is required to forecast a product.")

    # Generate correlation ID for end-to-end tracing
    forecast_run_id = uuid.uuid4().hex[:8]
    
    # Diagnostic: Log entry point
    logger.info(
        f"INFERENCE_ENTRY: forecast_run_id={forecast_run_id}, product_id={product_id}, days_ahead={days_ahead}"
    )

    service = ForecastService()
    result = service.generate_prophet_forecast_for_product(
        db=db,
        product_id=product_id,
        horizon_days=days_ahead,
        forecast_run_id=forecast_run_id,
    )
    
    # Diagnostic: Log result before conversion
    if result.points:
        first_3_yhat = [p.yhat for p in result.points[:3]]
        last_3_yhat = [p.yhat for p in result.points[-3:]]
        logger.info(
            f"INFERENCE_RESULT: forecast_run_id={forecast_run_id}, source={result.source}, "
            f"points_count={len(result.points)}, first_3_yhat={first_3_yhat}, last_3_yhat={last_3_yhat}"
        )

    points = [
        ForecastPointOut(
            date=_iso_to_date(point.date),
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
        for point in result.points
    ]

    forecast_out = ProductForecastOut(
        product_id=result.product_id,
        product_name=result.product_name,
        horizon_days=result.horizon_days,
        points=points,
    )
    
    return forecast_out




