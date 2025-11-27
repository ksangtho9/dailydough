from typing import List

from pydantic import BaseModel


class WeekdayValue(BaseModel):
    weekday: int  # 0 = Monday
    label: str
    avg_quantity: float


class WeekdayPatternResponse(BaseModel):
    product_id: int
    window_days: int
    points: List[WeekdayValue]




