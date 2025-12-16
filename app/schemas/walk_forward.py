from __future__ import annotations

from datetime import date, datetime
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field, ConfigDict


class WalkForwardResultBase(BaseModel):
    """Base schema for walk-forward result."""
    product_id: int
    test_date: date
    predicted_quantity: float
    actual_quantity: Optional[float] = None
    absolute_error: Optional[float] = None
    percentage_error: Optional[float] = None


class WalkForwardResultCreate(WalkForwardResultBase):
    """Schema for creating a walk-forward result."""
    pass


class WalkForwardResultOut(WalkForwardResultBase):
    """Schema for walk-forward result output."""
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WalkForwardPredictionRequest(BaseModel):
    """Request schema for making a prediction."""
    test_date: date
    training_end_date: date = Field(..., description="Last date to include in training data")
    model_name: str = Field(default="prophet", description="Model type: prophet, xgboost, or ensemble")


class WalkForwardUpdateActualRequest(BaseModel):
    """Request schema for updating actual sales."""
    test_date: date
    actual_quantity: float


class WalkForwardMetricsOut(BaseModel):
    """Schema for validation metrics."""
    n_points: int
    cumulative_mape: Optional[float] = None
    cumulative_rmse: Optional[float] = None
    cumulative_wape: Optional[float] = None
    rolling_7d_mape: Optional[float] = None
    rolling_7d_rmse: Optional[float] = None
    rolling_7d_wape: Optional[float] = None
    trend: str = Field(..., description="Trend: improving, declining, stable, or no_data")


class WalkForwardStatusOut(BaseModel):
    """Schema for validation status."""
    product_id: int
    test_period_start: date
    test_period_end: date
    total_test_days: int
    predictions_made: int
    predictions_with_actuals: int
    predictions_pending: int
    next_date_to_predict: Optional[date] = None
    is_complete: bool
    metrics: WalkForwardMetricsOut


class WalkForwardStartRequest(BaseModel):
    """Request schema for starting walk-forward validation."""
    test_period_start: date = Field(..., description="Start date of test period (e.g., first day of month 12)")
    test_period_end: date = Field(..., description="End date of test period (e.g., last day of month 12)")
    model_name: str = Field(default="prophet", description="Model type: prophet, xgboost, or ensemble")


class WalkForwardPredictionResponse(BaseModel):
    """Response schema for prediction."""
    product_id: int
    test_date: date
    predicted_quantity: float
    training_end_date: date
    n_training_days: int
    walk_forward_result_id: int


class WalkForwardReportOut(BaseModel):
    """Schema for validation report."""
    product_id: int
    product_name: str
    test_period_start: date
    test_period_end: date
    results: List[WalkForwardResultOut]
    metrics: WalkForwardMetricsOut
    daily_errors: List[Dict[str, Any]] = Field(..., description="Daily error breakdown for visualization")
