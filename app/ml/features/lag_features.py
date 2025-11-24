from __future__ import annotations

from typing import List, Optional

import pandas as pd


def add_lag_features(
    df: pd.DataFrame,
    lag_periods: List[int] = None,
    target_col: str = "y",
) -> pd.DataFrame:
    """
    Adds lag features for time series forecasting.
    
    Args:
        df: DataFrame with 'ds' (datetime) and target_col columns
        lag_periods: List of lag periods to create (e.g., [1, 7, 14, 30])
        target_col: Name of the target column to create lags from
    
    Returns:
        DataFrame with additional lag columns
    """
    if lag_periods is None:
        lag_periods = [1, 7, 14, 30]
    
    df = df.copy()
    df = df.sort_values("ds").reset_index(drop=True)
    
    for lag in lag_periods:
        df[f"{target_col}_lag_{lag}"] = df[target_col].shift(lag)
    
    return df

