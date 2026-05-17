from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, selectinload

from app.database.database import get_db
from app.models import Product, Bakery, ForecastMetrics
from app.user_schemas import ProductCreate, ProductOut
from app.schemas.forecast import ForecastMetricsSchema

router = APIRouter(
    prefix="/products",
    tags=["products"],
)


@router.post("/", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(
    product_in: ProductCreate,
    db: Session = Depends(get_db),
):
    # Make sure the bakery exists
    bakery = db.query(Bakery).filter(Bakery.id == product_in.bakery_id).first()
    if not bakery:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bakery not found",
        )

    # Enforce shelf life defaults and bounds at the API layer as well
    shelf_life_days = product_in.shelf_life_days or 1
    if shelf_life_days < 1 or shelf_life_days > 2:
        shelf_life_days = 1

    product = Product(
        bakery_id=product_in.bakery_id,
        name=product_in.name,
        sku=product_in.sku,
        category=product_in.category,
        price=product_in.price,
        cost_per_unit=product_in.cost_per_unit,
        shelf_life_days=shelf_life_days,
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@router.get("/", response_model=list[ProductOut])
def list_products(
    bakery_id: int | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(Product).options(selectinload(Product.forecast_metrics))
    if bakery_id is not None:
        query = query.filter(Product.bakery_id == bakery_id)
    return query.all()


@router.get(
    "/{product_id}/metrics",
    response_model=ForecastMetricsSchema,
    status_code=status.HTTP_200_OK,
)
def get_product_metrics(
    product_id: int,
    db: Session = Depends(get_db),
):
    product = db.query(Product).filter(Product.id == product_id).one_or_none()
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    metrics = (
        db.query(ForecastMetrics)
        .filter(ForecastMetrics.product_id == product_id)
        .one_or_none()
    )
    if metrics is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No forecast metrics for this product",
        )

    return metrics
