from __future__ import annotations

from typing import List, Optional
from sqlalchemy.orm import Session

from app.models import Product
from .train_product import train_product, TrainResult

ModelName = str  # "prophet", "lightgbm", etc.


def train_all_products(
    db: Session,
    model_name: ModelName = "prophet",
    product_ids: Optional[List[int]] = None,
) -> List[TrainResult]:
    """
    Loop over all products and call train_product(product.id).
    
    Reuses the actual DB/session access pattern from the current codebase.
    
    Args:
        db: Database session
        model_name: Model to train (default: "prophet")
        product_ids: Optional list of product IDs to train. If None, trains all products.
    
    Returns:
        List of TrainResult objects
    """
    results = []
    
    # Get product IDs
    if product_ids is None:
        products = db.query(Product).all()
        product_ids = [p.id for p in products]
    
    for product_id in product_ids:
        try:
            # Train product using the main training function
            result = train_product(db, product_id, model_name=model_name)
            results.append(result)
            print(f"Trained {model_name} for product {product_id}")
            
        except Exception as e:
            print(f"Failed to train product {product_id}: {e}")
            continue
    
    return results

