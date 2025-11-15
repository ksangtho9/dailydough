from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
import pandas as pd

try:
    from xgboost import XGBRegressor
except ImportError:  # pragma: no cover
    XGBRegressor = None  # type: ignore


@dataclass
class XGBoostConfig:
    """Hyperparameters for XGBoost-based forecaster."""
    max_depth: int = 3
    n_estimators: int = 200
    learning_rate: float = 0.05
    subsample: float = 0.8
    colsample_bytree: float = 0.8


class XGBoostSalesModel:
    """
    Feature-based model for time series (uses lag/features, not auto time index).
    """

    def __init__(self, config: Optional[XGBoostConfig] = None):
        if XGBRegressor is None:
            raise ImportError(
                "xgboost is not installed. "
                "Install with `pip install xgboost`."
            )
        self.config = config or XGBoostConfig()
        self.model: Optional[XGBRegressor] = None
        self.feature_cols: Optional[list[str]] = None

    def _split_features_target(self, df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        if "y" not in df.columns:
            raise ValueError("DataFrame must contain 'y' column as target.")

        self.feature_cols = [c for c in df.columns if c not in ["y", "ds"]]
        X = df[self.feature_cols].values
        y = df["y"].values
        return X, y

    def fit(self, df: pd.DataFrame) -> None:
        """
        df should contain:
        - y (target)
        - (optional) feature columns (lag features, calendar, etc.)
        """
        X, y = self._split_features_target(df)
        model = XGBRegressor(
            max_depth=self.config.max_depth,
            n_estimators=self.config.n_estimators,
            learning_rate=self.config.learning_rate,
            subsample=self.config.subsample,
            colsample_bytree=self.config.colsample_bytree,
            objective="reg:squarederror",
        )
        model.fit(X, y)
        self.model = model

    def predict(self, df_future: pd.DataFrame) -> np.ndarray:
        """
        Predict on future feature matrix with same feature columns.
        """
        if self.model is None or self.feature_cols is None:
            raise RuntimeError("Model is not fitted yet.")

        X_future = df_future[self.feature_cols].values
        preds = self.model.predict(X_future)
        return preds
