from typing import List, Optional

from pydantic import BaseModel


class ForecastVsActualPoint(BaseModel):
    date: str
    actual: Optional[float] = None
    forecast: Optional[float] = None


class ForecastVsActualResponse(BaseModel):
    product_id: int
    window_days: int
    points: List[ForecastVsActualPoint]



