from datetime import date
from typing import Optional

from pydantic import BaseModel


class DashboardSummaryResponse(BaseModel):
    bakery_id: int
    bakery_name: str
    as_of: date
    recommended_bake: Optional[int] = None
    expected_waste_pct: Optional[float] = None
    forecast_accuracy_pct: Optional[float] = None
    high_risk_items: int









