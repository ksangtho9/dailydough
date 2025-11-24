"""
DEPRECATED: logic moved to app/ml/training/ and app/ml/inference/

This file is kept for backward compatibility only.
"""

from dataclasses import dataclass
from typing import Literal, Optional
import pandas as pd

from app.ml.training.train_product import train_product_model, TrainResult
from app.ml.data.sales_preprocessor import CleanedTimeSeries

ModelName = Literal["prophet", "xgboost", "lightgbm"]


@dataclass
class ForecastResult:
    """Generic forecast output for a product."""
    product_id: int
    model_name: ModelName
    horizon_days: int
    forecast_df: pd.DataFrame


class ProductForecaster:
    """
    Backward compatibility wrapper for ProductForecaster.
    """
    def __init__(self, trainer=None):
        # trainer is ignored for backward compatibility
        pass

    def forecast(
        self,
        ts: CleanedTimeSeries,
        horizon_days: int = 14,
        model_name: ModelName = "prophet",
    ) -> ForecastResult:
        """
        Generate forecast (backward compatibility method).
        """
        # Map old model names
        if model_name == "xgboost":
            model_name = "lightgbm"
        
        # Train model
        train_result = train_product_model(ts, model_name=model_name)
        model = train_result.model

        # Generate forecast
        if train_result.model_name == "prophet":
            from app.ml.models.prophet_model import ProphetModel
            if isinstance(model, ProphetModel):
                forecast_df = model.predict_with_horizon(horizon_days)
                # Keep only future rows
                last_train_date = ts.df["ds"].max()
                forecast_df = forecast_df[forecast_df["ds"] > pd.Timestamp(last_train_date)].reset_index(drop=True)
            else:
                raise ValueError("Model is not a ProphetModel")
        else:
            # For other models, create future dataframe
            last_date = ts.df["ds"].max()
            future_dates = pd.date_range(
                start=pd.Timestamp(last_date) + pd.Timedelta(days=1),
                periods=horizon_days,
                freq="D"
            )
            future_df = pd.DataFrame({"ds": future_dates})
            forecast_df = model.predict(future_df)

        return ForecastResult(
            product_id=ts.product_id,
            model_name=train_result.model_name,
            horizon_days=horizon_days,
            forecast_df=forecast_df,
        )

__all__ = [
    "ProductForecaster",
    "ForecastResult",
]
