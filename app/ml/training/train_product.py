from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Dict, Any

import numpy as np
from sqlalchemy.orm import Session

from app.database.database import SessionLocal
from app.models import Product, SalesRecord, ForecastMetrics
from app.ml.preprocessing import SalesPreprocessor, RawSalesRecord
from app.ml.trainer import ModelTrainer
from app.ml.metrics import calculate_wape


def _compute_metrics(train_result, cleaned_df) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """
    Compute MAPE, RMSE, and WAPE metrics.
    
    Returns:
        Tuple of (mape, rmse, wape) - all can be None if calculation fails
    """
    try:
        if train_result.model_name == "prophet":
            forecast_df = train_result.model.predict(0)  # includes training range
            merged = forecast_df.merge(cleaned_df, on="ds", how="inner")
            if merged.empty:
                return None, None, None
            actual = merged["y"]
            predicted = merged["yhat"]
        elif train_result.model_name == "xgboost":
            # For XGBoost, we need to predict on the training data
            if train_result.model.feature_cols is None:
                return None, None, None
            # Extract features from cleaned_df
            feature_df = cleaned_df.copy()
            X = feature_df[train_result.model.feature_cols].values
            predictions = train_result.model.model.predict(X)
            
            merged = cleaned_df.copy()
            merged["yhat"] = predictions
            actual = merged["y"]
            predicted = merged["yhat"]
        else:
            return None, None, None
        
        # Calculate RMSE
        error = predicted - actual
        rmse = float((error.pow(2).mean()) ** 0.5)

        # Calculate MAPE
        non_zero_actual = actual.replace(0, None)
        ape = (predicted - actual).abs() / non_zero_actual
        ape = ape.dropna()
        mape = float(ape.mean()) * 100 if not ape.empty else None  # Convert to percentage
        
        # Calculate WAPE
        wape = calculate_wape(actual.values, predicted.values)
        wape = float(wape) * 100 if not (wape is None or np.isnan(wape)) else None  # Convert to percentage
        
        return mape, rmse, wape
    except Exception as e:
        import logging
        logger = logging.getLogger("bakezy.training")
        logger.warning(f"Error computing metrics: {e}")
        return None, None, None


def train_product(
    *,
    product_id: int,
    db: Optional[Session] = None,
    model_name: str = "prophet",
) -> Dict[str, Any]:
    owns_session = False
    if db is None:
        db = SessionLocal()
        owns_session = True

    try:
        product = (
            db.query(Product)
            .filter(Product.id == product_id)
            .one_or_none()
        )
        if product is None:
            raise ValueError(f"Product {product_id} not found")

        # Load sales records for this product, filtering by both product_id and bakery_id
        # to ensure complete bakery isolation
        sales_rows = (
            db.query(SalesRecord)
            .filter(
                SalesRecord.product_id == product_id,
                SalesRecord.bakery_id == product.bakery_id,  # Ensure bakery isolation
            )
            .order_by(SalesRecord.date.asc())
            .all()
        )

        if not sales_rows:
            return {
                "product_id": product_id,
                "product_name": product.name,
                "status": "skipped_no_data",
                "model_type": model_name,
                "n_points": 0,
                "mape": None,
                "rmse": None,
                "wape": None,
                "last_trained_at": None,
            }

        raw_records = [
            RawSalesRecord(
                date=row.date,
                product_id=row.product_id,
                quantity=row.quantity_sold,
                quantity_delivered=row.quantity_delivered,
            )
            for row in sales_rows
        ]

        preprocessor = SalesPreprocessor()
        cleaned = preprocessor.preprocess(raw_records, product_id=product_id)
        if cleaned.df.empty:
            return {
                "product_id": product_id,
                "product_name": product.name,
                "status": "skipped_no_timeseries",
                "model_type": model_name,
                "n_points": 0,
                "mape": None,
                "rmse": None,
                "wape": None,
                "last_trained_at": None,
            }

        trainer = ModelTrainer()
        train_result = trainer.train(cleaned, model_name=model_name, optimize_with_wape=True)

        mape, rmse, wape = _compute_metrics(train_result, cleaned.df)
        trained_at = datetime.now(timezone.utc)

        metrics = (
            db.query(ForecastMetrics)
            .filter(ForecastMetrics.product_id == product_id)
            .one_or_none()
        )
        if metrics is None:
            metrics = ForecastMetrics(product_id=product_id)
            db.add(metrics)

        metrics.mape = mape
        metrics.rmse = rmse
        metrics.wape = wape
        metrics.n_points = len(cleaned.df)
        metrics.model_type = train_result.model_name
        metrics.status = "ok"
        metrics.last_trained_at = trained_at

        db.commit()
        db.refresh(metrics)

        return {
            "product_id": product_id,
            "product_name": product.name,
            "status": "ok",
            "model_type": train_result.model_name,
            "n_points": len(cleaned.df),
            "mape": mape,
            "rmse": rmse,
            "wape": wape,
            "last_trained_at": trained_at,
        }
    finally:
        if owns_session:
            db.close()

