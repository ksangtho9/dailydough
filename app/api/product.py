from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models import Product, Bakery
from app.user_schemas import ProductCreate, ProductOut

router = APIRouter(
    prefix="/api/products",
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

    product = Product(
        bakery_id=product_in.bakery_id,
        name=product_in.name,
        sku=product_in.sku,
        category=product_in.category,
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
    query = db.query(Product)
    if bakery_id is not None:
        query = query.filter(Product.bakery_id == bakery_id)
    return query.all()
