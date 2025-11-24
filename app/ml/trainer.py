"""
DEPRECATED: logic moved to app/ml/training/ (train_product.py, evaluation.py, model_selection.py)

This file is kept for backward compatibility only.
"""

from app.ml.training.train_product import (
    train_product_model,
    train_product_with_evaluation,
    TrainResult,
)
from app.ml.models.prophet_model import ProphetModel, ProphetConfig
from app.ml.models.lightgbm_model import LightGBMModel, LightGBMConfig

# For backward compatibility
ModelName = str  # "prophet", "lightgbm", etc.

# Alias old class names
ProphetSalesModel = ProphetModel
XGBoostSalesModel = LightGBMModel  # Note: XGBoost is now LightGBM

class ModelTrainer:
    """
    Backward compatibility wrapper for ModelTrainer.
    """
    def __init__(self, feature_engineer=None):
        # feature_engineer is ignored for backward compatibility
        pass

    def train(self, ts, model_name="prophet"):
        """
        Train a model (backward compatibility method).
        
        Args:
            ts: CleanedTimeSeries
            model_name: Model name ("prophet" or "xgboost")
        
        Returns:
            TrainResult
        """
        # Map old model names
        if model_name == "xgboost":
            model_name = "lightgbm"
        
        return train_product_model(ts, model_name=model_name)

__all__ = [
    "ModelTrainer",
    "TrainResult",
    "train_product_model",
    "train_product_with_evaluation",
    "ProphetSalesModel",
    "XGBoostSalesModel",
    "ProphetModel",
    "LightGBMModel",
]
