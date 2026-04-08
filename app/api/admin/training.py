"""
Admin Training API

Endpoints for retraining models. Requires ADMIN_MODE_ENABLED=true.
"""

from __future__ import annotations

import logging
import time
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.database import get_db, SessionLocal
from app.models import Product
from app.ml.training.train_product import train_product, _compute_raw_prediction_stats_future
from app.ml.inference.forecast_service import get_forecast_for_product
from app.ml.forecast_service import ForecastService
from app.services.daily_forecast_service import upsert_product_daily_forecasts
from app.services.admin_training_jobs import job_manager, TrainingError, CancelledError
from app.models import ModelRun
from app.api.auth import set_user_state, require_admin_user
from app.core.rate_limiter import limiter
import numpy as np

logger = logging.getLogger("bakezy.admin.training")

router = APIRouter(
    prefix="/admin/training",
    tags=["admin-training"],
)


class RetrainRequest(BaseModel):
    """Request body for starting a retrain job.
    
    Filtering behavior:
    - If product_ids is provided: train exactly those products (ignore bakery_id)
    - Else if bakery_id is provided: train only products with that bakery_id
    - Else: train all products (backward compatibility)
    """
    product_ids: Optional[List[int]] = None
    bakery_id: Optional[int] = None
    optimize_hyperparameters: str = "auto"  # "auto", "true", or "false"


# Rebuild model to ensure it's fully defined for FastAPI schema generation
RetrainRequest.model_rebuild()


class RetrainResponse(BaseModel):
    """Response for starting a retrain job."""
    status: str
    job_id: str
    total: int


class JobStatusResponse(BaseModel):
    """Response for job status."""
    status: str  # "idle" | "running" | "cancelling" | "completed" | "failed" | "completed_with_errors" | "cancelled"
    job_id: Optional[str] = None
    progress: dict  # {"completed": 5, "total": 10}
    current_product_id: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    errors: List[dict] = []  # [{"product_id": 123, "error": "..."}]


class CancelResponse(BaseModel):
    """Response for cancelling a job."""
    status: str
    job_id: Optional[str] = None
    message: str


