from __future__ import annotations

from typing import List, Optional, Tuple
import logging

import numpy as np
import pandas as pd

logger = logging.getLogger("bakezy.feature_selection")


def compute_feature_importance(
    model,
    X: np.ndarray,
    y: np.ndarray,
    feature_names: List[str],
    model_name: str,
) -> pd.DataFrame:
    """
    Compute feature importance for a trained model.
    
    Args:
        model: Trained model (XGBoost or Prophet)
        X: Feature matrix
        y: Target values
        feature_names: List of feature names
        model_name: "xgboost" or "prophet"
        
    Returns:
        DataFrame with columns: feature_name, importance
    """
    if model_name == "xgboost":
        # Use built-in feature importances
        if hasattr(model, "feature_importances_"):
            importances = model.feature_importances_
        else:
            logger.warning("XGBoost model does not have feature_importances_")
            return pd.DataFrame(columns=["feature_name", "importance"])
    elif model_name == "prophet":
        # For Prophet, use permutation importance
        importances = compute_permutation_importance(model, X, y, feature_names)
    else:
        logger.warning(f"Unknown model type: {model_name}")
        return pd.DataFrame(columns=["feature_name", "importance"])
    
    # Create DataFrame
    importance_df = pd.DataFrame({
        "feature_name": feature_names,
        "importance": importances
    })
    
    # Sort by importance descending
    importance_df = importance_df.sort_values("importance", ascending=False)
    
    return importance_df


def compute_permutation_importance(
    model,
    X: np.ndarray,
    y: np.ndarray,
    feature_names: List[str],
    n_repeats: int = 5,
) -> np.ndarray:
    """
    Compute permutation importance for Prophet model.
    
    This is a simplified version - for full implementation, consider using
    sklearn.inspection.permutation_importance.
    """
    try:
        from sklearn.inspection import permutation_importance
        # Note: Prophet doesn't have a standard predict method for feature importance
        # This is a placeholder - may need custom implementation
        logger.warning("Permutation importance for Prophet not fully implemented")
        # Return uniform importance as fallback
        return np.ones(len(feature_names)) / len(feature_names)
    except ImportError:
        logger.warning("sklearn not available for permutation importance")
        return np.ones(len(feature_names)) / len(feature_names)


def prune_features_adaptive(
    importance_df: pd.DataFrame,
    bottom_percentile: float = 10.0,
) -> List[str]:
    """
    Prune features by dropping bottom percentile by importance.
    
    Args:
        importance_df: DataFrame with feature_name and importance columns
        bottom_percentile: Percentile to drop (default 10.0 = bottom 10%)
        
    Returns:
        List of feature names to keep
    """
    if importance_df.empty:
        return []
    
    # Calculate threshold
    threshold = np.percentile(importance_df["importance"].values, bottom_percentile)
    
    # Keep features above threshold
    features_to_keep = importance_df[importance_df["importance"] >= threshold]["feature_name"].tolist()
    
    features_removed = len(importance_df) - len(features_to_keep)
    logger.info(f"Feature pruning: removed {features_removed} features (bottom {bottom_percentile}%)")
    
    return features_to_keep

