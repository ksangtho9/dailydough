from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Union


def calculate_wape(
    actual: Union[pd.Series, np.ndarray],
    predicted: Union[pd.Series, np.ndarray],
    epsilon: float = 1e-8,
) -> float:
    """
    Calculate Weighted Absolute Percentage Error (WAPE).
    
    WAPE = Σ|predicted - actual| / Σ|actual|
    
    This metric weights errors by the magnitude of actual values, making it
    more suitable for forecasting scenarios where larger values are more important.
    
    Args:
        actual: Actual/true values
        predicted: Predicted values
        epsilon: Small value to avoid division by zero (default: 1e-8)
        
    Returns:
        WAPE as a float (typically between 0 and 1, can be > 1)
        
    Raises:
        ValueError: If actual and predicted have different lengths
        ValueError: If all actual values are zero or very close to zero
    """
    # Convert to numpy arrays if needed
    if isinstance(actual, pd.Series):
        actual = actual.values
    if isinstance(predicted, pd.Series):
        predicted = predicted.values
    
    # Ensure arrays are 1D
    actual = np.asarray(actual).flatten()
    predicted = np.asarray(predicted).flatten()
    
    # Check lengths match
    if len(actual) != len(predicted):
        raise ValueError(
            f"actual and predicted must have the same length. "
            f"Got {len(actual)} and {len(predicted)}"
        )
    
    # Remove any NaN or infinite values
    valid_mask = np.isfinite(actual) & np.isfinite(predicted)
    if not np.any(valid_mask):
        return np.nan
    
    actual = actual[valid_mask]
    predicted = predicted[valid_mask]
    
    # Calculate numerator: sum of absolute errors
    numerator = np.sum(np.abs(predicted - actual))
    
    # Calculate denominator: sum of absolute actual values
    denominator = np.sum(np.abs(actual))
    
    # Handle division by zero
    if denominator < epsilon:
        # If all actuals are zero or very small, return NaN
        # Alternatively, could use a different error metric
        return np.nan
    
    wape = numerator / denominator
    return float(wape)

