from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional
from datetime import timedelta

import pandas as pd

from .preprocessing import CleanedTimeSeries
from .trainer import ModelTrainer, TrainResult
from .features import FeatureEngineer

ModelName = Literal["prophet", "xgboost", "ensemble", "seasonal_naive", "rolling_mean"]


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
        self.feature_engineer = FeatureEngineer()

    def forecast(
        self,
        ts: CleanedTimeSeries,
        horizon_days: int = 14,
        model_name: ModelName = "prophet",
        hyperparameters: Optional[dict] = None,  # New parameter: stored hyperparameters
        holidays_df: Optional[pd.DataFrame] = None,
        weather_df: Optional[pd.DataFrame] = None,
        promotions_df: Optional[pd.DataFrame] = None,
        events_df: Optional[pd.DataFrame] = None,
        product_info: Optional[dict] = None,
        future_regressors: Optional[pd.DataFrame] = None,
    ) -> ForecastResult:
        # For forecasting (inference), don't optimize hyperparameters - use stored or defaults
        # Hyperparameter optimization should only run during explicit training
        train_result: TrainResult = self.trainer.train(
            ts,
            model_name=model_name,
            hyperparameters=hyperparameters,  # Pass stored hyperparameters as warm-start
            holidays_df=holidays_df,
            weather_df=weather_df,
            promotions_df=promotions_df,
            events_df=events_df,
            product_info=product_info,
            optimize_with_wape=False,  # Disable optimization for fast inference
        )

        if train_result.model_name == "prophet":
            # Pass historical delivery data if available for future predictions
            historical_delivery = None
            if "delivery" in ts.df.columns:
                historical_delivery = ts.df["delivery"]
            forecast_df = train_result.model.predict(
                horizon_days,
                historical_delivery=historical_delivery,
                future_regressors=future_regressors,
            )
            # keep only future rows
            last_train_date = ts.df["ds"].max()
            forecast_df = forecast_df[forecast_df["ds"] > last_train_date].reset_index(drop=True)

        elif train_result.model_name == "xgboost":
            # Generate future dates
            last_train_date = ts.df["ds"].max()
            future_dates = pd.date_range(
                start=last_train_date + timedelta(days=1),
                periods=horizon_days,
                freq="D",
            )
            future_df = pd.DataFrame({"ds": future_dates})
            
            # Use future_regressors if provided, otherwise generate basic features
            if future_regressors is not None and not future_regressors.empty:
                future_df = future_regressors.copy()
            else:
                # Apply basic feature engineering to future dates
                future_df = self.feature_engineer.transform(
                    future_df,
                    holidays_df=holidays_df,
                    weather_df=weather_df,
                    promotions_df=promotions_df,
                    events_df=events_df,
                    product_info=product_info,
                )
            
            # Use XGBoost's predict_future method for recursive prediction
            forecast_df = train_result.model.predict_future(
                historical_df=ts.df,
                future_df=future_df,
                feature_engineer=self.feature_engineer,
                holidays_df=holidays_df,
                weather_df=weather_df,
                promotions_df=promotions_df,
                events_df=events_df,
                product_info=product_info,
            )

        elif train_result.model_name == "ensemble":
            # Generate future dates for ensemble
            last_train_date = ts.df["ds"].max()
            future_dates = pd.date_range(
                start=last_train_date + timedelta(days=1),
                periods=horizon_days,
                freq="D",
            )
            future_df = pd.DataFrame({"ds": future_dates})
            
            # Apply feature engineering to future dates
            if future_regressors is not None and not future_regressors.empty:
                future_df = future_regressors.copy()
            else:
                future_df = self.feature_engineer.transform(
                    future_df,
                    holidays_df=holidays_df,
                    weather_df=weather_df,
                    promotions_df=promotions_df,
                    events_df=events_df,
                    product_info=product_info,
                )
            
            # Get historical delivery if available
            historical_delivery = None
            if "delivery" in ts.df.columns:
                historical_delivery = ts.df["delivery"]
            
            # Use ensemble model to predict
            forecast_df = train_result.model.predict(
                historical_df=ts.df,
                future_df=future_df,
                horizon_days=horizon_days,
                holidays_df=holidays_df,
                weather_df=weather_df,
                promotions_df=promotions_df,
                events_df=events_df,
                product_info=product_info,
                future_regressors=future_regressors,
                historical_delivery=historical_delivery,
            )
        
        elif train_result.model_name in ("seasonal_naive", "rolling_mean"):
            # Baseline models: use their predict method
            last_train_date = ts.df["ds"].max()
            forecast_df = train_result.model.predict(
                horizon_days=horizon_days,
                last_date=last_train_date,
            )
            
        else:
            raise ValueError(f"Unsupported model: {train_result.model_name}")

        return ForecastResult(
            product_id=ts.product_id,
            model_name=train_result.model_name,
            horizon_days=horizon_days,
            forecast_df=forecast_df,
        )