def run_training_job(
    job_id: str, 
    product_ids: Optional[List[int]] = None,
    optimize_hyperparameters: str = "auto",
    bakery_id: Optional[int] = None
):
    """
    Background task to run training job.
    
    Updates job_manager state as it progresses.
    Note: This is a synchronous function because train_product() and database operations are blocking.
    """
    logger.info(f"Training job {job_id}: Background task started (product_ids={product_ids})")
    db = None
    start_time = time.time()
    try:
        db = SessionLocal()
        logger.info(f"Training job {job_id}: Database session created")
        logger.info(f"Training job {job_id}: Resolving product list...")
        
        # Preserve requested product_ids for logging
        requested_product_ids = product_ids
        
        # Centralize filtering logic using explicit query builder pattern
        query = db.query(Product)
        if product_ids is not None:
            query = query.filter(Product.id.in_(product_ids))
        elif bakery_id is not None:
            query = query.filter(Product.bakery_id == bakery_id)
        products = query.order_by(Product.id.asc()).all()
        resolved_product_ids = [p.id for p in products]
        
        # Add clear logging at job start
        logger.info(
            f"Training job {job_id}: Starting retrain job - "
            f"bakery_id={bakery_id}, "
            f"requested_product_ids={requested_product_ids}, "
            f"resolved_product_ids={resolved_product_ids}, "
            f"resolved_product_count={len(resolved_product_ids)}"
        )
        
        # Handle empty product list
        if len(resolved_product_ids) == 0:
            logger.info(f"Training job {job_id}: No products found, completing immediately")
            job_manager.complete_job(job_id, status="completed")
            return
        
        total = len(resolved_product_ids)
        product_ids = resolved_product_ids  # Use resolved list for training loop
        
        logger.info(f"Training job {job_id}: Updating progress - total={total}, completed=0")
        job_manager.update_job_progress(job_id, total=total, completed=0)
        
        # Verify progress was updated
        job_state_check = job_manager.get_job(job_id)
        if job_state_check:
            logger.info(
                f"Training job {job_id}: Progress verified - total={job_state_check.total}, completed={job_state_check.completed}",
                extra={"job_id": job_id, "verified_total": job_state_check.total, "verified_completed": job_state_check.completed}
            )
        else:
            logger.error(f"Training job {job_id}: WARNING - Job state not found after progress update!")
        
        logger.info(
            f"Training job {job_id} starting product loop",
            extra={
                "job_id": job_id,
                "total_products": total,
                "product_ids": product_ids if len(product_ids) <= 10 else f"{len(product_ids)} products",
            }
        )
        
        # Loop through products
        for idx, product_id in enumerate(product_ids, start=1):
            # Check for cancellation before processing each product
            if job_manager.is_cancelled(job_id):
                logger.info(f"Training job {job_id} cancelled by user")
                job_manager.complete_job(job_id, status="cancelled")
                return
            
            job_manager.update_job_progress(
                job_id,
                completed=idx - 1,
                current_product_id=product_id,
            )
            
            try:
                product_start_time = time.time()
                logger.info(
                    f"Training job {job_id}: Training product {product_id} ({idx}/{total})",
                    extra={"job_id": job_id, "product_id": product_id, "progress": f"{idx}/{total}"}
                )
                
                # Train the product
                result = train_product(
                    product_id=product_id,
                    db=db,
                    model_name="prophet",  # Use default model
                    job_id=job_id,  # Pass job_id for cancellation
                    optimize_hyperparameters=optimize_hyperparameters,  # Pass optimization flag
                )
                
                product_duration = time.time() - product_start_time
                logger.info(
                    f"Training job {job_id}: Product {product_id} completed",
                    extra={
                        "job_id": job_id,
                        "product_id": product_id,
                        "status": result.get("status"),
                        "duration_seconds": round(product_duration, 2),
                    }
                )
                
                # Check if training was successful
                if result.get("status") not in ("skipped_no_data", "failed", None):
                    # Timing: Forecast precomputation + DB write
                    forecast_start_time = time.time()
                    try:
                        product = db.query(Product).filter(Product.id == product_id).first()
                        if product:
                            # Call forecast service directly to get raw predictions for future stats
                            forecast_service = ForecastService()
                            forecast_result = forecast_service.generate_prophet_forecast_for_product(
                                db=db,
                                product_id=product_id,
                                horizon_days=60,
                            )
                            
                            if forecast_result and forecast_result.points:
                                # Convert to ProductForecastOut for upsert
                                from app.schemas.sales_record import ForecastPointOut, ProductForecastOut
                                from datetime import date as date_type
                                forecast_out = ProductForecastOut(
                                    product_id=forecast_result.product_id,
                                    product_name=forecast_result.product_name,
                                    horizon_days=forecast_result.horizon_days,
                                    points=[
                                        ForecastPointOut(
                                            date=date_type.fromisoformat(point.date),
                                            yhat=point.yhat,
                                            yhat_lower=point.yhat_lower,
                                            yhat_upper=point.yhat_upper,
                                            revenue=getattr(point, "revenue", None),
                                            cost=getattr(point, "cost", None),
                                            waste_cost=getattr(point, "waste_cost", None),
                                            profit=getattr(point, "profit", None),
                                            waste_quantity=getattr(point, "waste_quantity", None),
                                            optimal_quantity=getattr(point, "optimal_quantity", None),
                                            expected_stockout_cost=getattr(point, "expected_stockout_cost", None),
                                            expected_waste_cost=getattr(point, "expected_waste_cost", None),
                                            expected_total_cost=getattr(point, "expected_total_cost", None),
                                            is_predicted_spike=getattr(point, "is_predicted_spike", False),
                                            spike_probability=getattr(point, "spike_probability", None),
                                            spike_magnitude=getattr(point, "spike_magnitude", None),
                                            spike_confidence=getattr(point, "spike_confidence", None),
                                        )
                                        for point in forecast_result.points
                                    ],
                                )
                                
                                upsert_product_daily_forecasts(
                                    db,
                                    product=product,
                                    forecast=forecast_out,
                                )
                                
                                # Phase 1b: Compute and store future slice raw prediction stats
                                if forecast_result.raw_yhat_values is not None and len(forecast_result.raw_yhat_values) > 0:
                                    try:
                                        # Get the active ModelRun for this product
                                        model_run = (
                                            db.query(ModelRun)
                                            .filter(
                                                ModelRun.product_id == product_id,
                                                ModelRun.is_active == True
                                            )
                                            .order_by(ModelRun.created_at.desc())
                                            .first()
                                        )
                                        
                                        if model_run:
                                            # Get feature_version from ModelRun
                                            feature_version = model_run.feature_version
                                            model_name = forecast_result.model_name or model_run.selected_model_type
                                            
                                            # Compute future slice stats
                                            raw_prediction_stats_future = _compute_raw_prediction_stats_future(
                                                forecast_result.raw_yhat_values,
                                                model_name,
                                                feature_version,
                                            )
                                            
                                            if raw_prediction_stats_future is not None:
                                                # Update ModelRun.metrics_json with future stats
                                                if model_run.metrics_json is None:
                                                    model_run.metrics_json = {}
                                                
                                                model_run.metrics_json["raw_prediction_summary_future"] = raw_prediction_stats_future
                                                db.commit()
                                                
                                                logger.info(
                                                    f"Training job {job_id}: Updated ModelRun for product_id={product_id} with future slice stats: "
                                                    f"raw_neg_pct={raw_prediction_stats_future.get('raw_neg_pct', 0):.1f}%, "
                                                    f"clamped_zero_pct={raw_prediction_stats_future.get('clamped_zero_pct', 0):.1f}%"
                                                )
                                                
                                                # Phase 5: Dense product sanity warning for future slice
                                                training_data_summary = model_run.metrics_json.get("training_data_summary", {})
                                                mean_y_train = training_data_summary.get("mean_y", 0.0)
                                                zero_rate_train = training_data_summary.get("zero_rate", 100.0)
                                                clamped_zero_pct_future = raw_prediction_stats_future.get("clamped_zero_pct", 0.0)
                                                
                                                if (mean_y_train > 10 and 
                                                    zero_rate_train < 30.0 and 
                                                    clamped_zero_pct_future > 50.0):
                                                    logger.warning(
                                                        f"Training job {job_id}: DENSE_PRODUCT_ZERO_FORECAST: Product {product_id} has healthy training data "
                                                        f"(mean_y={mean_y_train:.2f}, zero_rate={zero_rate_train:.1f}%) but "
                                                        f"{clamped_zero_pct_future:.1f}% of future forecasts are clamped to zero. "
                                                        f"Likely negative clamp or future feature/regressor issue."
                                                    )
                                            else:
                                                logger.warning(
                                                    f"Training job {job_id}: Failed to compute future slice stats for product_id={product_id}"
                                                )
                                        else:
                                            logger.warning(
                                                f"Training job {job_id}: No active ModelRun found for product_id={product_id} to update with future stats"
                                            )
                                    except Exception as stats_error:
                                        logger.warning(
                                            f"Training job {job_id}: Failed to compute/store future slice stats for product_id={product_id}: {stats_error}",
                                            exc_info=True
                                        )
                                
                                forecast_duration = time.time() - forecast_start_time
                                logger.info(
                                    f"Training job {job_id}: Precomputed forecasts for product {product_id} "
                                    f"(took {forecast_duration:.2f}s)"
                                )
                    except Exception as e:
                        forecast_duration = time.time() - forecast_start_time
                        logger.warning(
                            f"Training job {job_id}: Failed to precompute forecasts for product {product_id}: {e} "
                            f"(took {forecast_duration:.2f}s)"
                        )
                        # Don't fail the job for forecast precomputation errors
                
                # Update progress
                job_manager.update_job_progress(job_id, completed=idx)
                
                # Check for cancellation after each product
                if job_manager.is_cancelled(job_id):
                    logger.info(f"Training job {job_id} cancelled by user after product {product_id}")
                    job_manager.complete_job(job_id, status="cancelled")
                    return
                
            except CancelledError:
                logger.info(f"Training job {job_id} cancelled during product {product_id}")
                job_manager.complete_job(job_id, status="cancelled")
                return
            except Exception as e:
                error_msg = str(e)
                logger.error(
                    f"Training job {job_id}: Error training product {product_id}: {error_msg}",
                    exc_info=True,
                    extra={
                        "job_id": job_id,
                        "product_id": product_id,
                        "error": error_msg,
                        "error_type": type(e).__name__,
                    }
                )
                job_manager.add_job_error(job_id, product_id, error_msg)
                # Continue with next product
                job_manager.update_job_progress(job_id, completed=idx)
        
        # Mark job as completed
        total_duration = time.time() - start_time if start_time else 0
        job_state = job_manager.get_job(job_id)
        if job_state and job_state.errors:
            job_manager.complete_job(job_id, status="completed_with_errors")
            logger.info(
                f"Training job {job_id} completed with {len(job_state.errors)} errors",
                extra={
                    "job_id": job_id,
                    "status": "completed_with_errors",
                    "total_products": total,
                    "errors_count": len(job_state.errors),
                    "duration_seconds": round(total_duration, 2),
                }
            )
        else:
            job_manager.complete_job(job_id, status="completed")
            logger.info(
                f"Training job {job_id} completed successfully",
                extra={
                    "job_id": job_id,
                    "status": "completed",
                    "total_products": total,
                    "duration_seconds": round(total_duration, 2),
                }
            )
            
    except Exception as e:
        total_duration = time.time() - start_time if start_time else 0
        logger.error(
            f"Training job {job_id} failed: {e}",
            exc_info=True,
            extra={
                "job_id": job_id,
                "status": "failed",
                "error": str(e),
                "error_type": type(e).__name__,
                "duration_seconds": round(total_duration, 2),
            }
        )
        try:
            job_manager.complete_job(job_id, status="failed")
        except Exception as e2:
            logger.error(f"Training job {job_id}: Failed to update job status to 'failed': {e2}", exc_info=True)
    finally:
        if db is not None:
            try:
                db.close()
                logger.info(f"Training job {job_id}: Database session closed")
            except Exception as e:
                logger.error(f"Training job {job_id}: Error closing database session: {e}", exc_info=True)


