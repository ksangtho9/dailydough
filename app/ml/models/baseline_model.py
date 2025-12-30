from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import logging

import numpy as np
import pandas as pd

from app.core.config import settings

logger = logging.getLogger("bakezy.baseline")


@dataclass
class BaselineConfig:
    """Configuration for baseline models."""
    window_size: int = 7  # For rolling mean: number of days to average


class SeasonalNaiveModel:
    """
    Seasonal naive baseline: uses last week's same weekday value.
    """
    
    def __init__(self):
        self.weekday_means: Optional[dict] = None
    
    def fit(self, df: pd.DataFrame) -> None:
        """
        Fit the model by computing mean sales per weekday.
        
        Args:
            df: DataFrame with columns 'ds' (datetime) and 'y' (numeric)
        """
        df = df.copy()
        df["ds"] = pd.to_datetime(df["ds"])
        df["weekday"] = df["ds"].dt.dayofweek  # 0=Monday, 6=Sunday
        
        # Compute mean per weekday
        weekday_means = df.groupby("weekday")["y"].mean().to_dict()
        
        # Fill missing weekdays with overall mean
        overall_mean = df["y"].mean() if len(df) > 0 else 0.0
        self.weekday_means = {i: weekday_means.get(i, overall_mean) for i in range(7)}
    
    def predict(self, horizon_days: int, last_date: Optional[pd.Timestamp] = None, product_id: Optional[int] = None) -> pd.DataFrame:
        """
        Predict using seasonal naive (last week's same weekday).
        
        Args:
            horizon_days: Number of days to forecast
            last_date: Last date in training data (if None, uses today)
            product_id: For gated diagnostic logging
        
        Returns:
            DataFrame with columns 'ds' and 'yhat'
        """
        if self.weekday_means is None:
            raise ValueError("Model must be fitted before prediction")
        
        if last_date is None:
            last_date = pd.Timestamp.today()
        else:
            last_date = pd.Timestamp(last_date)
        
        # Generate future dates
        future_dates = pd.date_range(start=last_date + pd.Timedelta(days=1), periods=horizon_days, freq="D")
        
        # Predict using weekday means
        predictions = []
        for date in future_dates:
            weekday = date.dayofweek
            yhat = self.weekday_means[weekday]
            predictions.append(yhat)
        
        # Step 5: Log baseline selection (gated)
        should_log = settings.debug_zero_forecasts or (product_id is not None)  # TODO: Check flagged set
        if should_log:
            logger.info(
                f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                f"step=baseline_checks, Baseline selected: seasonal_naive"
            )
        
        return pd.DataFrame({
            "ds": future_dates,
            "yhat": predictions,
            "yhat_lower": predictions,  # No uncertainty for baseline
            "yhat_upper": predictions,
        })


class RollingMeanModel:
    """
    Rolling mean baseline: uses average of last N days.
    """
    
    def __init__(self, config: Optional[BaselineConfig] = None):
        self.config = config or BaselineConfig()
        self.mean_value: Optional[float] = None
    
    def fit(self, df: pd.DataFrame) -> None:
        """
        Fit the model by computing rolling mean.
        
        Args:
            df: DataFrame with columns 'ds' (datetime) and 'y' (numeric)
        """
        df = df.copy()
        df["ds"] = pd.to_datetime(df["ds"])
        df = df.sort_values("ds")
        
        # Use last window_size days, or all if fewer
        window = min(self.config.window_size, len(df))
        if window > 0:
            self.mean_value = df["y"].tail(window).mean()
        else:
            self.mean_value = 0.0
    
    def predict(self, horizon_days: int, last_date: Optional[pd.Timestamp] = None, product_id: Optional[int] = None) -> pd.DataFrame:
        """
        Predict using rolling mean.
        
        Args:
            horizon_days: Number of days to forecast
            last_date: Last date in training data (if None, uses today)
            product_id: For gated diagnostic logging
        
        Returns:
            DataFrame with columns 'ds' and 'yhat'
        """
        if self.mean_value is None:
            raise ValueError("Model must be fitted before prediction")
        
        if last_date is None:
            last_date = pd.Timestamp.today()
        else:
            last_date = pd.Timestamp(last_date)
        
        # Generate future dates
        future_dates = pd.date_range(start=last_date + pd.Timedelta(days=1), periods=horizon_days, freq="D")
        
        # Predict using mean value
        predictions = [self.mean_value] * horizon_days
        
        # Step 5: Log baseline selection (gated)
        should_log = settings.debug_zero_forecasts or (product_id is not None)  # TODO: Check flagged set
        if should_log:
            logger.info(
                f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                f"step=baseline_checks, Baseline selected: rolling_mean, mean_value={self.mean_value:.2f}"
            )
        
        return pd.DataFrame({
            "ds": future_dates,
            "yhat": predictions,
            "yhat_lower": predictions,  # No uncertainty for baseline
            "yhat_upper": predictions,
        })

