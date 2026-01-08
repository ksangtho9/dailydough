from datetime import date
from sqlalchemy import Column, Date, ForeignKey, Integer, String, Boolean
from sqlalchemy.orm import relationship

from app.database.database import Base


class Event(Base):
    """User-defined events (holidays, local events, special days) that affect sales."""
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)
    bakery_id = Column(Integer, ForeignKey("bakeries.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    date = Column(Date, nullable=False, index=True)
    is_recurring = Column(Boolean, nullable=False, default=False)
    # For recurring events: "first_friday", "last_monday", "15th_of_month", etc.
    recurrence_pattern = Column(String, nullable=True)
    # Multiplier effect on sales (1.0 = no effect, 1.5 = 50% increase, 0.5 = 50% decrease)
    sales_multiplier = Column(String, nullable=True, default="1.0")
    description = Column(String, nullable=True)

    bakery = relationship("Bakery", back_populates="events")









