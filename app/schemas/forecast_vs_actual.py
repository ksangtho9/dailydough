from typing import List, Optional
from datetime import date

from pydantic import BaseModel


class ForecastVsActualPoint(BaseModel):
    date: str
    actual: Optional[float] = None
    forecast: Optional[float] = None
    error: Optional[float] = None  # forecast - actual
    abs_error: Optional[float] = None  # abs(error)
    pct_error: Optional[float] = None  # abs_error / abs(actual) if actual > 0


class ForecastVsActualResponse(BaseModel):
    product_id: int
    rows: List[ForecastVsActualPoint]  # Renamed from points to rows
    wape: Optional[float] = None
    valid_points_count: int
    start_date: date
    end_date: date







