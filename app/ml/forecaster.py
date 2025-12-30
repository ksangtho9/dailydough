from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Union
from datetime import timedelta
import logging

import numpy as np
import pandas as pd

from .preprocessing import CleanedTimeSeries
from .trainer import ModelTrainer, TrainResult
from .features import FeatureEngineer
from app.core.config import settings

logger = logging.getLogger("bakezy.forecaster")

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
    
    def _should_log_deep_diagnostics(self, product_id: Optional[int]) -> bool:
        """Check if deep diagnostic logging should be enabled for this product."""
        if settings.debug_zero_forecasts:
            return True
        # TODO: Could check against flagged_product_ids set from diagnostics endpoint
        return False
    
    def _compute_raw_predictions_stats(
        self, 
        raw_predictions: Union[np.ndarray, pd.Series]
    ) -> dict:
        """
        Compute statistics on raw predictions (before clamping).
        
        Args:
            raw_predictions: Raw model predictions (can be negative)
            
        Returns:
            Dictionary with stats: min_raw_yhat, mean_raw_yhat, max_raw_yhat,
            raw_neg_pct, raw_zero_pct, first_5_raw_predictions
        """
        if isinstance(raw_predictions, pd.Series):
            raw_array = raw_predictions.values
        else:
            raw_array = raw_predictions
        
        if len(raw_array) == 0:
            return {
                "min_raw_yhat": None,
                "mean_raw_yhat": None,
                "max_raw_yhat": None,
                "raw_neg_pct": None,
                "raw_zero_pct": None,
                "first_5_raw_predictions": [],
            }
        
        min_raw_yhat = float(np.min(raw_array))
        mean_raw_yhat = float(np.mean(raw_array))
        max_raw_yhat = float(np.max(raw_array))
        raw_neg_pct = (raw_array < 0).sum() / len(raw_array) * 100
        raw_zero_pct = (raw_array == 0.0).sum() / len(raw_array) * 100
        first_5_raw_predictions = [float(x) for x in raw_array[:5].tolist()]
        
        return {
            "min_raw_yhat": min_raw_yhat,
            "mean_raw_yhat": mean_raw_yhat,
            "max_raw_yhat": max_raw_yhat,
            "raw_neg_pct": raw_neg_pct,
            "raw_zero_pct": raw_zero_pct,
            "first_5_raw_predictions": first_5_raw_predictions,
        }

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
                product_id=ts.product_id,  # Pass product_id for gated logging
            )
            # keep only future rows
            last_train_date = ts.df["ds"].max()
            forecast_df = forecast_df[forecast_df["ds"] > last_train_date].reset_index(drop=True)
            
            # Step 4: Log raw predictions before clamping (gated)
            if self._should_log_deep_diagnostics(ts.product_id) and not forecast_df.empty and "yhat" in forecast_df.columns:
                raw_yhat = forecast_df["yhat"].values
                stats = self._compute_raw_predictions_stats(raw_yhat)
                logger.info(
                    f"ZERO_FORECAST_INVESTIGATION: product_id={ts.product_id}, "
                    f"step=raw_predictions, model=prophet, "
                    f"min_raw_yhat={stats['min_raw_yhat']:.6f}, "
                    f"mean_raw_yhat={stats['mean_raw_yhat']:.6f}, "
                    f"max_raw_yhat={stats['max_raw_yhat']:.6f}, "
                    f"raw_neg_pct={stats['raw_neg_pct']:.1f}%, "
                    f"raw_zero_pct={stats['raw_zero_pct']:.1f}%, "
                    f"first_5_raw_predictions={stats['first_5_raw_predictions']}"
                )
                
                # Compute clamped predictions and forecast horizon stats
                clamped_yhat = np.maximum(raw_yhat, 0.0)
                zero_forecast_count = (clamped_yhat == 0.0).sum()
                zero_forecast_pct = (zero_forecast_count / len(clamped_yhat) * 100) if len(clamped_yhat) > 0 else 0.0
                
                logger.info(
                    f"ZERO_FORECAST_INVESTIGATION: product_id={ts.product_id}, "
                    f"step=forecast_horizon_stats, model=prophet, "
                    f"forecast_count={len(clamped_yhat)}, "
                    f"zero_forecast_count={int(zero_forecast_count)}, "
                    f"zero_forecast_pct={zero_forecast_pct:.1f}%"
                )
                
                # Warnings
                if stats['raw_neg_pct'] > 50.0:
                    logger.warning(
                        f"ZERO_FORECAST_INVESTIGATION: product_id={ts.product_id}, "
                        f"step=warning, High negative predictions ({stats['raw_neg_pct']:.1f}%) - "
                        f"likely being clamped to zero"
                    )
                elif stats['raw_zero_pct'] > 50.0 and stats['raw_neg_pct'] < 10.0:
                    logger.warning(
                        f"ZERO_FORECAST_INVESTIGATION: product_id={ts.product_id}, "
                        f"step=warning, High zero predictions ({stats['raw_zero_pct']:.1f}%) but low negatives "
                        f"({stats['raw_neg_pct']:.1f}%) - likely future feature/regressor issue"
                    )

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
                product_id=ts.product_id,  # Pass product_id for gated logging
            )
            
            # Step 4: Log raw predictions before clamping (gated)
            if self._should_log_deep_diagnostics(ts.product_id) and not forecast_df.empty and "yhat" in forecast_df.columns:
                raw_yhat = forecast_df["yhat"].values
                stats = self._compute_raw_predictions_stats(raw_yhat)
                logger.info(
                    f"ZERO_FORECAST_INVESTIGATION: product_id={ts.product_id}, "
                    f"step=raw_predictions, model=xgboost, "
                    f"min_raw_yhat={stats['min_raw_yhat']:.6f}, "
                    f"mean_raw_yhat={stats['mean_raw_yhat']:.6f}, "
                    f"max_raw_yhat={stats['max_raw_yhat']:.6f}, "
                    f"raw_neg_pct={stats['raw_neg_pct']:.1f}%, "
                    f"raw_zero_pct={stats['raw_zero_pct']:.1f}%, "
                    f"first_5_raw_predictions={stats['first_5_raw_predictions']}"
                )
                
                # Compute clamped predictions and forecast horizon stats
                clamped_yhat = np.maximum(raw_yhat, 0.0)
                zero_forecast_count = (clamped_yhat == 0.0).sum()
                zero_forecast_pct = (zero_forecast_count / len(clamped_yhat) * 100) if len(clamped_yhat) > 0 else 0.0
                
                logger.info(
                    f"ZERO_FORECAST_INVESTIGATION: product_id={ts.product_id}, "
                    f"step=forecast_horizon_stats, model=xgboost, "
                    f"forecast_count={len(clamped_yhat)}, "
                    f"zero_forecast_count={int(zero_forecast_count)}, "
                    f"zero_forecast_pct={zero_forecast_pct:.1f}%"
                )
                
                # Warnings
                if stats['raw_neg_pct'] > 50.0:
                    logger.warning(
                        f"ZERO_FORECAST_INVESTIGATION: product_id={ts.product_id}, "
                        f"step=warning, High negative predictions ({stats['raw_neg_pct']:.1f}%) - "
                        f"likely being clamped to zero"
                    )
                elif stats['raw_zero_pct'] > 50.0 and stats['raw_neg_pct'] < 10.0:
                    logger.warning(
                        f"ZERO_FORECAST_INVESTIGATION: product_id={ts.product_id}, "
                        f"step=warning, High zero predictions ({stats['raw_zero_pct']:.1f}%) but low negatives "
                        f"({stats['raw_neg_pct']:.1f}%) - likely future feature/regressor issue"
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
            
            # Step 4: Log raw predictions before clamping (gated)
            if self._should_log_deep_diagnostics(ts.product_id) and not forecast_df.empty and "yhat" in forecast_df.columns:
                raw_yhat = forecast_df["yhat"].values
                stats = self._compute_raw_predictions_stats(raw_yhat)
                logger.info(
                    f"ZERO_FORECAST_INVESTIGATION: product_id={ts.product_id}, "
                    f"step=raw_predictions, model=ensemble, "
                    f"min_raw_yhat={stats['min_raw_yhat']:.6f}, "
                    f"mean_raw_yhat={stats['mean_raw_yhat']:.6f}, "
                    f"max_raw_yhat={stats['max_raw_yhat']:.6f}, "
                    f"raw_neg_pct={stats['raw_neg_pct']:.1f}%, "
                    f"raw_zero_pct={stats['raw_zero_pct']:.1f}%, "
                    f"first_5_raw_predictions={stats['first_5_raw_predictions']}"
                )
                
                # Compute clamped predictions and forecast horizon stats
                clamped_yhat = np.maximum(raw_yhat, 0.0)
                zero_forecast_count = (clamped_yhat == 0.0).sum()
                zero_forecast_pct = (zero_forecast_count / len(clamped_yhat) * 100) if len(clamped_yhat) > 0 else 0.0
                
                logger.info(
                    f"ZERO_FORECAST_INVESTIGATION: product_id={ts.product_id}, "
                    f"step=forecast_horizon_stats, model=ensemble, "
                    f"forecast_count={len(clamped_yhat)}, "
                    f"zero_forecast_count={int(zero_forecast_count)}, "
                    f"zero_forecast_pct={zero_forecast_pct:.1f}%"
                )
                
                # Warnings
                if stats['raw_neg_pct'] > 50.0:
                    logger.warning(
                        f"ZERO_FORECAST_INVESTIGATION: product_id={ts.product_id}, "
                        f"step=warning, High negative predictions ({stats['raw_neg_pct']:.1f}%) - "
                        f"likely being clamped to zero"
                    )
                elif stats['raw_zero_pct'] > 50.0 and stats['raw_neg_pct'] < 10.0:
                    logger.warning(
                        f"ZERO_FORECAST_INVESTIGATION: product_id={ts.product_id}, "
                        f"step=warning, High zero predictions ({stats['raw_zero_pct']:.1f}%) but low negatives "
                        f"({stats['raw_neg_pct']:.1f}%) - likely future feature/regressor issue"
                    )
        
        elif train_result.model_name in ("seasonal_naive", "rolling_mean"):
            # Baseline models: use their predict method
            last_train_date = ts.df["ds"].max()
            forecast_df = train_result.model.predict(
                horizon_days=horizon_days,
                last_date=last_train_date,
                product_id=ts.product_id,  # Pass product_id for gated logging
            )
            
            # Step 4: Log raw predictions before clamping (gated)
            if self._should_log_deep_diagnostics(ts.product_id) and not forecast_df.empty and "yhat" in forecast_df.columns:
                raw_yhat = forecast_df["yhat"].values
                stats = self._compute_raw_predictions_stats(raw_yhat)
                logger.info(
                    f"ZERO_FORECAST_INVESTIGATION: product_id={ts.product_id}, "
                    f"step=raw_predictions, model={train_result.model_name}, "
                    f"min_raw_yhat={stats['min_raw_yhat']:.6f}, "
                    f"mean_raw_yhat={stats['mean_raw_yhat']:.6f}, "
                    f"max_raw_yhat={stats['max_raw_yhat']:.6f}, "
                    f"raw_neg_pct={stats['raw_neg_pct']:.1f}%, "
                    f"raw_zero_pct={stats['raw_zero_pct']:.1f}%, "
                    f"first_5_raw_predictions={stats['first_5_raw_predictions']}"
                )
                
                # Compute clamped predictions and forecast horizon stats
                clamped_yhat = np.maximum(raw_yhat, 0.0)
                zero_forecast_count = (clamped_yhat == 0.0).sum()
                zero_forecast_pct = (zero_forecast_count / len(clamped_yhat) * 100) if len(clamped_yhat) > 0 else 0.0
                
                logger.info(
                    f"ZERO_FORECAST_INVESTIGATION: product_id={ts.product_id}, "
                    f"step=forecast_horizon_stats, model={train_result.model_name}, "
                    f"forecast_count={len(clamped_yhat)}, "
                    f"zero_forecast_count={int(zero_forecast_count)}, "
                    f"zero_forecast_pct={zero_forecast_pct:.1f}%"
                )
                
                # Warnings
                if stats['raw_neg_pct'] > 50.0:
                    logger.warning(
                        f"ZERO_FORECAST_INVESTIGATION: product_id={ts.product_id}, "
                        f"step=warning, High negative predictions ({stats['raw_neg_pct']:.1f}%) - "
                        f"likely being clamped to zero"
                    )
                elif stats['raw_zero_pct'] > 50.0 and stats['raw_neg_pct'] < 10.0:
                    logger.warning(
                        f"ZERO_FORECAST_INVESTIGATION: product_id={ts.product_id}, "
                        f"step=warning, High zero predictions ({stats['raw_zero_pct']:.1f}%) but low negatives "
                        f"({stats['raw_neg_pct']:.1f}%) - likely future feature/regressor issue"
                    )
            
        else:
            raise ValueError(f"Unsupported model: {train_result.model_name}")

        return ForecastResult(
            product_id=ts.product_id,
            model_name=train_result.model_name,
            horizon_days=horizon_days,
            forecast_df=forecast_df,
        )
