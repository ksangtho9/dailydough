"""
Admin Training Job Manager

Manages training job state in-memory. Designed for single-process deployment.
For multi-worker deployments, this should be replaced with DB/Redis persistence.

TODO: Later store JobState in DB table admin_jobs or Redis for multi-worker support.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from app.core.config import settings


@dataclass
class TrainingError:
    """Error for a specific product during training."""
    product_id: int
    error: str


@dataclass
class JobState:
    """State of a training job."""
    job_id: str
    status: str  # "idle" | "running" | "completed" | "failed" | "completed_with_errors" | "cancelled"
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    completed: int = 0
    total: int = 0
    current_product_id: Optional[int] = None
    errors: List[TrainingError] = field(default_factory=list)
    product_ids: Optional[List[int]] = None  # None means all products
    cancelled: bool = False  # Flag to signal cancellation


class AdminTrainingJobManager:
    """
    Singleton job manager for admin training operations.
    
    Thread-safe for single-process FastAPI (uses simple locking).
    For multi-worker, replace with DB/Redis-based implementation.
    """
    
    _instance: Optional[AdminTrainingJobManager] = None
    _lock = None  # Will be set to threading.Lock if needed
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._current_job: Optional[JobState] = None
            import threading
            cls._lock = threading.Lock()
        return cls._instance
    
    def start_job(self, product_ids: Optional[List[int]] = None) -> str:
        """
        Start a new training job.
        
        Args:
            product_ids: List of product IDs to train, or None for all products
            
        Returns:
            job_id: UUID string for the job
            
        Raises:
            ValueError: If a job is already running (409 conflict)
        """
        with self._lock:
            if self._current_job is not None and self._current_job.status == "running":
                raise ValueError(
                    f"Training job already running: {self._current_job.job_id}. "
                    "Only one job can run at a time."
                )
            
            job_id = str(uuid.uuid4())
            self._current_job = JobState(
                job_id=job_id,
                status="running",
                started_at=datetime.now(timezone.utc),
                product_ids=product_ids,
            )
            return job_id
    
    def get_job(self, job_id: str) -> Optional[JobState]:
        """Get job state by job_id."""
        with self._lock:
            if self._current_job and self._current_job.job_id == job_id:
                return self._current_job
            return None
    
    def get_current_job(self) -> Optional[JobState]:
        """Get the current/last job state."""
        with self._lock:
            return self._current_job
    
    def update_job_progress(
        self,
        job_id: str,
        completed: Optional[int] = None,
        total: Optional[int] = None,
        current_product_id: Optional[int] = None,
    ) -> None:
        """Update job progress."""
        with self._lock:
            if self._current_job and self._current_job.job_id == job_id:
                if completed is not None:
                    self._current_job.completed = completed
                if total is not None:
                    self._current_job.total = total
                if current_product_id is not None:
                    self._current_job.current_product_id = current_product_id
    
    def add_job_error(self, job_id: str, product_id: int, error: str) -> None:
        """Add an error for a specific product."""
        with self._lock:
            if self._current_job and self._current_job.job_id == job_id:
                self._current_job.errors.append(TrainingError(product_id=product_id, error=error))
    
    def complete_job(self, job_id: str, status: str = "completed") -> None:
        """
        Mark job as completed.
        
        Args:
            job_id: Job ID
            status: "completed" or "completed_with_errors" or "failed"
        """
        with self._lock:
            if self._current_job and self._current_job.job_id == job_id:
                self._current_job.status = status
                self._current_job.finished_at = datetime.now(timezone.utc)
                # If there are errors but status is "completed", change to "completed_with_errors"
                if status == "completed" and self._current_job.errors:
                    self._current_job.status = "completed_with_errors"
    
    def cancel_job(self, job_id: str) -> bool:
        """
        Cancel a running job by setting the cancelled flag and updating status.
        
        Returns:
            True if job was cancelled, False if job not found or not running
        """
        with self._lock:
            if self._current_job and self._current_job.job_id == job_id:
                if self._current_job.status == "running":
                    self._current_job.cancelled = True
                    # Immediately update status to "cancelling" so frontend shows cancellation
                    # The training loop will change it to "cancelled" when it detects it
                    self._current_job.status = "cancelling"
                    return True
        return False
    
    def is_cancelled(self, job_id: str) -> bool:
        """Check if a job has been cancelled."""
        with self._lock:
            if self._current_job and self._current_job.job_id == job_id:
                return self._current_job.cancelled
            return False


# Singleton instance
job_manager = AdminTrainingJobManager()

