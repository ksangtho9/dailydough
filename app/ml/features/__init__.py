"""Feature engineering modules."""

import pandas as pd
from .time_features import add_time_features, TimeFeatureConfig
from .lag_features import add_lag_features
from .rolling_features import add_rolling_features

__all__ = [
    "add_time_features",
    "TimeFeatureConfig",
    "add_lag_features",
    "add_rolling_features",
    "add_all_features",
]


def add_all_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convenience function that applies all feature engineering steps.
    
    Args:
        df: DataFrame with 'ds' and 'y' columns
    
    Returns:
        DataFrame with all features added
    """
    df = add_time_features(df)
    df = add_lag_features(df)
    df = add_rolling_features(df)
    return df
