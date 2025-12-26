from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .metrics import calculate_wape
from .models.prophet_model import ProphetSalesModel, ProphetConfig
from .models.xgboost_model import XGBoostSalesModel, XGBoostConfig
from .preprocessing import CleanedTimeSeries
from .features import FeatureEngineer

logger = logging.getLogger("bakezy.hyperparameter_optimization")


@dataclass
class OptimizationResult:
    """Result of hyperparameter optimization."""
    best_params: Dict
    best_wape: float
    all_results: List[Tuple[Dict, float]]  # List of (params, wape) tuples


def time_series_cv_splits(
    df: pd.DataFrame,
    n_splits: int = 3,
    test_size: int = 14,
    gap: int = 0,
) -> List[Tuple[np.ndarray, np.ndarray]]:
    """
    Generate time-series cross-validation splits.
    
    Args:
        df: DataFrame with 'ds' column (datetime)
        n_splits: Number of CV folds
        test_size: Size of test set in days
        gap: Gap between train and test sets in days
        
    Returns:
        List of (train_indices, test_indices) tuples
    """
    if df.empty or len(df) < test_size + gap + 1:
        # Not enough data for CV
        return []
    
    df = df.sort_values("ds").reset_index(drop=True)
    splits = []
    total_len = len(df)
    
    # Calculate minimum train size (use at least 30 days for training)
    min_train_size = max(30, total_len - (n_splits * (test_size + gap)) - test_size)
    
    for i in range(n_splits):
        # Calculate split point
        # Start from the end and work backwards
        test_end = total_len - (i * (test_size + gap))
        test_start = test_end - test_size
        
        if test_start < min_train_size:
            # Not enough data for this split
            continue
            
        train_end = test_start - gap
        train_start = 0
        
        if train_end <= train_start:
            continue
            
        train_indices = np.arange(train_start, train_end)
        test_indices = np.arange(test_start, test_end)
        
        splits.append((train_indices, test_indices))
    
    return splits


