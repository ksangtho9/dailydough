from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class DailySalesBase(BaseModel):
	sale_date: date
	units_sold: int
	revenue: float


class DailySalesCreate(DailySalesBase):
	product_id: int


class DailySalesRead(DailySalesBase):
	id: int
	product_id: int

	class Config:
		from_attributes = True


class ProductBase(BaseModel):
	name: str
	description: Optional[str] = None
	price: float


class ProductCreate(ProductBase):
	bakery_id: int


class ProductRead(ProductBase):
	id: int
	bakery_id: int
	daily_sales: List[DailySalesRead] = Field(default_factory=list)

	class Config:
		from_attributes = True


class BakeryBase(BaseModel):
	name: str
	location: Optional[str] = None


class BakeryCreate(BakeryBase):
	pass


class BakeryRead(BakeryBase):
	id: int
	created_at: datetime
	products: List[ProductRead] = Field(default_factory=list)

	class Config:
		from_attributes = True


