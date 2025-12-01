from typing import Optional, List
from sqlalchemy.orm import Session

from app.models.product import Product
from app.schemas.product import ProductCreate, ProductUpdate


def create_product(
    db: Session,
    *,
    bakery_id: int,
    obj_in: ProductCreate,
) -> Product:
    db_obj = Product(
        bakery_id=bakery_id,
        name=obj_in.name,
        sku=obj_in.sku,
        category=obj_in.category,
        price=obj_in.price,
        cost_per_unit=obj_in.cost_per_unit,
        shelf_life_days=obj_in.shelf_life_days or 1,
        stockout_cost_ratio=getattr(obj_in, "stockout_cost_ratio", None) or 2.0,
    )
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj


def get_product(
    db: Session,
    *,
    bakery_id: int,
    product_id: int,
) -> Optional[Product]:
    return (
        db.query(Product)
        .filter(Product.bakery_id == bakery_id, Product.id == product_id)
        .first()
    )


def list_products(
    db: Session,
    *,
    bakery_id: int,
    skip: int = 0,
    limit: int = 100,
) -> List[Product]:
    return (
        db.query(Product)
        .filter(Product.bakery_id == bakery_id)
        .offset(skip)
        .limit(limit)
        .all()
    )


def update_product(
    db: Session,
    *,
    bakery_id: int,
    product_id: int,
    obj_in: ProductUpdate,
) -> Optional[Product]:
    db_obj = get_product(db, bakery_id=bakery_id, product_id=product_id)
    if not db_obj:
        return None

    if obj_in.name is not None:
        db_obj.name = obj_in.name
    if obj_in.sku is not None:
        db_obj.sku = obj_in.sku
    if obj_in.category is not None:
        db_obj.category = obj_in.category
    if obj_in.price is not None:
        db_obj.price = obj_in.price
    if obj_in.cost_per_unit is not None:
        db_obj.cost_per_unit = obj_in.cost_per_unit
    if getattr(obj_in, "shelf_life_days", None) is not None:
        # Enforce business rule: shelf life is 1 or 2 days max
        value = int(obj_in.shelf_life_days)  # type: ignore[arg-type]
        if value < 1 or value > 2:
            value = 1
        db_obj.shelf_life_days = value
    if getattr(obj_in, "stockout_cost_ratio", None) is not None:
        value = float(obj_in.stockout_cost_ratio)  # type: ignore[arg-type]
        if value < 0.1:  # Minimum reasonable ratio
            value = 0.1
        db_obj.stockout_cost_ratio = value

    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj


def delete_product(
    db: Session,
    *,
    bakery_id: int,
    product_id: int,
) -> bool:
    db_obj = get_product(db, bakery_id=bakery_id, product_id=product_id)
    if not db_obj:
        return False
    db.delete(db_obj)
    db.commit()
    return True
