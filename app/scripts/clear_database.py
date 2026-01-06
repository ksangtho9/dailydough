"""Utility script to wipe the application database that the API uses."""

from app.database.database import SessionLocal
from app.models.bakery import Bakery
from app.models.product import Product
from app.models.sales_record import SalesRecord


def _print_counts(db):
    print("  Bakeries:", db.query(Bakery).count())
    print("  Products:", db.query(Product).count())
    print("  Sales:", db.query(SalesRecord).count())


def clear_database() -> None:
    """Remove all rows from sales, products, and bakeries."""
    db = SessionLocal()
    try:
        print("Before clear:")
        _print_counts(db)

        db.query(SalesRecord).delete(synchronize_session=False)
        db.query(Product).delete(synchronize_session=False)
        db.query(Bakery).delete(synchronize_session=False)

        db.commit()

        print("After clear:")
        _print_counts(db)

        print("Database cleared successfully.")
    except Exception as exc:  # pragma: no cover - script level logging
        db.rollback()
        print("Error while clearing database:", exc)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    clear_database()