def optimize_prophet_hyperparameters(
    ts: CleanedTimeSeries,
    holidays_df: Optional[pd.DataFrame] = None,
    weather_df: Optional[pd.DataFrame] = None,
    promotions_df: Optional[pd.DataFrame] = None,
    events_df: Optional[pd.DataFrame] = None,
    product_info: Optional[dict] = None,
    n_splits: int = 3,
    max_iter: Optional[int] = None,
) -> OptimizationResult:
    """
    Optimize Prophet hyperparameters using WAPE as the optimization metric.
    
    Args:
        ts: CleanedTimeSeries for training
        holidays_df: Holidays DataFrame
        weather_df: Weather DataFrame
        promotions_df: Promotions DataFrame
        events_df: Events DataFrame
        product_info: Product metadata dict
        n_splits: Number of CV folds
        max_iter: Maximum number of parameter combinations to try (None = try all)
        
    Returns:
        OptimizationResult with best parameters and WAPE score
    """
    if ts.df.empty or len(ts.df) < 60:  # Need at least 60 days for meaningful CV
        logger.warning(
            f"Insufficient data for hyperparameter optimization: {len(ts.df)} days. "
            "Using default parameters."
        )
        default_config = ProphetConfig()
        return OptimizationResult(
            best_params={
                "changepoint_prior_scale": default_config.changepoint_prior_scale,
                "seasonality_mode": default_config.seasonality_mode,
            },
            best_wape=float("inf"),
            all_results=[],
        )
    
    # Prepare feature-engineered data if not already done
    df = ts.df.copy()
    df["ds"] = pd.to_datetime(df["ds"])
    
    # Check if features are already engineered (presence of feature columns)
    has_features = any(
        col in df.columns
        for col in [
            "lag_1", "lag_7", "rolling_mean_7", "month", "is_holiday",
            "temperature", "is_promotion", "is_event",
        ]
    )
    
    if not has_features:
        # Feature engineering not done yet, do it now
        feature_engineer = FeatureEngineer()
        df = feature_engineer.transform(
            df,
            holidays_df=holidays_df,
            weather_df=weather_df,
            promotions_df=promotions_df,
            events_df=events_df,
            product_info=product_info,
        )
    
    # Define search space
    changepoint_prior_scales = [0.001, 0.05, 0.1, 0.5]
    seasonality_modes = ["additive", "multiplicative"]
    
    param_combinations = [
        {"changepoint_prior_scale": cp, "seasonality_mode": sm}
        for cp in changepoint_prior_scales
        for sm in seasonality_modes
    ]
    
    if max_iter is not None:
        param_combinations = param_combinations[:max_iter]
    
    logger.info(
        f"Optimizing Prophet hyperparameters: {len(param_combinations)} combinations, "
        f"{n_splits} CV folds"
    )
    
    # Generate CV splits
    cv_splits = time_series_cv_splits(df, n_splits=n_splits, test_size=14, gap=0)
    
    if not cv_splits:
        logger.warning("Could not generate CV splits. Using default parameters.")
        default_config = ProphetConfig()
        return OptimizationResult(
            best_params={
                "changepoint_prior_scale": default_config.changepoint_prior_scale,
                "seasonality_mode": default_config.seasonality_mode,
            },
            best_wape=float("inf"),
            all_results=[],
        )
    
    best_wape = float("inf")
    best_params = None
    all_results = []
    
    for params in param_combinations:
        wapes = []
        
        for train_idx, test_idx in cv_splits:
            try:
                # Split data
                train_df = df.iloc[train_idx].copy()
                test_df = df.iloc[test_idx].copy()
                
                # Create model with current parameters
                config = ProphetConfig(
                    changepoint_prior_scale=params["changepoint_prior_scale"],
                    seasonality_mode=params["seasonality_mode"],
                    daily_seasonality=True,
                    weekly_seasonality=True,
                    yearly_seasonality=False,
                )
                
                model = ProphetSalesModel(config=config)
                model.fit(train_df)
                
                # Predict on test set using the wrapper's predict method
                horizon = len(test_df)
                
                # Prepare future regressors from test_df
                future_regressors = None
                regressors = getattr(model, "regressors", [])
                if regressors and not test_df.empty:
                    # Extract regressor columns from test_df for future dates
                    future_regressors = test_df[["ds"] + [r for r in regressors if r in test_df.columns]].copy()
                
                # Use historical delivery if available
                historical_delivery = None
                if "delivery" in train_df.columns:
                    historical_delivery = train_df["delivery"]
                
                forecast = model.predict(
                    horizon_days=horizon,
                    historical_delivery=historical_delivery,
                    future_regressors=future_regressors,
                )
                
                # Get predictions for test period only (last horizon days)
                test_forecast = forecast.tail(horizon).copy()
                
                if len(test_forecast) != len(test_df):
                    # Alignment issue, skip this fold
                    continue
                
                # Merge with actuals (include is_valid_day if present)
                test_cols = ["ds", "y"]
                if "is_valid_day" in test_df.columns:
                    test_cols.append("is_valid_day")
                
                test_merged = test_df[test_cols].merge(
                    test_forecast[["ds", "yhat"]],
                    on="ds",
                    how="inner",
                )
                
                if len(test_merged) == 0:
                    continue
                
                # Filter to valid days only for metrics computation
                # Keep CV split boundaries calendar-based, but evaluate only on valid days
                if "is_valid_day" in test_merged.columns:
                    test_merged = test_merged[test_merged["is_valid_day"] == 1]
                
                if len(test_merged) == 0:
                    continue
                
                # Calculate WAPE
                actual = test_merged["y"].values
                predicted = test_merged["yhat"].values
                
                # Ensure numeric types
                actual = pd.to_numeric(actual, errors='coerce')
                predicted = pd.to_numeric(predicted, errors='coerce')
                
                wape = calculate_wape(actual, predicted)
                # Safe NaN check using pandas which handles all types
                if wape is not None and pd.notna(wape):
                    try:
                        wapes.append(float(wape))
                    except (ValueError, TypeError):
                        pass
                    
            except Exception as e:
                logger.warning(f"Error in CV fold: {e}")
                continue
        
        if wapes:
            avg_wape = np.mean(wapes)
            all_results.append((params.copy(), avg_wape))
            
            if avg_wape < best_wape:
                best_wape = avg_wape
                best_params = params.copy()
    
    if best_params is None:
        # Fallback to default if optimization failed
        logger.warning("Hyperparameter optimization failed. Using default parameters.")
        default_config = ProphetConfig()
        best_params = {
            "changepoint_prior_scale": default_config.changepoint_prior_scale,
            "seasonality_mode": default_config.seasonality_mode,
        }
        best_wape = float("inf")
    
    logger.info(f"Best Prophet parameters: {best_params}, WAPE: {best_wape:.4f}")
    
    return OptimizationResult(
        best_params=best_params,
        best_wape=best_wape,
        all_results=all_results,
    )


