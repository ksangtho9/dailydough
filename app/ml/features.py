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
        Adds lag features and rolling statistics using previous N valid observations.
        
        Uses "previous N valid observations" approach (not calendar-based).
        Invalid days (is_valid_day == 0) are excluded from lag computation.

        Assumes df has column "y" (target), "ds" (datetime), and optionally "is_valid_day".
        """
        df = df.copy()
        df = df.sort_values("ds").reset_index(drop=True)

        if "y" not in df.columns:
            return df

        # Lag features
        if self.config.include_lag_features:
            # Check if is_valid_day column exists
            has_valid_day = "is_valid_day" in df.columns
            
            if has_valid_day:
                # Compute lags using "previous N valid observations" approach
                lag_windows = [1, 2, 3, 7, 14, 21, 30]  # lag_60 deferred
                
                # Initialize all lag columns
                for lag_n in lag_windows:
                    df[f"lag_{lag_n}"] = np.nan
                
                # Build a list of valid indices and their y values for efficient lookup
                valid_indices = []
                valid_y_values = []
                for i in range(len(df)):
                    if df.loc[i, "is_valid_day"] == 1 and pd.notna(df.loc[i, "y"]):
                        valid_indices.append(i)
                        valid_y_values.append(df.loc[i, "y"])
                
                # For each row, find the previous N valid observations
                for i in range(len(df)):
                    if df.loc[i, "is_valid_day"] == 1:
                        # Find position of current index in valid_indices list
                        try:
                            current_pos = valid_indices.index(i)
                        except ValueError:
                            # Current row not in valid list (shouldn't happen, but handle gracefully)
                            continue
                        
                        # For each lag window, get the value from N positions back
                        for lag_n in lag_windows:
                            lag_col = f"lag_{lag_n}"
                            if current_pos >= lag_n:
                                # We have enough history
                                prev_valid_idx = valid_indices[current_pos - lag_n]
                                df.loc[i, lag_col] = valid_y_values[current_pos - lag_n]
                
                # Compute rolling statistics on valid days only
                # Filter to valid days, compute rolling stats, then map back
                valid_mask = df["is_valid_day"] == 1
                if valid_mask.any():
                    valid_indices = df[valid_mask].index.tolist()
                    valid_y = df.loc[valid_mask, "y"].values
                    
                    # Compute rolling stats on valid series
                    valid_rolling_mean_7 = pd.Series(valid_y).rolling(window=7, min_periods=1).mean().values
                    valid_rolling_mean_30 = pd.Series(valid_y).rolling(window=30, min_periods=1).mean().values
                    valid_rolling_std_7 = pd.Series(valid_y).rolling(window=7, min_periods=1).std().fillna(0).values
                    valid_rolling_std_30 = pd.Series(valid_y).rolling(window=30, min_periods=1).std().fillna(0).values
                    
                    # Map back to original dataframe
                    df["rolling_mean_7"] = np.nan
                    df["rolling_mean_30"] = np.nan
                    df["rolling_std_7"] = np.nan
                    df["rolling_std_30"] = np.nan
                    
                    for idx, orig_idx in enumerate(valid_indices):
                        df.loc[orig_idx, "rolling_mean_7"] = valid_rolling_mean_7[idx]
                        df.loc[orig_idx, "rolling_mean_30"] = valid_rolling_mean_30[idx]
                        df.loc[orig_idx, "rolling_std_7"] = valid_rolling_std_7[idx]
                        df.loc[orig_idx, "rolling_std_30"] = valid_rolling_std_30[idx]
                else:
                    # No valid days - set all to NaN
                    df["rolling_mean_7"] = np.nan
                    df["rolling_mean_30"] = np.nan
                    df["rolling_std_7"] = np.nan
                    df["rolling_std_30"] = np.nan
            else:
                # No is_valid_day column - use calendar-based lags (backward compatibility)
                df["lag_1"] = df["y"].shift(1)
                df["lag_2"] = df["y"].shift(2)
                df["lag_3"] = df["y"].shift(3)
                df["lag_7"] = df["y"].shift(7)
                df["lag_14"] = df["y"].shift(14)
                df["lag_21"] = df["y"].shift(21)
                df["lag_30"] = df["y"].shift(30)
                
                # Rolling averages
                df["rolling_mean_7"] = df["y"].rolling(window=7, min_periods=1).mean()
                df["rolling_mean_30"] = df["y"].rolling(window=30, min_periods=1).mean()
                
                # Rolling standard deviations
                df["rolling_std_7"] = df["y"].rolling(window=7, min_periods=1).std().fillna(0)
                df["rolling_std_30"] = df["y"].rolling(window=30, min_periods=1).std().fillna(0)

        return df

    def add_ewma_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Adds Exponential Weighted Moving Average (EWMA) features.
        Computes on valid days only (treat invalid days as missing/NaN in series).
        """
        df = df.copy()
        df = df.sort_values("ds").reset_index(drop=True)

        if "y" not in df.columns:
            return df

        has_valid_day = "is_valid_day" in df.columns

        if has_valid_day and (df["is_valid_day"] == 1).any():
            # Filter to valid days for EWMA computation
            valid_mask = df["is_valid_day"] == 1
            valid_indices = df[valid_mask].index.tolist()
            valid_y = df.loc[valid_mask, "y"].values
            
            if len(valid_y) > 0:
                # Compute EWMA with different halflives
                # ewma_7_halflife_3: 7-day EWMA with 3-day halflife
                # ewma_14_halflife_7: 14-day EWMA with 7-day halflife
                # ewma_30_halflife_14: 30-day EWMA with 14-day halflife
                valid_series = pd.Series(valid_y)
                
                # Halflife = 3 days for 7-day EWMA
                ewma_7 = valid_series.ewm(halflife=3, min_periods=1).mean().values
                # Halflife = 7 days for 14-day EWMA
                ewma_14 = valid_series.ewm(halflife=7, min_periods=1).mean().values
                # Halflife = 14 days for 30-day EWMA
                ewma_30 = valid_series.ewm(halflife=14, min_periods=1).mean().values
                
                # Map back to original dataframe
                df["ewma_7_halflife_3"] = np.nan
                df["ewma_14_halflife_7"] = np.nan
                df["ewma_30_halflife_14"] = np.nan
                
                for idx, orig_idx in enumerate(valid_indices):
                    df.loc[orig_idx, "ewma_7_halflife_3"] = ewma_7[idx]
                    df.loc[orig_idx, "ewma_14_halflife_7"] = ewma_14[idx]
                    df.loc[orig_idx, "ewma_30_halflife_14"] = ewma_30[idx]
            else:
                df["ewma_7_halflife_3"] = np.nan
                df["ewma_14_halflife_7"] = np.nan
                df["ewma_30_halflife_14"] = np.nan
        else:
            # No is_valid_day or no valid days - compute on all data
            df["ewma_7_halflife_3"] = df["y"].ewm(halflife=3, min_periods=1).mean()
            df["ewma_14_halflife_7"] = df["y"].ewm(halflife=7, min_periods=1).mean()
            df["ewma_30_halflife_14"] = df["y"].ewm(halflife=14, min_periods=1).mean()

        return df

    def add_lagged_rolling_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Adds lagged rolling statistics.
        rolling_mean_7_lag_1: 7-day mean from 1 valid observation ago
        rolling_mean_7_lag_7: 7-day mean from 7 valid observations ago
        rolling_mean_30_lag_7: 30-day mean from 7 valid observations ago
        """
        df = df.copy()
        df = df.sort_values("ds").reset_index(drop=True)

        if "rolling_mean_7" not in df.columns or "rolling_mean_30" not in df.columns:
            return df

        has_valid_day = "is_valid_day" in df.columns

        if has_valid_day:
            # Use previous N valid observations approach
            df["rolling_mean_7_lag_1"] = np.nan
            df["rolling_mean_7_lag_7"] = np.nan
            df["rolling_mean_30_lag_7"] = np.nan

            # Build valid indices list for efficient lookup
            valid_indices = []
            for i in range(len(df)):
                if df.loc[i, "is_valid_day"] == 1:
                    valid_indices.append(i)

            for i in range(len(df)):
                if df.loc[i, "is_valid_day"] == 1:
                    try:
                        current_pos = valid_indices.index(i)
                        
                        # Find previous 1 valid observation for rolling_mean_7_lag_1
                        if current_pos >= 1:
                            prev_idx = valid_indices[current_pos - 1]
                            if pd.notna(df.loc[prev_idx, "rolling_mean_7"]):
                                df.loc[i, "rolling_mean_7_lag_1"] = df.loc[prev_idx, "rolling_mean_7"]
                        
                        # Find previous 7 valid observations for rolling_mean_7_lag_7 and rolling_mean_30_lag_7
                        if current_pos >= 7:
                            prev_idx = valid_indices[current_pos - 7]
                            if pd.notna(df.loc[prev_idx, "rolling_mean_7"]):
                                df.loc[i, "rolling_mean_7_lag_7"] = df.loc[prev_idx, "rolling_mean_7"]
                            if pd.notna(df.loc[prev_idx, "rolling_mean_30"]):
                                df.loc[i, "rolling_mean_30_lag_7"] = df.loc[prev_idx, "rolling_mean_30"]
                    except ValueError:
                        continue
        else:
            # No is_valid_day - use calendar-based shifts
            df["rolling_mean_7_lag_1"] = df["rolling_mean_7"].shift(1)
            df["rolling_mean_7_lag_7"] = df["rolling_mean_7"].shift(7)
            df["rolling_mean_30_lag_7"] = df["rolling_mean_30"].shift(7)

        return df

    def update_lag_features_for_future(
        self,
        historical_df: pd.DataFrame,
        future_df: pd.DataFrame,
        predictions: pd.Series,
    ) -> pd.DataFrame:
        """
        Updates lag features for future dates using predictions.
        
        Args:
            historical_df: Historical data with lag features
            future_df: Future dates DataFrame (may have partial features)
            predictions: Series of predictions for future dates (aligned with future_df)
            
        Returns:
            DataFrame with updated lag features
        """
        if not self.config.include_lag_features:
            return future_df
            
        future_df = future_df.copy()
        combined_df = pd.concat([historical_df, future_df], ignore_index=True).sort_values("ds").reset_index(drop=True)
        
        # Update y column with predictions for future dates
        if "y" not in combined_df.columns:
            combined_df["y"] = 0.0
        combined_df.loc[historical_df.index.max() + 1:, "y"] = predictions.values
        
        # Recalculate lag features
        combined_df["lag_1"] = combined_df["y"].shift(1)
        combined_df["lag_7"] = combined_df["y"].shift(7)
        combined_df["lag_14"] = combined_df["y"].shift(14)
        combined_df["lag_30"] = combined_df["y"].shift(30)
        
        # Recalculate rolling statistics
        combined_df["rolling_mean_7"] = combined_df["y"].rolling(window=7, min_periods=1).mean()
        combined_df["rolling_mean_30"] = combined_df["y"].rolling(window=30, min_periods=1).mean()
        combined_df["rolling_std_7"] = combined_df["y"].rolling(window=7, min_periods=1).std().fillna(0)
        combined_df["rolling_std_30"] = combined_df["y"].rolling(window=30, min_periods=1).std().fillna(0)
        
        # Extract only future rows
        future_start_idx = len(historical_df)
        future_with_lags = combined_df.iloc[future_start_idx:].copy()
        
        # Update future_df with lag features
        for col in ["lag_1", "lag_7", "lag_14", "lag_30", "rolling_mean_7", "rolling_mean_30", "rolling_std_7", "rolling_std_30"]:
            if col in future_with_lags.columns:
                future_df[col] = future_with_lags[col].values
        
        return future_df

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

        # Cyclical encoding for day_of_week and month (replace raw values)
        if self.config.include_day_of_week:
            day_of_week_raw = df["ds"].dt.dayofweek  # 0=Mon, 6=Sun
            # Cyclical encoding: sin and cos
            df["day_of_week_sin"] = np.sin(2 * np.pi * day_of_week_raw / 7)
            df["day_of_week_cos"] = np.cos(2 * np.pi * day_of_week_raw / 7)
            # Keep raw for backward compatibility during transition, but will drop later

        if self.config.include_is_weekend:
            df["is_weekend"] = df["ds"].dt.dayofweek.isin([5, 6]).astype(int)

        # Month and quarter - use cyclical encoding for month
        month_raw = df["ds"].dt.month
        df["month_sin"] = np.sin(2 * np.pi * month_raw / 12)
        df["month_cos"] = np.cos(2 * np.pi * month_raw / 12)
        # Keep raw month for backward compatibility during transition
        df["month"] = month_raw
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

        # Additional seasonal features for better seasonality capture
        df["week_of_year"] = df["ds"].dt.isocalendar().week
        df["day_of_year"] = df["ds"].dt.dayofyear
        
        # Seasonal indicators (spring, summer, fall, winter)
        month = df["ds"].dt.month
        df["is_spring"] = ((month >= 3) & (month <= 5)).astype(int)
        df["is_summer"] = ((month >= 6) & (month <= 8)).astype(int)
        df["is_fall"] = ((month >= 9) & (month <= 11)).astype(int)
        df["is_winter"] = ((month == 12) | (month <= 2)).astype(int)

        return df

    def add_trend_momentum_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Adds trend and momentum features.
        trend_slope_7: Linear trend over last 7 valid days
        trend_slope_30: Linear trend over last 30 valid days
        momentum_7d: rolling_mean_7 - rolling_mean_30
        sales_change_1d: lag_1 - lag_2
        sales_change_7d: lag_1 - lag_8 (using valid observations)
        """
        df = df.copy()
        df = df.sort_values("ds").reset_index(drop=True)

        # Return early if y column doesn't exist
        if "y" not in df.columns:
            df["trend_slope_7"] = np.nan
            df["trend_slope_30"] = np.nan
            df["momentum_7d"] = np.nan
            df["sales_change_1d"] = np.nan
            df["sales_change_7d"] = np.nan
            return df

        has_valid_day = "is_valid_day" in df.columns

        # Trend slopes - compute on valid days only
        if has_valid_day and (df["is_valid_day"] == 1).any():
            df["trend_slope_7"] = np.nan
            df["trend_slope_30"] = np.nan

            for i in range(len(df)):
                if df.loc[i, "is_valid_day"] == 1:
                    # Get last 7 valid observations for trend_slope_7
                    valid_y_7 = []
                    valid_indices_7 = []
                    for j in range(i, -1, -1):
                        if df.loc[j, "is_valid_day"] == 1 and pd.notna(df.loc[j, "y"]):
                            valid_y_7.insert(0, df.loc[j, "y"])
                            valid_indices_7.insert(0, j)
                            if len(valid_y_7) >= 7:
                                break
                    
                    if len(valid_y_7) >= 2:
                        # Compute linear trend (slope)
                        x = np.arange(len(valid_y_7))
                        slope = np.polyfit(x, valid_y_7, 1)[0]
                        df.loc[i, "trend_slope_7"] = slope
                    
                    # Get last 30 valid observations for trend_slope_30
                    valid_y_30 = []
                    for j in range(i, -1, -1):
                        if df.loc[j, "is_valid_day"] == 1 and pd.notna(df.loc[j, "y"]):
                            valid_y_30.insert(0, df.loc[j, "y"])
                            if len(valid_y_30) >= 30:
                                break
                    
                    if len(valid_y_30) >= 2:
                        x = np.arange(len(valid_y_30))
                        slope = np.polyfit(x, valid_y_30, 1)[0]
                        df.loc[i, "trend_slope_30"] = slope
        else:
            # No is_valid_day - compute on all data
            df["trend_slope_7"] = np.nan
            df["trend_slope_30"] = np.nan
            for i in range(len(df)):
                if i >= 1:
                    y_window_7 = df.loc[max(0, i-6):i+1, "y"].values
                    if len(y_window_7) >= 2 and pd.notna(y_window_7).all():
                        x = np.arange(len(y_window_7))
                        slope = np.polyfit(x, y_window_7, 1)[0]
                        df.loc[i, "trend_slope_7"] = slope
                
                if i >= 1:
                    y_window_30 = df.loc[max(0, i-29):i+1, "y"].values
                    if len(y_window_30) >= 2 and pd.notna(y_window_30).all():
                        x = np.arange(len(y_window_30))
                        slope = np.polyfit(x, y_window_30, 1)[0]
                        df.loc[i, "trend_slope_30"] = slope

        # Momentum and change features
        if "rolling_mean_7" in df.columns and "rolling_mean_30" in df.columns:
            df["momentum_7d"] = df["rolling_mean_7"] - df["rolling_mean_30"]
        else:
            df["momentum_7d"] = np.nan

        if "lag_1" in df.columns and "lag_2" in df.columns:
            df["sales_change_1d"] = df["lag_1"] - df["lag_2"]
        else:
            df["sales_change_1d"] = np.nan

        # sales_change_7d: lag_1 - value from 8 valid observations ago
        if has_valid_day and "lag_1" in df.columns:
            df["sales_change_7d"] = np.nan
            # Build valid indices list for efficient lookup
            valid_indices = []
            valid_y_values = []
            for i in range(len(df)):
                if df.loc[i, "is_valid_day"] == 1 and pd.notna(df.loc[i, "y"]):
                    valid_indices.append(i)
                    valid_y_values.append(df.loc[i, "y"])
            
            for i in range(len(df)):
                if df.loc[i, "is_valid_day"] == 1 and pd.notna(df.loc[i, "lag_1"]):
                    try:
                        current_pos = valid_indices.index(i)
                        if current_pos >= 8:
                            # Get value from 8 valid observations ago
                            prev_y = valid_y_values[current_pos - 8]
                            df.loc[i, "sales_change_7d"] = df.loc[i, "lag_1"] - prev_y
                    except ValueError:
                        continue
        else:
            if "lag_1" in df.columns:
                # Approximate with lag_1 - lag_8 (if lag_8 exists, otherwise use lag_7)
                if "lag_7" in df.columns:
                    df["sales_change_7d"] = df["lag_1"] - df["lag_7"]
                else:
                    df["sales_change_7d"] = np.nan
            else:
                df["sales_change_7d"] = np.nan

        return df

    def add_interaction_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Adds minimal interaction features (6 features).
        weekend_x_rolling_mean_7, weekend_x_lag_7, lag_1_div_rolling_mean_7,
        lag_7_div_rolling_mean_30, rolling_mean_diff, weekend_x_sales_change
        """
        df = df.copy()

        # weekend_x_rolling_mean_7
        if "is_weekend" in df.columns and "rolling_mean_7" in df.columns:
            df["weekend_x_rolling_mean_7"] = df["is_weekend"] * df["rolling_mean_7"]
        else:
            df["weekend_x_rolling_mean_7"] = 0.0

        # weekend_x_lag_7
        if "is_weekend" in df.columns and "lag_7" in df.columns:
            df["weekend_x_lag_7"] = df["is_weekend"] * df["lag_7"]
        else:
            df["weekend_x_lag_7"] = 0.0

        # lag_1_div_rolling_mean_7 (handle division by zero)
        if "lag_1" in df.columns and "rolling_mean_7" in df.columns:
            df["lag_1_div_rolling_mean_7"] = np.where(
                df["rolling_mean_7"] != 0,
                df["lag_1"] / df["rolling_mean_7"],
                np.nan
            )
        else:
            df["lag_1_div_rolling_mean_7"] = np.nan

        # lag_7_div_rolling_mean_30
        if "lag_7" in df.columns and "rolling_mean_30" in df.columns:
            df["lag_7_div_rolling_mean_30"] = np.where(
                df["rolling_mean_30"] != 0,
                df["lag_7"] / df["rolling_mean_30"],
                np.nan
            )
        else:
            df["lag_7_div_rolling_mean_30"] = np.nan

        # rolling_mean_diff
        if "rolling_mean_7" in df.columns and "rolling_mean_30" in df.columns:
            df["rolling_mean_diff"] = df["rolling_mean_7"] - df["rolling_mean_30"]
        else:
            df["rolling_mean_diff"] = np.nan

        # weekend_x_sales_change
        if "is_weekend" in df.columns and "sales_change_1d" in df.columns and "lag_7" in df.columns:
            # sales_change for weekend: lag_1 - lag_7
            if "lag_1" in df.columns:
                weekend_sales_change = df["lag_1"] - df["lag_7"]
                df["weekend_x_sales_change"] = df["is_weekend"] * weekend_sales_change
            else:
                df["weekend_x_sales_change"] = 0.0
        else:
            df["weekend_x_sales_change"] = 0.0

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
        Adds enhanced promotion features including duration, effectiveness, and decay.

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
        df["promotion_duration"] = 0  # Days into current promotion
        df["promotion_effectiveness"] = 1.0  # Historical effectiveness score
        df["promotion_decay_factor"] = 1.0  # Decay factor (decreases over time in promotion)

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
            
            # Calculate promotion duration (days into current promotion)
            df = df.sort_values("ds").reset_index(drop=True)
            df["promotion_duration"] = 0
            
            # Track consecutive promotion days
            in_promotion = False
            promo_start_idx = None
            for idx in df.index:
                if df.loc[idx, "is_promotion"] == 1:
                    if not in_promotion:
                        # Start of new promotion
                        in_promotion = True
                        promo_start_idx = idx
                        df.loc[idx, "promotion_duration"] = 1
                    else:
                        # Continuation of promotion
                        df.loc[idx, "promotion_duration"] = idx - promo_start_idx + 1
                else:
                    in_promotion = False
                    promo_start_idx = None
            
            # Calculate promotion decay factor (effect decreases over time)
            # Decay formula: 1.0 for day 1, decreases by 5% per day, minimum 0.7
            df["promotion_decay_factor"] = 1.0
            promo_mask = df["promotion_duration"] > 0
            if promo_mask.any():
                # Exponential decay: decay_factor = 0.95^(duration-1)
                df.loc[promo_mask, "promotion_decay_factor"] = np.power(
                    0.95, 
                    np.maximum(0, df.loc[promo_mask, "promotion_duration"] - 1)
                )
                # Cap minimum at 0.7
                df.loc[promo_mask, "promotion_decay_factor"] = np.maximum(
                    0.7,
                    df.loc[promo_mask, "promotion_decay_factor"]
                )
            
            # Calculate historical promotion effectiveness
            # This would ideally use historical sales data, but for now we use multiplier as proxy
            # In a full implementation, this would compare actual sales during promotions vs baseline
            if "y" in df.columns:
                # Calculate average sales during promotions vs non-promotions
                promo_sales = df[df["is_promotion"] == 1]["y"].mean() if (df["is_promotion"] == 1).any() else 0.0
                non_promo_sales = df[df["is_promotion"] == 0]["y"].mean() if (df["is_promotion"] == 0).any() else 0.0
                
                if non_promo_sales > 0 and promo_sales > 0:
                    # Effectiveness = actual boost / expected boost
                    actual_boost = promo_sales / non_promo_sales
                    expected_boost = df[df["is_promotion"] == 1]["promotion_multiplier"].mean() if (df["is_promotion"] == 1).any() else 1.0
                    effectiveness = actual_boost / expected_boost if expected_boost > 0 else 1.0
                    # Normalize to reasonable range (0.5 to 2.0)
                    effectiveness = np.clip(effectiveness, 0.5, 2.0)
                    df["promotion_effectiveness"] = effectiveness
                else:
                    df["promotion_effectiveness"] = 1.0
            else:
                # No sales data yet, use default
                df["promotion_effectiveness"] = 1.0
            
            # Apply decay to multiplier
            df["promotion_multiplier"] = df["promotion_multiplier"] * df["promotion_decay_factor"] * df["promotion_effectiveness"]

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
        Enhanced to better capture spike patterns including promotion proximity.
        
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
        df["spike_promotion_proximity"] = 0.0  # New: proximity to promotions
        
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
                
                # Week of year pattern (for better seasonal capture)
                spike_week = spike_dates.dt.isocalendar().week.value_counts(normalize=True)
                df["spike_week_prob"] = df["ds"].dt.isocalendar().week.map(spike_week).fillna(0.0)
                
                # Combined seasonality score (weighted)
                df["spike_seasonality"] = (
                    0.4 * df["spike_dow_prob"] + 
                    0.3 * df["spike_month_prob"] + 
                    0.3 * df["spike_week_prob"]
                )
                
                # Promotion proximity feature
                if "is_promotion" in df.columns:
                    # Calculate probability of spike during promotions
                    promo_spikes = df[(df["is_promotion"] == 1) & spike_mask]
                    promo_days = df[df["is_promotion"] == 1]
                    promo_spike_rate = len(promo_spikes) / len(promo_days) if len(promo_days) > 0 else 0.0
                    
                    # Days before/after promotion
                    for idx in df.index:
                        if df.loc[idx, "is_promotion"] == 1:
                            # On promotion day
                            df.loc[idx, "spike_promotion_proximity"] = promo_spike_rate
                        else:
                            # Check proximity to promotions (within 3 days)
                            nearby_promos = df[
                                (df["is_promotion"] == 1) & 
                                (np.abs(df.index - idx) <= 3)
                            ]
                            if len(nearby_promos) > 0:
                                # Closer to promotion = higher probability
                                min_dist = min(np.abs(nearby_promos.index - idx))
                                proximity_score = (4 - min_dist) / 4.0  # 1.0 if on promo, 0.25 if 3 days away
                                df.loc[idx, "spike_promotion_proximity"] = promo_spike_rate * proximity_score
                
                # Overall spike probability (based on historical frequency + seasonality + promotions)
                historical_spike_rate = spike_mask.sum() / len(df) if len(df) > 0 else 0.0
                base_prob = historical_spike_rate * df["spike_seasonality"]
                
                # Boost probability near promotions
                if "spike_promotion_proximity" in df.columns:
                    df["spike_probability"] = np.maximum(base_prob, df["spike_promotion_proximity"])
                else:
                    df["spike_probability"] = base_prob
            else:
                df["spike_probability"] = 0.0
                df["spike_seasonality"] = 0.0
        else:
            # No historical spike data - set defaults
            df["spike_probability"] = 0.0
            df["days_since_last_spike"] = np.nan
            df["spike_momentum"] = 0.0
            df["spike_seasonality"] = 0.0
            df["spike_promotion_proximity"] = 0.0
        
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

        # Add EWMA features (after lag features)
        df_out = self.add_ewma_features(df_out)

        # Add lagged rolling statistics (after rolling stats are computed)
        df_out = self.add_lagged_rolling_features(df_out)

        # Add calendar features (includes cyclical encoding)
        df_out = self.add_calendar_features(df_out)

        # Add trend and momentum features (after lag and rolling features)
        df_out = self.add_trend_momentum_features(df_out)

        # Add interaction features (after all base features)
        df_out = self.add_interaction_features(df_out)

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
