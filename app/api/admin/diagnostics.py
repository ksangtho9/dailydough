"""
Admin Diagnostics API

Endpoints for diagnosing zero forecast issues. Requires ADMIN_MODE_ENABLED=true.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional, Set, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, and_, or_, Integer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.database import get_db
from app.models import DailyForecast, ModelRun, ForecastMetrics, Product, SalesRecord

logger = logging.getLogger("bakezy.admin.diagnostics")

router = APIRouter(
    prefix="/admin/diagnostics",
    tags=["admin-diagnostics"],
)


def require_admin_mode():
    """Check if admin mode is enabled."""
    if not settings.admin_mode_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin mode is not enabled. Set ADMIN_MODE_ENABLED=true to enable."
        )


class ZeroForecastProduct(BaseModel):
    """Information about a product with zero forecasts."""
    product_id: int
    selected_model_type: str
    model_run_exists: bool
    last_trained_at: Optional[datetime]
    training_status: Optional[str]
    training_errors: Optional[str]
    training_date_range: Optional[date]
    forecast_count: int
    stored_zero_pct: float
    near_zero_pct: float


class ZeroForecastDetectionResponse(BaseModel):
    """Response for zero forecast detection."""
    flagged_product_ids: List[int]
    products: List[ZeroForecastProduct]
    total_products_checked: int


@router.get("/zero-forecasts", response_model=ZeroForecastDetectionResponse)
def detect_zero_forecasts(
    min_forecast_days: int = Query(7, ge=1, le=30, description="Minimum forecast days to consider"),
    near_zero_eps: float = Query(1e-6, description="Epsilon for near-zero detection"),
    days_ahead: int = Query(14, ge=1, le=30, description="Number of days ahead to check"),
    db: Session = Depends(get_db),
    _: None = Depends(require_admin_mode),
):
    """
    Identify products with persistent zero forecasts.
    
    Detects both stored zeros (yhat == 0) and near zeros (abs(yhat) < eps).
    Only flags products with at least min_forecast_days forecasts.
    """
    today = date.today()
    start_date = today
    end_date = today + timedelta(days=days_ahead - 1)
    
    # Query for forecasts in the date range
    forecasts_query = (
        db.query(
            DailyForecast.product_id,
            func.count(DailyForecast.id).label("forecast_count"),
            func.sum(func.cast(DailyForecast.yhat == 0, Integer)).label("stored_zero_count"),
            func.sum(func.cast(func.abs(DailyForecast.yhat) < near_zero_eps, Integer)).label("near_zero_count"),
        )
        .filter(
            DailyForecast.date >= start_date,
            DailyForecast.date <= end_date,
        )
        .group_by(DailyForecast.product_id)
        .having(func.count(DailyForecast.id) >= min_forecast_days)
    )
    
    forecast_stats = forecasts_query.all()
    
    # Get all product IDs that have forecasts
    product_ids_with_forecasts = {row.product_id for row in forecast_stats}
    
    # Filter to products where all forecasts are zeros or near-zeros
    flagged_products = []
    flagged_product_ids: Set[int] = set()
    
    for row in forecast_stats:
        product_id = row.product_id
        forecast_count = row.forecast_count
        stored_zero_count = row.stored_zero_count or 0
        near_zero_count = row.near_zero_count or 0
        
        stored_zero_pct = (stored_zero_count / forecast_count * 100) if forecast_count > 0 else 0.0
        near_zero_pct = (near_zero_count / forecast_count * 100) if forecast_count > 0 else 0.0
        
        # Flag if all forecasts are zeros or near-zeros
        if stored_zero_pct >= 100.0 or near_zero_pct >= 100.0:
            flagged_product_ids.add(product_id)
            
            # Get ModelRun info
            model_run = (
                db.query(ModelRun)
                .filter(
                    ModelRun.product_id == product_id,
                    ModelRun.is_active == True,
                )
                .order_by(ModelRun.created_at.desc())
                .first()
            )
            
            # Get ForecastMetrics info
            forecast_metrics = (
                db.query(ForecastMetrics)
                .filter(ForecastMetrics.product_id == product_id)
                .first()
            )
            
            # Determine selected_model_type
            selected_model_type = "unknown"
            if model_run:
                selected_model_type = model_run.selected_model_type
            elif forecast_metrics:
                selected_model_type = forecast_metrics.model_type
            
            # Determine last_trained_at
            last_trained_at = None
            if model_run:
                last_trained_at = model_run.created_at
            elif forecast_metrics:
                last_trained_at = forecast_metrics.last_trained_at
            
            # Determine training_status
            training_status = None
            if forecast_metrics:
                training_status = forecast_metrics.status
            
            # Training errors (if any) - could be extended to check logs
            training_errors = None
            
            # Training date range
            training_date_range = None
            if model_run:
                training_date_range = model_run.training_window_end
            
            flagged_products.append(
                ZeroForecastProduct(
                    product_id=product_id,
                    selected_model_type=selected_model_type,
                    model_run_exists=model_run is not None,
                    last_trained_at=last_trained_at,
                    training_status=training_status,
                    training_errors=training_errors,
                    training_date_range=training_date_range,
                    forecast_count=forecast_count,
                    stored_zero_pct=stored_zero_pct,
                    near_zero_pct=near_zero_pct,
                )
            )
            
            logger.info(
                f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                f"step=identify_products, selected_model_type={selected_model_type}, "
                f"model_run_exists={model_run is not None}, last_trained_at={last_trained_at}, "
                f"training_status={training_status}, forecast_count={forecast_count}, "
                f"stored_zero_pct={stored_zero_pct:.1f}%, near_zero_pct={near_zero_pct:.1f}%"
            )
    
    # Get total products checked (products with any forecasts in range)
    total_products_checked = len(product_ids_with_forecasts)
    
    logger.info(
        f"ZERO_FORECAST_INVESTIGATION: Detected {len(flagged_product_ids)} products "
        f"with persistent zero forecasts out of {total_products_checked} products checked"
    )
    
    return ZeroForecastDetectionResponse(
        flagged_product_ids=sorted(list(flagged_product_ids)),
        products=flagged_products,
        total_products_checked=total_products_checked,
    )


class RootCauseCategory(BaseModel):
    """Root cause classification for a product."""
    product_id: int
    final_model: str
    model_run_exists: bool
    last_trained_at: Optional[datetime]
    training_data_summary: dict
    raw_prediction_summary: dict
    clamp_stats: dict
    storage_stats: dict
    root_cause_category: str
    responsible_file_function: str


class RootCauseAnalysisResponse(BaseModel):
    """Response for root cause analysis."""
    products: List[RootCauseCategory]


@router.get("/zero-forecasts/analyze", response_model=RootCauseAnalysisResponse)
def analyze_zero_forecast_root_causes(
    product_ids: Optional[List[int]] = Query(None, description="Specific product IDs to analyze (if None, uses flagged products)"),
    db: Session = Depends(get_db),
    _: None = Depends(require_admin_mode),
):
    """
    Analyze root causes for products with zero forecasts.
    
    Categorizes each product as:
    - Expected: Ultra-sparse data with legitimate zero baseline
    - No Recent Training: Missing/stale ModelRun
    - Model Behavior: Prophet collapse, XGBoost feature issues
    - Feature Pipeline: NaN-dominated features, lag computation failing
    - Bug: Wrong model selected, predictions overwritten
    """
    # If no product_ids provided, get flagged products from detection endpoint
    if product_ids is None:
        detection_response = detect_zero_forecasts(db=db, _=None)
        product_ids = detection_response.flagged_product_ids
    
    if not product_ids:
        return RootCauseAnalysisResponse(products=[])
    
    categorized_products = []
    
    for product_id in product_ids:
        # Get ModelRun and ForecastMetrics
        model_run = (
            db.query(ModelRun)
            .filter(
                ModelRun.product_id == product_id,
                ModelRun.is_active == True,
            )
            .order_by(ModelRun.created_at.desc())
            .first()
        )
        
        forecast_metrics = (
            db.query(ForecastMetrics)
            .filter(ForecastMetrics.product_id == product_id)
            .first()
        )
        
        # Determine final model
        final_model = "unknown"
        model_run_exists = model_run is not None
        last_trained_at = None
        
        if model_run:
            final_model = model_run.selected_model_type
            last_trained_at = model_run.created_at
            metadata = model_run.metrics_json or {}
        elif forecast_metrics:
            final_model = forecast_metrics.model_type
            last_trained_at = forecast_metrics.last_trained_at
            metadata = {}
        else:
            metadata = {}
        
        # Get training data summary from metadata or defaults
        training_data_summary = metadata.get("training_data_summary", {})
        # Use new separate eval and future slice stats
        raw_prediction_summary_eval = metadata.get("raw_prediction_summary_eval", {})
        raw_prediction_summary_future = metadata.get("raw_prediction_summary_future", {})
        # Fallback to old format for backward compatibility
        raw_prediction_summary = raw_prediction_summary_eval if raw_prediction_summary_eval else metadata.get("raw_prediction_summary", {})
        clamp_stats = metadata.get("clamp_stats", {})
        storage_stats = metadata.get("storage_stats", {})
        
        # Categorize root cause
        root_cause_category = "Unknown"
        responsible_file_function = "unknown"
        
        # Check for "No Recent Training"
        if not model_run_exists:
            root_cause_category = "No Recent Training"
            responsible_file_function = "app/ml/training/train_product.py:train_product()"
        elif last_trained_at:
            from datetime import datetime, timezone, timedelta
            # Handle timezone-aware vs naive datetime mismatch
            now_utc = datetime.now(timezone.utc)
            trained_at = last_trained_at
            if trained_at.tzinfo is None:
                trained_at = trained_at.replace(tzinfo=timezone.utc)
            days_since_training = (now_utc - trained_at).days
            if days_since_training > settings.hyperparam_reuse_days * 2:  # Stale if > 2x reuse period
                root_cause_category = "No Recent Training"
                responsible_file_function = "app/ml/training/train_product.py:train_product()"
        
        # Check for "Expected" (ultra-sparse data)
        if root_cause_category == "Unknown":
            mean_y = training_data_summary.get("mean_y", 0.0)
            nonzero_days = training_data_summary.get("nonzero_days", 0)
            zero_rate = training_data_summary.get("zero_rate", 1.0)
            
            if mean_y < 0.1 and nonzero_days < 5 and zero_rate > 0.9:
                root_cause_category = "Expected"
                responsible_file_function = "app/ml/models/baseline_model.py:SeasonalNaiveModel.predict()"
        
        # Check for "Feature Pipeline" issues (NaN-dominated)
        if root_cause_category == "Unknown":
            # Check future slice for feature issues (more relevant for forecast horizon)
            future_rows_all_nan_pct = raw_prediction_summary_future.get("rows_all_nan_pct", 0.0)
            eval_rows_all_nan_pct = raw_prediction_summary_eval.get("rows_all_nan_pct", 0.0)
            rows_all_nan_pct = future_rows_all_nan_pct if future_rows_all_nan_pct > 0 else eval_rows_all_nan_pct
            if rows_all_nan_pct > 50.0:
                root_cause_category = "Feature Pipeline"
                responsible_file_function = "app/ml/models/xgboost_model.py:predict_future()"
        
        # Check for "Model Behavior" (Prophet collapse, XGBoost negatives)
        if root_cause_category == "Unknown":
            # Compare eval vs future slices to identify root cause
            eval_raw_neg_pct = raw_prediction_summary_eval.get("raw_neg_pct", 0.0)
            future_raw_neg_pct = raw_prediction_summary_future.get("raw_neg_pct", 0.0)
            
            # If eval is fine but future has negatives → future regressor/feature issue
            if eval_raw_neg_pct < 10.0 and future_raw_neg_pct > 50.0:
                root_cause_category = "Feature Pipeline"
                responsible_file_function = "app/ml/models/prophet_model.py:predict() or app/ml/models/xgboost_model.py:predict_future()"
            # If both have negatives → model issue
            elif (eval_raw_neg_pct > 50.0 or future_raw_neg_pct > 50.0):
                raw_neg_pct = max(eval_raw_neg_pct, future_raw_neg_pct)
                if final_model == "prophet":
                    root_cause_category = "Model Behavior"
                    responsible_file_function = "app/ml/models/prophet_model.py:predict()"
                elif final_model == "xgboost":
                    root_cause_category = "Model Behavior"
                    responsible_file_function = "app/ml/models/xgboost_model.py:predict_future()"
        
        # Default to "Bug" if still unknown
        if root_cause_category == "Unknown":
            root_cause_category = "Bug"
            responsible_file_function = "app/ml/trainer.py:train()"
        
        # Combine eval and future stats for response (backward compatibility)
        combined_raw_prediction_summary = {
            **raw_prediction_summary_eval,
            "future_slice": raw_prediction_summary_future,
        }
        
        categorized_products.append(
            RootCauseCategory(
                product_id=product_id,
                final_model=final_model,
                model_run_exists=model_run_exists,
                last_trained_at=last_trained_at,
                training_data_summary=training_data_summary,
                raw_prediction_summary=combined_raw_prediction_summary,
                clamp_stats=clamp_stats,
                storage_stats=storage_stats,
                root_cause_category=root_cause_category,
                responsible_file_function=responsible_file_function,
            )
        )
        
        # Step 7: Emit single summary row per product
        logger.info(
            f"ZERO_FORECAST_SUMMARY: product_id={product_id}, "
            f"final_model={final_model}, "
            f"training_stats={training_data_summary}, "
            f"raw_prediction_stats_eval={raw_prediction_summary_eval}, "
            f"raw_prediction_stats_future={raw_prediction_summary_future}, "
            f"clamp_stats={clamp_stats}, "
            f"storage_stats={storage_stats}, "
            f"root_cause={root_cause_category}"
        )
    
    return RootCauseAnalysisResponse(products=categorized_products)


# Helper functions for deep investigation

def _verify_training_data(product_id: int, db: Session) -> dict:
    """
    Verify training data quality for a product.
    
    Returns detailed statistics about raw sales data.
    """
    # Query all sales records for this product
    sales_records = db.query(SalesRecord).filter(
        SalesRecord.product_id == product_id
    ).order_by(SalesRecord.date).all()
    
    if not sales_records:
        return {
            "has_data": False,
            "total_records": 0,
            "date_range": None,
            "total_days": 0,
            "nonzero_days": 0,
            "zero_days": 0,
            "zero_rate": 1.0,
            "mean_quantity": 0.0,
            "median_quantity": 0.0,
            "max_quantity": 0.0,
            "min_quantity": 0.0,
            "date_gaps": [],
            "supply_capped_count": 0,
        }
    
    quantities = [r.quantity_sold for r in sales_records]
    dates = [r.date for r in sales_records]
    
    # Compute statistics
    nonzero_quantities = [q for q in quantities if q > 0]
    zero_count = sum(1 for q in quantities if q == 0)
    nonzero_count = len(nonzero_quantities)
    
    # Check for date gaps
    date_gaps = []
    if len(dates) > 1:
        sorted_dates = sorted(set(dates))
        for i in range(len(sorted_dates) - 1):
            gap_days = (sorted_dates[i + 1] - sorted_dates[i]).days
            if gap_days > 1:
                date_gaps.append({
                    "start": sorted_dates[i].isoformat(),
                    "end": sorted_dates[i + 1].isoformat(),
                    "gap_days": gap_days,
                })
    
    # Check for supply-capped days (if field exists)
    supply_capped_count = 0
    for r in sales_records:
        if hasattr(r, 'is_supply_capped_day') and getattr(r, 'is_supply_capped_day', False):
            supply_capped_count += 1
    
    return {
        "has_data": True,
        "total_records": len(sales_records),
        "date_range": {
            "start": min(dates).isoformat() if dates else None,
            "end": max(dates).isoformat() if dates else None,
        },
        "total_days": len(set(dates)),
        "nonzero_days": nonzero_count,
        "zero_days": zero_count,
        "zero_rate": zero_count / len(quantities) if quantities else 1.0,
        "mean_quantity": sum(quantities) / len(quantities) if quantities else 0.0,
        "median_quantity": sorted(quantities)[len(quantities) // 2] if quantities and len(quantities) > 0 else 0.0,
        "max_quantity": max(quantities) if quantities else 0.0,
        "min_quantity": min(quantities) if quantities else 0.0,
        "date_gaps": date_gaps,
        "supply_capped_count": supply_capped_count,
    }


def _analyze_model_selection(model_run: Optional[ModelRun], forecast_metrics: Optional[ForecastMetrics]) -> dict:
    """
    Analyze model selection decision tree from metadata.
    
    Returns selection path, skip reasons, and guardrail results.
    """
    if not model_run:
        return {
            "model_run_exists": False,
            "selection_path": "unknown",
            "skip_reasons": [],
            "guardrail_results": {},
            "hyperparameters": {},
        }
    
    metadata = model_run.metrics_json or {}
    
    # Extract selection path from metadata
    selection_path = metadata.get("selection_path", "unknown")
    skip_reasons = metadata.get("skip_reasons", [])
    guardrail_results = metadata.get("guardrail_results", {})
    hyperparameters = model_run.hyperparameters_json or {}
    
    return {
        "model_run_exists": True,
        "selected_model": model_run.selected_model_type,
        "selection_path": selection_path,
        "skip_reasons": skip_reasons,
        "guardrail_results": guardrail_results,
        "hyperparameters": hyperparameters,
        "feature_version": model_run.feature_version,
        "training_window_end": model_run.training_window_end.isoformat() if model_run.training_window_end else None,
    }


def _analyze_raw_predictions(model_run: Optional[ModelRun]) -> dict:
    """
    Analyze raw predictions from model metadata.
    
    Checks if predictions were negative (clamped), zero, or NaN.
    """
    if not model_run:
        return {
            "has_metadata": False,
            "raw_prediction_stats": {},
        }
    
    metadata = model_run.metrics_json or {}
    # Use new separate eval and future slice stats
    raw_prediction_summary_eval = metadata.get("raw_prediction_summary_eval", {})
    raw_prediction_summary_future = metadata.get("raw_prediction_summary_future", {})
    # Fallback to old format for backward compatibility
    raw_prediction_summary = raw_prediction_summary_eval if raw_prediction_summary_eval else metadata.get("raw_prediction_summary", {})
    
    if not raw_prediction_summary and not raw_prediction_summary_future:
        return {
            "has_metadata": True,
            "raw_prediction_stats_eval": {},
            "raw_prediction_stats_future": {},
            "analysis": "No raw prediction stats in metadata",
        }
    
    # Analyze the stats
    # Analyze eval slice
    min_raw_eval = raw_prediction_summary_eval.get("min_raw_yhat") if raw_prediction_summary_eval else raw_prediction_summary.get("min_raw_yhat")
    mean_raw_eval = raw_prediction_summary_eval.get("raw_mean") if raw_prediction_summary_eval else raw_prediction_summary.get("mean_raw_yhat")
    max_raw_eval = raw_prediction_summary_eval.get("max_raw_yhat") if raw_prediction_summary_eval else raw_prediction_summary.get("max_raw_yhat")
    raw_neg_pct_eval = raw_prediction_summary_eval.get("raw_neg_pct", 0.0) if raw_prediction_summary_eval else raw_prediction_summary.get("raw_neg_pct", 0.0)
    raw_zero_pct_eval = raw_prediction_summary_eval.get("raw_zero_pct", 0.0) if raw_prediction_summary_eval else raw_prediction_summary.get("raw_zero_pct", 0.0)
    
    # Analyze future slice
    min_raw_future = raw_prediction_summary_future.get("min_raw_yhat") if raw_prediction_summary_future else None
    mean_raw_future = raw_prediction_summary_future.get("raw_mean") if raw_prediction_summary_future else None
    max_raw_future = raw_prediction_summary_future.get("max_raw_yhat") if raw_prediction_summary_future else None
    raw_neg_pct_future = raw_prediction_summary_future.get("raw_neg_pct", 0.0) if raw_prediction_summary_future else None
    raw_zero_pct_future = raw_prediction_summary_future.get("raw_zero_pct", 0.0) if raw_prediction_summary_future else None
    clamped_zero_pct_future = raw_prediction_summary_future.get("clamped_zero_pct", 0.0) if raw_prediction_summary_future else None
    
    analysis = []
    
    # Analyze eval slice
    if raw_neg_pct_eval and raw_neg_pct_eval > 50.0:
        analysis.append(f"Eval slice: High negative predictions ({raw_neg_pct_eval:.1f}%) - likely clamped to zero")
    if raw_zero_pct_eval and raw_zero_pct_eval > 50.0:
        analysis.append(f"Eval slice: High zero predictions ({raw_zero_pct_eval:.1f}%) - model outputting zeros")
    if mean_raw_eval is not None and mean_raw_eval < 0:
        analysis.append(f"Eval slice: Negative mean prediction ({mean_raw_eval:.2f}) - all predictions likely negative")
    if min_raw_eval is not None and max_raw_eval is not None and min_raw_eval == max_raw_eval == 0:
        analysis.append("Eval slice: All predictions are exactly zero")
    
    # Analyze future slice
    if raw_neg_pct_future is not None:
        if raw_neg_pct_future > 50.0:
            analysis.append(f"Future slice: High negative predictions ({raw_neg_pct_future:.1f}%) - likely clamped to zero")
        if clamped_zero_pct_future is not None and clamped_zero_pct_future > 50.0:
            analysis.append(f"Future slice: High clamped zero rate ({clamped_zero_pct_future:.1f}%)")
    
    # Compare eval vs future
    if raw_neg_pct_eval is not None and raw_neg_pct_future is not None:
        if raw_neg_pct_eval < 10.0 and raw_neg_pct_future > 50.0:
            analysis.append("KEY DIAGNOSTIC: Eval slice is fine but future slice has high negatives → future regressor/feature issue")
        elif raw_neg_pct_eval > 50.0 and raw_neg_pct_future > 50.0:
            analysis.append("Both eval and future slices have high negatives → model issue")
    
    return {
        "has_metadata": True,
        "raw_prediction_stats_eval": raw_prediction_summary_eval,
        "raw_prediction_stats_future": raw_prediction_summary_future,
        "raw_prediction_stats": raw_prediction_summary,  # For backward compatibility
        "analysis": analysis if analysis else ["Predictions appear normal"],
    }


def _analyze_feature_engineering(product_id: int, model_run: Optional[ModelRun], db: Session) -> dict:
    """
    Analyze feature engineering quality.
    
    Note: We can't easily re-run feature engineering here, so we rely on metadata
    and check what we can from the model run.
    """
    if not model_run:
        return {
            "feature_version": None,
            "can_analyze": False,
            "analysis": "No ModelRun to analyze features",
        }
    
    metadata = model_run.metrics_json or {}
    
    # Check if we have feature statistics in metadata
    feature_stats = metadata.get("feature_stats", {})
    
    # Check XGBoost-specific feature issues from raw prediction summary
    raw_prediction_summary = metadata.get("raw_prediction_summary", {})
    rows_all_nan_pct = raw_prediction_summary.get("rows_all_nan_or_zero_pct", 0.0)
    nan_per_feature_pct = raw_prediction_summary.get("nan_per_feature_pct", {})
    
    analysis = []
    if rows_all_nan_pct and rows_all_nan_pct > 50.0:
        analysis.append(f"High percentage of rows with all NaN/zero features ({rows_all_nan_pct:.1f}%)")
    if nan_per_feature_pct:
        high_nan_features = {k: v for k, v in nan_per_feature_pct.items() if v > 50.0}
        if high_nan_features:
            analysis.append(f"Features with high NaN rates: {high_nan_features}")
    
    return {
        "feature_version": model_run.feature_version,
        "can_analyze": True,
        "feature_stats": feature_stats,
        "nan_analysis": {
            "rows_all_nan_pct": rows_all_nan_pct,
            "nan_per_feature_pct": nan_per_feature_pct,
        },
        "analysis": analysis if analysis else ["No obvious feature engineering issues detected"],
    }


def _analyze_forecast_generation(product_id: int, db: Session) -> dict:
    """
    Analyze forecast generation and storage.
    
    Checks DailyForecast table and compares with expected forecasts.
    """
    # Get all forecasts for this product
    forecasts = db.query(DailyForecast).filter(
        DailyForecast.product_id == product_id
    ).order_by(DailyForecast.date).all()
    
    if not forecasts:
        return {
            "has_forecasts": False,
            "forecast_count": 0,
            "zero_forecast_count": 0,
            "zero_forecast_pct": 100.0,
            "date_range": None,
            "analysis": "No forecasts found in DailyForecast table",
        }
    
    dates = [f.date for f in forecasts]
    quantities = [f.yhat for f in forecasts]
    zero_count = sum(1 for q in quantities if q == 0.0)
    
    # Check if forecasts are only for future dates
    today = date.today()
    future_forecasts = [f for f in forecasts if f.date >= today]
    past_forecasts = [f for f in forecasts if f.date < today]
    
    analysis = []
    if zero_count == len(forecasts):
        analysis.append("ALL forecasts are zero")
    elif zero_count > len(forecasts) * 0.9:
        analysis.append(f"Very high zero forecast rate ({zero_count}/{len(forecasts)} = {zero_count/len(forecasts)*100:.1f}%)")
    
    if len(future_forecasts) > 0 and len(past_forecasts) == 0:
        analysis.append("Forecasts only exist for future dates (precomputed)")
    elif len(past_forecasts) > 0:
        analysis.append(f"Forecasts exist for past dates ({len(past_forecasts)} past, {len(future_forecasts)} future)")
    
    return {
        "has_forecasts": True,
        "forecast_count": len(forecasts),
        "zero_forecast_count": zero_count,
        "zero_forecast_pct": (zero_count / len(forecasts) * 100) if forecasts else 0.0,
        "date_range": {
            "start": min(dates).isoformat() if dates else None,
            "end": max(dates).isoformat() if dates else None,
        },
        "future_forecast_count": len(future_forecasts),
        "past_forecast_count": len(past_forecasts),
        "analysis": analysis,
    }


def _determine_root_cause_and_recommendations(
    training_data: dict,
    model_selection: dict,
    raw_predictions: dict,
    feature_engineering: dict,
    forecast_generation: dict,
) -> Tuple[str, List[str], str]:
    """
    Determine root cause and generate recommendations based on all analyses.
    
    Returns: (root_cause, recommendations, severity)
    """
    recommendations = []
    root_cause = "Unknown"
    severity = "medium"
    
    # Check training data issues first
    if not training_data.get("has_data"):
        root_cause = "No Training Data"
        severity = "critical"
        recommendations.append("Upload sales data for this product")
        recommendations.append("Verify product exists and is linked to correct bakery")
        return root_cause, recommendations, severity
    
    if training_data.get("total_days", 0) < 7:
        root_cause = "Insufficient Training Data"
        severity = "high"
        recommendations.append(f"Only {training_data.get('total_days')} days of data - need at least 7 days")
        recommendations.append("Upload more historical sales data")
        return root_cause, recommendations, severity
    
    if training_data.get("zero_rate", 1.0) > 0.9 and training_data.get("mean_quantity", 0.0) < 0.1:
        root_cause = "Expected (Ultra-Sparse Data)"
        severity = "expected"
        recommendations.append("Product has very sparse sales data - zero predictions may be legitimate")
        recommendations.append("Consider if product should be discontinued or production schedule adjusted")
        return root_cause, recommendations, severity
    
    # Check model selection issues
    if not model_selection.get("model_run_exists"):
        root_cause = "No Recent Training"
        severity = "high"
        recommendations.append("Product has not been trained recently")
        recommendations.append("Run retraining job for this product")
        return root_cause, recommendations, severity
    
    # Check raw predictions
    raw_stats = raw_predictions.get("raw_prediction_stats", {})
    raw_neg_pct = raw_stats.get("raw_neg_pct", 0.0)
    raw_zero_pct = raw_stats.get("raw_zero_pct", 0.0)
    mean_raw = raw_stats.get("mean_raw_yhat")
    
    if raw_neg_pct and raw_neg_pct > 50.0:
        root_cause = "Model Predicting Negatives (Clamped to Zero)"
        severity = "high"
        selected_model = model_selection.get("selected_model", "unknown")
        if selected_model == "prophet":
            recommendations.append("Prophet is predicting negative values - check regressor handling")
            recommendations.append("Consider using XGBoost or baseline model instead")
        elif selected_model == "xgboost":
            recommendations.append("XGBoost is predicting negative values - check feature quality")
            recommendations.append("Review feature engineering and NaN handling")
        else:
            recommendations.append(f"{selected_model} is predicting negative values")
        recommendations.append("Review model hyperparameters and training data quality")
        return root_cause, recommendations, severity
    
    if raw_zero_pct and raw_zero_pct > 50.0:
        root_cause = "Model Outputting Zeros"
        severity = "high"
        selected_model = model_selection.get("selected_model", "unknown")
        recommendations.append(f"{selected_model} model is outputting zeros directly")
        recommendations.append("Check model training - may have converged to zero")
        recommendations.append("Review training data - may be too sparse for this model")
        return root_cause, recommendations, severity
    
    # Check feature engineering issues
    nan_analysis = feature_engineering.get("nan_analysis", {})
    rows_all_nan_pct = nan_analysis.get("rows_all_nan_pct", 0.0)
    if rows_all_nan_pct > 50.0:
        root_cause = "Feature Engineering Issues (NaN-Dominated)"
        severity = "high"
        recommendations.append(f"{rows_all_nan_pct:.1f}% of rows have all NaN/zero features")
        recommendations.append("Check lag feature computation")
        recommendations.append("Verify regressors (weather, holidays, etc.) are available")
        recommendations.append("Review feature engineering pipeline")
        return root_cause, recommendations, severity
    
    # Check forecast generation issues
    if forecast_generation.get("zero_forecast_pct", 0.0) >= 100.0:
        root_cause = "Forecast Storage Issue"
        severity = "critical"
        recommendations.append("All stored forecasts are zero - check forecast generation pipeline")
        recommendations.append("Verify forecasts are being written correctly to DailyForecast table")
        recommendations.append("Check for race conditions or overwrites")
        return root_cause, recommendations, severity
    
    # Default: likely a combination of issues or edge case
    root_cause = "Multiple Issues or Edge Case"
    severity = "medium"
    recommendations.append("Review all analysis sections above for specific issues")
    recommendations.append("Compare with working products to identify differences")
    recommendations.append("Enable DEBUG_ZERO_FORECASTS=true and retrain for detailed logs")
    
    return root_cause, recommendations, severity


# Comprehensive deep investigation models

class DeepInvestigationReport(BaseModel):
    """Comprehensive investigation report for a single product."""
    product_id: int
    product_name: Optional[str]
    bakery_id: Optional[int]
    
    # Training data analysis
    training_data: dict
    
    # Model selection analysis
    model_selection: dict
    
    # Raw predictions analysis
    raw_predictions: dict
    
    # Feature engineering analysis
    feature_engineering: dict
    
    # Forecast generation analysis
    forecast_generation: dict
    
    # Root cause summary
    root_cause: str
    recommendations: List[str]
    severity: str  # "critical", "high", "medium", "low", "expected"


class DeepInvestigationResponse(BaseModel):
    """Response for deep investigation."""
    products: List[DeepInvestigationReport]
    summary: dict


@router.get("/zero-forecasts/deep-investigate", response_model=DeepInvestigationResponse)
def deep_investigate_zero_forecasts(
    product_ids: Optional[List[int]] = Query(None, description="Specific product IDs to investigate"),
    bakery_id: Optional[int] = Query(None, description="Bakery ID to filter products"),
    db: Session = Depends(get_db),
    _: None = Depends(require_admin_mode),
):
    """
    Deep investigation into products with zero forecasts.
    
    Performs comprehensive analysis across:
    - Training data quality
    - Model selection decisions
    - Raw predictions (before clamping)
    - Feature engineering quality
    - Forecast generation and storage
    
    Returns detailed report with root cause analysis and recommendations.
    """
    # Determine which products to investigate
    if product_ids is None:
        # Get flagged products by duplicating detection logic (to avoid admin check)
        today = date.today()
        start_date = today
        end_date = today + timedelta(days=14 - 1)
        near_zero_eps = 1e-6
        min_forecast_days = 7
        
        forecasts_query = (
            db.query(
                DailyForecast.product_id,
                func.count(DailyForecast.id).label("forecast_count"),
                func.sum(func.cast(DailyForecast.yhat == 0, Integer)).label("stored_zero_count"),
                func.sum(func.cast(func.abs(DailyForecast.yhat) < near_zero_eps, Integer)).label("near_zero_count"),
            )
            .filter(
                DailyForecast.date >= start_date,
                DailyForecast.date <= end_date,
            )
            .group_by(DailyForecast.product_id)
            .having(func.count(DailyForecast.id) >= min_forecast_days)
        )
        
        forecast_stats = forecasts_query.all()
        product_ids = []
        for row in forecast_stats:
            forecast_count = row.forecast_count
            stored_zero_count = row.stored_zero_count or 0
            near_zero_count = row.near_zero_count or 0
            stored_zero_pct = (stored_zero_count / forecast_count * 100) if forecast_count > 0 else 0.0
            near_zero_pct = (near_zero_count / forecast_count * 100) if forecast_count > 0 else 0.0
            if stored_zero_pct >= 100.0 or near_zero_pct >= 100.0:
                product_ids.append(row.product_id)
    
    if not product_ids:
        return DeepInvestigationResponse(
            products=[],
            summary={"total_investigated": 0, "by_severity": {}, "by_root_cause": {}}
        )
    
    # Filter by bakery if provided
    if bakery_id is not None:
        products_in_bakery = db.query(Product.id).filter(Product.bakery_id == bakery_id).all()
        bakery_product_ids = {p.id for p in products_in_bakery}
        product_ids = [pid for pid in product_ids if pid in bakery_product_ids]
    
    if not product_ids:
        return DeepInvestigationResponse(
            products=[],
            summary={"total_investigated": 0, "by_severity": {}, "by_root_cause": {}}
        )
    
    reports = []
    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "expected": 0}
    root_cause_counts = {}
    
    for product_id in product_ids:
        # Get product info
        product = db.query(Product).filter(Product.id == product_id).first()
        product_name = product.name if product else None
        bakery_id_val = product.bakery_id if product else None
        
        # Get ModelRun and ForecastMetrics
        model_run = (
            db.query(ModelRun)
            .filter(
                ModelRun.product_id == product_id,
                ModelRun.is_active == True,
            )
            .order_by(ModelRun.created_at.desc())
            .first()
        )
        
        forecast_metrics = (
            db.query(ForecastMetrics)
            .filter(ForecastMetrics.product_id == product_id)
            .first()
        )
        
        # Run all analyses
        training_data = _verify_training_data(product_id, db)
        model_selection = _analyze_model_selection(model_run, forecast_metrics)
        raw_predictions = _analyze_raw_predictions(model_run)
        feature_engineering = _analyze_feature_engineering(product_id, model_run, db)
        forecast_generation = _analyze_forecast_generation(product_id, db)
        
        # Determine root cause and recommendations
        root_cause, recommendations, severity = _determine_root_cause_and_recommendations(
            training_data,
            model_selection,
            raw_predictions,
            feature_engineering,
            forecast_generation,
        )
        
        # Update counts
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
        root_cause_counts[root_cause] = root_cause_counts.get(root_cause, 0) + 1
        
        reports.append(
            DeepInvestigationReport(
                product_id=product_id,
                product_name=product_name,
                bakery_id=bakery_id_val,
                training_data=training_data,
                model_selection=model_selection,
                raw_predictions=raw_predictions,
                feature_engineering=feature_engineering,
                forecast_generation=forecast_generation,
                root_cause=root_cause,
                recommendations=recommendations,
                severity=severity,
            )
        )
    
    return DeepInvestigationResponse(
        products=reports,
        summary={
            "total_investigated": len(reports),
            "by_severity": severity_counts,
            "by_root_cause": root_cause_counts,
        }
    )
