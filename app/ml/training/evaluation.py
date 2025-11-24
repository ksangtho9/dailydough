from __future__ import annotations

from typing import Dict
import numpy as np
import pandas as pd


def mape(y_true: pd.Series, y_pred: pd.Series) -> float:
    """
    Calculate Mean Absolute Percentage Error (MAPE).
    
    Args:
        y_true: True values as pandas Series
        y_pred: Predicted values as pandas Series
    
    Returns:
        MAPE value
    """
    # Avoid division by zero
    mask = y_true != 0
    if not mask.any():
        return np.inf
    
    return np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100


def rmse(y_true: pd.Series, y_pred: pd.Series) -> float:
    """
    Calculate Root Mean Squared Error (RMSE).
    
    Args:
        y_true: True values as pandas Series
        y_pred: Predicted values as pandas Series
    
    Returns:
        RMSE value
    """
    return np.sqrt(np.mean((y_true - y_pred) ** 2))


def calculate_mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """
    Calculate Mean Absolute Percentage Error (MAPE).
    
    Args:
        y_true: True values
        y_pred: Predicted values
    
    Returns:
        MAPE value
    """
    # Avoid division by zero
    mask = y_true != 0
    if not mask.any():
        return np.inf
    
    return np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100


def calculate_rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """
    Calculate Root Mean Squared Error (RMSE).
    
    Args:
        y_true: True values
        y_pred: Predicted values
    
    Returns:
        RMSE value
    """
    return np.sqrt(np.mean((y_true - y_pred) ** 2))


def calculate_mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """
    Calculate Mean Absolute Error (MAE).
    
    Args:
        y_true: True values
        y_pred: Predicted values
    
    Returns:
        MAE value
    """
    return np.mean(np.abs(y_true - y_pred))


def evaluate_model(
    y_true: np.ndarray,
    y_pred: np.ndarray,
) -> Dict[str, float]:
    """
    Calculate multiple evaluation metrics.
    
    Args:
        y_true: True values
        y_pred: Predicted values
    
    Returns:
        Dictionary with metric names and values
    """
    return {
        "mape": calculate_mape(y_true, y_pred),
        "rmse": calculate_rmse(y_true, y_pred),
        "mae": calculate_mae(y_true, y_pred),
    }

