from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

try:
    from statsmodels.tsa.arima.model import ARIMA
except ImportError:
    ARIMA = None

from .base_model import BaseForecastModel


@dataclass
class SARIMAConfig:
    """Hyperparameters for SARIMA model."""
    order: tuple[int, int, int] = (1, 1, 1)  # (p, d, q)
    seasonal_order: tuple[int, int, int, int] = (1, 1, 1, 7)  # (P, D, Q, s)


class SARIMAForecastModel(BaseForecastModel):
    """
    SARIMA (Seasonal ARIMA) model.
    """

    def __init__(self, config: Optional[SARIMAConfig] = None):
        if ARIMA is None:
            raise ImportError(
                "statsmodels is not installed. "
                "Install with `pip install statsmodels`."
            )
        self.config = config or SARIMAConfig()
        self.model: Optional[ARIMA] = None

    def fit(self, df: pd.DataFrame) -> None:
        """
        Train SARIMA model.
        
        Args:
            df: DataFrame with 'ds' and 'y' columns
        """
        # Ensure ds is datetime and set as index
        df = df.copy()
        if not pd.api.types.is_datetime64_any_dtype(df["ds"]):
            df["ds"] = pd.to_datetime(df["ds"])
        
        df = df.set_index("ds").sort_index()
        
        self.model = ARIMA(
            df["y"],
            order=self.config.order,
            seasonal_order=self.config.seasonal_order,
        )
        self.model = self.model.fit()

    def predict(self, future_df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate predictions for future dates.
        
        Args:
            future_df: DataFrame with 'ds' column
        
        Returns:
            DataFrame with 'ds' and 'yhat' columns
        """
        if self.model is None:
            raise RuntimeError("Model is not fitted yet.")
        
        # Ensure ds is datetime
        if not pd.api.types.is_datetime64_any_dtype(future_df["ds"]):
            future_df["ds"] = pd.to_datetime(future_df["ds"])
        
        n_periods = len(future_df)
        forecast = self.model.forecast(steps=n_periods)
        conf_int = self.model.get_forecast(steps=n_periods).conf_int()
        
        result = future_df[["ds"]].copy()
        result["yhat"] = forecast.values
        result["yhat_lower"] = conf_int.iloc[:, 0].values
        result["yhat_upper"] = conf_int.iloc[:, 1].values
        
        return result


# Backward compatibility alias
SARIMAModel = SARIMAForecastModel

