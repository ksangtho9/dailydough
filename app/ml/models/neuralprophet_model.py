from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

try:
    from neuralprophet import NeuralProphet
except ImportError:
    NeuralProphet = None

from .base_model import BaseForecastModel


@dataclass
class NeuralProphetConfig:
    """Hyperparameters for NeuralProphet."""
    yearly_seasonality: bool = False
    weekly_seasonality: bool = True
    daily_seasonality: bool = True
    n_lags: int = 0
    n_forecasts: int = 1


class NeuralProphetForecastModel(BaseForecastModel):
    """
    NeuralProphet-based forecasting model.
    """

    def __init__(self, config: Optional[NeuralProphetConfig] = None):
        if NeuralProphet is None:
            raise ImportError(
                "neuralprophet is not installed. "
                "Install with `pip install neuralprophet`."
            )
        self.config = config or NeuralProphetConfig()
        self.model: Optional[NeuralProphet] = None

    def fit(self, df: pd.DataFrame) -> None:
        """
        Train NeuralProphet model.
        
        Args:
            df: DataFrame with 'ds' and 'y' columns
        """
        self.model = NeuralProphet(
            yearly_seasonality=self.config.yearly_seasonality,
            weekly_seasonality=self.config.weekly_seasonality,
            daily_seasonality=self.config.daily_seasonality,
            n_lags=self.config.n_lags,
            n_forecasts=self.config.n_forecasts,
        )
        self.model.fit(df)

    def predict(self, future_df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate predictions for future dates.
        
        Args:
            future_df: DataFrame with 'ds' column
        
        Returns:
            DataFrame with predictions
        """
        if self.model is None:
            raise RuntimeError("Model is not fitted yet.")
        
        forecast = self.model.predict(future_df)
        return forecast


# Backward compatibility alias
NeuralProphetModel = NeuralProphetForecastModel

