from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database.database import Base


class Bakery(Base):
    __tablename__ = "bakeries"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_bakeries_user_name"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, nullable=True, index=True)  # auth.users.id UUID
    name = Column(String, nullable=False)
    location = Column(String, nullable=True)
    timezone = Column(String, nullable=True, default="UTC")
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # relationships
    products = relationship(
        "Product",
        back_populates="bakery",
        cascade="all, delete-orphan",
    )

    sales_records = relationship(
        "SalesRecord",
        back_populates="bakery",
        cascade="all, delete-orphan",
    )
    events = relationship(
        "Event",
        back_populates="bakery",
        cascade="all, delete-orphan",
    )
    promotions = relationship(
        "Promotion",
        back_populates="bakery",
        cascade="all, delete-orphan",
    )
    weather_data = relationship(
        "WeatherData",
        back_populates="bakery",
        cascade="all, delete-orphan",
    )