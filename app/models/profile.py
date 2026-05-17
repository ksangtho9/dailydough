from datetime import datetime, timezone

from sqlalchemy import Column, String, Boolean, DateTime

from app.database.database import Base


class Profile(Base):
    """App-level user profile keyed on Supabase auth.users.id (UUID string)."""
    __tablename__ = "profiles"

    id = Column(String, primary_key=True)  # auth.users.id UUID
    email = Column(String, nullable=True)
    is_admin = Column(Boolean, nullable=False, default=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
