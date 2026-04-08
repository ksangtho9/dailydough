from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Union
from datetime import timedelta
import logging
import time

import numpy as np
import pandas as pd

from .preprocessing import CleanedTimeSeries
from .trainer import ModelTrainer, TrainResult
from .features import FeatureEngineer
from .models.baseline_model import SeasonalNaiveModel, RollingMeanModel
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
        if product_id is not None and product_id in settings.debug_forecast_product_ids:
            return True
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
    
    def _check_prophet_viability(
        self,
        forecast_df: pd.DataFrame,
        product_id: Optional[int] = None,
    ) -> tuple[bool, dict]:
        """
        Check if Prophet predictions are viable (not mostly negative).
        
        Args:
            forecast_df: DataFrame with 'yhat' column containing raw predictions
            product_id: Product ID for logging
            
        Returns:
            (is_viable, diagnostics_dict) tuple
            - is_viable: True if predictions pass viability check
            - diagnostics_dict: Contains raw_neg_pct, mean_raw_yhat, etc.
        """
        if forecast_df.empty or "yhat" not in forecast_df.columns:
            return False, {"reason": "empty_or_missing_yhat"}
        
        raw_yhat = forecast_df["yhat"].values
        stats = self._compute_raw_predictions_stats(raw_yhat)

        raw_neg_pct = stats.get("raw_neg_pct", 0.0)
        mean_raw_yhat = stats.get("mean_raw_yhat", 0.0)

        # Also check clamped zero rate — catches the case where a few large positive
        # predictions keep the mean positive, but the majority of days are negative
        # (getting clamped to 0). These products look "ok" by mean/neg_pct but the
        # stored forecast is mostly zeros.
        clamped_yhat = np.maximum(raw_yhat, 0.0)
        clamped_zero_pct = float((clamped_yhat == 0.0).sum() / len(clamped_yhat) * 100)

        # Viability criteria: fail if >50% negative OR mean < 0 OR >60% clamped zeros
        is_viable = raw_neg_pct <= 50.0 and mean_raw_yhat >= 0.0 and clamped_zero_pct <= 60.0

        fail_reason = None
        if not is_viable:
            if raw_neg_pct > 50.0:
                fail_reason = f"raw_neg_pct={raw_neg_pct:.1f}% > 50%"
            elif mean_raw_yhat < 0.0:
                fail_reason = f"mean_raw_yhat={mean_raw_yhat:.2f} < 0"
            else:
                fail_reason = f"clamped_zero_pct={clamped_zero_pct:.1f}% > 60%"

        diagnostics = {
            "raw_neg_pct": raw_neg_pct,
            "mean_raw_yhat": mean_raw_yhat,
            "min_raw_yhat": stats.get("min_raw_yhat"),
            "max_raw_yhat": stats.get("max_raw_yhat"),
            "clamped_zero_pct": clamped_zero_pct,
            "is_viable": is_viable,
            "reason": fail_reason,
        }
        
        if not is_viable:
            logger.warning(
                f"PROPHET_VIABILITY_CHECK: product_id={product_id}, "
                f"FAILED - {diagnostics['reason']}, "
                f"raw_neg_pct={raw_neg_pct:.1f}%, mean_raw_yhat={mean_raw_yhat:.2f}"
            )
        else:
            logger.info(
                f"PROPHET_VIABILITY_CHECK: product_id={product_id}, "
                f"PASSED - raw_neg_pct={raw_neg_pct:.1f}%, mean_raw_yhat={mean_raw_yhat:.2f}"
            )
        
        return is_viable, diagnostics

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
        forecast_run_id: Optional[str] = None,
    ) -> ForecastResult:
        # Store the requested model name before calling trainer
        # This allows us to check viability based on what was requested, not what was returned
        requested_model = model_name
        
        # Determine if we should force the model (Prophet)
        force_model_value = (model_name == "prophet")
        
        # Check if trainer has force_model parameter
        import inspect
        trainer_train_sig = inspect.signature(self.trainer.train)
        trainer_has_force_model = "force_model" in trainer_train_sig.parameters
        
        # Diagnostic: Log forecast request to trace code path (always log, unconditional)
        logger.info(
            f"FORECAST_REQUEST: forecast_run_id={forecast_run_id}, product_id={ts.product_id}, requested_model={requested_model}, "
            f"force_model={force_model_value}, trainer_has_force_model={trainer_has_force_model}"
        )
        
        # For forecasting (inference), don't optimize hyperparameters - use stored or defaults
        # Hyperparameter optimization should only run during explicit training
        # When explicitly requesting Prophet, use force_model=True to bypass early gates
        # The forecaster will then check viability on the actual predictions
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
            force_model=(model_name == "prophet"),  # Force Prophet when requested to allow viability check
            forecast_run_id=forecast_run_id,
        )

        # Check viability based on REQUESTED model, not the returned model
        # This ensures the viability gate runs even if trainer switched models
        if requested_model == "prophet":
            # If we requested Prophet but trainer returned something else, treat as viability failure
            if train_result.model_name != "prophet":
                logger.warning(
                    f"PROPHET_FALLBACK: product_id={ts.product_id}, "
                    f"Prophet training failed or was skipped (trainer returned {train_result.model_name}), "
                    f"treating as viability failure, falling back to alternative models"
                )
                
                # Trigger fallback chain immediately
                last_train_date = ts.df["ds"].max()
                fallback_success = False
                fallback_model = None
                fallback_forecast_df = None
                
                # Try XGBoost first (if eligible)
                try:
                    logger.info(f"PROPHET_FALLBACK: product_id={ts.product_id}, attempting XGBoost fallback")
                    xgb_train_result = self.trainer.train(
                        ts,
                        model_name="xgboost",
                        hyperparameters=hyperparameters,
                        holidays_df=holidays_df,
                        weather_df=weather_df,
                        promotions_df=promotions_df,
                        events_df=events_df,
                        product_info=product_info,
                        optimize_with_wape=False,
                        forecast_run_id=forecast_run_id,
                    )
                    
                    if xgb_train_result.model_name == "xgboost":
                        # Generate future dates for XGBoost
                        future_dates = pd.date_range(
                            start=last_train_date + timedelta(days=1),
                            periods=horizon_days,
                            freq="D",
                        )
                        future_df = pd.DataFrame({"ds": future_dates})
                        
                        # Use future_regressors if provided
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
                        
                        fallback_forecast_df = xgb_train_result.model.predict_future(
                            historical_df=ts.df,
                            future_df=future_df,
                            feature_engineer=self.feature_engineer,
                            holidays_df=holidays_df,
                            weather_df=weather_df,
                            promotions_df=promotions_df,
                            events_df=events_df,
                            product_info=product_info,
                            product_id=ts.product_id,
                        )
                        
                        # Check XGBoost viability too
                        if not fallback_forecast_df.empty and "yhat" in fallback_forecast_df.columns:
                            is_xgb_viable, _ = self._check_prophet_viability(
                                fallback_forecast_df, product_id=ts.product_id
                            )
                            if is_xgb_viable:
                                fallback_success = True
                                fallback_model = "xgboost"
                                logger.info(
                                    f"PROPHET_FALLBACK: product_id={ts.product_id}, "
                                    f"XGBoost fallback successful"
                                )
                except Exception as e:
                    logger.warning(
                        f"PROPHET_FALLBACK: product_id={ts.product_id}, "
                        f"XGBoost fallback failed: {e}"
                    )
                
                # If XGBoost failed, try seasonal naive
                if not fallback_success:
                    try:
                        logger.info(
                            f"PROPHET_FALLBACK: product_id={ts.product_id}, "
                            f"attempting seasonal_naive fallback"
                        )
                        seasonal_model = SeasonalNaiveModel()
                        seasonal_model.fit(ts.df)
                        fallback_forecast_df = seasonal_model.predict(
                            horizon_days=horizon_days,
                            last_date=last_train_date,
                            product_id=ts.product_id,
                        )
                        fallback_success = True
                        fallback_model = "seasonal_naive"
                        logger.info(
                            f"PROPHET_FALLBACK: product_id={ts.product_id}, "
                            f"seasonal_naive fallback successful"
                        )
                    except Exception as e:
                        logger.warning(
                            f"PROPHET_FALLBACK: product_id={ts.product_id}, "
                            f"seasonal_naive fallback failed: {e}"
                        )
                
                # If seasonal naive failed, try rolling mean
                if not fallback_success:
                    try:
                        logger.info(
                            f"PROPHET_FALLBACK: product_id={ts.product_id}, "
                            f"attempting rolling_mean fallback"
                        )
                        rolling_model = RollingMeanModel()
                        rolling_model.fit(ts.df)
                        fallback_forecast_df = rolling_model.predict(
                            horizon_days=horizon_days,
                            last_date=last_train_date,
                            product_id=ts.product_id,
                        )
                        fallback_success = True
                        fallback_model = "rolling_mean"
                        logger.info(
                            f"PROPHET_FALLBACK: product_id={ts.product_id}, "
                            f"rolling_mean fallback successful"
                        )
                    except Exception as e:
                        logger.error(
                            f"PROPHET_FALLBACK: product_id={ts.product_id}, "
                            f"ALL fallbacks failed! Last error: {e}"
                        )
                
                if fallback_success and fallback_forecast_df is not None:
                    # Use fallback model's predictions
                    forecast_df = fallback_forecast_df
                    # Track that we're using a fallback model
                    train_result = TrainResult(
                        model_name=fallback_model,
                        model=train_result.model,  # Keep original model for reference
                        metadata={
                            "prophet_training_failed": True,
                            "trainer_returned_model": train_result.model_name,
                            "fallback_reason": f"Prophet training failed (trainer returned {train_result.model_name})",
                            "original_model": "prophet",
                        }
                    )
                    logger.info(
                        f"PROPHET_FALLBACK: product_id={ts.product_id}, "
                        f"Using {fallback_model} instead of Prophet. "
                        f"Prophet was skipped by trainer (returned {train_result.model_name})"
                    )
                else:
                    # All fallbacks failed - this should not happen, but handle gracefully
                    logger.error(
                        f"PROPHET_FALLBACK: product_id={ts.product_id}, "
                        f"All fallbacks failed after Prophet training failure. "
                        f"Trainer returned: {train_result.model_name}"
                    )
                    # Return the model that trainer selected as fallback
                    return ForecastResult(
                        product_id=ts.product_id,
                        model_name=train_result.model_name,
                        horizon_days=horizon_days,
                        forecast_df=pd.DataFrame(),  # Empty - fallbacks failed
                    )
            else:
                # Prophet trained successfully - proceed with viability check on predictions
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
                
                # Diagnostic: Log raw predictions right after model.predict() (gated)
                if self._should_log_deep_diagnostics(ts.product_id) and not forecast_df.empty and "yhat" in forecast_df.columns:
                    raw_yhat = forecast_df["yhat"].values
                    raw_stats = self._compute_raw_predictions_stats(raw_yhat)
                    logger.info(
                        f"PREDICT_RAW: forecast_run_id={forecast_run_id}, product_id={ts.product_id}, model=prophet, "
                        f"min={raw_stats['min_raw_yhat']:.6f}, mean={raw_stats['mean_raw_yhat']:.6f}, "
                        f"max={raw_stats['max_raw_yhat']:.6f}, zero_count={(raw_yhat == 0.0).sum()}, "
                        f"negative_count={(raw_yhat < 0.0).sum()}"
                    )
                    
                    # Log clamped predictions
                    clamped_yhat = np.maximum(raw_yhat, 0.0)
                    clamped_zero_count = (clamped_yhat == 0.0).sum()
                    logger.info(
                        f"PREDICT_CLAMPED: forecast_run_id={forecast_run_id}, product_id={ts.product_id}, model=prophet, "
                        f"min={float(np.min(clamped_yhat)):.6f}, mean={float(np.mean(clamped_yhat)):.6f}, "
                        f"max={float(np.max(clamped_yhat)):.6f}, zero_count={clamped_zero_count}"
                    )
                
                # CRITICAL: Prophet Horizon Viability Gate (Fail Fast)
                # Check if Prophet predictions are viable before using them
                is_prophet_viable, prophet_diagnostics = self._check_prophet_viability(
                    forecast_df, product_id=ts.product_id
                )
                
                if not is_prophet_viable:
                    # Prophet failed viability - fall back to alternative models
                    logger.warning(
                        f"PROPHET_FALLBACK: product_id={ts.product_id}, "
                        f"Prophet horizon viability failed ({prophet_diagnostics['reason']}), "
                        f"falling back to alternative models"
                    )
                    
                    # Try XGBoost first (if eligible)
                    fallback_success = False
                    fallback_model = None
                    fallback_forecast_df = None
                    
                    try:
                        # Try XGBoost
                        logger.info(f"PROPHET_FALLBACK: product_id={ts.product_id}, attempting XGBoost fallback")
                        xgb_train_result = self.trainer.train(
                            ts,
                            model_name="xgboost",
                            hyperparameters=hyperparameters,
                            holidays_df=holidays_df,
                            weather_df=weather_df,
                            promotions_df=promotions_df,
                            events_df=events_df,
                            product_info=product_info,
                            optimize_with_wape=False,
                            forecast_run_id=forecast_run_id,
                        )
                        
                        if xgb_train_result.model_name == "xgboost":
                            # Generate future dates for XGBoost
                            future_dates = pd.date_range(
                                start=last_train_date + timedelta(days=1),
                                periods=horizon_days,
                                freq="D",
                            )
                            future_df = pd.DataFrame({"ds": future_dates})
                            
                            # Use future_regressors if provided
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
                            
                            fallback_forecast_df = xgb_train_result.model.predict_future(
                                historical_df=ts.df,
                                future_df=future_df,
                                feature_engineer=self.feature_engineer,
                                holidays_df=holidays_df,
                                weather_df=weather_df,
                                promotions_df=promotions_df,
                                events_df=events_df,
                                product_info=product_info,
                                product_id=ts.product_id,
                            )
                            
                            # Check XGBoost viability too
                            if not fallback_forecast_df.empty and "yhat" in fallback_forecast_df.columns:
                                is_xgb_viable, _ = self._check_prophet_viability(
                                    fallback_forecast_df, product_id=ts.product_id
                                )
                                if is_xgb_viable:
                                    fallback_success = True
                                    fallback_model = "xgboost"
                                    logger.info(
                                        f"PROPHET_FALLBACK: product_id={ts.product_id}, "
                                        f"XGBoost fallback successful"
                                    )
                    except Exception as e:
                        logger.warning(
                            f"PROPHET_FALLBACK: product_id={ts.product_id}, "
                            f"XGBoost fallback failed: {e}"
                        )
                    
                    # If XGBoost failed, try seasonal naive
                    if not fallback_success:
                        try:
                            logger.info(
                                f"PROPHET_FALLBACK: product_id={ts.product_id}, "
                                f"attempting seasonal_naive fallback"
                            )
                            seasonal_model = SeasonalNaiveModel()
                            seasonal_model.fit(ts.df)
                            fallback_forecast_df = seasonal_model.predict(
                                horizon_days=horizon_days,
                                last_date=last_train_date,
                                product_id=ts.product_id,
                            )
                            fallback_success = True
                            fallback_model = "seasonal_naive"
                            logger.info(
                                f"PROPHET_FALLBACK: product_id={ts.product_id}, "
                                f"seasonal_naive fallback successful"
                            )
                        except Exception as e:
                            logger.warning(
                                f"PROPHET_FALLBACK: product_id={ts.product_id}, "
                                f"seasonal_naive fallback failed: {e}"
                            )
                    
                    # If seasonal naive failed, try rolling mean
                    if not fallback_success:
                        try:
                            logger.info(
                                f"PROPHET_FALLBACK: product_id={ts.product_id}, "
                                f"attempting rolling_mean fallback"
                            )
                            rolling_model = RollingMeanModel()
                            rolling_model.fit(ts.df)
                            fallback_forecast_df = rolling_model.predict(
                                horizon_days=horizon_days,
                                last_date=last_train_date,
                                product_id=ts.product_id,
                            )
                            fallback_success = True
                            fallback_model = "rolling_mean"
                            logger.info(
                                f"PROPHET_FALLBACK: product_id={ts.product_id}, "
                                f"rolling_mean fallback successful"
                            )
                        except Exception as e:
                            logger.error(
                                f"PROPHET_FALLBACK: product_id={ts.product_id}, "
                                f"ALL fallbacks failed! Last error: {e}"
                            )
                    
                    if fallback_success and fallback_forecast_df is not None:
                        # Use fallback model's predictions
                        forecast_df = fallback_forecast_df
                        # Track that we're using a fallback model
                        train_result = TrainResult(
                            model_name=fallback_model,
                            model=train_result.model,  # Keep original model for reference
                            metadata={
                                "prophet_viability_failed": True,
                                "prophet_diagnostics": prophet_diagnostics,
                                "fallback_reason": prophet_diagnostics.get("reason"),
                                "original_model": "prophet",
                            }
                        )
                        logger.info(
                            f"PROPHET_FALLBACK: product_id={ts.product_id}, "
                            f"Using {fallback_model} instead of Prophet. "
                            f"Prophet diagnostics: {prophet_diagnostics}"
                        )
                    else:
                        # All fallbacks failed — returning clamped Prophet zeros is worse than no forecast.
                        # Return empty so the caller can surface "no forecast available" instead of misleading zeros.
                        logger.error(
                            f"PROPHET_FALLBACK: product_id={ts.product_id}, "
                            f"All fallbacks failed after Prophet viability failure. Returning empty forecast. "
                            f"Prophet diagnostics: {prophet_diagnostics}"
                        )
                        return ForecastResult(
                            product_id=ts.product_id,
                            model_name="prophet",
                            horizon_days=horizon_days,
                            forecast_df=pd.DataFrame(),
                        )
                
                # Step 4: Log raw predictions before clamping (gated) - only for Prophet
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
            
            # Diagnostic: Log raw predictions right after XGBoost predict (gated)
            if self._should_log_deep_diagnostics(ts.product_id) and not forecast_df.empty and "yhat" in forecast_df.columns:
                raw_yhat = forecast_df["yhat"].values
                raw_stats = self._compute_raw_predictions_stats(raw_yhat)
                logger.info(
                    f"PREDICT_RAW: forecast_run_id={forecast_run_id}, product_id={ts.product_id}, model=xgboost, "
                    f"min={raw_stats['min_raw_yhat']:.6f}, mean={raw_stats['mean_raw_yhat']:.6f}, "
                    f"max={raw_stats['max_raw_yhat']:.6f}, zero_count={(raw_yhat == 0.0).sum()}, "
                    f"negative_count={(raw_yhat < 0.0).sum()}"
                )
                
                # Log clamped predictions
                clamped_yhat = np.maximum(raw_yhat, 0.0)
                clamped_zero_count = (clamped_yhat == 0.0).sum()
                logger.info(
                    f"PREDICT_CLAMPED: forecast_run_id={forecast_run_id}, product_id={ts.product_id}, model=xgboost, "
                    f"min={float(np.min(clamped_yhat)):.6f}, mean={float(np.mean(clamped_yhat)):.6f}, "
                    f"max={float(np.max(clamped_yhat)):.6f}, zero_count={clamped_zero_count}"
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
        
        # Determine final model name (may have been changed by fallback logic)
        final_model_name = train_result.model_name

        return ForecastResult(
            product_id=ts.product_id,
            model_name=final_model_name,
            horizon_days=horizon_days,
            forecast_df=forecast_df,
        )
