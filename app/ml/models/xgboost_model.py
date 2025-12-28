from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple, TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from ..features import FeatureEngineer

try:
    from xgboost import XGBRegressor
except ImportError:  # pragma: no cover
    XGBRegressor = None  # type: ignore


@dataclass
class XGBoostConfig:
    """Hyperparameters for XGBoost-based forecaster."""
    max_depth: int = 3
    n_estimators: int = 200
    learning_rate: float = 0.05
    subsample: float = 0.8
    colsample_bytree: float = 0.8
    use_wape_loss: bool = False  # Use WAPE-approximating objective


class XGBoostSalesModel:
    """
    Feature-based model for time series (uses lag/features, not auto time index).
    """

    def __init__(self, config: Optional[XGBoostConfig] = None):
        if XGBRegressor is None:
            raise ImportError(
                "xgboost is not installed. "
                "Install with `pip install xgboost`."
            )
        self.config = config or XGBoostConfig()
        self.model: Optional[XGBRegressor] = None
        self.feature_cols: Optional[list[str]] = None

    def _split_features_target(self, df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        if "y" not in df.columns:
            raise ValueError("DataFrame must contain 'y' column as target.")

        # Exclude non-feature columns
        exclude_cols = ["y", "ds", "delivery", "is_spike", "spike_severity", "y_original", 
                       "product_category", "condition", "holiday_name"]  # Exclude string columns
        
        # Get all columns except excluded ones
        candidate_cols = [c for c in df.columns if c not in exclude_cols]
        
        # Filter to only numeric columns (XGBoost requires numeric features)
        numeric_cols = []
        for col in candidate_cols:
            if col in df.columns:
                # Check if column is numeric
                if pd.api.types.is_numeric_dtype(df[col]):
                    numeric_cols.append(col)
                else:
                    # Try to convert to numeric, skip if not possible
                    try:
                        pd.to_numeric(df[col], errors='raise')
                        numeric_cols.append(col)
                    except (ValueError, TypeError):
                        # Skip non-numeric columns
                        continue
        
        self.feature_cols = numeric_cols
        
        if len(self.feature_cols) == 0:
            raise ValueError("No numeric feature columns found in DataFrame")
        
        # Ensure all feature columns are numeric and handle NaN values
        X = df[self.feature_cols].copy()
        for col in self.feature_cols:
            X[col] = pd.to_numeric(X[col], errors='coerce').fillna(0.0)
        
        X = X[self.feature_cols].values
        y = df["y"].values
        return X, y

    def _wape_objective(self, y_pred: np.ndarray, dtrain) -> Tuple[np.ndarray, np.ndarray]:
        """
        Custom objective function that approximates WAPE behavior.
        
        WAPE weights errors by actual values. Since we can't use actual values
        in the gradient calculation, we use a weighted squared error where
        weights are based on predictions (approximating actuals).
        
        This encourages the model to focus more on getting high-value predictions right.
        """
        y_true = dtrain.get_label()
        epsilon = 1e-8
        
        # Calculate residuals
        residuals = y_pred - y_true
        
        # Use absolute values as weights (approximates WAPE weighting)
        # Clip to avoid division by zero
        weights = np.abs(y_true) + epsilon
        
        # Weighted squared error gradient
        grad = 2 * residuals / weights
        hess = 2 / weights
        
        return grad, hess
    
    def fit(self, df: pd.DataFrame, sample_weight: Optional[np.ndarray] = None) -> None:
        """
        df should contain:
        - y (target)
        - (optional) feature columns (lag features, calendar, etc.)
        
        Args:
            df: Training DataFrame
            sample_weight: Optional array of sample weights (for down-weighting supply-capped days)
        """
        X, y = self._split_features_target(df)
        
        # Determine objective function
        if self.config.use_wape_loss:
            objective = self._wape_objective
        else:
            objective = "reg:squarederror"
        
        model = XGBRegressor(
            max_depth=self.config.max_depth,
            n_estimators=self.config.n_estimators,
            learning_rate=self.config.learning_rate,
            subsample=self.config.subsample,
            colsample_bytree=self.config.colsample_bytree,
            objective=objective,
        )
        model.fit(X, y, sample_weight=sample_weight)
        self.model = model

    def predict(self, df_future: pd.DataFrame) -> np.ndarray:
        """
        Predict on future feature matrix with same feature columns.
        """
        if self.model is None or self.feature_cols is None:
            raise RuntimeError("Model is not fitted yet.")

        # Ensure all features are numeric
        X_future = df_future[self.feature_cols].copy()
        for col in self.feature_cols:
            if col in X_future.columns:
                X_future[col] = pd.to_numeric(X_future[col], errors='coerce').fillna(0.0)
        
        X_future = X_future[self.feature_cols].values
        preds = self.model.predict(X_future)
        return preds

    def predict_future(
        self,
        historical_df: pd.DataFrame,
        future_df: pd.DataFrame,
        feature_engineer: "FeatureEngineer",
        holidays_df: Optional[pd.DataFrame] = None,
        weather_df: Optional[pd.DataFrame] = None,
        promotions_df: Optional[pd.DataFrame] = None,
        events_df: Optional[pd.DataFrame] = None,
        product_info: Optional[dict] = None,
    ) -> pd.DataFrame:
        """
        Predict future values with recursive feature generation.
        
        This method iteratively predicts each future day, using previous predictions
        to generate lag features for subsequent days.
        
        Args:
            historical_df: Historical data with all features (used for context)
            future_df: DataFrame with future dates (ds column) and basic features
            feature_engineer: FeatureEngineer instance to generate features
            holidays_df: Optional holidays DataFrame
            weather_df: Optional weather DataFrame
            promotions_df: Optional promotions DataFrame
            events_df: Optional events DataFrame
            product_info: Optional product metadata
            
        Returns:
            DataFrame with columns: ds, yhat (predictions), and optionally yhat_lower, yhat_upper
        """
        if self.model is None or self.feature_cols is None:
            raise RuntimeError("Model is not fitted yet.")
        
        if future_df.empty:
            return pd.DataFrame(columns=["ds", "yhat"])
        
        # Ensure ds is datetime
        historical_df = historical_df.copy()
        historical_df["ds"] = pd.to_datetime(historical_df["ds"])
        future_df = future_df.copy()
        future_df["ds"] = pd.to_datetime(future_df["ds"])
        future_df = future_df.sort_values("ds").reset_index(drop=True)
        
        # Initialize predictions list and build complete time series
        predictions = []
        # Start with historical data - ensure it has y column
        complete_series = historical_df.copy()
        if "y" not in complete_series.columns:
            complete_series["y"] = 0.0
        
        # Iteratively predict each day
        for idx, row in future_df.iterrows():
            # Create a single-row DataFrame for this future date
            current_future = pd.DataFrame([row])
            current_future["y"] = 0.0  # Placeholder, will be replaced with prediction
            
            # Apply feature engineering (calendar, holidays, weather, promotions, events, product)
            current_future = feature_engineer.add_calendar_features(current_future)
            current_future = feature_engineer.add_holiday_features(current_future, holidays_df)
            current_future = feature_engineer.add_weather_features(current_future, weather_df)
            current_future = feature_engineer.add_promotion_features(current_future, promotions_df)
            current_future = feature_engineer.add_event_features(current_future, events_df)
            current_future = feature_engineer.add_product_features(current_future, product_info)
            
            # Append current future row to complete series for lag feature calculation
            complete_series = pd.concat([complete_series, current_future], ignore_index=True)
            
            # Recalculate lag features and rolling statistics on the complete series
            complete_series = feature_engineer.add_lag_features(complete_series)
            
            # Extract features for current future date (last row)
            current_future = complete_series.iloc[-1:].copy()
            
            # Add spike features (may need historical context)
            current_future = feature_engineer.add_spike_features(current_future)
            
            # Ensure all required feature columns exist
            for col in self.feature_cols:
                if col not in current_future.columns:
                    # Fill missing features with defaults
                    if col.startswith("lag_"):
                        current_future[col] = historical_df["y"].mean() if "y" in historical_df.columns and len(historical_df) > 0 else 0.0
                    elif col.startswith("rolling_"):
                        if "mean" in col:
                            current_future[col] = historical_df["y"].mean() if "y" in historical_df.columns and len(historical_df) > 0 else 0.0
                        else:
                            current_future[col] = 0.0
                    elif col in ["is_holiday", "is_promotion", "is_event", "is_rainy", "is_sunny", 
                                 "is_month_start", "is_month_end", "is_payday", "is_spike"]:
                        current_future[col] = 0
                    elif col in ["promotion_multiplier", "event_multiplier"]:
                        current_future[col] = 1.0
                    elif col in ["spike_probability", "spike_severity", "spike_seasonality", "spike_promotion_proximity"]:
                        current_future[col] = 0.0
                    elif col in ["days_since_last_spike", "spike_momentum"]:
                        current_future[col] = 999.0 if col == "days_since_last_spike" else 0.0
                    else:
                        current_future[col] = 0.0
            
            # Make prediction - ensure all features are numeric
            X_current = current_future[self.feature_cols].copy()
            # Convert all to numeric, filling NaN with 0
            for col in self.feature_cols:
                if col in X_current.columns:
                    X_current[col] = pd.to_numeric(X_current[col], errors='coerce').fillna(0.0)
            
            X_current = X_current[self.feature_cols].values
            pred = self.model.predict(X_current)[0]
            pred = max(0.0, float(pred))  # Ensure non-negative and numeric
            predictions.append(pred)
            
            # Update the complete_series with the actual prediction (for next iteration's rolling stats)
            complete_series.loc[len(complete_series) - 1, "y"] = pred
        
        # Create result DataFrame
        result_df = future_df[["ds"]].copy()
        result_df["yhat"] = predictions
        
        # Generate confidence intervals (simple approximation using historical std)
        if "y" in historical_df.columns:
            historical_std = historical_df["y"].std()
            mean_pred = np.mean(predictions)
            # Simple confidence intervals (can be improved)
            result_df["yhat_lower"] = np.maximum(0.0, result_df["yhat"] - 1.96 * historical_std)
            result_df["yhat_upper"] = result_df["yhat"] + 1.96 * historical_std
        else:
            result_df["yhat_lower"] = np.maximum(0.0, result_df["yhat"] * 0.8)
            result_df["yhat_upper"] = result_df["yhat"] * 1.2
        
        return result_df