from datetime import date
from sqlalchemy import Column, Date, ForeignKey, Integer, String, Float, Boolean
from sqlalchemy.orm import relationship

from app.database.database import Base


class Promotion(Base):
    """Promotion campaigns that affect product sales."""
    __tablename__ = "promotions"

    id = Column(Integer, primary_key=True, index=True)
    bakery_id = Column(Integer, ForeignKey("bakeries.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True, index=True)
    # If product_id is None, promotion applies to all products in bakery
    name = Column(String, nullable=False)
    start_date = Column(Date, nullable=False, index=True)
    end_date = Column(Date, nullable=False, index=True)
    # Discount percentage (0-100) or multiplier (e.g., 1.2 for 20% increase)
    discount_percent = Column(Float, nullable=True)
    sales_multiplier = Column(Float, nullable=True, default=1.0)
    description = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)

    bakery = relationship("Bakery", back_populates="promotions")
    product = relationship("Product", back_populates="promotions")


