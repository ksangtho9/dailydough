from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel


class ProductAccuracyOut(BaseModel):
    product_id: int
    product_name: str
    mape: Optional[float] = None
    rmse: Optional[float] = None
    wape: Optional[float] = None
    n_points: int
    valid_points_count: Optional[int] = None  # For date-filtered queries
    last_trained_at: Optional[datetime] = None
    start_date: Optional[date] = None  # For date-filtered queries
    end_date: Optional[date] = None  # For date-filtered queries

