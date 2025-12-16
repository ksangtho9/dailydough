from datetime import date, datetime

from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Integer, func
from sqlalchemy.orm import relationship

from app.database.database import Base


class WalkForwardResult(Base):
    __tablename__ = "walk_forward_results"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(
        Integer,
        ForeignKey("products.id"),
        nullable=False,
        index=True,
    )
    test_date = Column(Date, nullable=False, index=True)
    predicted_quantity = Column(Float, nullable=False)
    actual_quantity = Column(Float, nullable=True)
    absolute_error = Column(Float, nullable=True)
    percentage_error = Column(Float, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    product = relationship("Product", back_populates="walk_forward_results")
