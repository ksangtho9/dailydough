from datetime import datetime

from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.database.database import Base


class Bakery(Base):
	__tablename__ = "bakeries"

	id = Column(Integer, primary_key=True, index=True)
	name = Column(String, nullable=False, unique=True)
	location = Column(String, nullable=True)
	created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

	products = relationship(
		"Product",
		back_populates="bakery",
		cascade="all, delete-orphan",
	)


class Product(Base):
	__tablename__ = "products"

	id = Column(Integer, primary_key=True, index=True)
	bakery_id = Column(Integer, ForeignKey("bakeries.id"), nullable=False)
	name = Column(String, nullable=False)
	description = Column(String, nullable=True)
	price = Column(Float, nullable=False)

	bakery = relationship("Bakery", back_populates="products")
	daily_sales = relationship(
		"DailySales",
		back_populates="product",
		cascade="all, delete-orphan",
	)


class DailySales(Base):
	__tablename__ = "daily_sales"

	id = Column(Integer, primary_key=True, index=True)
	product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
	sale_date = Column(Date, nullable=False)
	units_sold = Column(Integer, nullable=False)
	revenue = Column(Float, nullable=False)

	product = relationship("Product", back_populates="daily_sales")


