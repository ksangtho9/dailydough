"""
Debug endpoints for database inspection and verification.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models import Bakery, Product, SalesRecord

router = APIRouter(prefix="/debug", tags=["debug"])


@router.get("/db-stats")
def debug_db_stats(db: Session = Depends(get_db)):
    """
    Return counts of all main tables.
    Useful for verifying database state after clearing.
    """
    return {
        "bakeries": db.query(Bakery).count(),
        "products": db.query(Product).count(),
        "sales": db.query(SalesRecord).count(),
    }

