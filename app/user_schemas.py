# schemas.py
from datetime import date
from pydantic import BaseModel, EmailStr, ConfigDict, constr



class UserBase(BaseModel):
    email: EmailStr
    full_name: str | None = None


class UserCreate(UserBase):
    password: constr(min_length=8, max_length=72)


class UserOut(UserBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    email: str | None = None

# --- Bakery schemas ---

class BakeryBase(BaseModel):
    name: str
    location: str | None = None


class BakeryCreate(BakeryBase):
    pass


class BakeryOut(BakeryBase):
    id: int
    owner_id: int

    model_config = ConfigDict(from_attributes=True)


# --- Product schemas ---

class ProductBase(BaseModel):
    name: str
    sku: str | None = None
    category: str | None = None


class ProductCreate(ProductBase):
    bakery_id: int


class ProductOut(ProductBase):
    id: int
    bakery_id: int
    is_active: int

    model_config = ConfigDict(from_attributes=True)
