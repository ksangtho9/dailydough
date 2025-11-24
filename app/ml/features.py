"""
DEPRECATED: logic moved to app/ml/features/ (time_features.py, lag_features.py, rolling_features.py)

This file is kept for backward compatibility only.
"""

from app.ml.features.time_features import (
    add_time_features,
    TimeFeatureConfig,
)
from app.ml.features.lag_features import add_lag_features
from app.ml.features.rolling_features import add_rolling_features

# For backward compatibility, create a FeatureEngineer class
from dataclasses import dataclass
from typing import Optional
import pandas as pd


@dataclass
class FeatureConfig:
    """
    Controls which features we add.
    Backward compatibility wrapper for TimeFeatureConfig.
    """
    include_day_of_week: bool = True
    include_is_weekend: bool = True


class FeatureEngineer:
    """Backward compatibility wrapper."""
    
    def __init__(self, config: Optional[FeatureConfig] = None):
        self.config = config or FeatureConfig()
        # Convert to TimeFeatureConfig
        self.time_config = TimeFeatureConfig(
            include_day_of_week=self.config.include_day_of_week,
            include_is_weekend=self.config.include_is_weekend,
        )

    def add_calendar_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Backward compatibility method."""
        return add_time_features(df, self.time_config)

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Main feature pipeline entrypoint."""
        return self.add_calendar_features(df)

__all__ = [
    "FeatureConfig",
    "FeatureEngineer",
    "add_time_features",
    "TimeFeatureConfig",
    "add_lag_features",
    "add_rolling_features",
]
