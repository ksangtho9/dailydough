from __future__ import annotations

from typing import Literal, Optional, Tuple
import pandas as pd
import numpy as np

from ..models.base_model import BaseForecastModel
from ..models.prophet_model import ProphetForecastModel, ProphetConfig
from .evaluation import mape, rmse, evaluate_model

ModelName = Literal["prophet", "lightgbm", "neuralprophet", "tft", "sarima"]


def train_and_select_model(
    train_df: pd.DataFrame,
    valid_df: Optional[pd.DataFrame] = None,
) -> Tuple[BaseForecastModel, dict]:
    """
    Train and select the best model.
    
    For now:
    - Train a ProphetForecastModel on train_df
    - Evaluate on valid_df
    - Return the trained model and metrics
    
    Args:
        train_df: Training DataFrame with 'ds' and 'y' columns
        valid_df: Optional validation DataFrame
    
    Returns:
        Tuple of (trained_model, metrics_dict)
    """
    # For now, just train Prophet
    model = ProphetForecastModel()
    model.fit(train_df[["ds", "y"]])
    
    metrics = {}
    if valid_df is not None and not valid_df.empty:
        # Evaluate on validation set
        predictions = model.predict(valid_df[["ds"]])
        
        if "yhat" in predictions.columns:
            y_pred = predictions["yhat"].values
        else:
            numeric_cols = predictions.select_dtypes(include=[np.number]).columns
            y_pred = predictions[numeric_cols[0]].values
        
        y_true = valid_df["y"].values
        metrics = evaluate_model(y_true, y_pred)
    
    return model, metrics


def select_best_model(
    models: dict[ModelName, BaseForecastModel],
    train_df: pd.DataFrame,
    val_df: Optional[pd.DataFrame] = None,
) -> tuple[ModelName, BaseForecastModel]:
    """
    Select the best model based on validation performance.
    
    For now, this is a simple implementation that defaults to Prophet
    if no validation data is provided or if only one model is provided.
    
    Args:
        models: Dictionary mapping model names to fitted models
        train_df: Training data
        val_df: Optional validation data for model selection
    
    Returns:
        Tuple of (best_model_name, best_model)
    """
    if len(models) == 1:
        model_name = list(models.keys())[0]
        return model_name, models[model_name]
    
    if val_df is None or val_df.empty:
        # Default to Prophet if no validation data
        if "prophet" in models:
            return "prophet", models["prophet"]
        # Otherwise return first model
        model_name = list(models.keys())[0]
        return model_name, models[model_name]
    
    # Evaluate all models on validation set
    best_model_name = None
    best_model = None
    best_score = np.inf
    
    for model_name, model in models.items():
        try:
            # Generate predictions on validation set
            val_predictions = model.predict(val_df[["ds"]])
            
            # Extract yhat column
            if "yhat" in val_predictions.columns:
                y_pred = val_predictions["yhat"].values
            else:
                # Fallback: use first numeric column
                numeric_cols = val_predictions.select_dtypes(include=[np.number]).columns
                y_pred = val_predictions[numeric_cols[0]].values
            
            # Calculate RMSE
            y_true = val_df["y"].values
            metrics = evaluate_model(y_true, y_pred)
            score = metrics["rmse"]
            
            if score < best_score:
                best_score = score
                best_model_name = model_name
                best_model = model
        except Exception as e:
            # Skip models that fail
            print(f"Model {model_name} failed evaluation: {e}")
            continue
    
    if best_model is None:
        # Fallback to Prophet
        if "prophet" in models:
            return "prophet", models["prophet"]
        model_name = list(models.keys())[0]
        return model_name, models[model_name]
    
    return best_model_name, best_model

