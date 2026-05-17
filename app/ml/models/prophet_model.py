from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import logging

import pandas as pd

from app.core.config import settings

try:
    from prophet import Prophet
except ImportError:  # pragma: no cover
    Prophet = None  # type: ignore


@dataclass
class ProphetConfig:
    """Hyperparameters for Prophet."""
    daily_seasonality: bool = False  # meaningless for daily-granularity data
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
        self.logger = logging.getLogger("bakezy.prophet")
        self.regressors = []

    def fit(self, df: pd.DataFrame) -> None:
        """
        df must contain columns: 'ds' (datetime), 'y' (numeric quantity).
        Can contain additional regressor columns that will be automatically added.
        
        Automatically enables yearly seasonality if >1 year of data is available.
        Automatically enables quarterly seasonality if >3 months of data is available.
        
        NOTE: Prophet does NOT support sample weights. This model trains on all valid days
        (is_valid_day == 1) without any weighting. In ensemble models, sample weights
        only apply to the XGBoost component, not the Prophet component.
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
                numeric_series = pd.to_numeric(series, errors='coerce')
                numeric_series = numeric_series.fillna(0.0)
                df[feature_name] = numeric_series
                # Only add if it has non-trivial variance (constant columns hurt more than help)
                if numeric_series.notna().any() and (numeric_series != 0).any() and numeric_series.nunique() > 1:
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

        # Prophet is a trend+seasonality model. Lag/rolling regressors are nearly perfectly
        # collinear with the trend component, causing coefficient explosion (matmul overflow)
        # and mostly-negative predictions that clamp to zero.
        # Use Prophet with zero regressors — just trend + weekly/yearly seasonality.
        # XGBoost handles lag/rolling features correctly and serves as the fallback.

        # Only add is_holiday when there is real variation (not all zeros)
        if "is_holiday" in df.columns:
            safe_add_regressor("is_holiday", df["is_holiday"])

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
                self.logger.warning(f"Prophet fit failed with regressors, trying without: {e}")
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
        
        # Store training dataframe for later reference (for regressor imputation)
        self._training_df = df_for_fit.copy()
        
        # Log regressors that were added
        self.logger.info(
            f"Prophet model fitted with {len(self.regressors)} regressors: {self.regressors}"
        )

    def predict(
        self,
        horizon_days: int,
        historical_delivery: Optional[pd.Series] = None,
        future_regressors: Optional[pd.DataFrame] = None,
        product_id: Optional[int] = None,  # For gated diagnostic logging
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
                self.logger.warning(f"Error converting 'y' column to numeric: {e}")
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
        
        # Log regressor availability (Step 0: Confirm Expected Regressors)
        if regressors:
            self.logger.info(f"Prophet predict: Expected {len(regressors)} regressors: {regressors}")
            if future_regressors is not None and not future_regressors.empty:
                available_regressors = [r for r in regressors if r in future_regressors.columns]
                missing_regressors = [r for r in regressors if r not in future_regressors.columns]
                self.logger.info(
                    f"Prophet predict: {len(available_regressors)} regressors available, "
                    f"{len(missing_regressors)} missing: {missing_regressors}"
                )
            else:
                self.logger.warning(f"Prophet predict: future_regressors is None/empty, all {len(regressors)} regressors will be missing")

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

        # Add default values for any missing regressors (Fix 2: Safer imputation)
        # Use smarter imputation: forward-fill, rolling mean, median, then 0.0 as last resort
        for regressor in regressors:
            if regressor not in future.columns:
                # Try to get historical values from training data (forward-fill)
                imputed = False
                if hasattr(self, '_training_df') and regressor in self._training_df.columns:
                    training_data = self._training_df[regressor].copy()
                    training_data = pd.to_numeric(training_data, errors='coerce')
                    if not training_data.isna().all():
                        # Use last known value (forward-fill)
                        last_value = training_data.dropna().iloc[-1] if len(training_data.dropna()) > 0 else None
                        if last_value is not None and pd.notna(last_value):
                            future[regressor] = float(last_value)
                            self.logger.debug(f"Prophet: Imputed {regressor} using last training value: {last_value}")
                            imputed = True
                
                if not imputed:
                    # Fall back to type-specific defaults
                    if regressor == "delivery" and historical_delivery is not None and len(historical_delivery) > 0:
                        # Use historical average for delivery
                        avg_delivery = historical_delivery.mean()
                        future[regressor] = avg_delivery
                        self.logger.debug(f"Prophet: Imputed {regressor} using historical average: {avg_delivery}")
                    elif regressor.startswith("lag_"):
                        # For lag features, use last known value from training or 0.0
                        if hasattr(self, '_training_df') and regressor in self._training_df.columns:
                            training_data = pd.to_numeric(self._training_df[regressor], errors='coerce').dropna()
                            if len(training_data) > 0:
                                future[regressor] = float(training_data.iloc[-1])
                                self.logger.debug(f"Prophet: Imputed {regressor} using last lag value")
                            else:
                                future[regressor] = 0.0
                        else:
                            future[regressor] = 0.0
                    elif regressor.startswith("rolling_"):
                        # Rolling features: use last known rolling mean from training
                        if hasattr(self, '_training_df') and regressor in self._training_df.columns:
                            training_data = pd.to_numeric(self._training_df[regressor], errors='coerce').dropna()
                            if len(training_data) > 0:
                                future[regressor] = float(training_data.iloc[-1])
                                self.logger.debug(f"Prophet: Imputed {regressor} using last rolling value")
                            else:
                                future[regressor] = 0.0
                        else:
                            future[regressor] = 0.0
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
                        # Unknown regressor type: try median from training data, then 0.0
                        if hasattr(self, '_training_df') and regressor in self._training_df.columns:
                            training_data = pd.to_numeric(self._training_df[regressor], errors='coerce').dropna()
                            if len(training_data) > 0:
                                median_value = float(training_data.median())
                                future[regressor] = median_value
                                self.logger.debug(f"Prophet: Imputed {regressor} using training median: {median_value}")
                            else:
                                future[regressor] = 0.0
                                self.logger.warning(f"Prophet: Unknown regressor {regressor}, defaulting to 0.0 (no training data)")
                        else:
                            # Unknown regressor type, default to 0.0 as last resort
                            future[regressor] = 0.0
                            self.logger.warning(f"Prophet: Unknown regressor {regressor}, defaulting to 0.0 (no training data available)")

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
        
        # Step 5: Model-specific checks (Prophet) - gated logging
        # Ensure logging is triggered for flagged products
        should_log = settings.debug_zero_forecasts
        if should_log:
            # Log growth type and hyperparameters
            growth_type = getattr(self.model, 'growth', 'linear')
            self.logger.info(
                f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                f"step=prophet_checks, growth_type={growth_type}, "
                f"changepoint_prior_scale={self.config.changepoint_prior_scale}, "
                f"seasonality_mode={self.config.seasonality_mode}"
            )
            
            # Log regressor usage
            regressors_used = len(regressors) > 0
            regressor_imputation_count = 0
            for regressor in regressors:
                if regressor not in future.columns:
                    regressor_imputation_count += 1
                elif regressor in future_for_predict.columns:
                    # Check if values were imputed (all same value or all zero)
                    reg_data = future_for_predict[regressor]
                    if reg_data.nunique() == 1 or (reg_data == 0.0).all():
                        regressor_imputation_count += 1
            
            self.logger.info(
                f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                f"step=prophet_checks, regressors_used={regressors_used}, "
                f"regressor_count={len(regressors)}, "
                f"regressor_imputation_count={regressor_imputation_count}"
            )
            
            if regressors_used and regressor_imputation_count == len(regressors):
                # Fix 4: Log which regressors were imputed
                imputed_regressors = []
                for regressor in regressors:
                    if regressor in future_for_predict.columns:
                        reg_data = pd.to_numeric(future_for_predict[regressor], errors='coerce')
                        reg_valid = reg_data.dropna()
                        if len(reg_valid) > 0:
                            # Check if constant (likely imputed)
                            if reg_valid.nunique() == 1 or (reg_valid == 0.0).all():
                                imputed_regressors.append(regressor)
                        else:
                            imputed_regressors.append(regressor)  # All NaN
                    else:
                        imputed_regressors.append(regressor)  # Missing
                
                self.logger.warning(
                    f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                    f"step=prophet_checks, WARNING: All regressors were imputed, "
                    f"imputed_regressors={imputed_regressors}, total_regressors={len(regressors)}"
                )
            
            # Log detailed regressor stats (only if gated)
            if should_log and regressors:
                # Log regressor list
                self.logger.info(
                    f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                    f"step=prophet_checks, regressor_list={regressors}"
                )
                
                # For each regressor, log min/mean/max/null_count and % imputed
                for regressor in regressors:
                    if regressor in future_for_predict.columns:
                        reg_data = future_for_predict[regressor]
                        reg_numeric = pd.to_numeric(reg_data, errors='coerce')
                        reg_valid = reg_numeric.dropna()
                        null_count = reg_numeric.isna().sum()
                        null_pct = (null_count / len(reg_numeric) * 100) if len(reg_numeric) > 0 else 0.0
                        
                        # Check if values were imputed (all same value or all zero/NaN)
                        imputed_pct = 0.0
                        if len(reg_valid) > 0:
                            # If all values are the same, likely imputed
                            if reg_valid.nunique() == 1:
                                imputed_pct = 100.0
                            # If all are zero, likely imputed
                            elif (reg_valid == 0.0).all():
                                imputed_pct = 100.0
                            else:
                                # Check if values match training data (indicating forward-fill)
                                if hasattr(self, '_training_df') and regressor in self._training_df.columns:
                                    training_last = pd.to_numeric(self._training_df[regressor], errors='coerce').dropna()
                                    if len(training_last) > 0:
                                        training_last_val = float(training_last.iloc[-1])
                                        # If all future values match last training value, likely imputed
                                        if (reg_valid == training_last_val).all():
                                            imputed_pct = 100.0
                        
                        min_val = float(reg_valid.min()) if len(reg_valid) > 0 else None
                        mean_val = float(reg_valid.mean()) if len(reg_valid) > 0 else None
                        max_val = float(reg_valid.max()) if len(reg_valid) > 0 else None
                        
                        min_str = f"{min_val:.6f}" if min_val is not None else "None"
                        mean_str = f"{mean_val:.6f}" if mean_val is not None else "None"
                        max_str = f"{max_val:.6f}" if max_val is not None else "None"
                        self.logger.info(
                            f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                            f"step=prophet_checks, regressor={regressor}, "
                            f"min={min_str}, mean={mean_str}, max={max_str}, "
                            f"null_count={int(null_count)}, null_pct={null_pct:.1f}%, "
                            f"imputed_pct={imputed_pct:.1f}%"
                        )
                    else:
                        # Regressor missing from future_df - 100% imputed
                        self.logger.info(
                            f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                            f"step=prophet_checks, regressor={regressor}, "
                            f"status=missing_from_future_df, imputed_pct=100.0%"
                        )
                
                # Phase 3: Log regressor values for first 3 and last 3 forecast dates
                if should_log and regressors and len(future_for_predict) > 0:
                    # Determine indices to log
                    log_indices = set()
                    if len(future_for_predict) >= 3:
                        log_indices.update([0, 1, 2])  # First 3
                        log_indices.update([len(future_for_predict) - 3, len(future_for_predict) - 2, len(future_for_predict) - 1])  # Last 3
                    else:
                        log_indices = set(range(len(future_for_predict)))
                    
                    # Log regressor values for each date
                    for idx in sorted(log_indices):
                        if idx < len(future_for_predict):
                            date_str = future_for_predict.iloc[idx]["ds"].strftime("%Y-%m-%d") if "ds" in future_for_predict.columns else f"idx_{idx}"
                            regressor_values = {}
                            for regressor in regressors:
                                if regressor in future_for_predict.columns:
                                    val = future_for_predict.iloc[idx][regressor]
                                    regressor_values[regressor] = float(val) if pd.notna(val) else None
                                else:
                                    regressor_values[regressor] = None
                            
                            self.logger.info(
                                f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                                f"step=future_regressor_health, date={date_str}, idx={idx}, "
                                f"regressor_values={regressor_values}"
                            )
        
        try:
            forecast = self.model.predict(future_for_predict)
        except Exception as e:
            # If predict fails, try with absolute minimal columns (just ds)
            self.logger.warning(f"Prophet predict failed with regressors, trying minimal: {e}")
            # Create a completely fresh future DataFrame with only 'ds'
            future_minimal = self.model.make_future_dataframe(periods=horizon_days, freq="D")
            # Only keep 'ds' column - remove everything else including 'y'
            future_minimal = future_minimal[["ds"]].copy()
            try:
                forecast = self.model.predict(future_minimal)
            except Exception as e2:
                self.logger.error(f"Prophet predict failed even with minimal columns: {e2}")
                raise RuntimeError(f"Prophet prediction failed: {e2}") from e2
        
        # Add summary log after Prophet prediction showing which regressors were used vs imputed
        if should_log and regressors:
            # Determine which regressors were actually used (not imputed)
            used_regressors = []
            imputed_regressor_list = []
            
            for regressor in regressors:
                if regressor in future_for_predict.columns:
                    reg_data = pd.to_numeric(future_for_predict[regressor], errors='coerce')
                    reg_valid = reg_data.dropna()
                    if len(reg_valid) > 0:
                        # Check if constant (likely imputed)
                        if reg_valid.nunique() == 1 or (reg_valid == 0.0).all():
                            imputed_regressor_list.append(regressor)
                        else:
                            used_regressors.append(regressor)
                    else:
                        imputed_regressor_list.append(regressor)  # All NaN
                else:
                    imputed_regressor_list.append(regressor)  # Missing
            
            self.logger.info(
                f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                f"step=prophet_prediction_summary, total_regressors={len(regressors)}, "
                f"used_regressors={used_regressors}, used_count={len(used_regressors)}, "
                f"imputed_regressors={imputed_regressor_list}, imputed_count={len(imputed_regressor_list)}"
            )
            
            if len(imputed_regressor_list) == len(regressors) and len(regressors) > 0:
                self.logger.warning(
                    f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                    f"step=prophet_prediction_summary, WARNING: ALL regressors were imputed! "
                    f"This may cause zero forecasts."
                )
        
        return forecast
