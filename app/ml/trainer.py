from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

import pandas as pd

from .preprocessing import CleanedTimeSeries
from .features import FeatureEngineer
from .models.prophet_model import ProphetSalesModel, ProphetConfig
from .models.xgboost_model import XGBoostSalesModel, XGBoostConfig
from .hyperparameter_optimization import (
    optimize_prophet_hyperparameters,
    optimize_xgboost_hyperparameters,
)


ModelName = Literal["prophet", "xgboost"]


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

        # Feature engineering
        df["ds"] = pd.to_datetime(df["ds"])
        df = self.feature_engineer.transform(
            df,
            holidays_df=holidays_df,
            weather_df=weather_df,
            promotions_df=promotions_df,
            events_df=events_df,
            product_info=product_info,
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
            model.fit(df)
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
            model.fit(df)
            return TrainResult(model_name="xgboost", model=model)

        else:
            raise ValueError(f"Unsupported model: {model_name}")
