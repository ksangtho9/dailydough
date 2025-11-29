from pydantic import BaseModel


class ProductBase(BaseModel):
    name: str
    sku: str
    category: str | None = None
    price: float | None = None
    cost_per_unit: float | None = None


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    name: str | None = None
    sku: str | None = None
    category: str | None = None
    price: float | None = None
    cost_per_unit: float | None = None


class Product(ProductBase):
    id: int
    bakery_id: int

    class Config:
        from_attributes = True  # Pydantic v2 style
