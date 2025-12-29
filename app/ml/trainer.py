from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Callable, Tuple
from datetime import datetime, timezone, timedelta
import hashlib
import logging
import time

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from .preprocessing import CleanedTimeSeries
from .features import FeatureEngineer
from .models.prophet_model import ProphetSalesModel, ProphetConfig
from .models.xgboost_model import XGBoostSalesModel, XGBoostConfig
from .models.ensemble_model import EnsembleForecaster, EnsembleConfig
from .models.baseline_model import SeasonalNaiveModel, RollingMeanModel
from .hyperparameter_optimization import (
    optimize_prophet_hyperparameters,
    optimize_xgboost_hyperparameters,
)
from app.core.config import settings
from app.services.admin_training_jobs import CancelledError

logger = logging.getLogger("bakezy.training")


ModelName = Literal["prophet", "xgboost", "ensemble", "seasonal_naive", "rolling_mean"]


@dataclass
class TrainResult:
    model_name: ModelName
    # In MLOps v2, you might store metrics here (MAE, MAPE, etc.)
    # For now this is a simple placeholder.
    model: object
    metadata: Optional[dict] = None  # Store skip reasons, eligibility info, etc.


class ModelTrainer:
    def __init__(self, feature_engineer: Optional[FeatureEngineer] = None):
        self.feature_engineer = feature_engineer or FeatureEngineer()
    
    def _compute_feature_version(self, feature_cols: list[str]) -> str:
        """Compute a version identifier for feature engineering based on feature columns."""
        if not feature_cols:
            return "v0"
        sorted_cols = sorted(feature_cols)
        cols_str = ",".join(sorted_cols)
        return hashlib.md5(cols_str.encode()).hexdigest()[:8]
    
    def _should_optimize_hyperparameters(
        self,
        optimize_hyperparameters: str,
        product_id: Optional[int],
        db: Optional[Session],
        current_feature_version: str,
        selected_model_type: str,
    ) -> Tuple[bool, Optional[dict]]:
        """
        Determine if we should optimize hyperparameters or reuse stored ones.
        
        Returns:
            (should_optimize, stored_hyperparameters)
            If should_optimize=False, stored_hyperparameters contains hyperparams to reuse.
        """
        if optimize_hyperparameters == "false":
            return False, None
        if optimize_hyperparameters == "true":
            return True, None
        
        # "auto" mode: check if we can reuse stored hyperparameters
        if product_id is None or db is None:
            return True, None  # Can't check, optimize
        
        try:
            from app.models import ModelRun
            from datetime import datetime, timezone, timedelta
            
            model_run = db.query(ModelRun).filter(
                ModelRun.product_id == product_id,
                ModelRun.is_active == True,
                ModelRun.feature_version == current_feature_version,
                ModelRun.selected_model_type == selected_model_type,  # Must match current decision
                ModelRun.created_at >= datetime.now(timezone.utc) - timedelta(days=settings.hyperparam_reuse_days)
            ).first()
            
            if model_run is None:
                return True, None  # No stored hyperparameters or model type mismatch, optimize
            
            # Reuse without expensive validation - let normal post-fit validation catch issues
            return False, model_run.hyperparameters_json
        except Exception as e:
            logger.warning(f"Error checking ModelRun for product {product_id}: {e}")
            return True, None  # On error, optimize
    
    def _quick_prophet_viability_check(
        self,
        train_df_for_training: pd.DataFrame,
        eval_df: pd.DataFrame,
        holidays_df: Optional[pd.DataFrame] = None,
        weather_df: Optional[pd.DataFrame] = None,
        promotions_df: Optional[pd.DataFrame] = None,
        events_df: Optional[pd.DataFrame] = None,
        product_info: Optional[dict] = None,
    ) -> bool:
        """Quick check if Prophet is viable before expensive optimization.
        
        Keep it minimal: fit once, predict on eval slice, run guardrail.
        No component decomposition, no heavy logging - just summary stats.
        """
        if eval_df.empty or len(eval_df) < 7:  # Need at least 7 days for meaningful eval
            logger.info("Skipping Prophet viability check: insufficient eval data.")
            return True  # Assume viable if not enough data to check
        
        try:
            # Fit with default config (fast, no optimization)
            quick_model = ProphetSalesModel(config=ProphetConfig())
            quick_model.fit(train_df_for_training)
            
            # Predict on eval slice (already computed, small window)
            raw_yhat = self._get_raw_predictions(
                quick_model, "prophet", eval_df, train_df_for_training,
                holidays_df=holidays_df, weather_df=weather_df, promotions_df=promotions_df,
                events_df=events_df, product_info=product_info,
            )
            
            # Check guardrail (minimal check, no heavy diagnostics)
            if len(raw_yhat) > 0 and "y" in eval_df.columns:
                should_fallback, _ = self._check_guardrail(
                    eval_df, raw_yhat, train_df_for_training["y"]
                )
                passes = not should_fallback
            else:
                passes = True  # Can't check, assume passes
            
            # Log only summary: pass/fail
            if not passes:
                logger.info("Prophet viability check failed, skipping optimization")
            
            return passes
        except Exception as e:
            logger.warning(f"Prophet viability check exception, assuming not viable: {e}")
            return False  # If check fails, assume not viable
    
    def _get_raw_predictions(
        self,
        model: object,
        model_name: ModelName,
        eval_df: pd.DataFrame,
        train_df: pd.DataFrame,
        holidays_df: Optional[pd.DataFrame] = None,
        weather_df: Optional[pd.DataFrame] = None,
        promotions_df: Optional[pd.DataFrame] = None,
        events_df: Optional[pd.DataFrame] = None,
        product_info: Optional[dict] = None,
    ) -> np.ndarray:
        """
        Get raw predictions (before clamping) from a model for evaluation.
        
        Returns:
            numpy array of raw predictions (can be negative)
        """
        import logging
        logger = logging.getLogger("bakezy.training")
        
        try:
            if model_name == "prophet":
                # Prophet: predict on eval_df dates
                horizon_days = len(eval_df)
                
                # Step 0: Log regressor availability before prediction
                regressors = getattr(model, "regressors", [])
                logger.info(
                    f"Prophet validation: Model has {len(regressors)} regressors: {regressors}"
                )
                
                # Apply feature engineering to eval_df to get regressor values (Fix 1: CRITICAL)
                eval_df_processed = eval_df.copy()
                eval_df_processed["ds"] = pd.to_datetime(eval_df_processed["ds"])
                eval_df_processed = self.feature_engineer.transform(
                    eval_df_processed,
                    holidays_df=holidays_df,
                    weather_df=weather_df,
                    promotions_df=promotions_df,
                    events_df=events_df,
                    product_info=product_info,
                )
                
                # Step 1: Log regressor statistics from eval_df (after feature engineering)
                if regressors:
                    eval_regressor_stats = {}
                    for reg in regressors:
                        if reg in eval_df_processed.columns:
                            reg_data = pd.to_numeric(eval_df_processed[reg], errors='coerce').dropna()
                            if len(reg_data) > 0:
                                eval_regressor_stats[reg] = {
                                    "min": float(reg_data.min()),
                                    "mean": float(reg_data.mean()),
                                    "max": float(reg_data.max()),
                                    "available": True,
                                }
                            else:
                                eval_regressor_stats[reg] = {"available": False, "reason": "all_nan"}
                        else:
                            eval_regressor_stats[reg] = {"available": False, "reason": "missing_column"}
                    
                    logger.info(
                        f"Prophet validation: Eval regressor stats: {eval_regressor_stats}"
                    )
                
                # Create future_regressors DataFrame with eval_df dates and regressor values
                if regressors:
                    # Extract regressor columns that Prophet was trained with
                    available_regressor_cols = [r for r in regressors if r in eval_df_processed.columns]
                    if available_regressor_cols:
                        future_regressors = eval_df_processed[["ds"] + available_regressor_cols].copy()
                        logger.info(
                            f"Prophet validation: Created future_regressors with {len(available_regressor_cols)} regressors: {available_regressor_cols}"
                        )
                    else:
                        future_regressors = None
                        logger.warning(
                            f"Prophet validation: No regressors available in eval_df_processed, using None"
                        )
                else:
                    future_regressors = None
                
                # Prophet needs historical delivery if it was used as regressor
                historical_delivery = None
                if "delivery" in train_df.columns:
                    historical_delivery = train_df["delivery"]
                
                forecast_df = model.predict(
                    horizon_days=horizon_days,
                    historical_delivery=historical_delivery,
                    future_regressors=future_regressors,  # Pass proper regressors instead of None (Fix 1)
                )
                
                # Step 2: Component diagnostics - extract and log Prophet components
                if not forecast_df.empty:
                    component_cols = ["trend", "weekly", "yearly", "additive_terms", "multiplicative_terms"]
                    # Add regressor component columns if they exist
                    for reg in regressors:
                        if reg in forecast_df.columns:
                            component_cols.append(reg)
                    
                    available_components = [col for col in component_cols if col in forecast_df.columns]
                    if available_components:
                        component_stats = {}
                        for comp in available_components:
                            comp_data = pd.to_numeric(forecast_df[comp], errors='coerce').dropna()
                            if len(comp_data) > 0:
                                component_stats[comp] = {
                                    "min": float(comp_data.min()),
                                    "mean": float(comp_data.mean()),
                                    "max": float(comp_data.max()),
                                }
                        logger.info(
                            f"Prophet validation: Component stats: {component_stats}"
                        )
                        
                        # Check which components are negative
                        negative_components = [
                            comp for comp, stats in component_stats.items()
                            if stats["min"] < 0
                        ]
                        if negative_components:
                            logger.warning(
                                f"Prophet validation: Negative components detected: {negative_components}"
                            )
                # Filter to eval_df dates
                if not forecast_df.empty and "yhat" in forecast_df.columns:
                    # Merge with eval_df to get matching dates
                    merged = forecast_df.merge(eval_df[["ds"]], on="ds", how="inner")
                    if not merged.empty:
                        return merged["yhat"].values
                    else:
                        logger.warning("Prophet predictions didn't match eval_df dates")
                        return np.array([])
                return np.array([])
                
            elif model_name == "xgboost":
                # XGBoost: need to apply feature engineering to eval_df
                eval_df_processed = eval_df.copy()
                eval_df_processed["ds"] = pd.to_datetime(eval_df_processed["ds"])
                eval_df_processed = self.feature_engineer.transform(
                    eval_df_processed,
                    holidays_df=holidays_df,
                    weather_df=weather_df,
                    promotions_df=promotions_df,
                    events_df=events_df,
                    product_info=product_info,
                )
                
                if model.feature_cols is None:
                    logger.warning("XGBoost model has no feature_cols")
                    return np.array([])
                
                # Get predictions
                X_eval = eval_df_processed[model.feature_cols].values
                raw_preds = model.model.predict(X_eval)
                return raw_preds
                
            elif model_name == "ensemble":
                # Ensemble: use predict method
                eval_df_processed = eval_df.copy()
                eval_df_processed["ds"] = pd.to_datetime(eval_df_processed["ds"])
                eval_df_processed = self.feature_engineer.transform(
                    eval_df_processed,
                    holidays_df=holidays_df,
                    weather_df=weather_df,
                    promotions_df=promotions_df,
                    events_df=events_df,
                    product_info=product_info,
                )
                
                # Get historical delivery if available
                historical_delivery = None
                if "delivery" in train_df.columns:
                    historical_delivery = train_df["delivery"]
                
                # Ensemble predict
                predictions = model.predict(
                    historical_df=train_df,
                    future_df=eval_df_processed,
                    horizon_days=len(eval_df),
                    holidays_df=holidays_df,
                    weather_df=weather_df,
                    promotions_df=promotions_df,
                    events_df=events_df,
                    product_info=product_info,
                    future_regressors=None,
                    historical_delivery=historical_delivery,
                )
                if predictions is not None and len(predictions) > 0:
                    return np.array(predictions)
                return np.array([])
                
            elif model_name in ("seasonal_naive", "rolling_mean"):
                # Baseline models: predict and return
                last_date = train_df["ds"].max() if "ds" in train_df.columns else pd.Timestamp.today()
                forecast_df = model.predict(horizon_days=len(eval_df), last_date=last_date)
                if not forecast_df.empty and "yhat" in forecast_df.columns:
                    # Merge with eval_df to get matching dates
                    merged = forecast_df.merge(eval_df[["ds"]], on="ds", how="inner")
                    if not merged.empty:
                        return merged["yhat"].values
                return np.array([])
            else:
                logger.warning(f"Unknown model type for raw predictions: {model_name}")
                return np.array([])
        except Exception as e:
            logger.warning(f"Error getting raw predictions for {model_name}: {e}")
            return np.array([])
    
    def _check_guardrail(
        self,
        eval_df: pd.DataFrame,
        raw_yhat: np.ndarray,
        y_train: pd.Series,
    ) -> tuple[bool, Optional[dict]]:
        """
        Check if model should be rejected based on guardrail.
        
        Returns:
            (should_fallback, guardrail_info) tuple
        """
        if len(raw_yhat) == 0 or len(eval_df) == 0:
            return False, None
        
        training_zero_pct = (y_train == 0.0).sum() / len(y_train) * 100 if len(y_train) > 0 else 0
        yhat_zero_pct = (np.maximum(raw_yhat, 0.0) == 0.0).sum() / len(raw_yhat) * 100 if len(raw_yhat) > 0 else 0
        raw_neg_pct = (raw_yhat < 0).sum() / len(raw_yhat) * 100 if len(raw_yhat) > 0 else 0
        mean_raw_yhat = float(raw_yhat.mean()) if len(raw_yhat) > 0 else 0.0
        mean_y = float(y_train.mean()) if len(y_train) > 0 else 0.0
        
        # Robust trigger: ALL conditions must be true
        if (training_zero_pct < 30 and 
            yhat_zero_pct > 60 and 
            (raw_neg_pct > 50 or (mean_y > 0 and mean_raw_yhat < 0.2 * mean_y))):
            return True, {
                "training_zero_pct": training_zero_pct,
                "yhat_zero_pct": yhat_zero_pct,
                "raw_neg_pct": raw_neg_pct,
                "mean_raw_yhat": mean_raw_yhat,
                "mean_y": mean_y
            }
        return False, None

    def train(
        self,
        ts: CleanedTimeSeries,
        model_name: ModelName = "prophet",
        hyperparameters: Optional[dict] = None,  # New parameter: stored hyperparameters for warm-start
        holidays_df: Optional[pd.DataFrame] = None,
        weather_df: Optional[pd.DataFrame] = None,
        promotions_df: Optional[pd.DataFrame] = None,
        events_df: Optional[pd.DataFrame] = None,
        product_info: Optional[dict] = None,
        optimize_with_wape: bool = True,
        sample_weights: Optional[np.ndarray] = None,
        should_cancel: Optional[Callable[[], bool]] = None,  # New parameter: cancellation callback
        optimize_hyperparameters: str = "auto",  # "auto", "true", or "false"
        db: Optional[Session] = None,  # For ModelRun queries
        product_id: Optional[int] = None,  # For ModelRun queries
    ) -> TrainResult:
        """
        High-level training routine for a single product time series.
        
        Args:
            ts: CleanedTimeSeries to train on
            model_name: Model type ("prophet" or "xgboost")
            holidays_df: Optional holidays DataFrame
            weather_df: Optional weather DataFrame
            promotions_df: Optional promotions DataFrame
            events_df: Optional events DataFrame
            product_info: Optional product metadata dict
            optimize_with_wape: If True, optimize hyperparameters using WAPE
        """
        df = ts.df.copy()

        # Feature engineering (on all data first, including invalid days for feature computation)
        df["ds"] = pd.to_datetime(df["ds"])
        df = self.feature_engineer.transform(
            df,
            holidays_df=holidays_df,
            weather_df=weather_df,
            promotions_df=promotions_df,
            events_df=events_df,
            product_info=product_info,
        )

        # Filter out invalid days from training (but keep in df for reference)
        # Only train on is_valid_day == 1
        if "is_valid_day" in df.columns:
            train_df = df[df["is_valid_day"] == 1].copy()
        else:
            train_df = df.copy()

        # Explicit validation that invalid days are excluded
        # Weight Policy:
        # - is_valid_day == 0: Excluded from training (never gets a weight)
        # - is_valid_day == 1 AND is_supply_capped_day == 0: Weight = 1.0 (normal day)
        # - is_valid_day == 1 AND is_supply_capped_day == 1: Weight = 0.3 (supply-capped day)
        if "is_valid_day" in train_df.columns:
            invalid_count = (train_df["is_valid_day"] == 0).sum()
            if invalid_count > 0:
                import logging
                logger = logging.getLogger("bakezy.training")
                logger.error(f"CRITICAL: {invalid_count} invalid days found in train_df. Removing them.")
                train_df = train_df[train_df["is_valid_day"] == 1].copy()

        # NOTE: Sample weights will be computed AFTER train/eval split to ensure alignment
        # We'll compute them later based on train_df_for_training
        initial_sample_weights = sample_weights
        
        # Diagnostic logging: Check for potential issues that could cause zero predictions
        if not train_df.empty and "y" in train_df.columns:
            import logging
            logger = logging.getLogger("bakezy.training")
            zero_count = (train_df["y"] == 0.0).sum()
            total_count = len(train_df)
            zero_pct = (zero_count / total_count * 100) if total_count > 0 else 0
            mean_y = train_df["y"].mean() if total_count > 0 else 0
            
            if "is_supply_capped_day" in train_df.columns:
                capped_count = (train_df["is_supply_capped_day"] == 1).sum()
                capped_pct = (capped_count / total_count * 100) if total_count > 0 else 0
                logger.info(
                    f"Training data diagnostics: {total_count} samples, {zero_count} zeros ({zero_pct:.1f}%), "
                    f"{capped_count} supply-capped ({capped_pct:.1f}%), mean y={mean_y:.2f}"
                )
                
                # Warn if too many supply-capped days (could bias model toward low predictions)
                if capped_pct > 70:
                    logger.warning(
                        f"WARNING: {capped_pct:.1f}% of training days are supply-capped. "
                        f"This may bias the model toward under-prediction."
                    )
            else:
                logger.info(
                    f"Training data diagnostics: {total_count} samples, {zero_count} zeros ({zero_pct:.1f}%), "
                    f"mean y={mean_y:.2f}"
                )
            
            # Warn if too many zeros in training data (could cause model to learn zero)
            if zero_pct > 50:
                logger.warning(
                    f"WARNING: {zero_pct:.1f}% of training data is zero. "
                    f"This may cause the model to predict zero frequently."
                )

        # Handle tiny training windows
        if len(train_df) < settings.min_training_window:
            import logging
            logger = logging.getLogger("bakezy.training")
            logger.info(
                f"Training window too small ({len(train_df)} days < {settings.min_training_window}). "
                f"Skipping Prophet and XGBoost, using seasonal naive."
            )
            skip_reason = f"training_window_too_small_{len(train_df)}"
            model = SeasonalNaiveModel()
            model.fit(train_df)
            return TrainResult(
                model_name="seasonal_naive",
                model=model,
                metadata={"prophet_skipped_reason": skip_reason, "training_window_days": len(train_df)}
            )

        # Split training data into train and eval slices
        # Use last N valid days for evaluation (more meaningful than training predictions)
        eval_df = None
        train_df_for_training = train_df.copy()
        
        if len(train_df) > settings.eval_window_days:
            # Split: use last eval_window_days for evaluation
            eval_df = train_df.tail(settings.eval_window_days).copy()
            train_df_for_training = train_df.iloc[:-settings.eval_window_days].copy()
            import logging
            logger = logging.getLogger("bakezy.training")
            logger.info(
                f"Split training data: {len(train_df_for_training)} days for training, "
                f"{len(eval_df)} days for evaluation"
            )
        
        # Compute sample weights AFTER train/eval split to ensure alignment with train_df_for_training
        # Normal day (is_supply_capped_day == 0): weight = 1.0
        # Supply-capped day (is_supply_capped_day == 1): weight = 0.3 (configurable)
        computed_sample_weights = None
        if initial_sample_weights is None and "is_supply_capped_day" in train_df_for_training.columns:
            # Compute weights from train_df_for_training to ensure perfect alignment
            computed_sample_weights = np.where(
                train_df_for_training["is_supply_capped_day"] == 1,
                0.3,  # Supply-capped days get reduced weight
                1.0   # Normal days get full weight
            )
            capped_count = int((train_df_for_training["is_supply_capped_day"] == 1).sum())
            total_valid = len(train_df_for_training)
            if total_valid > 0:
                import logging
                logger = logging.getLogger("bakezy.training")
                logger.info(
                    f"Sample weights computed - {capped_count}/{total_valid} supply-capped days "
                    f"(weight=0.3), {total_valid - capped_count} normal days (weight=1.0)"
                )
        elif initial_sample_weights is not None:
            # Use provided weights, but need to slice them to match train_df_for_training
            # If weights were provided for full train_df, slice them
            if len(initial_sample_weights) == len(train_df):
                # Weights are for full train_df, need to slice to match train_df_for_training
                if len(train_df_for_training) < len(train_df):
                    # We split the data, so slice the weights
                    computed_sample_weights = initial_sample_weights[:len(train_df_for_training)]
                    import logging
                    logger = logging.getLogger("bakezy.training")
                    logger.info(
                        f"Sliced sample weights from {len(initial_sample_weights)} to {len(computed_sample_weights)} "
                        f"to match training split"
                    )
                else:
                    computed_sample_weights = initial_sample_weights
            elif len(initial_sample_weights) == len(train_df_for_training):
                # Weights already match train_df_for_training
                computed_sample_weights = initial_sample_weights
            else:
                # Length mismatch - recompute from train_df_for_training
                import logging
                logger = logging.getLogger("bakezy.training")
                logger.warning(
                    f"Sample weights length ({len(initial_sample_weights)}) doesn't match training data length ({len(train_df_for_training)}). "
                    f"Computing weights from train_df_for_training instead."
                )
                if "is_supply_capped_day" in train_df_for_training.columns:
                    computed_sample_weights = np.where(
                        train_df_for_training["is_supply_capped_day"] == 1,
                        0.3,
                        1.0
                    )
                else:
                    computed_sample_weights = None
        
        # Use computed weights
        final_sample_weights = computed_sample_weights
        
        # Index-based validation: Ensure weights align with training data by index, not just length
        # This catches subtle bugs where row count matches but ordering differs
        if final_sample_weights is not None:
            import logging
            logger = logging.getLogger("bakezy.training")
            
            # Convert to Series aligned to train_df_for_training.index for index-based validation
            weight_series = pd.Series(final_sample_weights, index=train_df_for_training.index)
            
            # Validate index alignment (same set + same order)
            if not weight_series.index.equals(train_df_for_training.index):
                logger.error(
                    f"CRITICAL: Weight index doesn't match train_df_for_training index. "
                    f"Weight index: {list(weight_series.index[:5])}..., "
                    f"train_df_for_training index: {list(train_df_for_training.index[:5])}... "
                    f"Setting weights to None to prevent model corruption."
                )
                final_sample_weights = None
            elif len(final_sample_weights) != len(train_df_for_training):
                # Fallback length check (shouldn't happen if index matches, but double-check)
                logger.error(
                    f"CRITICAL: Sample weights length ({len(final_sample_weights)}) doesn't match training data length ({len(train_df_for_training)}). "
                    f"Setting weights to None to prevent model corruption."
                )
                final_sample_weights = None
            else:
                # Index matches, convert back to array for XGBoost
                final_sample_weights = weight_series.values

        # Determine selected_model_type FIRST (before any optimization)
        # This is critical for auto mode to check stored hyperparameters correctly
        selected_model_type = model_name
        metadata = None
        
        # Prophet eligibility check (on training window, not full historical)
        if model_name == "prophet":
            nonzero_days = (train_df_for_training["y"] > 0).sum() if "y" in train_df_for_training.columns else 0
            zero_rate = (train_df_for_training["y"] == 0.0).sum() / len(train_df_for_training) if len(train_df_for_training) > 0 and "y" in train_df_for_training.columns else 1.0
            
            if nonzero_days < settings.prophet_min_nonzero_days or zero_rate > settings.prophet_max_zero_rate:
                skip_reason = f"nonzero_days={nonzero_days},zero_rate={zero_rate:.2f}"
                logger.info(
                    f"Prophet skipped ({skip_reason}). "
                    f"Using XGBoost-only as fallback."
                )
                
                # Store in metadata for dashboard debugging
                metadata = {
                    "prophet_skipped_reason": skip_reason,
                    "nonzero_days": nonzero_days,
                    "zero_rate": zero_rate
                }
                
                # Fall back to XGBoost
                selected_model_type = "xgboost"
                model_name = "xgboost"
            else:
                # Prophet is eligible - run quick viability check BEFORE optimization
                if eval_df is not None and len(eval_df) >= 7:
                    viability_start_time = time.time()
                    prophet_viable = self._quick_prophet_viability_check(
                        train_df_for_training, eval_df, holidays_df, weather_df, promotions_df, events_df, product_info
                    )
                    viability_duration = time.time() - viability_start_time
                    logger.info(f"Prophet viability check took {viability_duration:.2f}s. Viable: {prophet_viable}")
                    
                    if not prophet_viable:
                        logger.info("Prophet viability check failed, skipping Prophet optimization. Trying XGBoost.")
                        metadata = {
                            "prophet_skipped_reason": "viability_check_failed",
                            "nonzero_days": nonzero_days,
                            "zero_rate": zero_rate
                        }
                        selected_model_type = "xgboost"
                        model_name = "xgboost"
        
        # Compute feature_version for auto mode check
        current_feature_version = "v0"
        if selected_model_type == "xgboost":
            # For XGBoost, we'll compute feature_version after feature engineering
            # For now, use a placeholder - will be computed after model training
            current_feature_version = "v1"  # Placeholder
        elif selected_model_type == "prophet":
            current_feature_version = "v1"  # Placeholder for Prophet
        
        # Check if we should optimize (auto mode logic)
        should_optimize, stored_hyperparams = self._should_optimize_hyperparameters(
            optimize_hyperparameters=optimize_hyperparameters,
            product_id=product_id,
            db=db,
            current_feature_version=current_feature_version,
            selected_model_type=selected_model_type,
        )
        
        # Update optimize_with_wape based on should_optimize
        # If we're reusing hyperparameters, don't optimize
        if not should_optimize and stored_hyperparams:
            optimize_with_wape = False
            hyperparameters = stored_hyperparams
            logger.info(f"Reusing stored hyperparameters for {selected_model_type} (auto mode)")
        elif should_optimize and optimize_hyperparameters == "auto":
            # Use reduced optimization settings for retraining
            logger.info(f"Running optimization with reduced settings for {selected_model_type} (auto mode)")

        if model_name == "prophet":
            # Optimize hyperparameters if requested (with reduced settings in auto mode)
            if optimize_with_wape:
                # Use reduced settings for retraining (auto mode)
                n_splits = settings.cv_splits_retrain if optimize_hyperparameters == "auto" else 3
                max_iter = settings.prophet_opt_max_iter_retrain if optimize_hyperparameters == "auto" else None
                
                opt_result = optimize_prophet_hyperparameters(
                    ts=CleanedTimeSeries(product_id=ts.product_id, df=df, shelf_life_days=ts.shelf_life_days),
                    holidays_df=holidays_df,
                    weather_df=weather_df,
                    promotions_df=promotions_df,
                    events_df=events_df,
                    product_info=product_info,
                    n_splits=n_splits,
                    max_iter=max_iter,
                    should_cancel=should_cancel,
                )
                # Use optimized hyperparameters
                config = ProphetConfig(
                    changepoint_prior_scale=opt_result.best_params.get("changepoint_prior_scale", 0.05),
                    seasonality_mode=opt_result.best_params.get("seasonality_mode", "additive"),
                    daily_seasonality=True,
                    weekly_seasonality=True,
                    yearly_seasonality=False,
                )
                model = ProphetSalesModel(config=config)
            else:
                # Use stored hyperparameters if available, otherwise defaults
                if hyperparameters and "prophet" in hyperparameters:
                    prophet_params = hyperparameters["prophet"]
                    config = ProphetConfig(
                        changepoint_prior_scale=prophet_params.get("changepoint_prior_scale", 0.05),
                        seasonality_mode=prophet_params.get("seasonality_mode", "additive"),
                        daily_seasonality=prophet_params.get("daily_seasonality", True),
                        weekly_seasonality=prophet_params.get("weekly_seasonality", True),
                        yearly_seasonality=prophet_params.get("yearly_seasonality", False),
                        monthly_seasonality=prophet_params.get("monthly_seasonality", False),
                        quarterly_seasonality=prophet_params.get("quarterly_seasonality", False),
                    )
                    model = ProphetSalesModel(config=config)
                else:
                    # Use default configuration
                    model = ProphetSalesModel()
            model.fit(train_df_for_training)
            
            # Validate on eval_df if available
            if eval_df is not None and "y" in eval_df.columns:
                raw_yhat = self._get_raw_predictions(
                    model, "prophet", eval_df, train_df_for_training,
                    holidays_df, weather_df, promotions_df, events_df, product_info
                )
                if len(raw_yhat) > 0:
                    should_fallback, guardrail_info = self._check_guardrail(
                        eval_df, raw_yhat, train_df_for_training["y"]
                    )
                    if should_fallback:
                        import logging
                        logger = logging.getLogger("bakezy.training")
                        logger.warning(
                            f"Prophet validation failed on eval slice: {guardrail_info}. "
                            f"Falling back to XGBoost."
                        )
                        # Fall back to XGBoost - continue to xgboost block
                        model_name = "xgboost"
                        if metadata is None:
                            metadata = {}
                        metadata["prophet_validation_failed"] = guardrail_info
                        metadata["fallback_reason"] = "prophet_validation_failed_negative_predictions"
                        # Don't return - continue to xgboost block
                    else:
                        # Prophet passed validation
                        return TrainResult(model_name="prophet", model=model, metadata=metadata)
                else:
                    # Couldn't get predictions, accept model
                    return TrainResult(model_name="prophet", model=model, metadata=metadata)
            else:
                # No eval_df, accept model
                return TrainResult(model_name="prophet", model=model, metadata=metadata)
        
        # If we get here and model_name is still "prophet", something went wrong
        if model_name == "prophet":
            return TrainResult(model_name="prophet", model=model, metadata=metadata)

        elif model_name == "xgboost":
            # Optimize hyperparameters if requested (with reduced settings in auto mode)
            if optimize_with_wape:
                # Use reduced settings for retraining (auto mode)
                n_splits = settings.cv_splits_retrain if optimize_hyperparameters == "auto" else 3
                max_iter = settings.xgb_opt_max_iter_retrain if optimize_hyperparameters == "auto" else 27
                
                opt_result = optimize_xgboost_hyperparameters(
                    ts=CleanedTimeSeries(product_id=ts.product_id, df=df, shelf_life_days=ts.shelf_life_days),
                    holidays_df=holidays_df,
                    weather_df=weather_df,
                    promotions_df=promotions_df,
                    events_df=events_df,
                    product_info=product_info,
                    n_splits=n_splits,
                    max_iter=max_iter,
                    use_wape_loss=True,  # Also use WAPE objective
                    should_cancel=should_cancel,  # Pass cancellation callback
                )
                # Use optimized hyperparameters
                config = XGBoostConfig(
                    max_depth=opt_result.best_params.get("max_depth", 3),
                    learning_rate=opt_result.best_params.get("learning_rate", 0.05),
                    n_estimators=opt_result.best_params.get("n_estimators", 200),
                    subsample=opt_result.best_params.get("subsample", 0.8),
                    use_wape_loss=True,  # Enable WAPE loss
                )
                model = XGBoostSalesModel(config=config)
            else:
                # Use stored hyperparameters if available, otherwise defaults
                if hyperparameters and "xgboost" in hyperparameters:
                    xgb_params = hyperparameters["xgboost"]
                    config = XGBoostConfig(
                        max_depth=xgb_params.get("max_depth", 3),
                        learning_rate=xgb_params.get("learning_rate", 0.05),
                        n_estimators=xgb_params.get("n_estimators", 200),
                        subsample=xgb_params.get("subsample", 0.8),
                        colsample_bytree=xgb_params.get("colsample_bytree", 0.8),
                        use_wape_loss=xgb_params.get("use_wape_loss", False),
                    )
                    model = XGBoostSalesModel(config=config)
                else:
                    # Use default configuration
                    model = XGBoostSalesModel()
            # Pass sample weights to XGBoost (Prophet doesn't support weights)
            try:
                model.fit(train_df_for_training, sample_weight=final_sample_weights)
                
                # XGBoost feature diagnostics
                if eval_df is not None and model.feature_cols is not None:
                    import logging
                    logger = logging.getLogger("bakezy.training")
                    eval_df_processed = eval_df.copy()
                    eval_df_processed["ds"] = pd.to_datetime(eval_df_processed["ds"])
                    eval_df_processed = self.feature_engineer.transform(
                        eval_df_processed,
                        holidays_df=holidays_df,
                        weather_df=weather_df,
                        promotions_df=promotions_df,
                        events_df=events_df,
                        product_info=product_info,
                    )
                    
                    # Log feature diagnostics
                    feature_stats = {}
                    critical_features = ["lag_1", "rolling_mean_7", "ewma_7"]
                    for col in model.feature_cols:
                        if col in eval_df_processed.columns:
                            try:
                                col_data = eval_df_processed[col]
                                nan_pct = col_data.isna().sum() / len(eval_df_processed) * 100 if len(eval_df_processed) > 0 else 0.0
                                
                                # Safe min/max/mean calculation - handle NaN values
                                col_numeric = pd.to_numeric(col_data, errors='coerce')
                                col_valid = col_numeric.dropna()
                                
                                min_val = float(col_valid.min()) if len(col_valid) > 0 else None
                                max_val = float(col_valid.max()) if len(col_valid) > 0 else None
                                mean_val = float(col_valid.mean()) if len(col_valid) > 0 else None
                                
                                feature_stats[col] = {
                                    "nan_pct": nan_pct,
                                    "min": min_val,
                                    "max": max_val,
                                    "mean": mean_val,
                                }
                            except Exception as e:
                                logger.warning(f"Error computing stats for feature {col}: {e}")
                                feature_stats[col] = {
                                    "nan_pct": 100.0,
                                    "min": None,
                                    "max": None,
                                    "mean": None,
                                }
                    
                    # Log critical features
                    for feat in critical_features:
                        if feat in feature_stats:
                            stats = feature_stats[feat]
                            # Safe formatting - handle None values
                            min_str = f"{stats['min']:.2f}" if stats['min'] is not None else "None"
                            max_str = f"{stats['max']:.2f}" if stats['max'] is not None else "None"
                            mean_str = f"{stats['mean']:.2f}" if stats['mean'] is not None else "None"
                            logger.info(
                                f"XGBoost feature {feat}: NaN%={stats['nan_pct']:.1f}%, "
                                f"min={min_str}, max={max_str}, mean={mean_str}"
                            )
                    
                    if metadata is None:
                        metadata = {}
                    metadata["xgboost_feature_stats"] = feature_stats
                
                # Validate on eval_df if available
                if eval_df is not None and "y" in eval_df.columns:
                    raw_yhat = self._get_raw_predictions(
                        model, "xgboost", eval_df, train_df_for_training,
                        holidays_df, weather_df, promotions_df, events_df, product_info
                    )
                    if len(raw_yhat) > 0:
                        should_fallback, guardrail_info = self._check_guardrail(
                            eval_df, raw_yhat, train_df_for_training["y"]
                        )
                        if should_fallback:
                            import logging
                            logger = logging.getLogger("bakezy.training")
                            logger.warning(
                                f"XGBoost validation failed on eval slice: {guardrail_info}. "
                                f"Falling back to seasonal naive."
                            )
                            # Fall back to seasonal naive
                            if metadata is None:
                                metadata = {}
                            metadata["xgboost_validation_failed"] = guardrail_info
                            metadata["fallback_reason"] = "xgboost_validation_failed_negative_predictions"
                            model = SeasonalNaiveModel()
                            model.fit(train_df_for_training)
                            return TrainResult(model_name="seasonal_naive", model=model, metadata=metadata)
                        else:
                            # XGBoost passed validation
                            return TrainResult(model_name="xgboost", model=model, metadata=metadata)
                    else:
                        # Couldn't get predictions, accept model
                        return TrainResult(model_name="xgboost", model=model, metadata=metadata)
                else:
                    # No eval_df, accept model
                    return TrainResult(model_name="xgboost", model=model, metadata=metadata)
            except Exception as e:
                # If XGBoost fails, fall back to seasonal naive
                import logging
                logger = logging.getLogger("bakezy.training")
                logger.warning(f"XGBoost training failed: {e}. Falling back to seasonal naive.")
                if metadata is None:
                    metadata = {}
                metadata["xgboost_failed"] = str(e)
                metadata["fallback_to"] = "seasonal_naive"
                model = SeasonalNaiveModel()
                model.fit(train_df_for_training)
                return TrainResult(model_name="seasonal_naive", model=model, metadata=metadata)

        elif model_name == "ensemble":
            # Train both Prophet and XGBoost models
            # Train Prophet
            if optimize_with_wape:
                # Use reduced settings for retraining (auto mode)
                n_splits = settings.cv_splits_retrain if optimize_hyperparameters == "auto" else 3
                max_iter = settings.prophet_opt_max_iter_retrain if optimize_hyperparameters == "auto" else None
                
                prophet_opt_result = optimize_prophet_hyperparameters(
                    ts=CleanedTimeSeries(product_id=ts.product_id, df=df, shelf_life_days=ts.shelf_life_days),
                    holidays_df=holidays_df,
                    weather_df=weather_df,
                    promotions_df=promotions_df,
                    events_df=events_df,
                    product_info=product_info,
                    n_splits=n_splits,
                    max_iter=max_iter,
                    should_cancel=should_cancel,
                )
                prophet_config = ProphetConfig(
                    changepoint_prior_scale=prophet_opt_result.best_params.get("changepoint_prior_scale", 0.05),
                    seasonality_mode=prophet_opt_result.best_params.get("seasonality_mode", "additive"),
                    daily_seasonality=True,
                    weekly_seasonality=True,
                    yearly_seasonality=False,
                )
                prophet_model = ProphetSalesModel(config=prophet_config)
            else:
                # Use stored hyperparameters if available
                if hyperparameters and "prophet" in hyperparameters:
                    prophet_params = hyperparameters["prophet"]
                    prophet_config = ProphetConfig(
                        changepoint_prior_scale=prophet_params.get("changepoint_prior_scale", 0.05),
                        seasonality_mode=prophet_params.get("seasonality_mode", "additive"),
                        daily_seasonality=prophet_params.get("daily_seasonality", True),
                        weekly_seasonality=prophet_params.get("weekly_seasonality", True),
                        yearly_seasonality=prophet_params.get("yearly_seasonality", False),
                    )
                    prophet_model = ProphetSalesModel(config=prophet_config)
                else:
                    prophet_model = ProphetSalesModel()
            prophet_model.fit(train_df_for_training)
            
            # Train XGBoost
            if optimize_with_wape:
                # Use reduced settings for retraining (auto mode)
                n_splits = settings.cv_splits_retrain if optimize_hyperparameters == "auto" else 3
                max_iter = settings.xgb_opt_max_iter_retrain if optimize_hyperparameters == "auto" else 27
                
                xgb_opt_result = optimize_xgboost_hyperparameters(
                    ts=CleanedTimeSeries(product_id=ts.product_id, df=df, shelf_life_days=ts.shelf_life_days),
                    holidays_df=holidays_df,
                    weather_df=weather_df,
                    promotions_df=promotions_df,
                    events_df=events_df,
                    product_info=product_info,
                    n_splits=n_splits,
                    max_iter=max_iter,
                    use_wape_loss=True,
                    should_cancel=should_cancel,  # Pass cancellation callback
                )
                xgb_config = XGBoostConfig(
                    max_depth=xgb_opt_result.best_params.get("max_depth", 3),
                    learning_rate=xgb_opt_result.best_params.get("learning_rate", 0.05),
                    n_estimators=xgb_opt_result.best_params.get("n_estimators", 200),
                    subsample=xgb_opt_result.best_params.get("subsample", 0.8),
                    use_wape_loss=True,
                )
                xgboost_model = XGBoostSalesModel(config=xgb_config)
            else:
                xgboost_model = XGBoostSalesModel()
            # Pass sample weights to XGBoost component (Prophet doesn't support weights)
            # Prophet component trains on all valid days without weights
            xgboost_model.fit(train_df_for_training, sample_weight=final_sample_weights)
            
            # Calculate optimal weights based on cross-validation performance if available
            # Use stored ensemble weights if available
            if hyperparameters and "ensemble" in hyperparameters:
                ensemble_params = hyperparameters["ensemble"]
                ensemble_config = EnsembleConfig(
                    strategy="weighted_average",
                    prophet_weight=ensemble_params.get("prophet_weight", 0.5),
                    xgboost_weight=ensemble_params.get("xgboost_weight", 0.5),
                )
            else:
                ensemble_config = EnsembleConfig(strategy="weighted_average")
            if optimize_with_wape:
                # Use WAPE from optimization to determine weights
                prophet_wape = prophet_opt_result.best_wape if hasattr(prophet_opt_result, 'best_wape') else float('inf')
                xgb_wape = xgb_opt_result.best_wape if hasattr(xgb_opt_result, 'best_wape') else float('inf')
                
                if prophet_wape != float('inf') and xgb_wape != float('inf'):
                    prophet_weight, xgb_weight = EnsembleForecaster.calculate_optimal_weights(
                        [prophet_wape],
                        [xgb_wape],
                    )
                    ensemble_config.prophet_weight = prophet_weight
                    ensemble_config.xgboost_weight = xgb_weight
            
            # Create ensemble model
            ensemble_model = EnsembleForecaster(
                prophet_model=prophet_model,
                xgboost_model=xgboost_model,
                config=ensemble_config,
            )
            
            # Validate on eval_df if available
            if eval_df is not None and "y" in eval_df.columns:
                raw_yhat = self._get_raw_predictions(
                    ensemble_model, "ensemble", eval_df, train_df_for_training,
                    holidays_df, weather_df, promotions_df, events_df, product_info
                )
                if len(raw_yhat) > 0:
                    should_fallback, guardrail_info = self._check_guardrail(
                        eval_df, raw_yhat, train_df_for_training["y"]
                    )
                    if should_fallback:
                        import logging
                        logger = logging.getLogger("bakezy.training")
                        logger.warning(
                            f"Ensemble validation failed on eval slice: {guardrail_info}. "
                            f"Falling back to XGBoost."
                        )
                        # Fall back to XGBoost
                        if metadata is None:
                            metadata = {}
                        metadata["ensemble_validation_failed"] = guardrail_info
                        metadata["fallback_reason"] = "ensemble_validation_failed_negative_predictions"
                        # Try XGBoost-only
                        return self.train(
                            ts=CleanedTimeSeries(product_id=ts.product_id, df=df, shelf_life_days=ts.shelf_life_days),
                            model_name="xgboost",
                            holidays_df=holidays_df,
                            weather_df=weather_df,
                            promotions_df=promotions_df,
                            events_df=events_df,
                            product_info=product_info,
                            optimize_with_wape=False,  # Fast fallback
                            sample_weights=final_sample_weights,
                        )
                    else:
                        # Ensemble passed validation
                        return TrainResult(model_name="ensemble", model=ensemble_model, metadata=metadata)
                else:
                    # Couldn't get predictions, accept model
                    return TrainResult(model_name="ensemble", model=ensemble_model, metadata=metadata)
            else:
                # No eval_df, accept model
                return TrainResult(model_name="ensemble", model=ensemble_model, metadata=metadata)

        else:
            raise ValueError(f"Unsupported model: {model_name}")
