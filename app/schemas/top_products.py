from typing import List

from pydantic import BaseModel


class TopProductItem(BaseModel):
    product_id: int
    product_name: str
    total_quantity: float


class TopProductsResponse(BaseModel):
    bakery_id: int
    window_days: int
    items: List[TopProductItem]




