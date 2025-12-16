from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

import numpy as np
import pandas as pd

from .prophet_model import ProphetSalesModel
from .xgboost_model import XGBoostSalesModel
from ..features import FeatureEngineer


@dataclass
class EnsembleConfig:
    """Configuration for ensemble forecasting."""
    strategy: Literal["simple_average", "weighted_average", "stacking"] = "weighted_average"
    prophet_weight: float = 0.5  # Weight for Prophet (used in weighted_average)
    xgboost_weight: float = 0.5  # Weight for XGBoost (used in weighted_average)
    # For stacking: use Prophet as base, XGBoost to correct residuals
    use_stacking: bool = False


class EnsembleForecaster:
    """
    Combines Prophet and XGBoost models for improved forecasting accuracy.
    
    Supports multiple ensemble strategies:
    - simple_average: Equal weights for both models
    - weighted_average: Configurable weights based on historical performance
    - stacking: Use one model to correct the other
    """
    
    def __init__(
        self,
        prophet_model: ProphetSalesModel,
        xgboost_model: XGBoostSalesModel,
        config: Optional[EnsembleConfig] = None,
    ):
        self.prophet_model = prophet_model
        self.xgboost_model = xgboost_model
        self.config = config or EnsembleConfig()
        self.feature_engineer = FeatureEngineer()
    
    def predict(
        self,
        historical_df: pd.DataFrame,
        future_df: pd.DataFrame,
        horizon_days: int,
        holidays_df: Optional[pd.DataFrame] = None,
        weather_df: Optional[pd.DataFrame] = None,
        promotions_df: Optional[pd.DataFrame] = None,
        events_df: Optional[pd.DataFrame] = None,
        product_info: Optional[dict] = None,
        future_regressors: Optional[pd.DataFrame] = None,
        historical_delivery: Optional[pd.Series] = None,
    ) -> pd.DataFrame:
        """
        Generate ensemble forecast combining Prophet and XGBoost predictions.
        
        Args:
            historical_df: Historical data with features
            future_df: Future dates DataFrame
            horizon_days: Number of days to forecast
            holidays_df: Optional holidays DataFrame
            weather_df: Optional weather DataFrame
            promotions_df: Optional promotions DataFrame
            events_df: Optional events DataFrame
            product_info: Optional product metadata
            future_regressors: Optional future regressor values
            historical_delivery: Optional historical delivery data
            
        Returns:
            DataFrame with columns: ds, yhat, yhat_lower, yhat_upper
        """
        # Get Prophet prediction
        prophet_forecast = self.prophet_model.predict(
            horizon_days=horizon_days,
            historical_delivery=historical_delivery,
            future_regressors=future_regressors,
        )
        
        # Get XGBoost prediction
        xgboost_forecast = self.xgboost_model.predict_future(
            historical_df=historical_df,
            future_df=future_df,
            feature_engineer=self.feature_engineer,
            holidays_df=holidays_df,
            weather_df=weather_df,
            promotions_df=promotions_df,
            events_df=events_df,
            product_info=product_info,
        )
        
        # Ensure both forecasts have the same dates
        if prophet_forecast.empty or xgboost_forecast.empty:
            # Fallback to whichever has data
            return prophet_forecast if not prophet_forecast.empty else xgboost_forecast
        
        # Merge on date
        prophet_forecast["ds"] = pd.to_datetime(prophet_forecast["ds"])
        xgboost_forecast["ds"] = pd.to_datetime(xgboost_forecast["ds"])
        
        merged = prophet_forecast[["ds", "yhat", "yhat_lower", "yhat_upper"]].merge(
            xgboost_forecast[["ds", "yhat"]].rename(columns={"yhat": "yhat_xgb"}),
            on="ds",
            how="inner",
        )
        
        if merged.empty:
            return prophet_forecast  # Fallback
        
        # Apply ensemble strategy
        if self.config.strategy == "simple_average":
            merged["yhat"] = (merged["yhat"] + merged["yhat_xgb"]) / 2.0
            
        elif self.config.strategy == "weighted_average":
            # Normalize weights
            total_weight = self.config.prophet_weight + self.config.xgboost_weight
            prophet_w = self.config.prophet_weight / total_weight
            xgboost_w = self.config.xgboost_weight / total_weight
            merged["yhat"] = prophet_w * merged["yhat"] + xgboost_w * merged["yhat_xgb"]
            
        elif self.config.strategy == "stacking":
            # Use Prophet as base, XGBoost to correct
            # Calculate residual from historical data if available
            # For now, use a simple weighted combination favoring Prophet
            merged["yhat"] = 0.7 * merged["yhat"] + 0.3 * merged["yhat_xgb"]
        else:
            # Default to simple average
            merged["yhat"] = (merged["yhat"] + merged["yhat_xgb"]) / 2.0
        
        # Update confidence intervals (use wider intervals for ensemble)
        prophet_range = merged["yhat_upper"] - merged["yhat_lower"]
        merged["yhat_lower"] = np.maximum(0.0, merged["yhat"] - 0.5 * prophet_range)
        merged["yhat_upper"] = merged["yhat"] + 0.5 * prophet_range
        
        # Return only required columns
        result = merged[["ds", "yhat", "yhat_lower", "yhat_upper"]].copy()
        return result
    
    @classmethod
    def calculate_optimal_weights(
        cls,
        prophet_errors: list[float],
        xgboost_errors: list[float],
    ) -> tuple[float, float]:
        """
        Calculate optimal weights based on historical errors.
        
        Args:
            prophet_errors: List of Prophet prediction errors (e.g., WAPE)
            xgboost_errors: List of XGBoost prediction errors
            
        Returns:
            Tuple of (prophet_weight, xgboost_weight)
        """
        if not prophet_errors or not xgboost_errors:
            return 0.5, 0.5
        
        # Inverse error weighting: lower error gets higher weight
        prophet_avg_error = np.mean(prophet_errors)
        xgboost_avg_error = np.mean(xgboost_errors)
        
        # Avoid division by zero
        if prophet_avg_error == 0 and xgboost_avg_error == 0:
            return 0.5, 0.5
        if prophet_avg_error == 0:
            return 1.0, 0.0
        if xgboost_avg_error == 0:
            return 0.0, 1.0
        
        # Inverse weighting
        prophet_weight = 1.0 / prophet_avg_error
        xgboost_weight = 1.0 / xgboost_avg_error
        
        # Normalize
        total = prophet_weight + xgboost_weight
        return prophet_weight / total, xgboost_weight / total


