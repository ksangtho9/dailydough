from sqlalchemy import Column, Integer, String, ForeignKey, Date, Float
from sqlalchemy.orm import relationship

from app.database.database import Base


class SalesRecord(Base):
    __tablename__ = "sales_records"

    id = Column(Integer, primary_key=True, index=True)
    bakery_id = Column(Integer, ForeignKey("bakeries.id"), index=True, nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), index=True, nullable=False)

    date = Column(Date, nullable=False, index=True)
    quantity_sold = Column(Float, nullable=False)
    quantity_delivered = Column(Float, nullable=True)

    bakery = relationship("Bakery", back_populates="sales_records")
    product = relationship("Product", back_populates="sales_records")
