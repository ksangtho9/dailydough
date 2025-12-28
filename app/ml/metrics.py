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
    
    # Ensure arrays are numeric - convert to numeric, coercing errors to NaN
    actual = pd.to_numeric(actual, errors='coerce')
    predicted = pd.to_numeric(predicted, errors='coerce')
    
    # Convert to numpy arrays and ensure 1D
    actual = np.asarray(actual, dtype=np.float64).flatten()
    predicted = np.asarray(predicted, dtype=np.float64).flatten()
    
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


def calculate_adjusted_wape(
    actual: Union[pd.Series, np.ndarray],
    predicted: Union[pd.Series, np.ndarray],
    is_supply_capped: Union[pd.Series, np.ndarray],
    capped_overpred_penalty: float = 0.2,
    epsilon: float = 1e-8,
) -> Optional[float]:
    """
    Calculate Censor-Aware Weighted Absolute Percentage Error (Adjusted WAPE).
    
    This metric adjusts error calculation for supply-capped days where sales may be
    constrained by delivery quantity rather than true demand.
    
    Adjusted WAPE = Σ(adjusted_errors) / Σ(actual_sales)
    
    Where adjusted_errors are:
    - Normal days: error = abs(prediction - actual)
    - Supply-capped days:
      - If prediction > actual (over-prediction): error = abs(pred - actual) * capped_overpred_penalty
      - If prediction <= actual (under-prediction): error = abs(pred - actual) (full penalty)
    
    Args:
        actual: Actual/true values
        predicted: Predicted values
        is_supply_capped: Boolean array indicating supply-capped days (1 = capped, 0 = normal)
        capped_overpred_penalty: Penalty multiplier for over-prediction on capped days (default 0.2)
            - 0.2 = soft censor (80% penalty reduction)
            - 0.0 = hard censor (no penalty for over-prediction)
        epsilon: Small value to avoid division by zero (default: 1e-8)
        
    Returns:
        Adjusted WAPE as a float, or None if denominator is zero
        
    Raises:
        ValueError: If actual, predicted, and is_supply_capped have different lengths
    """
    # Convert to numpy arrays if needed
    if isinstance(actual, pd.Series):
        actual = actual.values
    if isinstance(predicted, pd.Series):
        predicted = predicted.values
    if isinstance(is_supply_capped, pd.Series):
        is_supply_capped = is_supply_capped.values
    
    # Ensure arrays are numeric
    actual = pd.to_numeric(actual, errors='coerce')
    predicted = pd.to_numeric(predicted, errors='coerce')
    is_supply_capped = pd.to_numeric(is_supply_capped, errors='coerce')
    
    # Convert to numpy arrays and ensure 1D
    actual = np.asarray(actual, dtype=np.float64).flatten()
    predicted = np.asarray(predicted, dtype=np.float64).flatten()
    is_supply_capped = np.asarray(is_supply_capped, dtype=np.float64).flatten()
    
    # Check lengths match
    if len(actual) != len(predicted) or len(actual) != len(is_supply_capped):
        raise ValueError(
            f"actual, predicted, and is_supply_capped must have the same length. "
            f"Got {len(actual)}, {len(predicted)}, {len(is_supply_capped)}"
        )
    
    # Remove any NaN or infinite values
    valid_mask = np.isfinite(actual) & np.isfinite(predicted) & np.isfinite(is_supply_capped)
    if not np.any(valid_mask):
        return None
    
    actual = actual[valid_mask]
    predicted = predicted[valid_mask]
    is_supply_capped = is_supply_capped[valid_mask]
    
    # Calculate adjusted errors
    errors = np.abs(predicted - actual)
    adjusted_errors = errors.copy()
    
    # For supply-capped days with over-prediction, apply penalty multiplier
    capped_mask = is_supply_capped == 1
    overpred_mask = capped_mask & (predicted > actual)
    adjusted_errors[overpred_mask] = errors[overpred_mask] * capped_overpred_penalty
    
    # Calculate numerator: sum of adjusted errors
    numerator = np.sum(adjusted_errors)
    
    # Calculate denominator: sum of absolute actual values
    denominator = np.sum(np.abs(actual))
    
    # Guard against denominator=0
    if denominator < epsilon:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(
            "Adjusted WAPE calculation failed: sum of actual sales is zero or very small. "
            "Returning None."
        )
        return None
    
    adjusted_wape = numerator / denominator
    return float(adjusted_wape)

