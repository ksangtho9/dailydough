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
    changepoint_prior_scale: float = 0.05
    # Custom seasonalities
    monthly_seasonality: bool = False
    quarterly_seasonality: bool = False


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
        Can contain additional regressor columns that will be automatically added.
        """
        m = Prophet(
            daily_seasonality=self.config.daily_seasonality,
            weekly_seasonality=self.config.weekly_seasonality,
            yearly_seasonality=self.config.yearly_seasonality,
            seasonality_mode=self.config.seasonality_mode,
            changepoint_prior_scale=self.config.changepoint_prior_scale,
        )

        # Add custom seasonalities
        if self.config.monthly_seasonality:
            m.add_seasonality(name="monthly", period=30.5, fourier_order=5)
        if self.config.quarterly_seasonality:
            m.add_seasonality(name="quarterly", period=91.25, fourier_order=5)

        # Track which regressors we've added
        self.regressors = []

        # Add delivery as additional regressor if present
        if "delivery" in df.columns:
            delivery_series = df["delivery"]
            if delivery_series.notna().any() and (delivery_series != 0).any():
                m.add_regressor("delivery")
                self.regressors.append("delivery")
                self.has_delivery_regressor = True
            else:
                self.has_delivery_regressor = False
        else:
            self.has_delivery_regressor = False

        # Add lag features as regressors
        lag_features = ["lag_1", "lag_7", "lag_14", "lag_30"]
        for feature in lag_features:
            if feature in df.columns:
                series = df[feature]
                if series.notna().any():
                    m.add_regressor(feature)
                    self.regressors.append(feature)

        # Add rolling statistics as regressors
        rolling_features = ["rolling_mean_7", "rolling_mean_30", "rolling_std_7", "rolling_std_30"]
        for feature in rolling_features:
            if feature in df.columns:
                series = df[feature]
                if series.notna().any():
                    m.add_regressor(feature)
                    self.regressors.append(feature)

        # Add calendar features as regressors (numeric ones)
        calendar_features = [
            "month", "quarter", "day_of_month", "is_month_start", "is_month_end",
            "days_until_weekend", "days_since_weekend", "is_payday"
        ]
        for feature in calendar_features:
            if feature in df.columns:
                m.add_regressor(feature)
                self.regressors.append(feature)

        # Add holiday/event features
        holiday_features = ["is_holiday", "days_before_holiday", "days_after_holiday", "holiday_proximity"]
        for feature in holiday_features:
            if feature in df.columns:
                m.add_regressor(feature)
                self.regressors.append(feature)

        # Add weather features
        weather_features = ["temperature", "precipitation", "is_rainy", "is_sunny"]
        for feature in weather_features:
            if feature in df.columns:
                series = df[feature]
                if series.notna().any():
                    m.add_regressor(feature)
                    self.regressors.append(feature)

        # Add promotion/event features
        promo_features = ["is_promotion", "promotion_multiplier", "is_event", "event_multiplier"]
        for feature in promo_features:
            if feature in df.columns:
                m.add_regressor(feature)
                self.regressors.append(feature)

        # Add spike-related features
        spike_features = [
            "is_spike",  # Historical spike flag
            "spike_probability",  # Predicted spike probability
            "spike_severity",  # Historical spike severity
            "days_since_last_spike",
            "spike_momentum",
            "spike_seasonality",
        ]
        for feature in spike_features:
            if feature in df.columns:
                series = df[feature]
                if series.notna().any():
                    m.add_regressor(feature)
                    self.regressors.append(feature)

        # Add product features (if they vary, though typically they're constant)
        product_features = ["shelf_life_days", "price", "cost_price_ratio"]
        for feature in product_features:
            if feature in df.columns:
                series = df[feature]
                if series.notna().any() and series.nunique() > 1:  # Only add if it varies
                    m.add_regressor(feature)
                    self.regressors.append(feature)

        m.fit(df)
        self.model = m

    def predict(
        self,
        horizon_days: int,
        historical_delivery: Optional[pd.Series] = None,
        future_regressors: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """
        Returns a DataFrame with columns including:
        - ds
        - yhat
        - yhat_lower
        - yhat_upper
        
        Args:
            horizon_days: Number of days to forecast
            historical_delivery: Historical delivery data for future estimation
            future_regressors: DataFrame with future regressor values (columns: ds, and regressor names)
        """
        if self.model is None:
            raise RuntimeError("Model is not fitted yet.")

        future = self.model.make_future_dataframe(periods=horizon_days, freq="D")

        # Add regressor values for future dates
        regressors = getattr(self, "regressors", [])

        if future_regressors is not None and not future_regressors.empty:
            # Merge provided future regressor values
            future_regressors = future_regressors.copy()
            future_regressors["ds"] = pd.to_datetime(future_regressors["ds"])
            future = future.merge(future_regressors, on="ds", how="left")

        # Add default values for any missing regressors (whether future_regressors was provided or not)
        for regressor in regressors:
            if regressor not in future.columns:
                if regressor == "delivery" and historical_delivery is not None and len(historical_delivery) > 0:
                    # Use historical average for delivery
                    avg_delivery = historical_delivery.mean()
                    future[regressor] = avg_delivery
                elif regressor.startswith("lag_"):
                    # For lag features, we can't predict future values easily
                    # Use the last known value or mean
                    future[regressor] = 0.0  # Will be filled by preprocessing
                elif regressor.startswith("rolling_"):
                    # Rolling features need historical context
                    future[regressor] = 0.0  # Will be filled by preprocessing
                elif regressor in ["is_holiday", "is_promotion", "is_event", "is_rainy", "is_sunny",
                                   "is_month_start", "is_month_end", "is_payday", "is_spike"]:
                    # Binary flags default to 0
                    future[regressor] = 0
                elif regressor in ["promotion_multiplier", "event_multiplier"]:
                    # Multipliers default to 1.0
                    future[regressor] = 1.0
                elif regressor in ["spike_probability", "spike_severity", "spike_seasonality"]:
                    # Spike probabilities default to 0.0
                    future[regressor] = 0.0
                elif regressor in ["days_since_last_spike", "spike_momentum"]:
                    # Spike timing features default to 0 or large value
                    if regressor == "days_since_last_spike":
                        future[regressor] = 999.0  # Large value if no previous spike
                    else:
                        future[regressor] = 0.0
                else:
                    # For other numeric regressors, use 0 or mean
                    future[regressor] = 0.0

        # Fill any remaining NaN values (for regressors that were merged but have NaN values)
        for regressor in regressors:
            if regressor in future.columns:
                future[regressor] = future[regressor].fillna(0.0)

        forecast = self.model.predict(future)
        return forecast
