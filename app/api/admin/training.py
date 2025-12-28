"""
Admin Training API

Endpoints for retraining models. Requires ADMIN_MODE_ENABLED=true.
"""

from __future__ import annotations

import logging
import time
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.database import get_db, SessionLocal
from app.models import Product
from app.ml.training.train_product import train_product
from app.ml.inference.forecast_service import get_forecast_for_product
from app.services.daily_forecast_service import upsert_product_daily_forecasts
from app.services.admin_training_jobs import job_manager, TrainingError

logger = logging.getLogger("bakezy.admin.training")

router = APIRouter(
    prefix="/admin/training",
    tags=["admin-training"],
)


def require_admin_mode():
    """Check if admin mode is enabled."""
    if not settings.admin_mode_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin mode is not enabled. Set ADMIN_MODE_ENABLED=true to enable."
        )


class RetrainRequest(BaseModel):
    """Request body for starting a retrain job."""
    product_ids: Optional[List[int]] = None


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


def run_training_job(job_id: str, product_ids: Optional[List[int]] = None):
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
        
        # Resolve product list
        if product_ids is None:
            # Get all products
            logger.info(f"Training job {job_id}: Fetching all products from database...")
            products = db.query(Product).order_by(Product.id.asc()).all()
            product_ids = [p.id for p in products]
            logger.info(f"Training job {job_id}: Found {len(product_ids)} products")
        else:
            logger.info(f"Training job {job_id}: Using provided product_ids: {len(product_ids)} products")
        
        total = len(product_ids)
        if total == 0:
            logger.warning(f"Training job {job_id}: No products to train")
            job_manager.complete_job(job_id, status="failed")
            return
        
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
                    # Precompute forecasts
                    try:
                        product = db.query(Product).filter(Product.id == product_id).first()
                        if product:
                            forecast_out = get_forecast_for_product(
                                product_id=product_id,
                                days_ahead=60,
                                db=db,
                            )
                            
                            if forecast_out and forecast_out.points:
                                upsert_product_daily_forecasts(
                                    db,
                                    product=product,
                                    forecast=forecast_out,
                                )
                                logger.info(f"Training job {job_id}: Precomputed forecasts for product {product_id}")
                    except Exception as e:
                        logger.warning(f"Training job {job_id}: Failed to precompute forecasts for product {product_id}: {e}")
                        # Don't fail the job for forecast precomputation errors
                
                # Update progress
                job_manager.update_job_progress(job_id, completed=idx)
                
                # Check for cancellation after each product
                if job_manager.is_cancelled(job_id):
                    logger.info(f"Training job {job_id} cancelled by user after product {product_id}")
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


@router.post("/retrain", response_model=RetrainResponse, status_code=status.HTTP_202_ACCEPTED)
async def start_retrain(
    request: RetrainRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Start a retrain job for all products or selected products.
    
    Returns 409 Conflict if a job is already running.
    """
    require_admin_mode()
    
    # Check if job is already running
    current_job = job_manager.get_current_job()
    if current_job and current_job.status == "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Training job already running: {current_job.job_id}",
            headers={"X-Existing-Job-Id": current_job.job_id},
        )
    
    # Determine total count
    if request.product_ids is None:
        total = db.query(Product).count()
    else:
        total = len(request.product_ids)
    
    # Start job
    try:
        job_id = job_manager.start_job(product_ids=request.product_ids)
    except ValueError as e:
        # This shouldn't happen due to check above, but handle it
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    
    # Launch background task using FastAPI BackgroundTasks
    # Note: BackgroundTasks executes after the response is sent
    background_tasks.add_task(run_training_job, job_id, request.product_ids)
    
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
):
    """Get training job status."""
    require_admin_mode()
    
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
):
    """Cancel a running training job."""
    require_admin_mode()
    
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

