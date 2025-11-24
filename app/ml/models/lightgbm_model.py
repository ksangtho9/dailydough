from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd
import numpy as np

try:
    import lightgbm as lgb
except ImportError:
    lgb = None

from .base_model import BaseForecastModel


@dataclass
class LightGBMConfig:
    """Hyperparameters for LightGBM."""
    num_leaves: int = 31
    learning_rate: float = 0.05
    n_estimators: int = 200
    max_depth: int = -1
    min_child_samples: int = 20


class LightGBMForecastModel(BaseForecastModel):
    """
    LightGBM-based forecasting model.
    Requires feature engineering (lags, rolling features, etc.)
    """

    def __init__(self, config: Optional[LightGBMConfig] = None):
        if lgb is None:
            raise ImportError(
                "lightgbm is not installed. "
                "Install with `pip install lightgbm`."
            )
        self.config = config or LightGBMConfig()
        self.model: Optional[lgb.LGBMRegressor] = None
        self.feature_cols: Optional[list[str]] = None

    def fit(self, df: pd.DataFrame) -> None:
        """
        Train LightGBM model.
        
        Args:
            df: DataFrame with 'ds', 'y', and feature columns
        """
        if "y" not in df.columns:
            raise ValueError("DataFrame must contain 'y' column as target.")
        
        # Identify feature columns (exclude ds and y)
        self.feature_cols = [c for c in df.columns if c not in ["y", "ds"]]
        
        if not self.feature_cols:
            raise ValueError("No feature columns found. Add features before training.")
        
        X = df[self.feature_cols].values
        y = df["y"].values
        
        self.model = lgb.LGBMRegressor(
            num_leaves=self.config.num_leaves,
            learning_rate=self.config.learning_rate,
            n_estimators=self.config.n_estimators,
            max_depth=self.config.max_depth,
            min_child_samples=self.config.min_child_samples,
            objective="regression",
            metric="rmse",
        )
        self.model.fit(X, y)

    def predict(self, future_df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate predictions for future dates.
        
        Args:
            future_df: DataFrame with 'ds' and same feature columns as training
        
        Returns:
            DataFrame with 'ds' and 'yhat' columns
        """
        if self.model is None or self.feature_cols is None:
            raise RuntimeError("Model is not fitted yet.")
        
        # Check that all feature columns are present
        missing_cols = set(self.feature_cols) - set(future_df.columns)
        if missing_cols:
            raise ValueError(f"Missing feature columns: {missing_cols}")
        
        X_future = future_df[self.feature_cols].values
        yhat = self.model.predict(X_future)
        
        result = future_df[["ds"]].copy()
        result["yhat"] = yhat
        result["yhat_lower"] = yhat  # TODO: implement prediction intervals
        result["yhat_upper"] = yhat  # TODO: implement prediction intervals
        
        return result


# Backward compatibility alias
LightGBMModel = LightGBMForecastModel

