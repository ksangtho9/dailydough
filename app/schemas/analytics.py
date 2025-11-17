from datetime import date
from pydantic import BaseModel
from typing import List


class TopProductSummary(BaseModel):
    product_id: int
    product_name: str
    units_sold: float


class BakerySummary(BaseModel):
    bakery_id: int
    bakery_name: str 
    as_of: date

    total_units_last_7_days: float
    total_units_last_30_days: float

    top_products_last_30_days: List[TopProductSummary]
