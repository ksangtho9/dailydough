from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

import pandas as pd

from .preprocessing import CleanedTimeSeries
from .trainer import ModelTrainer, TrainResult

ModelName = Literal["prophet", "xgboost"]


@dataclass
class ForecastResult:
    """Generic forecast output for a product."""
    product_id: int
    model_name: ModelName
    horizon_days: int
    # For Prophet, we’ll keep full df (with yhat, yhat_lower, yhat_upper)
    # For XGBoost, we might only have point forecasts.
    forecast_df: pd.DataFrame


class ProductForecaster:
    """
    High-level orchestrator:
    - takes cleaned time series
    - trains model (for now, on-the-fly)
    - returns forecast for N days
    """

    def __init__(self, trainer: Optional[ModelTrainer] = None):
        self.trainer = trainer or ModelTrainer()

    def forecast(
        self,
        ts: CleanedTimeSeries,
        horizon_days: int = 14,
        model_name: ModelName = "prophet",
    ) -> ForecastResult:
        train_result: TrainResult = self.trainer.train(ts, model_name=model_name)

        if train_result.model_name == "prophet":
            # Pass historical delivery data if available for future predictions
            historical_delivery = None
            if "delivery" in ts.df.columns:
                historical_delivery = ts.df["delivery"]
            forecast_df = train_result.model.predict(horizon_days, historical_delivery=historical_delivery)
            # keep only future rows
            last_train_date = ts.df["ds"].max()
            forecast_df = forecast_df[forecast_df["ds"] > last_train_date].reset_index(drop=True)

        elif train_result.model_name == "xgboost":
            # For now, we’ll leave the XGBoost future feature generation as a TODO
            # because it depends on how you design lag & calendar features.
            # Placeholder empty df:
            forecast_df = pd.DataFrame()
        else:
            raise ValueError(f"Unsupported model: {train_result.model_name}")

        return ForecastResult(
            product_id=ts.product_id,
            model_name=train_result.model_name,
            horizon_days=horizon_days,
            forecast_df=forecast_df,
        )
