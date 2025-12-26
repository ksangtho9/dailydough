from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Dict, Any

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.database.database import SessionLocal
from app.models import Product, SalesRecord, ForecastMetrics
from app.ml.preprocessing import SalesPreprocessor, RawSalesRecord
from app.ml.trainer import ModelTrainer
from app.ml.metrics import calculate_wape
import logging

logger = logging.getLogger("bakezy.training")


def _compute_metrics(train_result, cleaned_df) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """
    Compute MAPE, RMSE, and WAPE metrics.
    
    Returns:
        Tuple of (mape, rmse, wape) - all can be None if calculation fails
    """
    # Ensure pandas is available (explicit reference to avoid local variable issues)
    _ = pd  # noqa: F841
    try:
        if train_result.model_name == "prophet":
            forecast_df = train_result.model.predict(0)  # includes training range
            # Include is_valid_day in merge if present
            merge_cols = ["ds", "y"]
            if "is_valid_day" in cleaned_df.columns:
                merge_cols.append("is_valid_day")
            merged = forecast_df.merge(cleaned_df[merge_cols], on="ds", how="inner")
            if merged.empty:
                return None, None, None
            # Filter to valid days only for metrics
            if "is_valid_day" in merged.columns:
                merged = merged[merged["is_valid_day"] == 1]
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
            # Filter to valid days for prediction and metrics
            if "is_valid_day" in feature_df.columns:
                feature_df = feature_df[feature_df["is_valid_day"] == 1].copy()
            if feature_df.empty:
                return None, None, None
            X = feature_df[train_result.model.feature_cols].values
            predictions = train_result.model.model.predict(X)
            
            merged = feature_df.copy()
            merged["yhat"] = predictions
            actual = merged["y"]
            predicted = merged["yhat"]
        elif train_result.model_name == "ensemble":
            # For ensemble, we need to generate predictions on training data
            # Create a future_df with same dates as training data
            from datetime import timedelta
            from app.ml.features import FeatureEngineer
            
            future_df = cleaned_df[["ds"]].copy()
            feature_engineer = FeatureEngineer()
            future_df = feature_engineer.transform(future_df)
            
            # Get historical delivery if available
            historical_delivery = None
            if "delivery" in cleaned_df.columns:
                historical_delivery = cleaned_df["delivery"]
            
            # Use ensemble to predict
            forecast_df = train_result.model.predict(
                historical_df=cleaned_df,
                future_df=future_df,
                horizon_days=len(cleaned_df),
                future_regressors=future_df,
                historical_delivery=historical_delivery,
            )
            
            # Merge with actuals
            forecast_df["ds"] = pd.to_datetime(forecast_df["ds"])
            cleaned_df["ds"] = pd.to_datetime(cleaned_df["ds"])
            merge_cols = ["ds", "y"]
            if "is_valid_day" in cleaned_df.columns:
                merge_cols.append("is_valid_day")
            merged = forecast_df.merge(cleaned_df[merge_cols], on="ds", how="inner")
            if merged.empty:
                return None, None, None
            # Filter to valid days only for metrics
            if "is_valid_day" in merged.columns:
                merged = merged[merged["is_valid_day"] == 1]
            if merged.empty:
                return None, None, None
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
        # Ensure numeric types
        actual_numeric = pd.to_numeric(actual.values, errors='coerce')
        predicted_numeric = pd.to_numeric(predicted.values, errors='coerce')
        wape = calculate_wape(actual_numeric, predicted_numeric)
        # Safe NaN check using pandas
        wape = float(wape) * 100 if (wape is not None and pd.notna(wape)) else None  # Convert to percentage
        
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
        
        # Initial training
        train_result = trainer.train(cleaned, model_name=model_name, optimize_with_wape=True)
        
        # Feature pruning (adaptive: drop bottom 10%) - only for XGBoost
        if model_name == "xgboost" and train_result.model.feature_cols is not None:
            from app.ml.feature_selection import compute_feature_importance, prune_features_adaptive
            
            # Get training data with features
            feature_df = cleaned.df.copy()
            if "is_valid_day" in feature_df.columns:
                feature_df = feature_df[feature_df["is_valid_day"] == 1].copy()
            
            if not feature_df.empty and len(train_result.model.feature_cols) > 5:
                try:
                    # Compute feature importance
                    X = feature_df[train_result.model.feature_cols].values
                    y = feature_df["y"].values
                    
                    importance_df = compute_feature_importance(
                        model=train_result.model.model,
                        X=X,
                        y=y,
                        feature_names=train_result.model.feature_cols,
                        model_name="xgboost",
                    )
                    
                    # Prune features (drop bottom 10%)
                    features_to_keep = prune_features_adaptive(importance_df, bottom_percentile=10.0)
                    
                    original_feature_count = len(train_result.model.feature_cols)
                    if len(features_to_keep) < original_feature_count and len(features_to_keep) > 0:
                        # Retrain model with pruned features
                        X_pruned = feature_df[features_to_keep].values
                        train_result.model.model.fit(X_pruned, y)
                        # Update feature_cols in model after retraining
                        train_result.model.feature_cols = features_to_keep
                        logger.info(f"Feature pruning: retrained with {len(features_to_keep)} features (removed {original_feature_count - len(features_to_keep)})")
                except Exception as e:
                    logger.warning(f"Feature pruning failed: {e}, continuing with all features")
        
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
        # Count only valid days for n_points
        if "is_valid_day" in cleaned.df.columns:
            metrics.n_points = len(cleaned.df[cleaned.df["is_valid_day"] == 1])
        else:
            metrics.n_points = len(cleaned.df)
        metrics.model_type = train_result.model_name
        metrics.status = "ok"
        metrics.last_trained_at = trained_at

        db.commit()
        db.refresh(metrics)

        # Count only valid days for n_points
        if "is_valid_day" in cleaned.df.columns:
            n_points = len(cleaned.df[cleaned.df["is_valid_day"] == 1])
        else:
            n_points = len(cleaned.df)
        
        return {
            "product_id": product_id,
            "product_name": product.name,
            "status": "ok",
            "model_type": train_result.model_name,
            "n_points": n_points,
            "mape": mape,
            "rmse": rmse,
            "wape": wape,
            "last_trained_at": trained_at,
        }
    finally:
        if owns_session:
            db.close()