@router.post(
    "/retrain",
    response_model=RetrainResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_retrain(
    request: Request,
    retrain_request: RetrainRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(set_user_state),
    _admin_user=Depends(require_admin_user),
):
    """
    Start a retrain job for all products or selected products.
    
    Returns 409 Conflict if a job is already running.
    """
    
    # Check if job is already running
    current_job = job_manager.get_current_job()
    if current_job and current_job.status == "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Training job already running: {current_job.job_id}",
            headers={"X-Existing-Job-Id": current_job.job_id},
        )
    
    # Determine total count using same filtering logic as run_training_job
    query = db.query(Product)
    if retrain_request.product_ids is not None:
        query = query.filter(Product.id.in_(retrain_request.product_ids))
    elif retrain_request.bakery_id is not None:
        query = query.filter(Product.bakery_id == retrain_request.bakery_id)
    total = query.count()
    
    # Handle no products found
    if retrain_request.product_ids is not None and total == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No matching products found for given product_ids"
        )
    
    # Start job
    try:
        job_id = job_manager.start_job(product_ids=retrain_request.product_ids)
    except ValueError as e:
        # This shouldn't happen due to check above, but handle it
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    
    # Launch background task using FastAPI BackgroundTasks
    # Note: BackgroundTasks executes after the response is sent
    # Pass optimize_hyperparameters and bakery_id to the background task
    background_tasks.add_task(
        run_training_job, 
        job_id, 
        retrain_request.product_ids,
        retrain_request.optimize_hyperparameters,
        retrain_request.bakery_id
    )
    
    logger.info(
        f"Training job {job_id} queued for background execution: {total} products",
        extra={"job_id": job_id, "total": total}
    )
    
    return RetrainResponse(
        status="started",
        job_id=job_id,
        total=total,
    )


