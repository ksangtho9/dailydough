from __future__ import annotations

from typing import List, Optional

import pandas as pd


def add_rolling_features(
    df: pd.DataFrame,
    windows: List[int] = None,
    target_col: str = "y",
    include_mean: bool = True,
    include_std: bool = True,
    include_min: bool = False,
    include_max: bool = False,
) -> pd.DataFrame:
    """
    Adds rolling window features (mean, std, min, max).
    
    Args:
        df: DataFrame with 'ds' (datetime) and target_col columns
        windows: List of window sizes (e.g., [7, 14, 30])
        target_col: Name of the target column
        include_mean: Whether to include rolling mean
        include_std: Whether to include rolling std
        include_min: Whether to include rolling min
        include_max: Whether to include rolling max
    
    Returns:
        DataFrame with additional rolling feature columns
    """
    if windows is None:
        windows = [7, 14, 30]
    
    df = df.copy()
    df = df.sort_values("ds").reset_index(drop=True)
    
    for window in windows:
        if include_mean:
            df[f"{target_col}_rolling_mean_{window}"] = df[target_col].rolling(window=window, min_periods=1).mean()
        
        if include_std:
            df[f"{target_col}_rolling_std_{window}"] = df[target_col].rolling(window=window, min_periods=1).std()
        
        if include_min:
            df[f"{target_col}_rolling_min_{window}"] = df[target_col].rolling(window=window, min_periods=1).min()
        
        if include_max:
            df[f"{target_col}_rolling_max_{window}"] = df[target_col].rolling(window=window, min_periods=1).max()
    
    return df

