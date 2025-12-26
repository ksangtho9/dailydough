from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

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
            model.fit(train_df)
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
            xgboost_model.fit(train_df)
            
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
