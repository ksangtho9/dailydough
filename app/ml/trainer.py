from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

import numpy as np
import pandas as pd

from .preprocessing import CleanedTimeSeries
from .features import FeatureEngineer
from .models.prophet_model import ProphetSalesModel, ProphetConfig
from .models.xgboost_model import XGBoostSalesModel, XGBoostConfig
from .models.ensemble_model import EnsembleForecaster, EnsembleConfig
from .hyperparameter_optimization import (
    optimize_prophet_hyperparameters,
    optimize_xgboost_hyperparameters,
)


ModelName = Literal["prophet", "xgboost", "ensemble"]


@dataclass
class TrainResult:
    model_name: ModelName
    # In MLOps v2, you might store metrics here (MAE, MAPE, etc.)
    # For now this is a simple placeholder.
    model: object


class ModelTrainer:
    def __init__(self, feature_engineer: Optional[FeatureEngineer] = None):
        self.feature_engineer = feature_engineer or FeatureEngineer()

    def train(
        self,
        ts: CleanedTimeSeries,
        model_name: ModelName = "prophet",
        holidays_df: Optional[pd.DataFrame] = None,
        weather_df: Optional[pd.DataFrame] = None,
        promotions_df: Optional[pd.DataFrame] = None,
        events_df: Optional[pd.DataFrame] = None,
        product_info: Optional[dict] = None,
        optimize_with_wape: bool = True,
        sample_weights: Optional[np.ndarray] = None,
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

        # Compute sample weights AFTER feature engineering and filtering to ensure alignment
        # Normal day (is_supply_capped_day == 0): weight = 1.0
        # Supply-capped day (is_supply_capped_day == 1): weight = 0.3 (configurable)
        computed_sample_weights = None
        if sample_weights is None and "is_supply_capped_day" in train_df.columns:
            # Compute weights from train_df to ensure perfect alignment
            computed_sample_weights = np.where(
                train_df["is_supply_capped_day"] == 1,
                0.3,  # Supply-capped days get reduced weight
                1.0   # Normal days get full weight
            )
            capped_count = int((train_df["is_supply_capped_day"] == 1).sum())
            total_valid = len(train_df)
            if total_valid > 0:
                import logging
                logger = logging.getLogger("bakezy.training")
                logger.info(
                    f"Sample weights computed - {capped_count}/{total_valid} supply-capped days "
                    f"(weight=0.3), {total_valid - capped_count} normal days (weight=1.0)"
                )
        elif sample_weights is not None:
            # Use provided weights (for backward compatibility, but warn if length mismatch)
            if len(sample_weights) != len(train_df):
                import logging
                logger = logging.getLogger("bakezy.training")
                logger.warning(
                    f"Sample weights length ({len(sample_weights)}) doesn't match training data length ({len(train_df)}). "
                    f"Computing weights from train_df instead."
                )
                if "is_supply_capped_day" in train_df.columns:
                    computed_sample_weights = np.where(
                        train_df["is_supply_capped_day"] == 1,
                        0.3,
                        1.0
                    )
                else:
                    computed_sample_weights = None
            else:
                computed_sample_weights = sample_weights
        
        # Use computed weights
        final_sample_weights = computed_sample_weights
        
        # Index-based validation: Ensure weights align with training data by index, not just length
        # This catches subtle bugs where row count matches but ordering differs
        if final_sample_weights is not None:
            import logging
            logger = logging.getLogger("bakezy.training")
            
            # Convert to Series aligned to train_df.index for index-based validation
            weight_series = pd.Series(final_sample_weights, index=train_df.index)
            
            # Validate index alignment (same set + same order)
            if not weight_series.index.equals(train_df.index):
                logger.error(
                    f"CRITICAL: Weight index doesn't match train_df index. "
                    f"Weight index: {list(weight_series.index[:5])}..., "
                    f"train_df index: {list(train_df.index[:5])}... "
                    f"Setting weights to None to prevent model corruption."
                )
                final_sample_weights = None
            elif len(final_sample_weights) != len(train_df):
                # Fallback length check (shouldn't happen if index matches, but double-check)
                logger.error(
                    f"CRITICAL: Sample weights length ({len(final_sample_weights)}) doesn't match training data length ({len(train_df)}). "
                    f"Setting weights to None to prevent model corruption."
                )
                final_sample_weights = None
            else:
                # Index matches, convert back to array for XGBoost
                final_sample_weights = weight_series.values
        
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

        if model_name == "prophet":
            # Optimize hyperparameters if requested
            if optimize_with_wape:
                opt_result = optimize_prophet_hyperparameters(
                    ts=CleanedTimeSeries(product_id=ts.product_id, df=df, shelf_life_days=ts.shelf_life_days),
                    holidays_df=holidays_df,
                    weather_df=weather_df,
                    promotions_df=promotions_df,
                    events_df=events_df,
                    product_info=product_info,
                    n_splits=3,
                    max_iter=None,  # Try all combinations
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
                # Use default configuration
                model = ProphetSalesModel()
            model.fit(train_df)
            return TrainResult(model_name="prophet", model=model)

        elif model_name == "xgboost":
            # Optimize hyperparameters if requested
            if optimize_with_wape:
                opt_result = optimize_xgboost_hyperparameters(
                    ts=CleanedTimeSeries(product_id=ts.product_id, df=df, shelf_life_days=ts.shelf_life_days),
                    holidays_df=holidays_df,
                    weather_df=weather_df,
                    promotions_df=promotions_df,
                    events_df=events_df,
                    product_info=product_info,
                    n_splits=3,
                    max_iter=27,  # Limit combinations for speed
                    use_wape_loss=True,  # Also use WAPE objective
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
                # Use default configuration
                model = XGBoostSalesModel()
            # Pass sample weights to XGBoost (Prophet doesn't support weights)
            model.fit(train_df, sample_weight=final_sample_weights)
            return TrainResult(model_name="xgboost", model=model)

        elif model_name == "ensemble":
            # Train both Prophet and XGBoost models
            # Train Prophet
            if optimize_with_wape:
                prophet_opt_result = optimize_prophet_hyperparameters(
                    ts=CleanedTimeSeries(product_id=ts.product_id, df=df, shelf_life_days=ts.shelf_life_days),
                    holidays_df=holidays_df,
                    weather_df=weather_df,
                    promotions_df=promotions_df,
                    events_df=events_df,
                    product_info=product_info,
                    n_splits=3,
                    max_iter=None,
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
                prophet_model = ProphetSalesModel()
            prophet_model.fit(train_df)
            
            # Train XGBoost
            if optimize_with_wape:
                xgb_opt_result = optimize_xgboost_hyperparameters(
                    ts=CleanedTimeSeries(product_id=ts.product_id, df=df, shelf_life_days=ts.shelf_life_days),
                    holidays_df=holidays_df,
                    weather_df=weather_df,
                    promotions_df=promotions_df,
                    events_df=events_df,
                    product_info=product_info,
                    n_splits=3,
                    max_iter=27,
                    use_wape_loss=True,
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
            xgboost_model.fit(train_df, sample_weight=final_sample_weights)
            
            # Calculate optimal weights based on cross-validation performance if available
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
            return TrainResult(model_name="ensemble", model=ensemble_model)

        else:
            raise ValueError(f"Unsupported model: {model_name}")
