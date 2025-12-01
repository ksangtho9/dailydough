from pydantic import BaseModel


class ProductBase(BaseModel):
    name: str
    sku: str
    category: str | None = None
    price: float | None = None
    cost_per_unit: float | None = None
    # Shelf life in days (1 = same-day only, 2 = can be sold next day)
    shelf_life_days: int = 1


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    name: str | None = None
    sku: str | None = None
    category: str | None = None
    price: float | None = None
    cost_per_unit: float | None = None
    shelf_life_days: int | None = None


class Product(ProductBase):
    id: int
    bakery_id: int

    class Config:
        from_attributes = True  # Pydantic v2 style
