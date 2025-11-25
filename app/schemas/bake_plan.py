from datetime import date
from typing import List

from pydantic import BaseModel


class BakePlanItem(BaseModel):
    product_id: int
    product_name: str
    forecast_quantity: int


class BakePlanResponse(BaseModel):
    bakery_id: int
    bakery_name: str
    date: date
    items: List[BakePlanItem]

