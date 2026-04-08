from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Dict, Any
import time

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.database.database import SessionLocal
from app.models import Product, SalesRecord, ForecastMetrics, ModelRun
from app.ml.preprocessing import SalesPreprocessor, RawSalesRecord
from app.ml.trainer import ModelTrainer
from app.ml.metrics import calculate_wape, calculate_adjusted_wape
from app.services.admin_training_jobs import CancelledError
import logging
import numpy as np
import hashlib

logger = logging.getLogger("bakezy.training")


def _compute_raw_prediction_stats_future(
    raw_yhat_values: np.ndarray,
    model_name: str,
    feature_version: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Compute raw prediction statistics for the future forecast slice.
    
    Args:
        raw_yhat_values: Raw predictions (before clamping) for future dates
        model_name: Name of the model used
        feature_version: Feature version used
    
    Returns:
        Dictionary with raw prediction stats, or None if computation fails.
    """
    if raw_yhat_values is None or len(raw_yhat_values) == 0:
        return None
    
    # Compute statistics
    raw_neg_pct = (raw_yhat_values < 0).sum() / len(raw_yhat_values) * 100
    raw_zero_pct = (raw_yhat_values == 0.0).sum() / len(raw_yhat_values) * 100
    
    yhat_values = np.maximum(raw_yhat_values, 0.0)  # After clamping
    clamped_zero_pct = (yhat_values == 0.0).sum() / len(yhat_values) * 100
    
    min_raw_yhat = float(np.min(raw_yhat_values))
    mean_raw_yhat = float(np.mean(raw_yhat_values))
    max_raw_yhat = float(np.max(raw_yhat_values))
    
    # Compute percentiles
    sorted_raw = np.sort(raw_yhat_values)
    raw_p05 = float(np.percentile(sorted_raw, 5)) if len(sorted_raw) > 0 else None
    raw_p50 = float(np.percentile(sorted_raw, 50)) if len(sorted_raw) > 0 else None
    raw_p95 = float(np.percentile(sorted_raw, 95)) if len(sorted_raw) > 0 else None
    
    return {
        "raw_min": min_raw_yhat,
        "raw_mean": mean_raw_yhat,
        "raw_p05": raw_p05,
        "raw_p50": raw_p50,
        "raw_p95": raw_p95,
        "raw_max": max_raw_yhat,
        "raw_neg_pct": float(raw_neg_pct),
        "raw_zero_pct": float(raw_zero_pct),
        "clamped_zero_pct": float(clamped_zero_pct),
        "n_points_future": int(len(raw_yhat_values)),  # Ensure Python int for JSON serialization
        "model_name": model_name,
        "feature_version": feature_version,
    }


def _compute_raw_prediction_stats_eval(
    train_result,
    train_df_for_analysis: pd.DataFrame,
    model_name: str,
) -> Optional[Dict[str, Any]]:
    """
    Compute raw prediction statistics for the evaluation (training) slice.
    
    Returns a dictionary with raw prediction stats, or None if computation fails.
    """
    if train_df_for_analysis.empty or "y" not in train_df_for_analysis.columns:
        return None
    
    raw_yhat_values = None
    yhat_values = None
    
    try:
        if model_name == "prophet":
            # Prophet: Get predictions for training period
            forecast_df = train_result.model.predict(0)  # includes training range
            if not forecast_df.empty and "yhat" in forecast_df.columns:
                # Merge with training dates
                merged = forecast_df.merge(
                    train_df_for_analysis[["ds", "y"]], 
                    on="ds", 
                    how="inner"
                )
                if not merged.empty:
                    raw_yhat_values = merged["yhat"].values  # Before clamping
                    yhat_values = np.maximum(raw_yhat_values, 0.0)  # After clamping
        elif model_name == "xgboost":
            # XGBoost: Predict on training data
            if train_result.model.feature_cols is not None:
                # Need to apply feature engineering to get predictions
                from app.ml.features import FeatureEngineer
                feature_engineer = FeatureEngineer()
                feature_df = train_df_for_analysis.copy()
                feature_df["ds"] = pd.to_datetime(feature_df["ds"])
                feature_df = feature_engineer.transform(feature_df)
                
                X = feature_df[train_result.model.feature_cols].values
                raw_yhat_values = train_result.model.model.predict(X)  # Can be negative
                yhat_values = np.maximum(raw_yhat_values, 0.0)  # After clamping
        elif model_name == "ensemble":
            # Ensemble: Use ensemble prediction
            from app.ml.features import FeatureEngineer
            feature_engineer = FeatureEngineer()
            feature_df = train_df_for_analysis.copy()
            feature_df["ds"] = pd.to_datetime(feature_df["ds"])
            feature_df = feature_engineer.transform(feature_df)
            
            # Get ensemble predictions
            predictions = train_result.model.predict(feature_df)
            if predictions is not None and len(predictions) > 0:
                raw_yhat_values = np.array(predictions)  # Can be negative
                yhat_values = np.maximum(raw_yhat_values, 0.0)  # After clamping
        elif model_name in ["seasonal_naive", "rolling_mean"]:
            # Baseline models: predict on training data dates
            # Get last date from training data
            if not train_df_for_analysis.empty and "ds" in train_df_for_analysis.columns:
                last_date = pd.to_datetime(train_df_for_analysis["ds"].max())
                horizon_days = len(train_df_for_analysis)
                forecast_df = train_result.model.predict(horizon_days, last_date=last_date)
                if not forecast_df.empty and "yhat" in forecast_df.columns:
                    # Merge with training dates to get aligned predictions
                    merged = forecast_df.merge(
                        train_df_for_analysis[["ds"]], 
                        on="ds", 
                        how="inner"
                    )
                    if not merged.empty:
                        raw_yhat_values = merged["yhat"].values  # Can be negative
                        yhat_values = np.maximum(raw_yhat_values, 0.0)  # After clamping
    except Exception as e:
        logger.warning(f"Could not compute raw prediction stats for eval slice: {e}")
        return None
    
    if raw_yhat_values is None or len(raw_yhat_values) == 0:
        return None
    
    # Compute statistics
    raw_neg_pct = (raw_yhat_values < 0).sum() / len(raw_yhat_values) * 100
    raw_zero_pct = (raw_yhat_values == 0.0).sum() / len(raw_yhat_values) * 100
    clamped_zero_pct = (yhat_values == 0.0).sum() / len(yhat_values) * 100 if yhat_values is not None else 0.0
    
    min_raw_yhat = float(np.min(raw_yhat_values))
    mean_raw_yhat = float(np.mean(raw_yhat_values))
    max_raw_yhat = float(np.max(raw_yhat_values))
    
    # Compute percentiles
    sorted_raw = np.sort(raw_yhat_values)
    raw_p05 = float(np.percentile(sorted_raw, 5)) if len(sorted_raw) > 0 else None
    raw_p50 = float(np.percentile(sorted_raw, 50)) if len(sorted_raw) > 0 else None
    raw_p95 = float(np.percentile(sorted_raw, 95)) if len(sorted_raw) > 0 else None
    
    return {
        "raw_min": min_raw_yhat,
        "raw_mean": mean_raw_yhat,
        "raw_p05": raw_p05,
        "raw_p50": raw_p50,
        "raw_p95": raw_p95,
        "raw_max": max_raw_yhat,
        "raw_neg_pct": float(raw_neg_pct),
        "raw_zero_pct": float(raw_zero_pct),
        "clamped_zero_pct": float(clamped_zero_pct),
        "n_points_eval": int(len(raw_yhat_values)),  # Ensure Python int for JSON serialization
    }


def _compute_metrics(train_result, cleaned_df) -> tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """
    Compute MAPE, RMSE, WAPE, and Adjusted WAPE metrics.
    
    Returns:
        Tuple of (mape, rmse, wape, wape_adjusted) - all can be None if calculation fails
    """
    # Ensure pandas is available (explicit reference to avoid local variable issues)
    _ = pd  # noqa: F841
    try:
        if train_result.model_name == "prophet":
            forecast_df = train_result.model.predict(0)  # includes training range
            # Include is_valid_day and is_supply_capped_day in merge if present
            merge_cols = ["ds", "y"]
            if "is_valid_day" in cleaned_df.columns:
                merge_cols.append("is_valid_day")
            if "is_supply_capped_day" in cleaned_df.columns:
                merge_cols.append("is_supply_capped_day")
            merged = forecast_df.merge(cleaned_df[merge_cols], on="ds", how="inner")
            if merged.empty:
                return None, None, None, None
            # Filter to valid days only for metrics
            if "is_valid_day" in merged.columns:
                merged = merged[merged["is_valid_day"] == 1]
            if merged.empty:
                return None, None, None, None
            actual = merged["y"]
            predicted = merged["yhat"]
            is_supply_capped = merged["is_supply_capped_day"] if "is_supply_capped_day" in merged.columns else pd.Series([0] * len(merged))
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
                return None, None, None, None
            X = feature_df[train_result.model.feature_cols].values
            predictions = train_result.model.model.predict(X)
            
            merged = feature_df.copy()
            merged["yhat"] = predictions
            actual = merged["y"]
            predicted = merged["yhat"]
            is_supply_capped = merged["is_supply_capped_day"] if "is_supply_capped_day" in merged.columns else pd.Series([0] * len(merged))
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
            if "is_supply_capped_day" in cleaned_df.columns:
                merge_cols.append("is_supply_capped_day")
            merged = forecast_df.merge(cleaned_df[merge_cols], on="ds", how="inner")
            if merged.empty:
                return None, None, None, None
            # Filter to valid days only for metrics
            if "is_valid_day" in merged.columns:
                merged = merged[merged["is_valid_day"] == 1]
            if merged.empty:
                return None, None, None, None
            actual = merged["y"]
            predicted = merged["yhat"]
            is_supply_capped = merged["is_supply_capped_day"] if "is_supply_capped_day" in merged.columns else pd.Series([0] * len(merged))
        else:
            return None, None, None, None
        
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
        
        # Calculate Adjusted WAPE (censor-aware)
        is_supply_capped_numeric = pd.to_numeric(is_supply_capped.values, errors='coerce')
        wape_adjusted = calculate_adjusted_wape(
            actual_numeric,
            predicted_numeric,
            is_supply_capped_numeric,
            capped_overpred_penalty=0.2,  # Default soft censor
        )
        # Safe NaN check using pandas
        wape_adjusted = float(wape_adjusted) * 100 if (wape_adjusted is not None and pd.notna(wape_adjusted)) else None  # Convert to percentage
        
        return mape, rmse, wape, wape_adjusted
    except Exception as e:
        import logging
        logger = logging.getLogger("bakezy.training")
        logger.warning(f"Error computing metrics: {e}")
        return None, None, None, None


def train_product(
    *,
    product_id: int,
    db: Optional[Session] = None,
    model_name: str = "prophet",
    job_id: Optional[str] = None,  # New parameter: job_id for cancellation
    optimize_hyperparameters: str = "auto",  # "auto", "true", or "false"
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
                "wape_adjusted": None,
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

        # Timing: Start total time
        total_start_time = time.time()
        
        # Timing: Feature engineering
        fe_start_time = time.time()
        preprocessor = SalesPreprocessor()
        cleaned = preprocessor.preprocess(raw_records, product_id=product_id)
        fe_duration = time.time() - fe_start_time
        logger.info(f"Product {product_id}: Feature engineering took {fe_duration:.2f}s")
        
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
                "wape_adjusted": None,
                "last_trained_at": None,
            }

        # Create cancellation callback
        def should_cancel() -> bool:
            if job_id:
                from app.services.admin_training_jobs import job_manager
                return job_manager.is_cancelled(job_id)
            return False
        
        # Check cancellation before training
        if should_cancel():
            raise CancelledError("Training cancelled by user")
        
        trainer = ModelTrainer()
        
        # Note: Sample weights are computed INSIDE trainer.train() after feature engineering
        # to ensure perfect alignment with training data. We pass a flag to indicate
        # that weights should be computed from the cleaned time series.
        
        # Timing: Training (includes optimization if enabled)
        training_start_time = time.time()
        train_result = trainer.train(
            cleaned, 
            model_name=model_name, 
            optimize_with_wape=True,
            sample_weights=None,  # Will be computed inside trainer after feature engineering
            should_cancel=should_cancel,  # Pass cancellation callback
            optimize_hyperparameters=optimize_hyperparameters,  # Pass optimization flag
            db=db,  # Pass db for ModelRun queries
            product_id=product_id,  # Pass product_id for ModelRun queries
        )
        training_duration = time.time() - training_start_time
        logger.info(f"Product {product_id}: Training (including optimization) took {training_duration:.2f}s")
        
        # Check cancellation after training
        if should_cancel():
            raise CancelledError("Training cancelled by user")
        
        # Feature pruning (adaptive: drop bottom 10%) - only for XGBoost
        # Use train_result.model_name (actual) not model_name (requested) — guardrail may have fallen back
        if train_result.model_name == "xgboost" and train_result.model.feature_cols is not None:
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
        
        # Timing: Metrics computation
        metrics_start_time = time.time()
        mape, rmse, wape, wape_adjusted = _compute_metrics(train_result, cleaned.df)
        metrics_duration = time.time() - metrics_start_time
        logger.info(f"Product {product_id}: Metrics computation took {metrics_duration:.2f}s")
        
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
        metrics.wape_adjusted = wape_adjusted
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

        # Get training data (valid days only) for analysis - needed for raw prediction stats and logging
        # Initialize before try block so it's available for logging even if ModelRun save fails
        train_df_for_analysis = cleaned.df.copy()
        if "is_valid_day" in train_df_for_analysis.columns:
            train_df_for_analysis = train_df_for_analysis[train_df_for_analysis["is_valid_day"] == 1].copy()
        
        # Initialize raw_prediction_stats_eval to None (will be computed in try block)
        raw_prediction_stats_eval = None

        # Save ModelRun with hyperparameters and metadata
        try:
            # Extract hyperparameters from trained model
            hyperparams = {}
            if train_result.model_name == "prophet":
                if hasattr(train_result.model, 'config') and train_result.model.config:
                    config = train_result.model.config
                    hyperparams["prophet"] = {
                        "changepoint_prior_scale": config.changepoint_prior_scale,
                        "seasonality_mode": config.seasonality_mode,
                        "daily_seasonality": config.daily_seasonality,
                        "weekly_seasonality": config.weekly_seasonality,
                        "yearly_seasonality": config.yearly_seasonality,
                        "monthly_seasonality": getattr(config, 'monthly_seasonality', False),
                        "quarterly_seasonality": getattr(config, 'quarterly_seasonality', False),
                    }
            elif train_result.model_name == "xgboost":
                if hasattr(train_result.model, 'config') and train_result.model.config:
                    config = train_result.model.config
                    hyperparams["xgboost"] = {
                        "max_depth": config.max_depth,
                        "n_estimators": config.n_estimators,
                        "learning_rate": config.learning_rate,
                        "subsample": config.subsample,
                        "colsample_bytree": config.colsample_bytree,
                        "use_wape_loss": config.use_wape_loss,
                    }
            elif train_result.model_name == "ensemble":
                # Ensemble may have both Prophet and XGBoost configs
                if hasattr(train_result.model, 'prophet_model') and hasattr(train_result.model.prophet_model, 'config'):
                    config = train_result.model.prophet_model.config
                    hyperparams["prophet"] = {
                        "changepoint_prior_scale": config.changepoint_prior_scale,
                        "seasonality_mode": config.seasonality_mode,
                        "daily_seasonality": config.daily_seasonality,
                        "weekly_seasonality": config.weekly_seasonality,
                        "yearly_seasonality": config.yearly_seasonality,
                    }
                if hasattr(train_result.model, 'xgboost_model') and hasattr(train_result.model.xgboost_model, 'config'):
                    config = train_result.model.xgboost_model.config
                    hyperparams["xgboost"] = {
                        "max_depth": config.max_depth,
                        "n_estimators": config.n_estimators,
                        "learning_rate": config.learning_rate,
                        "subsample": config.subsample,
                        "colsample_bytree": config.colsample_bytree,
                        "use_wape_loss": config.use_wape_loss,
                    }
                if hasattr(train_result.model, 'config') and train_result.model.config:
                    config = train_result.model.config
                    hyperparams["ensemble"] = {
                        "prophet_weight": getattr(config, 'prophet_weight', 0.5),
                        "xgboost_weight": getattr(config, 'xgboost_weight', 0.5),
                    }

            # Determine selected_model_type (actual model used after gating/fallback)
            selected_model_type = train_result.model_name

            # Compute feature_version (hash of feature column names)
            feature_version = None
            if train_result.model_name == "xgboost" and hasattr(train_result.model, 'feature_cols') and train_result.model.feature_cols:
                # Use feature columns from XGBoost model
                sorted_cols = sorted(train_result.model.feature_cols)
                cols_str = ",".join(sorted_cols)
                feature_version = hashlib.md5(cols_str.encode()).hexdigest()[:8]
            elif train_result.model_name == "prophet":
                # For Prophet, we can use a default version or check regressors
                # For now, use a simple version string
                feature_version = "v1"
            elif train_result.model_name in ["seasonal_naive", "rolling_mean"]:
                # Baseline models don't use features
                feature_version = "baseline"
            else:
                feature_version = "v1"

            # Get training window end date
            training_window_end = None
            if not cleaned.df.empty and "ds" in cleaned.df.columns:
                training_window_end = pd.to_datetime(cleaned.df["ds"].max()).date()

            # Mark previous runs as inactive
            db.query(ModelRun).filter(
                ModelRun.product_id == product_id,
                ModelRun.is_active == True
            ).update({"is_active": False})

            # Compute raw prediction stats for eval slice BEFORE building metrics_json_data
            # train_df_for_analysis is already defined above
            raw_prediction_stats_eval = _compute_raw_prediction_stats_eval(
                train_result,
                train_df_for_analysis,
                train_result.model_name,
            )

            # Build enhanced metrics_json with diagnostic information
            metrics_json_data = {
                "wape": float(wape) if wape is not None else None,
                "wape_adjusted": float(wape_adjusted) if wape_adjusted is not None else None,
                "mape": float(mape) if mape is not None else None,
                "rmse": float(rmse) if rmse is not None else None,
            }
            
            # Add training data summary if available
            if not train_df_for_analysis.empty and "y" in train_df_for_analysis.columns:
                total_training_days = len(train_df_for_analysis)
                nonzero_days = (train_df_for_analysis["y"] > 0).sum()
                zero_rate = (train_df_for_analysis["y"] == 0.0).sum() / total_training_days * 100 if total_training_days > 0 else 0.0
                mean_y = float(train_df_for_analysis["y"].mean()) if total_training_days > 0 else 0.0
                median_y = float(train_df_for_analysis["y"].median()) if total_training_days > 0 else 0.0
                max_y = float(train_df_for_analysis["y"].max()) if total_training_days > 0 else 0.0
                
                is_valid_day_count = total_training_days
                supply_capped_count = 0
                supply_capped_pct = 0.0
                if "is_supply_capped_day" in train_df_for_analysis.columns:
                    supply_capped_count = int((train_df_for_analysis["is_supply_capped_day"] == 1).sum())  # Convert numpy int64 to Python int
                    supply_capped_pct = float((supply_capped_count / total_training_days * 100) if total_training_days > 0 else 0.0)
                
                metrics_json_data["training_data_summary"] = {
                    "total_training_days": int(total_training_days),  # Ensure Python int
                    "nonzero_days": int(nonzero_days),  # Already converted, but ensure int
                    "zero_rate": float(zero_rate),
                    "mean_y": mean_y,
                    "median_y": median_y,
                    "max_y": max_y,
                    "is_valid_day_count": int(is_valid_day_count),  # Ensure Python int
                    "supply_capped_count": int(supply_capped_count),  # Ensure Python int
                    "supply_capped_pct": float(supply_capped_pct),  # Ensure Python float
                }
            
            # Add raw prediction summary for eval slice if available
            if raw_prediction_stats_eval is not None:
                # Ensure all values in raw_prediction_stats_eval are JSON-serializable (convert numpy types)
                cleaned_stats = {}
                for k, v in raw_prediction_stats_eval.items():
                    if isinstance(v, (np.integer, np.int64, np.int32)):
                        cleaned_stats[k] = int(v)
                    elif isinstance(v, (np.floating, np.float64, np.float32)):
                        cleaned_stats[k] = float(v)
                    elif isinstance(v, np.ndarray):
                        cleaned_stats[k] = v.tolist()  # Convert arrays to lists
                    else:
                        cleaned_stats[k] = v
                metrics_json_data["raw_prediction_summary_eval"] = {
                    **cleaned_stats,
                    "model_name": train_result.model_name,
                    "feature_version": feature_version,
                }
            
            # Add model selection path from metadata
            if train_result.metadata and "model_selection_path" in train_result.metadata:
                metrics_json_data["model_selection_path"] = train_result.metadata["model_selection_path"]
            
            # Create new ModelRun
            model_run = ModelRun(
                product_id=product_id,
                created_at=trained_at,
                model_type=model_name,  # Requested model
                selected_model_type=selected_model_type,  # Actual model used
                hyperparameters_json=hyperparams if hyperparams else None,
                training_window_end=training_window_end,
                feature_version=feature_version,
                metrics_json=metrics_json_data,
                is_active=True,
                is_best=False,  # Can be set later if we implement best run tracking
            )
            db.add(model_run)
            db.commit()
            logger.info(f"Saved ModelRun for product {product_id}: model_type={model_name}, selected={selected_model_type}, hyperparams={bool(hyperparams)}")
            
            # Dense Product Sanity Trigger: Warn if healthy training data but high zero forecasts
            if (raw_prediction_stats_eval is not None and 
                not train_df_for_analysis.empty and "y" in train_df_for_analysis.columns):
                mean_y_train = float(train_df_for_analysis["y"].mean())
                zero_rate_train = (train_df_for_analysis["y"] == 0.0).sum() / len(train_df_for_analysis) * 100
                clamped_zero_pct_eval = raw_prediction_stats_eval.get("clamped_zero_pct", 0.0)
                
                # Check eval slice for now (will check future slice when available)
                if (mean_y_train > 5 and 
                    zero_rate_train < 30.0 and 
                    clamped_zero_pct_eval > 50.0):
                    logger.warning(
                        f"DENSE_PRODUCT_ZERO_FORECAST: Product {product_id} has healthy training data "
                        f"(mean_y={mean_y_train:.2f}, zero_rate={zero_rate_train:.1f}%) but "
                        f"{clamped_zero_pct_eval:.1f}% of eval forecasts are clamped to zero. "
                        f"Likely negative clamp or future regressor drift."
                    )
        except Exception as e:
            logger.warning(f"Failed to save ModelRun for product {product_id}: {e}")
            # Don't fail training if ModelRun save fails
            db.rollback()

        # Count only valid days for n_points
        if "is_valid_day" in cleaned.df.columns:
            n_points = len(cleaned.df[cleaned.df["is_valid_day"] == 1])
        else:
            n_points = len(cleaned.df)
        
        # Enhanced post-training logging: Comprehensive metrics to distinguish data problems vs model bugs
        # train_df_for_analysis is already defined above, reuse it
        if not train_df_for_analysis.empty and "y" in train_df_for_analysis.columns:
            # Training data statistics
            zero_count = (train_df_for_analysis["y"] == 0.0).sum()
            total_count = len(train_df_for_analysis)
            zero_pct = (zero_count / total_count * 100) if total_count > 0 else 0
            mean_y = train_df_for_analysis["y"].mean() if total_count > 0 else 0
            median_y = train_df_for_analysis["y"].median() if total_count > 0 else 0
            
            # Supply-capped statistics
            capped_count = 0
            capped_pct = 0
            if "is_supply_capped_day" in train_df_for_analysis.columns:
                capped_count = int((train_df_for_analysis["is_supply_capped_day"] == 1).sum())
                capped_pct = (capped_count / total_count * 100) if total_count > 0 else 0
            
            # Use raw prediction stats from eval slice (already computed above)
            yhat_mean = None
            yhat_zero_pct = None
            raw_yhat_neg_pct = None
            
            if raw_prediction_stats_eval is not None:
                yhat_mean = raw_prediction_stats_eval.get("raw_mean")
                yhat_zero_pct = raw_prediction_stats_eval.get("clamped_zero_pct")
                raw_yhat_neg_pct = raw_prediction_stats_eval.get("raw_neg_pct")
            
            # Log comprehensive metrics (on consistent evaluation set: training fitted values)
            log_msg = (
                f"Product {product_id} training metrics [training_fitted]:\n"
                f"  Training data: {total_count} unique days, "
                f"{zero_count} zeros ({zero_pct:.1f}%), "
                f"mean y={mean_y:.2f}, median y={median_y:.2f}"
            )
            
            if capped_count > 0:
                log_msg += f"\n  Supply-capped: {capped_count} days ({capped_pct:.1f}%)"
            
            if yhat_mean is not None:
                log_msg += (
                    f"\n  Predictions: mean yhat={yhat_mean:.2f}"
                )
                if raw_yhat_neg_pct is not None:
                    log_msg += f", {raw_yhat_neg_pct:.1f}% raw_yhat<0 (negative before clamp)"
                if yhat_zero_pct is not None:
                    log_msg += f", {yhat_zero_pct:.1f}% yhat==0 (after clamp)"
            
            logger.info(log_msg)
            
            # Guardrail warning: Model predicting too many zeros relative to training data
            from app.core.config import settings
            if (yhat_zero_pct is not None and raw_yhat_neg_pct is not None and 
                zero_pct < settings.zero_guardrail_train_max * 100 and 
                yhat_zero_pct > settings.zero_guardrail_pred_min * 100):
                logger.warning(
                    f"GUARDRAIL: {train_result.model_name} predicting too many zeros relative to training data "
                    f"(training zeros: {zero_pct:.1f}%, predicted zeros: {yhat_zero_pct:.1f}%, "
                    f"negative predictions: {raw_yhat_neg_pct:.1f}%). "
                    f"This may indicate feature bugs, scaling issues, or preprocessing regressions."
                )
                
                # Interpretation guide
                if zero_pct < 50 and yhat_zero_pct is not None and yhat_zero_pct > 50:
                    log_msg += "\n  ⚠️  WARNING: y isn't mostly zero but yhat is mostly zero → potential modeling/feature bug"
                elif zero_pct > 50:
                    log_msg += "\n  ℹ️  INFO: y is mostly zero → data/product-availability problem (not a model bug)"
            
            wape_str = f"{wape:.2f}%" if wape is not None else "N/A"
            wape_adj_str = f", Adjusted WAPE={wape_adjusted:.2f}%" if wape_adjusted is not None else ""
            log_msg += f"\n  Accuracy: WAPE={wape_str}{wape_adj_str}"
            
            logger.info(log_msg)
        else:
            # Fallback to simpler logging if we can't get training data
            if "is_supply_capped_day" in cleaned.df.columns:
                capped_count = int(cleaned.df[cleaned.df["is_supply_capped_day"] == 1].shape[0])
                valid_count = int(cleaned.df[cleaned.df["is_valid_day"] == 1].shape[0]) if "is_valid_day" in cleaned.df.columns else n_points
                logger.info(
                    f"Product {product_id}: {capped_count} supply-capped days out of {valid_count} valid days. "
                    f"Raw WAPE: {wape:.2f}%, Adjusted WAPE: {wape_adjusted:.2f}%" if (wape is not None and wape_adjusted is not None) else (f"Raw WAPE: {wape:.2f}%" if wape is not None else "WAPE: N/A")
                )
        
        return {
            "product_id": product_id,
            "product_name": product.name,
            "status": "ok",
            "model_type": train_result.model_name,
            "n_points": n_points,
            "mape": mape,
            "rmse": rmse,
            "wape": wape,
            "wape_adjusted": wape_adjusted,
            "last_trained_at": trained_at,
        }
    finally:
        if owns_session:
            db.close()

