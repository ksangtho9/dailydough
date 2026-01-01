from datetime import date
from typing import List

from pydantic import BaseModel


class BakePlanItem(BaseModel):
    product_id: int
    product_name: str
    forecast_quantity: int
    sku: str | None = None
    # Risk metrics (computed from forecast uncertainty)
    waste_risk_prob: float | None = None
    stockout_risk_prob: float | None = None
    risk_sigma: float | None = None
    interval_level_used: float | str | None = None  # 0.8, 0.95, or "fallback"
    risk_method: str | None = None  # "interval_based" | "residual_based" | "fallback"
    debug_source: str | None = None  # "prophet_interval" | "xgb_interval" | "fallback"
    sigma_clamped: bool | None = None


class BakePlanResponse(BaseModel):
    bakery_id: int
    bakery_name: str
    date: date
    items: List[BakePlanItem]




