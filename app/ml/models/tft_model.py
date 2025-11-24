from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

try:
    from pytorch_forecasting import TemporalFusionTransformer, TimeSeriesDataSet
except ImportError:
    TemporalFusionTransformer = None
    TimeSeriesDataSet = None

from .base_model import BaseForecastModel


@dataclass
class TFTConfig:
    """Hyperparameters for Temporal Fusion Transformer."""
    hidden_size: int = 16
    attention_head_size: int = 4
    dropout: float = 0.1
    hidden_continuous_size: int = 8
    output_size: int = 7


class TFTForecastModel(BaseForecastModel):
    """
    Temporal Fusion Transformer (TFT) model.
    Stub implementation - requires PyTorch Forecasting library.
    """

    def __init__(self, config: Optional[TFTConfig] = None):
        if TemporalFusionTransformer is None:
            raise ImportError(
                "pytorch-forecasting is not installed. "
                "Install with `pip install pytorch-forecasting`."
            )
        self.config = config or TFTConfig()
        self.model: Optional[TemporalFusionTransformer] = None

    def fit(self, df: pd.DataFrame) -> None:
        """
        Train TFT model.
        
        Args:
            df: DataFrame with 'ds' and 'y' columns
        """
        # TODO: Implement TFT training
        raise NotImplementedError("TFT model training not yet implemented")

    def predict(self, future_df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate predictions for future dates.
        
        Args:
            future_df: DataFrame with 'ds' column
        
        Returns:
            DataFrame with predictions
        """
        if self.model is None:
            raise RuntimeError("Model is not fitted yet.")
        
        # TODO: Implement TFT prediction
        raise NotImplementedError("TFT model prediction not yet implemented")


# Backward compatibility alias
TFTModel = TFTForecastModel

