from datetime import date
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database.database import get_db
from app.models import WeatherData, Bakery

router = APIRouter(
    prefix="/weather",
    tags=["weather"],
)


class WeatherDataCreate(BaseModel):
    bakery_id: int
    date: date
    temperature: float | None = None
    precipitation: float | None = None
    condition: str | None = None
    source: str = "manual"
    is_forecast: str = "false"


class WeatherDataUpdate(BaseModel):
    temperature: float | None = None
    precipitation: float | None = None
    condition: str | None = None
    source: str | None = None
    is_forecast: str | None = None


class WeatherDataOut(BaseModel):
    id: int
    bakery_id: int
    date: date
    temperature: float | None
    precipitation: float | None
    condition: str | None
    source: str
    is_forecast: str

    class Config:
        from_attributes = True


@router.post("/", response_model=WeatherDataOut, status_code=status.HTTP_201_CREATED)
def create_weather_data(
    weather_in: WeatherDataCreate,
    db: Session = Depends(get_db),
):
    """Create or update weather data for a specific date and bakery."""
    bakery = db.query(Bakery).filter(Bakery.id == weather_in.bakery_id).first()
    if not bakery:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bakery not found",
        )

    # Check if weather data already exists for this date and bakery
    existing = (
        db.query(WeatherData)
        .filter(
            WeatherData.bakery_id == weather_in.bakery_id,
            WeatherData.date == weather_in.date,
        )
        .first()
    )

    if existing:
        # Update existing record
        if weather_in.temperature is not None:
            existing.temperature = weather_in.temperature
        if weather_in.precipitation is not None:
            existing.precipitation = weather_in.precipitation
        if weather_in.condition is not None:
            existing.condition = weather_in.condition
        existing.source = weather_in.source
        existing.is_forecast = weather_in.is_forecast
        db.commit()
        db.refresh(existing)
        return existing
    else:
        # Create new record
        weather = WeatherData(
            bakery_id=weather_in.bakery_id,
            date=weather_in.date,
            temperature=weather_in.temperature,
            precipitation=weather_in.precipitation,
            condition=weather_in.condition,
            source=weather_in.source,
            is_forecast=weather_in.is_forecast,
        )
        db.add(weather)
        db.commit()
        db.refresh(weather)
        return weather


@router.get("/", response_model=list[WeatherDataOut])
def list_weather_data(
    bakery_id: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    db: Session = Depends(get_db),
):
    """List weather data, optionally filtered by bakery and date range."""
    query = db.query(WeatherData)
    if bakery_id is not None:
        query = query.filter(WeatherData.bakery_id == bakery_id)
    if start_date is not None:
        query = query.filter(WeatherData.date >= start_date)
    if end_date is not None:
        query = query.filter(WeatherData.date <= end_date)
    return query.order_by(WeatherData.date).all()


@router.get("/{weather_id}", response_model=WeatherDataOut)
def get_weather_data(
    weather_id: int,
    db: Session = Depends(get_db),
):
    """Get specific weather data."""
    weather = db.query(WeatherData).filter(WeatherData.id == weather_id).first()
    if not weather:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Weather data not found",
        )
    return weather


@router.patch("/{weather_id}", response_model=WeatherDataOut)
def update_weather_data(
    weather_id: int,
    weather_update: WeatherDataUpdate,
    db: Session = Depends(get_db),
):
    """Update weather data."""
    weather = db.query(WeatherData).filter(WeatherData.id == weather_id).first()
    if not weather:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Weather data not found",
        )

    if weather_update.temperature is not None:
        weather.temperature = weather_update.temperature
    if weather_update.precipitation is not None:
        weather.precipitation = weather_update.precipitation
    if weather_update.condition is not None:
        weather.condition = weather_update.condition
    if weather_update.source is not None:
        weather.source = weather_update.source
    if weather_update.is_forecast is not None:
        weather.is_forecast = weather_update.is_forecast

    db.commit()
    db.refresh(weather)
    return weather


@router.delete("/{weather_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_weather_data(
    weather_id: int,
    db: Session = Depends(get_db),
):
    """Delete weather data."""
    weather = db.query(WeatherData).filter(WeatherData.id == weather_id).first()
    if not weather:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Weather data not found",
        )
    db.delete(weather)
    db.commit()
    return None







