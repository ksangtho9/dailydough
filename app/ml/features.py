from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd
import numpy as np


@dataclass
class FeatureConfig:
    """
    Controls which features we add.
    """
    include_day_of_week: bool = True
    include_is_weekend: bool = True
    include_lag_features: bool = True
    include_calendar_features: bool = True
    include_product_features: bool = True
    include_holidays: bool = True
    include_weather: bool = True
    include_promotions: bool = True
    include_events: bool = True


class FeatureEngineer:
    def __init__(self, config: Optional[FeatureConfig] = None):
        self.config = config or FeatureConfig()

    def add_lag_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Adds lag features and rolling statistics.

        Assumes df has column "y" (target) and "ds" (datetime).
        """
        df = df.copy()
        df = df.sort_values("ds").reset_index(drop=True)

        if "y" not in df.columns:
            return df

        # Lag features
        if self.config.include_lag_features:
            df["lag_1"] = df["y"].shift(1)
            df["lag_7"] = df["y"].shift(7)
            df["lag_14"] = df["y"].shift(14)
            df["lag_30"] = df["y"].shift(30)

            # Rolling averages
            df["rolling_mean_7"] = df["y"].rolling(window=7, min_periods=1).mean()
            df["rolling_mean_30"] = df["y"].rolling(window=30, min_periods=1).mean()

            # Rolling standard deviations
            df["rolling_std_7"] = df["y"].rolling(window=7, min_periods=1).std().fillna(0)
            df["rolling_std_30"] = df["y"].rolling(window=30, min_periods=1).std().fillna(0)

            # Fill NaN values for early rows
            df["lag_1"] = df["lag_1"].fillna(df["y"].mean() if not df["y"].empty else 0)
            df["lag_7"] = df["lag_7"].fillna(df["y"].mean() if not df["y"].empty else 0)
            df["lag_14"] = df["lag_14"].fillna(df["y"].mean() if not df["y"].empty else 0)
            df["lag_30"] = df["lag_30"].fillna(df["y"].mean() if not df["y"].empty else 0)

        return df

    def add_calendar_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Adds expanded calendar-based features.

        Assumes df has column "ds" (datetime-like).
        """
        df = df.copy()

        if not self.config.include_calendar_features:
            if self.config.include_day_of_week:
                df["day_of_week"] = df["ds"].dt.dayofweek
            if self.config.include_is_weekend:
                df["is_weekend"] = df["ds"].dt.dayofweek.isin([5, 6]).astype(int)
            return df

        # Basic day of week
        if self.config.include_day_of_week:
            df["day_of_week"] = df["ds"].dt.dayofweek  # 0=Mon, 6=Sun

        if self.config.include_is_weekend:
            df["is_weekend"] = df["ds"].dt.dayofweek.isin([5, 6]).astype(int)

        # Month and quarter
        df["month"] = df["ds"].dt.month
        df["quarter"] = df["ds"].dt.quarter
        df["day_of_month"] = df["ds"].dt.day

        # Month start/end
        df["is_month_start"] = df["ds"].dt.is_month_start.astype(int)
        df["is_month_end"] = df["ds"].dt.is_month_end.astype(int)

        # Days until/since weekend
        df["days_until_weekend"] = (5 - df["ds"].dt.dayofweek).clip(lower=0)
        df["days_since_weekend"] = (df["ds"].dt.dayofweek).clip(upper=2)

        # Payday indicators (1st and 15th of month)
        df["is_payday"] = df["ds"].dt.day.isin([1, 15]).astype(int)

        return df

    def add_holiday_features(self, df: pd.DataFrame, holidays_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        """
        Adds holiday and event features.

        Args:
            df: DataFrame with "ds" column
            holidays_df: Optional DataFrame with columns ["ds", "is_holiday", "holiday_name", "days_before", "days_after"]
        """
        df = df.copy()

        if not self.config.include_holidays:
            return df

        # Initialize holiday columns
        df["is_holiday"] = 0
        df["days_before_holiday"] = 0
        df["days_after_holiday"] = 0
        df["holiday_proximity"] = 0.0

        if holidays_df is not None and not holidays_df.empty:
            # Merge holiday information
            holidays_df = holidays_df.copy()
            holidays_df["ds"] = pd.to_datetime(holidays_df["ds"])

            # Mark holiday days
            df = df.merge(
                holidays_df[["ds", "is_holiday"]].rename(columns={"is_holiday": "holiday_flag"}),
                on="ds",
                how="left",
            )
            df["is_holiday"] = df["holiday_flag"].fillna(0).astype(int)
            df = df.drop(columns=["holiday_flag"], errors="ignore")

            # Calculate proximity to holidays
            holiday_dates = pd.to_datetime(holidays_df[holidays_df["is_holiday"] == 1]["ds"].unique())
            if len(holiday_dates) > 0:
                df["ds_datetime"] = pd.to_datetime(df["ds"])
                for holiday_date in holiday_dates:
                    days_diff = (df["ds_datetime"] - holiday_date).dt.days
                    # Days before holiday (negative values)
                    before_mask = (days_diff < 0) & (days_diff >= -7)
                    df.loc[before_mask, "days_before_holiday"] = -days_diff[before_mask]
                    # Days after holiday (positive values)
                    after_mask = (days_diff > 0) & (days_diff <= 7)
                    df.loc[after_mask, "days_after_holiday"] = days_diff[after_mask]
                    # Proximity score (closer = higher)
                    proximity = 1.0 / (1.0 + np.abs(days_diff))
                    df["holiday_proximity"] = np.maximum(df["holiday_proximity"], proximity)
                df = df.drop(columns=["ds_datetime"], errors="ignore")

        return df

    def add_weather_features(self, df: pd.DataFrame, weather_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        """
        Adds weather features.

        Args:
            df: DataFrame with "ds" column
            weather_df: Optional DataFrame with columns ["ds", "temperature", "precipitation", "condition"]
        """
        df = df.copy()

        if not self.config.include_weather:
            return df

        # Initialize weather columns
        df["temperature"] = np.nan
        df["precipitation"] = 0.0
        df["is_rainy"] = 0
        df["is_sunny"] = 0

        if weather_df is not None and not weather_df.empty:
            weather_df = weather_df.copy()
            weather_df["ds"] = pd.to_datetime(weather_df["ds"])

            # Merge weather data
            df = df.merge(
                weather_df[["ds", "temperature", "precipitation", "condition"]],
                on="ds",
                how="left",
            )

            # Fill missing values with forward/backward fill
            df["temperature"] = df["temperature"].ffill().bfill()
            df["precipitation"] = df["precipitation"].fillna(0.0)

            # Weather condition flags
            if "condition" in df.columns:
                df["is_rainy"] = df["condition"].str.lower().str.contains("rain", na=False).astype(int)
                df["is_sunny"] = df["condition"].str.lower().str.contains("sun", na=False).astype(int)
            else:
                # Use precipitation as proxy
                df["is_rainy"] = (df["precipitation"] > 0).astype(int)
                df["is_sunny"] = (df["precipitation"] == 0).astype(int)

        return df

    def add_promotion_features(self, df: pd.DataFrame, promotions_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        """
        Adds promotion features.

        Args:
            df: DataFrame with "ds" and optionally "product_id" columns
            promotions_df: Optional DataFrame with columns ["ds", "product_id", "is_promotion", "sales_multiplier"]
        """
        df = df.copy()

        if not self.config.include_promotions:
            return df

        # Initialize promotion columns
        df["is_promotion"] = 0
        df["promotion_multiplier"] = 1.0

        if promotions_df is not None and not promotions_df.empty:
            promotions_df = promotions_df.copy()
            promotions_df["ds"] = pd.to_datetime(promotions_df["ds"])

            # Merge promotion data
            merge_cols = ["ds"]
            if "product_id" in df.columns and "product_id" in promotions_df.columns:
                merge_cols.append("product_id")

            df = df.merge(
                promotions_df[merge_cols + ["is_promotion", "sales_multiplier"]],
                on=merge_cols,
                how="left",
            )

            df["is_promotion"] = df["is_promotion"].fillna(0).astype(int)
            df["promotion_multiplier"] = df["sales_multiplier"].fillna(1.0)

        return df

    def add_event_features(self, df: pd.DataFrame, events_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        """
        Adds event features.

        Args:
            df: DataFrame with "ds" column
            events_df: Optional DataFrame with columns ["ds", "is_event", "event_multiplier"]
        """
        df = df.copy()

        if not self.config.include_events:
            return df

        # Initialize event columns
        df["is_event"] = 0
        df["event_multiplier"] = 1.0

        if events_df is not None and not events_df.empty:
            events_df = events_df.copy()
            events_df["ds"] = pd.to_datetime(events_df["ds"])

            # Merge event data
            df = df.merge(
                events_df[["ds", "is_event", "sales_multiplier"]].rename(columns={"sales_multiplier": "event_mult"}),
                on="ds",
                how="left",
            )

            df["is_event"] = df["is_event"].fillna(0).astype(int)
            df["event_multiplier"] = df["event_mult"].fillna(1.0)
            df = df.drop(columns=["event_mult"], errors="ignore")

        return df

    def add_product_features(self, df: pd.DataFrame, product_info: Optional[dict] = None) -> pd.DataFrame:
        """
        Adds product-level features.

        Args:
            df: DataFrame (product features are constant across dates)
            product_info: Optional dict with keys: category, shelf_life_days, price, cost_per_unit
        """
        df = df.copy()

        if not self.config.include_product_features or product_info is None:
            return df

        # Product category (one-hot encoding would be done separately if needed)
        if "category" in product_info:
            df["product_category"] = product_info["category"]

        # Shelf life
        if "shelf_life_days" in product_info:
            df["shelf_life_days"] = product_info["shelf_life_days"]

        # Price tier (normalized)
        if "price" in product_info and product_info["price"] is not None:
            df["price"] = product_info["price"]
            # Could normalize by product category average if needed

        # Cost-to-price ratio
        if "price" in product_info and "cost_per_unit" in product_info:
            price = product_info.get("price")
            cost = product_info.get("cost_per_unit")
            if price is not None and cost is not None and price > 0:
                df["cost_price_ratio"] = cost / price
            else:
                df["cost_price_ratio"] = 0.0

        return df

    def add_spike_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Adds spike-related features based on historical spike patterns.
        
        Args:
            df: DataFrame with "ds" column and optionally "is_spike" column
        """
        df = df.copy()
        df = df.sort_values("ds").reset_index(drop=True)
        
        # Initialize spike features
        df["spike_probability"] = 0.0
        df["days_since_last_spike"] = np.nan
        df["spike_momentum"] = 0.0
        df["spike_seasonality"] = 0.0
        
        # If is_spike column exists, calculate features from historical data
        if "is_spike" in df.columns:
            spike_mask = df["is_spike"] == 1
            
            # Days since last spike
            spike_indices = df[spike_mask].index
            if len(spike_indices) > 0:
                for idx in df.index:
                    # Find the most recent spike before this index
                    previous_spikes = spike_indices[spike_indices < idx]
                    if len(previous_spikes) > 0:
                        df.loc[idx, "days_since_last_spike"] = idx - previous_spikes[-1]
                    else:
                        df.loc[idx, "days_since_last_spike"] = np.nan
            
            # Spike momentum (rolling count of recent spikes in last 30 days)
            if len(spike_indices) > 0:
                for idx in df.index:
                    window_start = max(0, idx - 30)
                    recent_spikes = spike_mask[window_start:idx+1].sum()
                    df.loc[idx, "spike_momentum"] = recent_spikes
            
            # Spike seasonality (day-of-week and month patterns)
            if len(spike_indices) > 0:
                spike_dates = df.loc[spike_indices, "ds"]
                
                # Day of week pattern
                spike_dow = spike_dates.dt.dayofweek.value_counts(normalize=True)
                df["spike_dow_prob"] = df["ds"].dt.dayofweek.map(spike_dow).fillna(0.0)
                
                # Month pattern
                spike_month = spike_dates.dt.month.value_counts(normalize=True)
                df["spike_month_prob"] = df["ds"].dt.month.map(spike_month).fillna(0.0)
                
                # Combined seasonality score
                df["spike_seasonality"] = (df["spike_dow_prob"] + df["spike_month_prob"]) / 2.0
                
                # Overall spike probability (based on historical frequency)
                historical_spike_rate = spike_mask.sum() / len(df) if len(df) > 0 else 0.0
                df["spike_probability"] = historical_spike_rate * df["spike_seasonality"]
            else:
                df["spike_probability"] = 0.0
                df["spike_seasonality"] = 0.0
        else:
            # No historical spike data - set defaults
            df["spike_probability"] = 0.0
            df["days_since_last_spike"] = np.nan
            df["spike_momentum"] = 0.0
            df["spike_seasonality"] = 0.0
        
        # Fill NaN values
        df["days_since_last_spike"] = df["days_since_last_spike"].fillna(999.0)  # Large value if no previous spike
        
        return df

    def transform(
        self,
        df: pd.DataFrame,
        holidays_df: Optional[pd.DataFrame] = None,
        weather_df: Optional[pd.DataFrame] = None,
        promotions_df: Optional[pd.DataFrame] = None,
        events_df: Optional[pd.DataFrame] = None,
        product_info: Optional[dict] = None,
    ) -> pd.DataFrame:
        """Main feature pipeline entrypoint."""
        df_out = df.copy()

        # Add lag features (needs to be done early, before other features)
        df_out = self.add_lag_features(df_out)

        # Add calendar features
        df_out = self.add_calendar_features(df_out)

        # Add external regressors
        df_out = self.add_holiday_features(df_out, holidays_df)
        df_out = self.add_weather_features(df_out, weather_df)
        df_out = self.add_promotion_features(df_out, promotions_df)
        df_out = self.add_event_features(df_out, events_df)

        # Add product features
        df_out = self.add_product_features(df_out, product_info)
        
        # Add spike features (after other features so it can use calendar features)
        df_out = self.add_spike_features(df_out)

        return df_out
