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
