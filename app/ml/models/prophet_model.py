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
        
        Automatically enables yearly seasonality if >1 year of data is available.
        Automatically enables quarterly seasonality if >3 months of data is available.
        """
        # Determine data span
        df = df.copy()
        df["ds"] = pd.to_datetime(df["ds"])
        date_range = df["ds"].max() - df["ds"].min()
        days_of_data = date_range.days
        
        # Auto-enable yearly seasonality if we have >1 year of data
        yearly_seasonality = self.config.yearly_seasonality
        if days_of_data > 365:
            yearly_seasonality = True
        
        # Auto-enable quarterly seasonality if we have >3 months of data
        quarterly_seasonality = self.config.quarterly_seasonality
        if days_of_data > 90:
            quarterly_seasonality = True
        
        m = Prophet(
            daily_seasonality=self.config.daily_seasonality,
            weekly_seasonality=self.config.weekly_seasonality,
            yearly_seasonality=yearly_seasonality,
            seasonality_mode=self.config.seasonality_mode,
            changepoint_prior_scale=self.config.changepoint_prior_scale,
        )

        # Add custom seasonalities
        if self.config.monthly_seasonality:
            m.add_seasonality(name="monthly", period=30.5, fourier_order=5)
        if quarterly_seasonality:
            m.add_seasonality(name="quarterly", period=91.25, fourier_order=5)

        # Track which regressors we've added
        self.regressors = []
        
        # Helper function to safely add regressor (ensures numeric type)
        def safe_add_regressor(feature_name: str, series: pd.Series) -> bool:
            """Add regressor to Prophet model, ensuring it's numeric."""
            try:
                # Convert to numeric, coercing errors to NaN
                numeric_series = pd.to_numeric(series, errors='coerce')
                # Fill NaN with 0
                numeric_series = numeric_series.fillna(0.0)
                # Update the dataframe
                df[feature_name] = numeric_series
                # Check if we have valid data
                if numeric_series.notna().any() and (numeric_series != 0).any():
                    m.add_regressor(feature_name)
                    self.regressors.append(feature_name)
                    return True
            except Exception:
                pass
            return False

        # Add delivery as additional regressor if present
        if "delivery" in df.columns:
            delivery_series = df["delivery"]
            if safe_add_regressor("delivery", delivery_series):
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
                safe_add_regressor(feature, series)

        # Add rolling statistics as regressors
        rolling_features = ["rolling_mean_7", "rolling_mean_30", "rolling_std_7", "rolling_std_30"]
        for feature in rolling_features:
            if feature in df.columns:
                series = df[feature]
                safe_add_regressor(feature, series)

        # Add calendar features as regressors (numeric ones)
        calendar_features = [
            "month", "quarter", "day_of_month", "is_month_start", "is_month_end",
            "days_until_weekend", "days_since_weekend", "is_payday",
            "week_of_year", "day_of_year", "is_spring", "is_summer", "is_fall", "is_winter"
        ]
        for feature in calendar_features:
            if feature in df.columns:
                series = df[feature]
                safe_add_regressor(feature, series)

        # Add holiday/event features
        holiday_features = ["is_holiday", "days_before_holiday", "days_after_holiday", "holiday_proximity"]
        for feature in holiday_features:
            if feature in df.columns:
                series = df[feature]
                safe_add_regressor(feature, series)

        # Add weather features
        weather_features = ["temperature", "precipitation", "is_rainy", "is_sunny"]
        for feature in weather_features:
            if feature in df.columns:
                series = df[feature]
                safe_add_regressor(feature, series)

        # Add promotion/event features
        promo_features = ["is_promotion", "promotion_multiplier", "is_event", "event_multiplier"]
        for feature in promo_features:
            if feature in df.columns:
                series = df[feature]
                safe_add_regressor(feature, series)

        # Add spike-related features
        spike_features = [
            "is_spike",  # Historical spike flag
            "spike_probability",  # Predicted spike probability
            "spike_severity",  # Historical spike severity
            "days_since_last_spike",
            "spike_momentum",
            "spike_seasonality",
            "spike_promotion_proximity",  # New feature
        ]
        for feature in spike_features:
            if feature in df.columns:
                series = df[feature]
                safe_add_regressor(feature, series)

        # Add product features (if they vary, though typically they're constant)
        product_features = ["shelf_life_days", "price", "cost_price_ratio"]
        for feature in product_features:
            if feature in df.columns:
                series = df[feature]
                # Only add if it varies
                numeric_series = pd.to_numeric(series, errors='coerce').fillna(0.0)
                if numeric_series.notna().any() and numeric_series.nunique() > 1:
                    df[feature] = numeric_series
                    m.add_regressor(feature)
                    self.regressors.append(feature)

        # Before fitting, ensure all columns are numeric
        # Never forward-fill y - only impute regressor features if required
        # Ensure 'y' is numeric but keep NaN if missing (Prophet will handle it)
        df["y"] = pd.to_numeric(df["y"], errors='coerce')
        # Do NOT fillna y - keep as NaN if missing
        
        df_for_fit = df[["ds", "y"]].copy()
        
        # Add only numeric regressor columns
        # For regressor features: forward-fill from past, then fallback to rolling_mean_30, then global median
        for regressor in self.regressors:
            if regressor in df.columns:
                # Ensure it's numeric
                numeric_col = pd.to_numeric(df[regressor], errors='coerce')
                # Impute regressor features: forward-fill from past, then fallback
                if numeric_col.isna().any():
                    # Forward-fill from past
                    numeric_col = numeric_col.ffill()
                    # If still NaN, use rolling_mean_30 if available
                    if numeric_col.isna().any() and "rolling_mean_30" in df.columns:
                        rolling_mean = pd.to_numeric(df["rolling_mean_30"], errors='coerce')
                        numeric_col = numeric_col.fillna(rolling_mean)
                    # If still NaN, use global median
                    if numeric_col.isna().any():
                        global_median = numeric_col.median()
                        if pd.notna(global_median):
                            numeric_col = numeric_col.fillna(global_median)
                        else:
                            numeric_col = numeric_col.fillna(0.0)
                df_for_fit[regressor] = numeric_col
        
        # Also add delivery if it was in the original df but not in regressors
        # Impute delivery (regressor) but not y
        if "delivery" in df.columns and "delivery" not in df_for_fit.columns:
            numeric_delivery = pd.to_numeric(df["delivery"], errors='coerce')
            # Forward-fill delivery from past, then 0.0
            numeric_delivery = numeric_delivery.ffill().fillna(0.0)
            df_for_fit["delivery"] = numeric_delivery
        
        # Final check: ensure all columns in df_for_fit are numeric (except 'ds')
        # CRITICAL: Prophet stores this DataFrame internally and extends it during prediction
        # So ALL columns must be numeric, including 'y'
        cols_to_keep_fit = ["ds"]
        for col in df_for_fit.columns:
            if col != "ds":
                try:
                    # Convert to numeric
                    numeric_col = pd.to_numeric(df_for_fit[col], errors='coerce')
                    # For regressor columns (not y), impute if needed
                    if col != "y" and numeric_col.isna().any():
                        numeric_col = numeric_col.ffill()
                        if numeric_col.isna().any():
                            numeric_col = numeric_col.fillna(0.0)
                    # Ensure it's actually numeric dtype
                    numeric_col = numeric_col.astype(float)
                    df_for_fit[col] = numeric_col
                    cols_to_keep_fit.append(col)
                except Exception:
                    # If conversion fails, skip this column
                    continue
        
        # Keep only numeric columns
        df_for_fit = df_for_fit[cols_to_keep_fit].copy()
        
        # Ensure 'y' column exists and is definitely numeric
        if "y" not in df_for_fit.columns:
            raise ValueError("'y' column is required but was removed during numeric conversion")
        
        # Final check: ensure 'y' is float type
        df_for_fit["y"] = df_for_fit["y"].astype(float)
        
        try:
            m.fit(df_for_fit)
        except Exception as e:
            # If fit fails, try with just ds and y (no regressors)
            if len(self.regressors) > 0:
                import logging
                logger = logging.getLogger("bakezy.prophet")
                logger.warning(f"Prophet fit failed with regressors, trying without: {e}")
                df_minimal = df_for_fit[["ds", "y"]].copy()
                # Never fill y - keep as NaN if missing, Prophet will handle it
                df_minimal["y"] = pd.to_numeric(df_minimal["y"], errors='coerce')
                m = Prophet(
                    daily_seasonality=self.config.daily_seasonality,
                    weekly_seasonality=self.config.weekly_seasonality,
                    yearly_seasonality=yearly_seasonality,
                    seasonality_mode=self.config.seasonality_mode,
                    changepoint_prior_scale=self.config.changepoint_prior_scale,
                )
                if quarterly_seasonality:
                    m.add_seasonality(name="quarterly", period=91.25, fourier_order=5)
                m.fit(df_minimal)
                self.regressors = []  # Clear regressors since we're not using them
            else:
                raise
        
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

        # Create future dataframe - this extends the training data
        # Prophet's make_future_dataframe extends the training DataFrame, so it includes 'y'
        future = self.model.make_future_dataframe(periods=horizon_days, freq="D")
        
        # CRITICAL: Ensure 'y' column is numeric (it comes from training data extension)
        # Never forward-fill y - keep as NaN for future dates (Prophet will handle it)
        if "y" in future.columns:
            try:
                future["y"] = pd.to_numeric(future["y"], errors='coerce')
                # Do NOT fillna y - keep NaN for future dates
            except Exception as e:
                import logging
                logger = logging.getLogger("bakezy.prophet")
                logger.warning(f"Error converting 'y' column to numeric: {e}")
                # If conversion fails, remove 'y' column (Prophet can work without it for prediction)
                if "y" in future.columns:
                    future = future.drop(columns=["y"])
        
        # Remove any other non-numeric columns that might have been added
        cols_to_remove = []
        for col in future.columns:
            if col != "ds" and col != "y":
                try:
                    # Test if column is numeric
                    pd.to_numeric(future[col], errors='raise')
                except (ValueError, TypeError):
                    # Mark for removal
                    cols_to_remove.append(col)
        
        # Remove non-numeric columns
        for col in cols_to_remove:
            future = future.drop(columns=[col])

        # Add regressor values for future dates
        regressors = getattr(self, "regressors", [])

        if future_regressors is not None and not future_regressors.empty:
            # Merge provided future regressor values
            future_regressors = future_regressors.copy()
            future_regressors["ds"] = pd.to_datetime(future_regressors["ds"])
            
            # Only merge numeric regressor columns (filter out non-numeric columns)
            numeric_regressor_cols = ["ds"]
            for col in future_regressors.columns:
                if col != "ds":
                    # Check if column is numeric or can be converted
                    try:
                        pd.to_numeric(future_regressors[col], errors='raise')
                        numeric_regressor_cols.append(col)
                    except (ValueError, TypeError):
                        # Skip non-numeric columns
                        continue
            
            # Only merge numeric columns
            if len(numeric_regressor_cols) > 1:  # More than just "ds"
                future = future.merge(
                    future_regressors[numeric_regressor_cols], 
                    on="ds", 
                    how="left"
                )

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
        # Ensure all regressors are numeric
        for regressor in regressors:
                if regressor in future.columns:
                    # Convert to numeric and impute regressor features (not y)
                    numeric_reg = pd.to_numeric(future[regressor], errors='coerce')
                    # Forward-fill from past, then fallback
                    numeric_reg = numeric_reg.ffill()
                    if numeric_reg.isna().any():
                        numeric_reg = numeric_reg.fillna(0.0)
                    future[regressor] = numeric_reg

        # Before predicting, ensure all columns are numeric
        # Prophet may check all columns for NaN during prediction
        future_for_predict = future[["ds"]].copy()
        
        # Add only numeric regressor columns
        for regressor in regressors:
            if regressor in future.columns:
                try:
                    # Ensure it's numeric and impute regressor features
                    numeric_col = pd.to_numeric(future[regressor], errors='coerce')
                    # Forward-fill from past, then fallback
                    numeric_col = numeric_col.ffill()
                    if numeric_col.isna().any():
                        numeric_col = numeric_col.fillna(0.0)
                    future_for_predict[regressor] = numeric_col
                except Exception:
                    # Skip if conversion fails
                    continue
        
        # Also ensure 'y' column is numeric if it exists (for historical data)
        # Never fill y - keep as NaN if missing
        if "y" in future.columns:
            try:
                numeric_y = pd.to_numeric(future["y"], errors='coerce')
                # Do NOT fillna - keep NaN
                future_for_predict["y"] = numeric_y
            except Exception:
                # If 'y' conversion fails, don't include it
                pass
        
        # Final safety check: remove any non-numeric columns (except 'ds')
        cols_to_keep = ["ds"]
        for col in future_for_predict.columns:
            if col != "ds":
                try:
                    # Test if column is numeric
                    test_val = future_for_predict[col].iloc[0] if len(future_for_predict) > 0 else 0.0
                    pd.to_numeric([test_val], errors='raise')
                    cols_to_keep.append(col)
                except (ValueError, TypeError):
                    # Skip non-numeric columns
                    continue
        
        future_for_predict = future_for_predict[cols_to_keep].copy()
        
        # Ensure all remaining columns are numeric
        # For regressor columns (not y), impute if needed
        for col in future_for_predict.columns:
            if col != "ds" and col != "y":
                numeric_col = pd.to_numeric(future_for_predict[col], errors='coerce')
                # Forward-fill from past, then fallback
                numeric_col = numeric_col.ffill()
                if numeric_col.isna().any():
                    numeric_col = numeric_col.fillna(0.0)
                future_for_predict[col] = numeric_col
            elif col == "y":
                # Never fill y - keep as NaN if missing
                future_for_predict[col] = pd.to_numeric(future_for_predict[col], errors='coerce')
        
        # Final safety: ensure all columns are explicitly numeric with proper dtypes
        for col in future_for_predict.columns:
            if col != "ds":
                future_for_predict[col] = future_for_predict[col].astype(float)
        
        try:
            forecast = self.model.predict(future_for_predict)
        except Exception as e:
            # If predict fails, try with absolute minimal columns (just ds)
            import logging
            logger = logging.getLogger("bakezy.prophet")
            logger.warning(f"Prophet predict failed with regressors, trying minimal: {e}")
            # Create a completely fresh future DataFrame with only 'ds'
            future_minimal = self.model.make_future_dataframe(periods=horizon_days, freq="D")
            # Only keep 'ds' column - remove everything else including 'y'
            future_minimal = future_minimal[["ds"]].copy()
            try:
                forecast = self.model.predict(future_minimal)
            except Exception as e2:
                logger.error(f"Prophet predict failed even with minimal columns: {e2}")
                raise RuntimeError(f"Prophet prediction failed: {e2}") from e2
        
        return forecast
