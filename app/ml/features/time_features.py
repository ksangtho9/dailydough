from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass
class TimeFeatureConfig:
    """Configuration for time-based features."""
    include_day_of_week: bool = True
    include_is_weekend: bool = True
    include_month: bool = False
    include_year: bool = False
    include_day_of_month: bool = False
    include_quarter: bool = False


def add_time_features(df: pd.DataFrame, config: Optional[TimeFeatureConfig] = None) -> pd.DataFrame:
    """
    Adds basic calendar-based features.

    Assumes df has column "ds" (datetime-like).
    """
    if config is None:
        config = TimeFeatureConfig()
    
    df = df.copy()
    
    # Ensure ds is datetime
    if not pd.api.types.is_datetime64_any_dtype(df["ds"]):
        df["ds"] = pd.to_datetime(df["ds"])

    if config.include_day_of_week:
        df["day_of_week"] = df["ds"].dt.dayofweek  # 0=Mon, 6=Sun

    if config.include_is_weekend:
        df["is_weekend"] = df["ds"].dt.dayofweek.isin([5, 6]).astype(int)

    if config.include_month:
        df["month"] = df["ds"].dt.month

    if config.include_year:
        df["year"] = df["ds"].dt.year

    if config.include_day_of_month:
        df["day_of_month"] = df["ds"].dt.day

    if config.include_quarter:
        df["quarter"] = df["ds"].dt.quarter

    return df

