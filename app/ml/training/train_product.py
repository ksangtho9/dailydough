from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

import pandas as pd
from sqlalchemy.orm import Session

from ..data.sales_preprocessor import CleanedTimeSeries, build_base_timeseries
from ..features import add_all_features
from ..models.base_model import BaseForecastModel
from ..models.prophet_model import ProphetForecastModel, ProphetModel, ProphetConfig
from ..models.lightgbm_model import LightGBMForecastModel, LightGBMModel, LightGBMConfig
from ..registry.file_registry import save_model
from .evaluation import evaluate_model
from .model_selection import train_and_select_model

ModelName = Literal["prophet", "lightgbm", "neuralprophet", "tft", "sarima"]


@dataclass
class TrainResult:
    """Result of training a model."""
    model_name: ModelName
    model: BaseForecastModel
    metrics: Optional[dict[str, float]] = None


def train_product_model(
    ts: CleanedTimeSeries,
    model_name: ModelName = "prophet",
    feature_config: Optional[TimeFeatureConfig] = None,
) -> TrainResult:
    """
    Train a forecasting model for a single product.
    
    This is the main training entrypoint that:
    1. Applies feature engineering
    2. Instantiates and trains the specified model
    3. Returns the trained model
    
    Args:
        ts: CleanedTimeSeries with product data
        model_name: Name of the model to train
        feature_config: Optional configuration for feature engineering
    
    Returns:
        TrainResult with trained model
    """
    df = ts.df.copy()
    
    # Ensure ds is datetime
    if not pd.api.types.is_datetime64_any_dtype(df["ds"]):
        df["ds"] = pd.to_datetime(df["ds"])
    
    # Feature engineering
    if model_name in ["lightgbm", "xgboost"]:
        # For tree-based models, add features
        df = add_time_features(df, feature_config)
        df = add_lag_features(df, lag_periods=[1, 7, 14, 30])
        df = add_rolling_features(df, windows=[7, 14, 30])
    else:
        # For Prophet and other time-series models, minimal features
        # They handle seasonality internally
        pass
    
    # Train model
    if model_name == "prophet":
        model = ProphetForecastModel()
        model.fit(df[["ds", "y"]])
        return TrainResult(model_name="prophet", model=model)
    
    elif model_name == "lightgbm":
        model = LightGBMForecastModel()
        model.fit(df)
        return TrainResult(model_name="lightgbm", model=model)
    
    else:
        raise ValueError(f"Model {model_name} training not yet implemented")


def train_product_with_evaluation(
    ts: CleanedTimeSeries,
    model_name: ModelName = "prophet",
    train_split: float = 0.8,
) -> TrainResult:
    """
    Train a model with train/validation split and evaluation.
    
    Args:
        ts: CleanedTimeSeries with product data
        model_name: Name of the model to train
        train_split: Fraction of data to use for training (rest for validation)
    
    Returns:
        TrainResult with trained model and metrics
    """
    df = ts.df.copy()
    df = df.sort_values("ds").reset_index(drop=True)
    
    # Split data
    split_idx = int(len(df) * train_split)
    train_df = df.iloc[:split_idx].copy()
    val_df = df.iloc[split_idx:].copy()
    
    # Create CleanedTimeSeries for training
    train_ts = CleanedTimeSeries(product_id=ts.product_id, df=train_df[["ds", "y"]])
    
    # Train model
    result = train_product_model(train_ts, model_name=model_name)
    
    # Evaluate on validation set
    if not val_df.empty:
        try:
            # Generate predictions
            val_predictions = result.model.predict(val_df[["ds"]])
            
            # Extract yhat
            if "yhat" in val_predictions.columns:
                y_pred = val_predictions["yhat"].values
            else:
                # Fallback
                import numpy as np
                numeric_cols = val_predictions.select_dtypes(include=[np.number]).columns
                y_pred = val_predictions[numeric_cols[0]].values
            
            y_true = val_df["y"].values
            metrics = evaluate_model(y_true, y_pred)
            result.metrics = metrics
        except Exception as e:
            print(f"Evaluation failed: {e}")
    
    return result


def train_product(
    db: Session,
    product_id: int,
    model_name: ModelName = "prophet",
    train_split: float = 0.8,
) -> TrainResult:
    """
    Main training function for a product.
    
    1. Load + clean data
    2. Build train/valid split (reuse existing logic)
    3. Add features
    4. Train + select model (Prophet for now)
    5. Save model via registry
    6. Return metrics
    
    Args:
        db: Database session
        product_id: Product ID to train
        model_name: Model to train (default: "prophet")
        train_split: Fraction of data for training (default: 0.8)
    
    Returns:
        TrainResult with trained model and metrics
    """
    # 1. Load + clean data
    df = build_base_timeseries(db, product_id)
    
    if df.empty:
        raise ValueError(f"No sales data for product {product_id}")
    
    # 2. Build train/valid split
    df = df.sort_values("ds").reset_index(drop=True)
    split_idx = int(len(df) * train_split)
    train_df = df.iloc[:split_idx].copy()
    val_df = df.iloc[split_idx:].copy()
    
    # 3. Add features
    train_df = add_all_features(train_df)
    if not val_df.empty:
        val_df = add_all_features(val_df)
    
    # 4. Train + select model
    # For now, just train Prophet directly
    if model_name == "prophet":
        # Prophet only needs ds and y
        model = ProphetForecastModel()
        model.fit(train_df[["ds", "y"]])
        result = TrainResult(model_name="prophet", model=model)
    elif model_name == "lightgbm":
        model = LightGBMForecastModel()
        model.fit(train_df)
        result = TrainResult(model_name="lightgbm", model=model)
    else:
        raise ValueError(f"Model {model_name} not yet implemented")
    
    # 5. Evaluate and get metrics
    if not val_df.empty:
        try:
            # Generate predictions
            if model_name == "prophet":
                val_predictions = model.predict(val_df[["ds"]])
            else:
                val_predictions = model.predict(val_df)
            
            # Extract yhat
            if "yhat" in val_predictions.columns:
                y_pred = val_predictions["yhat"].values
            else:
                import numpy as np
                numeric_cols = val_predictions.select_dtypes(include=[np.number]).columns
                y_pred = val_predictions[numeric_cols[0]].values
            
            y_true = val_df["y"].values
            metrics = evaluate_model(y_true, y_pred)
            result.metrics = metrics
        except Exception as e:
            print(f"Evaluation failed: {e}")
    
    # 6. Save model via registry
    save_model(product_id, model)
    
    return result

