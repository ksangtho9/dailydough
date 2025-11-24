from __future__ import annotations

from typing import Protocol

import pandas as pd


class BaseForecastModel(Protocol):
    """
    Protocol defining the interface for all forecasting models.
    
    All forecasting models should implement this interface.
    """
    
    def fit(self, df: pd.DataFrame) -> None:
        """
        Train the model on historical data.
        
        Args:
            df: DataFrame with at least 'ds' (datetime) and 'y' (target) columns
        """
        ...
    
    def predict(self, future_df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate predictions for future dates.
        
        Args:
            future_df: DataFrame with 'ds' column for future dates
        
        Returns:
            DataFrame with predictions, including at least 'yhat' column
        """
        ...

