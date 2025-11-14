from pydantic import BaseModel
from datetime import date


class ProductForecastPoint(BaseModel):
    date: date
    quantity: float


class ProductForecastResponse(BaseModel):
    product_id: int
    points: list[ProductForecastPoint]
