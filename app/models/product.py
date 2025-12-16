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
    # Shelf life in days for this product. Most products are 1-day; some can be carried
    # over to the next day (2 days max as per business rules).
    shelf_life_days = Column(
        Integer,
        nullable=False,
        server_default="1",  # Existing rows default to 1-day shelf life
    )
    # Stockout cost ratio: how much more expensive stockouts are compared to waste.
    # Default 2.0 means stockouts cost 2x waste (e.g., lost revenue + customer dissatisfaction).
    # Used for cost-aware production optimization.
    stockout_cost_ratio = Column(
        Float,
        nullable=False,
        server_default="2.0",  # Default: stockouts cost 2x waste
    )

    bakery = relationship("Bakery", back_populates="products")
    sales_records = relationship("SalesRecord", back_populates="product")
    forecast_metrics = relationship(
        "ForecastMetrics",
        uselist=False,
        back_populates="product",
        cascade="all, delete-orphan",
    )
    promotions = relationship(
        "Promotion",
        back_populates="product",
        cascade="all, delete-orphan",
    )
    walk_forward_results = relationship(
        "WalkForwardResult",
        back_populates="product",
        cascade="all, delete-orphan",
    )
