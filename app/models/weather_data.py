from datetime import date
from sqlalchemy import Column, Date, ForeignKey, Integer, Float, String
from sqlalchemy.orm import relationship

from app.database.database import Base


class WeatherData(Base):
    """Historical and forecasted weather data for bakeries."""
    __tablename__ = "weather_data"

    id = Column(Integer, primary_key=True, index=True)
    bakery_id = Column(Integer, ForeignKey("bakeries.id"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    # Temperature in Celsius
    temperature = Column(Float, nullable=True)
    # Precipitation in mm
    precipitation = Column(Float, nullable=True)
    # Weather condition: "sunny", "rainy", "cloudy", "snowy", etc.
    condition = Column(String, nullable=True)
    # Source: "api", "csv", "manual"
    source = Column(String, nullable=False, default="manual")
    # Whether this is forecasted data (True) or historical (False)
    is_forecast = Column(String, nullable=False, default="false")  # Using String for compatibility

    bakery = relationship("Bakery", back_populates="weather_data")

