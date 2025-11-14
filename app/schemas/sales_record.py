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
