from __future__ import annotations

import pickle
from pathlib import Path
from typing import Optional

from ..models.base_model import BaseForecastModel


# Model storage directory
MODEL_DIR = Path("app/models/forecast")
MODEL_DIR.mkdir(parents=True, exist_ok=True)


def get_model_path(product_id: int, version: int = 1) -> Path:
    """
    Get the file path for a model.
    
    Args:
        product_id: Product ID
        version: Model version (default: 1)
    
    Returns:
        Path to model file
    """
    return MODEL_DIR / f"product_{product_id}_v{version}.pkl"


def save_model(product_id: int, model: BaseForecastModel, version: int = 1) -> Path:
    """
    Save a trained model to disk.
    
    Args:
        product_id: Product ID
        model: Trained model object
        version: Model version (default: 1)
    
    Returns:
        Path to saved model file
    """
    model_path = get_model_path(product_id, version)
    
    with open(model_path, "wb") as f:
        pickle.dump(model, f)
    
    return model_path


def load_model(product_id: int, version: int = 1) -> Optional[BaseForecastModel]:
    """
    Load a trained model from disk.
    
    Args:
        product_id: Product ID
        version: Model version (default: 1)
    
    Returns:
        Loaded model object, or None if not found
    """
    model_path = get_model_path(product_id, version)
    
    if not model_path.exists():
        return None
    
    with open(model_path, "rb") as f:
        model = pickle.load(f)
    
    return model


def model_exists(product_id: int, version: int = 1) -> bool:
    """
    Check if a model exists for a product.
    
    Args:
        product_id: Product ID
        version: Model version (default: 1)
    
    Returns:
        True if model exists, False otherwise
    """
    model_path = get_model_path(product_id, version)
    return model_path.exists()


def delete_model(product_id: int, version: int = 1) -> bool:
    """
    Delete a model file.
    
    Args:
        product_id: Product ID
        version: Model version (default: 1)
    
    Returns:
        True if deleted, False if not found
    """
    model_path = get_model_path(product_id, version)
    
    if model_path.exists():
        model_path.unlink()
        return True
    
    return False

