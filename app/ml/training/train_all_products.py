from __future__ import annotations

from typing import List, Dict, Any, Optional

from sqlalchemy.orm import Session

from app.database.database import SessionLocal
from app.models import Product
from .train_product import train_product


def train_all_products(
    *,
    db: Optional[Session] = None,
    model_name: str = "prophet",
) -> List[Dict[str, Any]]:
    owns_session = False
    if db is None:
        db = SessionLocal()
        owns_session = True

    results: List[Dict[str, Any]] = []
    try:
        products = db.query(Product).order_by(Product.id.asc()).all()
        for product in products:
            try:
                result = train_product(
                    product_id=product.id,
                    db=db,
                    model_name=model_name,
                )
            except Exception as exc:
                result = {
                    "product_id": product.id,
                    "product_name": product.name,
                    "status": "failed",
                    "model_type": model_name,
                    "n_points": 0,
                    "mape": None,
                    "rmse": None,
                    "last_trained_at": None,
                    "error": str(exc),
                }
            results.append(result)
        return results
    finally:
        if owns_session:
            db.close()

