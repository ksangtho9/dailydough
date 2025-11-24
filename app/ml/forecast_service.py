"""
DEPRECATED: logic moved to app/ml/inference/forecast_service.py

This file is kept for backward compatibility only.
"""

from app.ml.inference.forecast_service import (
    ForecastService,
    ProductForecast,
    ForecastPoint,
    get_forecast_for_product,
)

__all__ = [
    "ForecastService",
    "ProductForecast",
    "ForecastPoint",
    "get_forecast_for_product",
]
