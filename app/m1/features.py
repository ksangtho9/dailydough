from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass
class FeatureConfig:
    """
    Controls which features we add.

    Examples:
    - include_day_of_week
    - include_holiday_flags
    - include_promo_flags
    """
    include_day_of_week: bool = True
    include_is_weekend: bool = True
    # Add more flags later (holiday, weather, etc.)


class FeatureEngineer:
    def __init__(self, config: Optional[FeatureConfig] = None):
        self.config = config or FeatureConfig()

    def add_calendar_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Adds basic calendar-based features.

        Assumes df has column "ds" (datetime-like).
        """
        df = df.copy()

        if self.config.include_day_of_week:
            df["day_of_week"] = df["ds"].dt.dayofweek  # 0=Mon, 6=Sun

        if self.config.include_is_weekend:
            df["is_weekend"] = df["ds"].dt.dayofweek.isin([5, 6]).astype(int)

        return df

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Main feature pipeline entrypoint."""
        df_out = self.add_calendar_features(df)
        # Future hooks: promo flags, weather, holidays, etc.
        return df_out
