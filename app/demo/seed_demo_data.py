from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Iterable, Iterator, Tuple

from app.database.database import SessionLocal
from app.models import Bakery, Product, SalesRecord

DEMO_BAKERY_NAME = "Demo Bakery"


def generate_sales_series(
    start_date: date,
    end_date: date,
    base: int,
    weekly_seasonality: bool = True,
    noise: int = 10,
) -> Iterator[Tuple[date, int]]:
    """
    Generate simple daily quantities between start_date and end_date.

    Adds a naive weekly pattern (low Mondays, high weekends) plus random noise.
    """
    current = start_date
    while current <= end_date:
        qty = base

        if weekly_seasonality:
            dow = current.weekday()  # 0 = Monday
            if dow == 0:
                qty = int(qty * 0.7)
            elif dow in (5, 6):  # Saturday / Sunday
                qty = int(qty * 1.3)

        qty = max(0, qty + random.randint(-noise, noise))
        yield current, qty
        current += timedelta(days=1)


def _ensure_demo_bakery(db) -> Bakery:
    bakery = db.query(Bakery).filter(Bakery.name == DEMO_BAKERY_NAME).one_or_none()
    if bakery is None:
        bakery = Bakery(
            name=DEMO_BAKERY_NAME,
            location="Demo City",
            timezone="America/Los_Angeles",
        )
        db.add(bakery)
        db.flush()
    return bakery


def _ensure_products(db, bakery: Bakery) -> Iterable[Tuple[Product, int]]:
    catalog = [
        {"name": "Butter Croissant", "base": 90},
        {"name": "Chocolate Croissant", "base": 70},
        {"name": "Baguette", "base": 55},
        {"name": "Sourdough Loaf", "base": 45},
        {"name": "Blueberry Muffin", "base": 65},
        {"name": "Almond Danish", "base": 40},
    ]

    results: list[Tuple[Product, int]] = []
    for item in catalog:
        product = (
            db.query(Product)
            .filter(
                Product.bakery_id == bakery.id,
                Product.name == item["name"],
            )
            .one_or_none()
        )
        if product is None:
            product = Product(
                bakery_id=bakery.id,
                name=item["name"],
                sku=item["name"].lower().replace(" ", "-"),
                category="bakery",
            )
            db.add(product)
            db.flush()
        results.append((product, item["base"]))
    return results


def seed_demo_data() -> None:
    """
    Populate the database with a demo bakery, catalog, and six months of sales.
    """
    db = SessionLocal()
    try:
        bakery = _ensure_demo_bakery(db)
        products = list(_ensure_products(db, bakery))

        end_date = date.today() - timedelta(days=1)
        start_date = end_date - timedelta(days=180)

        # Clear prior demo sales
        db.query(SalesRecord).filter(SalesRecord.bakery_id == bakery.id).delete(
            synchronize_session=False
        )

        for product, base in products:
            for day, quantity in generate_sales_series(
                start_date,
                end_date,
                base=base,
                weekly_seasonality=True,
                noise=max(5, base // 4),
            ):
                sale = SalesRecord(
                    bakery_id=bakery.id,
                    product_id=product.id,
                    date=day,
                    quantity_sold=quantity,
                )
                db.add(sale)

        db.commit()
        print(f"Demo data seeded successfully for '{DEMO_BAKERY_NAME}'.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_demo_data()

