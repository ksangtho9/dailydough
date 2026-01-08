from datetime import date
from typing import Optional

from pydantic import BaseModel


class DashboardSummaryResponse(BaseModel):
    bakery_id: int
    bakery_name: str
    as_of: date
    recommended_bake: Optional[int] = None
    expected_waste_pct: Optional[float] = None
    forecast_accuracy_pct: Optional[float] = None  # Deprecated: kept for backward compatibility
    post_training_wape: Optional[float] = None
    high_risk_items: int
    # Date window fields for expected waste calculation (populated even when expected_waste_pct is None)
    expected_waste_forecast_date: Optional[date] = None
    expected_waste_lookback_start: Optional[date] = None
    expected_waste_lookback_end: Optional[date] = None











