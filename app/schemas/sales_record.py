from pydantic import BaseModel
from datetime import date


class SalesRecordBase(BaseModel):
    product_id: int
    date: date
    quantity_sold: float


class SalesRecordCreate(SalesRecordBase):
    pass


class SalesRecord(SalesRecordBase):
    id: int
    bakery_id: int

    class Config:
        from_attributes = True

from datetime import date
from typing import List, Optional
from pydantic import BaseModel


class ProductSalesPoint(BaseModel):
    date: date
    quantity: float

    class Config:
        orm_mode = True


class ProductSalesSeries(BaseModel):
    product_id: int
    product_name: Optional[str] = None
    sales: List[ProductSalesPoint]

class ForecastPointOut(BaseModel):
    date: date          # forecast date
    yhat: float         # point forecast
    yhat_lower: float   # lower bound (P10-ish)
    yhat_upper: float   # upper bound (P90-ish)
    # Profit metrics (optional - only included if product has price/cost)
    revenue: float | None = None
    cost: float | None = None
    waste_cost: float | None = None
    profit: float | None = None
    waste_quantity: float | None = None

    class Config:
        from_attributes = True  # Pydantic v2 (replaces orm_mode)


class ProductForecastOut(BaseModel):
    product_id: int
    product_name: str
    horizon_days: int
    points: List[ForecastPointOut]