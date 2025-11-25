from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

try:
    from prophet import Prophet
except ImportError:  # pragma: no cover
    Prophet = None  # type: ignore


@dataclass
class ProphetConfig:
    """Hyperparameters for Prophet."""
    daily_seasonality: bool = True
    weekly_seasonality: bool = True
    yearly_seasonality: bool = False
    seasonality_mode: str = "additive"  # or "multiplicative"


class ProphetSalesModel:
    """
    Thin wrapper around Facebook/Meta Prophet for product-level forecasts.
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

    def predict(self, horizon_days: int) -> pd.DataFrame:
        """
        Returns a DataFrame with columns including:
        - ds
        - yhat
        - yhat_lower
        - yhat_upper
        """
        if self.model is None:
            raise RuntimeError("Model is not fitted yet.")

        future = self.model.make_future_dataframe(periods=horizon_days, freq="D")
        forecast = self.model.predict(future)
        return forecast
