from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models.bakery import Bakery
from app.models.product import Product
from app.models.sales_record import SalesRecord

router = APIRouter(prefix="/debug", tags=["debug"])


@router.get("/db-stats")
def debug_db_stats(db: Session = Depends(get_db)):
    return {
        "bakeries": db.query(Bakery).count(),
        "products": db.query(Product).count(),
        "sales": db.query(SalesRecord).count(),
    }


