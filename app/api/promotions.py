from datetime import date
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database.database import get_db
from app.models import Promotion, Bakery, Product

router = APIRouter(
    prefix="/promotions",
    tags=["promotions"],
)


class PromotionCreate(BaseModel):
    bakery_id: int
    product_id: int | None = None
    name: str
    start_date: date
    end_date: date
    discount_percent: float | None = None
    sales_multiplier: float = 1.0
    description: str | None = None
    is_active: bool = True


class PromotionUpdate(BaseModel):
    name: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    discount_percent: float | None = None
    sales_multiplier: float | None = None
    description: str | None = None
    is_active: bool | None = None


class PromotionOut(BaseModel):
    id: int
    bakery_id: int
    product_id: int | None
    name: str
    start_date: date
    end_date: date
    discount_percent: float | None
    sales_multiplier: float | None
    description: str | None
    is_active: bool

    class Config:
        from_attributes = True


@router.post("/", response_model=PromotionOut, status_code=status.HTTP_201_CREATED)
def create_promotion(
    promotion_in: PromotionCreate,
    db: Session = Depends(get_db),
):
    """Create a new promotion."""
    bakery = db.query(Bakery).filter(Bakery.id == promotion_in.bakery_id).first()
    if not bakery:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bakery not found",
        )

    if promotion_in.product_id is not None:
        product = db.query(Product).filter(Product.id == promotion_in.product_id).first()
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found",
            )
        if product.bakery_id != promotion_in.bakery_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Product does not belong to the specified bakery",
            )

    if promotion_in.start_date > promotion_in.end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Start date must be before end date",
        )

    promotion = Promotion(
        bakery_id=promotion_in.bakery_id,
        product_id=promotion_in.product_id,
        name=promotion_in.name,
        start_date=promotion_in.start_date,
        end_date=promotion_in.end_date,
        discount_percent=promotion_in.discount_percent,
        sales_multiplier=promotion_in.sales_multiplier,
        description=promotion_in.description,
        is_active=promotion_in.is_active,
    )
    db.add(promotion)
    db.commit()
    db.refresh(promotion)
    return promotion


@router.get("/", response_model=list[PromotionOut])
def list_promotions(
    bakery_id: int | None = None,
    product_id: int | None = None,
    is_active: bool | None = None,
    db: Session = Depends(get_db),
):
    """List promotions, optionally filtered."""
    query = db.query(Promotion)
    if bakery_id is not None:
        query = query.filter(Promotion.bakery_id == bakery_id)
    if product_id is not None:
        query = query.filter(
            (Promotion.product_id == product_id) | (Promotion.product_id.is_(None))
        )
    if is_active is not None:
        query = query.filter(Promotion.is_active == is_active)
    return query.order_by(Promotion.start_date).all()


@router.get("/{promotion_id}", response_model=PromotionOut)
def get_promotion(
    promotion_id: int,
    db: Session = Depends(get_db),
):
    """Get a specific promotion."""
    promotion = db.query(Promotion).filter(Promotion.id == promotion_id).first()
    if not promotion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Promotion not found",
        )
    return promotion


@router.patch("/{promotion_id}", response_model=PromotionOut)
def update_promotion(
    promotion_id: int,
    promotion_update: PromotionUpdate,
    db: Session = Depends(get_db),
):
    """Update a promotion."""
    promotion = db.query(Promotion).filter(Promotion.id == promotion_id).first()
    if not promotion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Promotion not found",
        )

    if promotion_update.name is not None:
        promotion.name = promotion_update.name
    if promotion_update.start_date is not None:
        promotion.start_date = promotion_update.start_date
    if promotion_update.end_date is not None:
        promotion.end_date = promotion_update.end_date
    if promotion_update.discount_percent is not None:
        promotion.discount_percent = promotion_update.discount_percent
    if promotion_update.sales_multiplier is not None:
        promotion.sales_multiplier = promotion_update.sales_multiplier
    if promotion_update.description is not None:
        promotion.description = promotion_update.description
    if promotion_update.is_active is not None:
        promotion.is_active = promotion_update.is_active

    if promotion.start_date > promotion.end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Start date must be before end date",
        )

    db.commit()
    db.refresh(promotion)
    return promotion


@router.delete("/{promotion_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_promotion(
    promotion_id: int,
    db: Session = Depends(get_db),
):
    """Delete a promotion."""
    promotion = db.query(Promotion).filter(Promotion.id == promotion_id).first()
    if not promotion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Promotion not found",
        )
    db.delete(promotion)
    db.commit()
    return None









