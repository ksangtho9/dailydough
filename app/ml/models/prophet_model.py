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
        self.has_delivery_regressor: bool = False

    def fit(self, df: pd.DataFrame) -> None:
        """
        df must contain columns: 'ds' (datetime), 'y' (numeric quantity).
        Optionally can contain 'delivery' column which will be used as an additional regressor.
        """
        m = Prophet(
            daily_seasonality=self.config.daily_seasonality,
            weekly_seasonality=self.config.weekly_seasonality,
            yearly_seasonality=self.config.yearly_seasonality,
            seasonality_mode=self.config.seasonality_mode,
        )
        
        # Add delivery as additional regressor if present
        if "delivery" in df.columns:
            # Check if delivery has meaningful data (not all zeros/NaN)
            delivery_series = df["delivery"]
            if delivery_series.notna().any() and (delivery_series != 0).any():
                m.add_regressor("delivery")
                self.has_delivery_regressor = True
            else:
                self.has_delivery_regressor = False
        else:
            self.has_delivery_regressor = False
        
        m.fit(df)
        self.model = m

    def predict(self, horizon_days: int, historical_delivery: Optional[pd.Series] = None) -> pd.DataFrame:
        """
        Returns a DataFrame with columns including:
        - ds
        - yhat
        - yhat_lower
        - yhat_upper
        
        If the model was trained with delivery regressor, historical_delivery should be provided
        to estimate future delivery values. If not provided, uses historical average.
        """
        if self.model is None:
            raise RuntimeError("Model is not fitted yet.")

        future = self.model.make_future_dataframe(periods=horizon_days, freq="D")
        
        # If model uses delivery regressor, we need to provide delivery values for future dates
        if getattr(self, "has_delivery_regressor", False):
            if historical_delivery is not None and len(historical_delivery) > 0:
                # Use historical average for future delivery values
                # This is a simple approach; can be refined later with trend/seasonality
                avg_delivery = historical_delivery.mean()
                future["delivery"] = avg_delivery
            else:
                # Fallback: use 0 if no historical data
                future["delivery"] = 0.0
        
        forecast = self.model.predict(future)
        return forecast
