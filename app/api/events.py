from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database.database import get_db
from app.models import Event, Bakery

router = APIRouter(
    prefix="/events",
    tags=["events"],
)


class EventCreate(BaseModel):
    bakery_id: int
    name: str
    date: date
    is_recurring: bool = False
    recurrence_pattern: Optional[str] = None
    sales_multiplier: str = "1.0"
    description: Optional[str] = None


class EventUpdate(BaseModel):
    name: Optional[str] = None
    date: Optional[date] = None
    is_recurring: Optional[bool] = None
    recurrence_pattern: Optional[str] = None
    sales_multiplier: Optional[str] = None
    description: Optional[str] = None


class EventOut(BaseModel):
    id: int
    bakery_id: int
    name: str
    date: date
    is_recurring: bool
    recurrence_pattern: Optional[str]
    sales_multiplier: Optional[str]
    description: Optional[str]

    class Config:
        from_attributes = True


@router.post("/", response_model=EventOut, status_code=status.HTTP_201_CREATED)
def create_event(
    event_in: EventCreate,
    db: Session = Depends(get_db),
):
    """Create a new event."""
    bakery = db.query(Bakery).filter(Bakery.id == event_in.bakery_id).first()
    if not bakery:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bakery not found",
        )

    event = Event(
        bakery_id=event_in.bakery_id,
        name=event_in.name,
        date=event_in.date,
        is_recurring=event_in.is_recurring,
        recurrence_pattern=event_in.recurrence_pattern,
        sales_multiplier=event_in.sales_multiplier,
        description=event_in.description,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@router.get("/", response_model=list[EventOut])
def list_events(
    bakery_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
):
    """List events, optionally filtered by bakery and date range."""
    query = db.query(Event)
    if bakery_id is not None:
        query = query.filter(Event.bakery_id == bakery_id)
    if start_date is not None:
        query = query.filter(Event.date >= start_date)
    if end_date is not None:
        query = query.filter(Event.date <= end_date)
    return query.order_by(Event.date).all()


@router.get("/{event_id}", response_model=EventOut)
def get_event(
    event_id: int,
    db: Session = Depends(get_db),
):
    """Get a specific event."""
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )
    return event


@router.patch("/{event_id}", response_model=EventOut)
def update_event(
    event_id: int,
    event_update: EventUpdate,
    db: Session = Depends(get_db),
):
    """Update an event."""
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    if event_update.name is not None:
        event.name = event_update.name
    if event_update.date is not None:
        event.date = event_update.date
    if event_update.is_recurring is not None:
        event.is_recurring = event_update.is_recurring
    if event_update.recurrence_pattern is not None:
        event.recurrence_pattern = event_update.recurrence_pattern
    if event_update.sales_multiplier is not None:
        event.sales_multiplier = event_update.sales_multiplier
    if event_update.description is not None:
        event.description = event_update.description

    db.commit()
    db.refresh(event)
    return event


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(
    event_id: int,
    db: Session = Depends(get_db),
):
    """Delete an event."""
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )
    db.delete(event)
    db.commit()
    return None

