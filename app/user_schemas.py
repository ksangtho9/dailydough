from datetime import datetime, date

from pydantic import BaseModel, EmailStr, ConfigDict, constr

from app.schemas.forecast import ForecastMetricsSchema


# ========== User schemas ==========

class UserBase(BaseModel):
    email: EmailStr


class UserCreate(UserBase):
    password: constr(min_length=8, max_length=72)


class UserOut(BaseModel):
    id: int
    email: EmailStr
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    email: str | None = None


# ========== Bakery schemas ==========

class BakeryBase(BaseModel):
    name: str
    location: str | None = None
    timezone: str | None = None


class BakeryCreate(BakeryBase):
    pass


class BakeryOut(BakeryBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ========== Product schemas ==========

class ProductBase(BaseModel):
    name: str
    sku: str | None = None
    category: str | None = None
    price: float | None = None
    cost_per_unit: float | None = None


class ProductCreate(ProductBase):
    bakery_id: int


class ProductOut(ProductBase):
    id: int
    bakery_id: int
    forecast_metrics: ForecastMetricsSchema | None = None

    model_config = ConfigDict(from_attributes=True)


# ========== Sales record schemas ==========

class SalesRecordBase(BaseModel):
    bakery_id: int
    product_id: int
    date: date
    quantity_sold: float


class SalesRecordCreate(SalesRecordBase):
    pass


class SalesRecordOut(SalesRecordBase):
    id: int

    model_config = ConfigDict(from_attributes=True)
