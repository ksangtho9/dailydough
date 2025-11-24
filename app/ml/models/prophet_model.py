from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

try:
    from prophet import Prophet
except ImportError:  # pragma: no cover
    Prophet = None  # type: ignore

from .base_model import BaseForecastModel


@dataclass
class ProphetConfig:
    """Hyperparameters for Prophet."""
    daily_seasonality: bool = True
    weekly_seasonality: bool = True
    yearly_seasonality: bool = False
    seasonality_mode: str = "additive"  # or "multiplicative"


class ProphetForecastModel(BaseForecastModel):
    """
    Thin wrapper around Facebook/Meta Prophet for product-level forecasts.
    Implements BaseForecastModel interface.
    """

    def __init__(self, config: Optional[ProphetConfig] = None):
        if Prophet is None:
            raise ImportError(
                "prophet is not installed. "
                "Install with `pip install prophet`."
            )
        self.config = config or ProphetConfig()
        self.model: Optional[Prophet] = None

    def fit(self, df: pd.DataFrame) -> None:
        """
        df must contain columns: 'ds' (datetime), 'y' (numeric quantity).
        """
        m = Prophet(
            daily_seasonality=self.config.daily_seasonality,
            weekly_seasonality=self.config.weekly_seasonality,
            yearly_seasonality=self.config.yearly_seasonality,
            seasonality_mode=self.config.seasonality_mode,
        )
        m.fit(df)
        self.model = m

    def predict(self, future_df: pd.DataFrame = None, horizon_days: int = None) -> pd.DataFrame:
        """
        Returns a DataFrame with columns including:
        - ds
        - yhat
        - yhat_lower
        - yhat_upper
        
        Args:
            future_df: DataFrame with 'ds' column for future dates (preferred).
            horizon_days: Number of days to forecast (for backward compatibility).
                         Only used if future_df is not provided.
        """
        if self.model is None:
            raise RuntimeError("Model is not fitted yet.")

        # Support both new interface (future_df) and old interface (horizon_days)
        if future_df is not None and not future_df.empty:
            forecast = self.model.predict(future_df)
        elif horizon_days is not None:
            # Backward compatibility: create future dataframe
            future = self.make_future_dataframe(periods=horizon_days, freq="D")
            forecast = self.model.predict(future)
        else:
            raise ValueError("Either future_df or horizon_days must be provided")
        
        return forecast
    
    def make_future_dataframe(self, periods: int, freq: str = "D") -> pd.DataFrame:
        """
        Helper method to create future dataframe for Prophet.
        This is Prophet-specific and not part of the base interface.
        """
        if self.model is None:
            raise RuntimeError("Model is not fitted yet.")
        return self.model.make_future_dataframe(periods=periods, freq=freq)
    
    def predict_with_horizon(self, horizon_days: int) -> pd.DataFrame:
        """
        Convenience method that combines make_future_dataframe and predict.
        This maintains backward compatibility with existing code.
        """
        if self.model is None:
            raise RuntimeError("Model is not fitted yet.")
        
        future = self.make_future_dataframe(periods=horizon_days, freq="D")
        return self.predict(future)


# Backward compatibility alias
ProphetModel = ProphetForecastModel
