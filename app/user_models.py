from datetime import datetime, date

from sqlalchemy import Column, Integer, String, DateTime, Date, ForeignKey, Float
from sqlalchemy.orm import relationship

from .db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    bakeries = relationship("Bakery", back_populates="owner")


class Bakery(Base):
    __tablename__ = "bakeries"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    location = Column(String, nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="bakeries")
    products = relationship("Product", back_populates="bakery")
    sales = relationship("Sale", back_populates="bakery")


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    bakery_id = Column(Integer, ForeignKey("bakeries.id"), nullable=False)
    name = Column(String, nullable=False)
    sku = Column(String, index=True, nullable=True)
    category = Column(String, nullable=True)
    is_active = Column(Integer, default=1)  # 1 = active, 0 = inactive

    bakery = relationship("Bakery", back_populates="products")
    sales = relationship("Sale", back_populates="product")


class Sale(Base):
    __tablename__ = "sales"

    id = Column(Integer, primary_key=True, index=True)
    bakery_id = Column(Integer, ForeignKey("bakeries.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    sale_date = Column(Date, nullable=False)
    quantity = Column(Integer, nullable=False)
    revenue = Column(Float, nullable=True)
    channel = Column(String, nullable=True)  # e.g. "in_store", "online"

    bakery = relationship("Bakery", back_populates="sales")
    product = relationship("Product", back_populates="sales")

