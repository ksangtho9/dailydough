"""
Clear all application data from the database while keeping schema intact.

This script deletes all rows from:
- sales_records (SalesRecord)
- products (Product)
- bakeries (Bakery)

Deletion order respects foreign key constraints.

Uses the same SessionLocal as the main FastAPI app (app.database.database).

Usage:
    python -m app.scripts.clear_database

Note: Must be run as a module (using -m) for imports to work correctly.
"""

from app.database.database import SessionLocal
from app.models import Bakery, Product, SalesRecord


def clear_database():
    """
    Delete all rows from sales_records, products, and bakeries tables.
    
    Order of deletion respects FK constraints:
    1. SalesRecord (has FK to both Product and Bakery)
    2. Product (has FK to Bakery)
    3. Bakery (no dependencies)
    
    Uses synchronize_session=False to avoid stale-state issues.
    """
    db = SessionLocal()
    
    try:
        # Print counts before deletion
        print("Before clear:")
        bakeries_before = db.query(Bakery).count()
        products_before = db.query(Product).count()
        sales_before = db.query(SalesRecord).count()
        print(f"  Bakeries: {bakeries_before}")
        print(f"  Products: {products_before}")
        print(f"  Sales: {sales_before}")
        
        # Delete in FK-safe order with synchronize_session=False
        deleted_sales = db.query(SalesRecord).delete(synchronize_session=False)
        print(f"\nDeleted {deleted_sales} sales records")
        
        deleted_products = db.query(Product).delete(synchronize_session=False)
        print(f"Deleted {deleted_products} products")
        
        deleted_bakeries = db.query(Bakery).delete(synchronize_session=False)
        print(f"Deleted {deleted_bakeries} bakeries")
        
        db.commit()
        
        # Print counts after deletion
        print("\nAfter clear:")
        bakeries_after = db.query(Bakery).count()
        products_after = db.query(Product).count()
        sales_after = db.query(SalesRecord).count()
        print(f"  Bakeries: {bakeries_after}")
        print(f"  Products: {products_after}")
        print(f"  Sales: {sales_after}")
        
        if bakeries_after == 0 and products_after == 0 and sales_after == 0:
            print("\n✅ Database cleared successfully.")
        else:
            print("\n⚠️  Warning: Some data may still remain.")
        
    except Exception as e:
        db.rollback()
        print(f"\n❌ Error while clearing database: {e}")
        raise
    
    finally:
        db.close()


if __name__ == "__main__":
    clear_database()