def optimize_xgboost_hyperparameters(
    ts: CleanedTimeSeries,
    holidays_df: Optional[pd.DataFrame] = None,
    weather_df: Optional[pd.DataFrame] = None,
    promotions_df: Optional[pd.DataFrame] = None,
    events_df: Optional[pd.DataFrame] = None,
    product_info: Optional[dict] = None,
    n_splits: int = 3,
    max_iter: Optional[int] = None,
    use_wape_loss: bool = False,
) -> OptimizationResult:
    """
    Optimize XGBoost hyperparameters using WAPE as the optimization metric.
    
    Args:
        ts: CleanedTimeSeries for training
        holidays_df: Holidays DataFrame
        weather_df: Weather DataFrame
        promotions_df: Promotions DataFrame
        events_df: Events DataFrame
        product_info: Product metadata dict
        n_splits: Number of CV folds
        max_iter: Maximum number of parameter combinations to try (None = try all)
        use_wape_loss: Whether to use WAPE as the objective function (not just metric)
        
    Returns:
        OptimizationResult with best parameters and WAPE score
    """
    if ts.df.empty or len(ts.df) < 60:
        logger.warning(
            f"Insufficient data for hyperparameter optimization: {len(ts.df)} days. "
            "Using default parameters."
        )
        default_config = XGBoostConfig()
        return OptimizationResult(
            best_params={
                "max_depth": default_config.max_depth,
                "learning_rate": default_config.learning_rate,
                "n_estimators": default_config.n_estimators,
                "subsample": default_config.subsample,
            },
            best_wape=float("inf"),
            all_results=[],
        )
    
    # Prepare feature-engineered data if not already done
    df = ts.df.copy()
    df["ds"] = pd.to_datetime(df["ds"])
    
    # Check if features are already engineered
    has_features = any(
        col in df.columns
        for col in [
            "lag_1", "lag_7", "rolling_mean_7", "month", "is_holiday",
            "temperature", "is_promotion", "is_event",
        ]
    )
    
    if not has_features:
        # Feature engineering not done yet, do it now
        feature_engineer = FeatureEngineer()
        df = feature_engineer.transform(
            df,
            holidays_df=holidays_df,
            weather_df=weather_df,
            promotions_df=promotions_df,
            events_df=events_df,
            product_info=product_info,
        )
    
    # Define search space
    max_depths = [3, 5, 7]
    learning_rates = [0.01, 0.05, 0.1]
    n_estimators_list = [100, 200, 300]
    subsamples = [0.8, 0.9, 1.0]
    
    # Generate all combinations
    param_combinations = [
        {
            "max_depth": md,
            "learning_rate": lr,
            "n_estimators": ne,
            "subsample": ss,
        }
        for md in max_depths
        for lr in learning_rates
        for ne in n_estimators_list
        for ss in subsamples
    ]
    
    if max_iter is not None:
        param_combinations = param_combinations[:max_iter]
    else:
        # Limit to 27 combinations by default (3x3x3x1 or similar)
        param_combinations = param_combinations[:27]
    
    logger.info(
        f"Optimizing XGBoost hyperparameters: {len(param_combinations)} combinations, "
        f"{n_splits} CV folds"
    )
    
    # Generate CV splits
    cv_splits = time_series_cv_splits(df, n_splits=n_splits, test_size=14, gap=0)
    
    if not cv_splits:
        logger.warning("Could not generate CV splits. Using default parameters.")
        default_config = XGBoostConfig()
        return OptimizationResult(
            best_params={
                "max_depth": default_config.max_depth,
                "learning_rate": default_config.learning_rate,
                "n_estimators": default_config.n_estimators,
                "subsample": default_config.subsample,
            },
            best_wape=float("inf"),
            all_results=[],
        )
    
    best_wape = float("inf")
    best_params = None
    all_results = []
    
    for params in param_combinations:
        wapes = []
        
        for train_idx, test_idx in cv_splits:
            try:
                # Split data
                train_df = df.iloc[train_idx].copy()
                test_df = df.iloc[test_idx].copy()
                
                # Create model with current parameters
                config = XGBoostConfig(
                    max_depth=params["max_depth"],
                    learning_rate=params["learning_rate"],
                    n_estimators=params["n_estimators"],
                    subsample=params["subsample"],
                )
                
                model = XGBoostSalesModel(config=config)
                model.fit(train_df)
                
                # Predict on test set
                # For XGBoost, we need features for test set
                if model.feature_cols is None:
                    continue
                
                # Ensure test_df has all required feature columns
                missing_cols = set(model.feature_cols) - set(test_df.columns)
                if missing_cols:
                    # Skip this fold if features are missing
                    continue
                
                predictions = model.predict(test_df)
                
                # Filter to valid days only for metrics computation
                # Keep CV split boundaries calendar-based, but evaluate only on valid days
                if "is_valid_day" in test_df.columns:
                    test_df_valid = test_df[test_df["is_valid_day"] == 1].copy()
                    if len(test_df_valid) == 0:
                        continue
                    # Re-predict on valid test set only
                    if model.feature_cols is None:
                        continue
                    missing_cols = set(model.feature_cols) - set(test_df_valid.columns)
                    if missing_cols:
                        continue
                    predictions = model.predict(test_df_valid)
                    actual = test_df_valid["y"].values
                else:
                    actual = test_df["y"].values
                
                # Ensure numeric types
                actual = pd.to_numeric(actual, errors='coerce')
                predictions = pd.to_numeric(predictions, errors='coerce')
                
                # Calculate WAPE
                wape = calculate_wape(actual, predictions)
                # Safe NaN check using pandas which handles all types
                if wape is not None and pd.notna(wape):
                    try:
                        wapes.append(float(wape))
                    except (ValueError, TypeError):
                        pass
                    
            except Exception as e:
                logger.warning(f"Error in CV fold: {e}")
                continue
        
        if wapes:
            avg_wape = np.mean(wapes)
            all_results.append((params.copy(), avg_wape))
            
            if avg_wape < best_wape:
                best_wape = avg_wape
                best_params = params.copy()
    
    if best_params is None:
        # Fallback to default if optimization failed
        logger.warning("Hyperparameter optimization failed. Using default parameters.")
        default_config = XGBoostConfig()
        best_params = {
            "max_depth": default_config.max_depth,
            "learning_rate": default_config.learning_rate,
            "n_estimators": default_config.n_estimators,
            "subsample": default_config.subsample,
        }
        best_wape = float("inf")
    
    logger.info(f"Best XGBoost parameters: {best_params}, WAPE: {best_wape:.4f}")
    
    return OptimizationResult(
        best_params=best_params,
        best_wape=best_wape,
        all_results=all_results,
    )

