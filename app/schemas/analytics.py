from __future__ import annotations
from datetime import date
from pydantic import BaseModel


class TopProductSummary(BaseModel):
    product_id: int
    product_name: str
    units_sold: float


class BakerySummary(BaseModel):
    bakery_id: int
    bakery_name: str
    as_of: date

    window_days: int
    total_units: float

    previous_total_units: float
    pct_change_vs_previous: float | None  # percent, e.g. +12.3, -5.4

    top_products: list[TopProductSummary]
