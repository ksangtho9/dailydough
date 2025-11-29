from sqlalchemy import Column, Integer, String, ForeignKey, Float
from sqlalchemy.orm import relationship

from app.database.database import Base


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    bakery_id = Column(Integer, ForeignKey("bakeries.id"), index=True, nullable=False)

    name = Column(String, nullable=False, index=True)
    sku = Column(String, nullable=False, index=True)
    category = Column(String, nullable=True)
    price = Column(Float, nullable=True)  # Selling price per unit
    cost_per_unit = Column(Float, nullable=True)  # Production cost per unit

    bakery = relationship("Bakery", back_populates="products")
    sales_records = relationship("SalesRecord", back_populates="product")
    forecast_metrics = relationship(
        "ForecastMetrics",
        uselist=False,
        back_populates="product",
        cascade="all, delete-orphan",
    )