@router.get("/status", response_model=JobStatusResponse)
async def get_training_status(
    job_id: Optional[str] = Query(None, description="Job ID to check. If not provided, returns current/last job."),
    db: Session = Depends(get_db),
    _admin_user=Depends(require_admin_user),
):
    """Get training job status."""
    
    if job_id:
        job_state = job_manager.get_job(job_id)
    else:
        job_state = job_manager.get_current_job()
    
    if job_state is None:
        return JobStatusResponse(
            status="idle",
            progress={"completed": 0, "total": 0},
        )
    
    # If job is cancelled but status is still "running" or "cancelling", return "cancelling"
    # This ensures frontend shows cancellation immediately even if training loop hasn't detected it yet
    display_status = job_state.status
    if job_state.cancelled and job_state.status in ("running", "cancelling"):
        display_status = "cancelling"
    elif job_state.cancelled and job_state.status == "cancelled":
        display_status = "cancelled"
    
    return JobStatusResponse(
        status=display_status,
        job_id=job_state.job_id,
        progress={
            "completed": job_state.completed,
            "total": job_state.total,
        },
        current_product_id=str(job_state.current_product_id) if job_state.current_product_id is not None else None,
        started_at=job_state.started_at.isoformat() if job_state.started_at else None,
        finished_at=job_state.finished_at.isoformat() if job_state.finished_at else None,
        errors=[
            {"product_id": err.product_id, "error": err.error}
            for err in job_state.errors
        ],
    )


@router.post("/cancel", response_model=CancelResponse)
async def cancel_training_job(
    job_id: Optional[str] = Query(None, description="Job ID to cancel. If not provided, cancels current job."),
    db: Session = Depends(get_db),
    _admin_user=Depends(require_admin_user),
):
    """Cancel a running training job."""
    
    if job_id is None:
        current_job = job_manager.get_current_job()
        if current_job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No training job found",
            )
        job_id = current_job.job_id
    
    # Check if job exists and is running
    job_state = job_manager.get_job(job_id)
    if job_state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )
    
    if job_state.status not in ("running", "cancelling"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Job {job_id} cannot be cancelled (status: {job_state.status})",
        )
    
    # If already cancelling, just return success (idempotent)
    if job_state.status == "cancelling":
        return CancelResponse(
            status="cancelling",
            job_id=job_id,
            message=f"Job {job_id} is already being cancelled.",
        )
    
    # Cancel the job
    cancelled = job_manager.cancel_job(job_id)
    if cancelled:
        logger.info(f"Training job {job_id} cancellation requested")
        return CancelResponse(
            status="cancelled",
            job_id=job_id,
            message=f"Job {job_id} cancellation requested. It will stop after the current product completes.",
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to cancel job {job_id}",
        )

