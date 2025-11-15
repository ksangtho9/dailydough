from datetime import datetime
import csv
from io import StringIO
from typing import List, Tuple

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models import SalesRecord, Product, Bakery
from app.user_schemas import SalesRecordCreate, SalesRecordOut
from app.api.auth import get_current_user          # ✅ import from auth.py
from app.schemas import sales_record               # ✅ our sales-series schemas


router = APIRouter(
    prefix="/sales",        # combined with /api prefix from router.py → /api/sales
    tags=["sales"],
)


# ---------- JSON sales endpoints ----------

@router.post("/", response_model=SalesRecordOut, status_code=status.HTTP_201_CREATED)
def create_sales_record(
    sales_in: SalesRecordCreate,
    db: Session = Depends(get_db),
):
    # Ensure bakery exists
    bakery = db.query(Bakery).filter(Bakery.id == sales_in.bakery_id).first()
    if not bakery:
        raise HTTPException(status_code=404, detail="Bakery not found")

    # Ensure product exists and belongs to that bakery
    product = db.query(Product).filter(Product.id == sales_in.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if product.bakery_id != sales_in.bakery_id:
        raise HTTPException(
            status_code=400,
            detail="Product does not belong to the given bakery",
        )

    record = SalesRecord(
        bakery_id=sales_in.bakery_id,
        product_id=sales_in.product_id,
        date=sales_in.date,
        quantity_sold=sales_in.quantity_sold,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.get("/", response_model=List[SalesRecordOut])
def list_sales(
    bakery_id: int | None = None,
    product_id: int | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(SalesRecord)
    if bakery_id is not None:
        query = query.filter(SalesRecord.bakery_id == bakery_id)
    if product_id is not None:
        query = query.filter(SalesRecord.product_id == product_id)
    return query.order_by(SalesRecord.date).all()


# ---------- CSV upload helpers + endpoint ----------

def parse_csv(content: str) -> Tuple[List[dict], List[str]]:
    """
    Parse CSV with columns:
      product_id,sale_date,units_sold,revenue

    We map:
      sale_date   -> date
      units_sold  -> quantity_sold
      revenue     -> ignored in DB for now
    """
    reader = csv.DictReader(StringIO(content))
    required_fields = {"product_id", "sale_date", "units_sold", "revenue"}
    rows: List[dict] = []
    errors: List[str] = []

    # Validate headers
    missing = required_fields - set((reader.fieldnames or []))
    if missing:
        errors.append(f"Missing required columns: {', '.join(sorted(missing))}")
        return [], errors

    for idx, raw in enumerate(reader, start=2):  # start=2 accounts for header line
        try:
            product_id = int(raw["product_id"])
            sale_date = datetime.strptime(raw["sale_date"], "%Y-%m-%d").date()
            quantity_sold = float(raw["units_sold"])
            # revenue is parsed but not stored in SalesRecord
            _ = float(raw["revenue"])

            rows.append(
                {
                    "product_id": product_id,
                    "date": sale_date,
                    "quantity_sold": quantity_sold,
                }
            )
        except Exception as exc:
            errors.append(f"Line {idx}: {exc}")
    return rows, errors


@router.post("/upload-csv", status_code=status.HTTP_201_CREATED)
async def upload_sales(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if not file.filename.endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .csv files are accepted",
        )

    content_bytes = await file.read()
    try:
        content = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSV must be UTF-8 encoded",
        )

    rows, parse_errors = parse_csv(content)
    if not rows and parse_errors:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="; ".join(parse_errors),
        )

    inserted = 0
    skipped_missing_product = 0
    row_errors: List[str] = []

    for idx, row in enumerate(rows, start=2):
        product = db.query(Product).filter(Product.id == row["product_id"]).first()
        if not product:
            skipped_missing_product += 1
            row_errors.append(
                f"Line {idx}: product_id {row['product_id']} not found"
            )
            continue

        try:
            record = SalesRecord(
                bakery_id=product.bakery_id,
                product_id=row["product_id"],
                date=row["date"],
                quantity_sold=row["quantity_sold"],
            )
            db.add(record)
            inserted += 1
        except Exception as exc:
            row_errors.append(f"Line {idx}: {exc}")
            db.rollback()

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )

    return {
        "filename": file.filename,
        "inserted": inserted,
        "skipped_missing_product": skipped_missing_product,
        "parse_errors": parse_errors,
        "row_errors": row_errors,
    }


# ---------- NEW: product-level timeseries endpoint ----------

@router.get("/product/{product_id}", response_model=sales_record.ProductSalesSeries)
def get_product_sales_for_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """
    Return time-series sales data for a single product.
    Backed by SalesRecord rows.
    """

    # Ensure product exists
    product = (
        db.query(Product)
        .filter(Product.id == product_id)
        .first()
    )

    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found.",
        )

    # Fetch sales records for that product
    sales_rows = (
        db.query(SalesRecord)
        .filter(SalesRecord.product_id == product_id)
        .order_by(SalesRecord.date.asc())
        .all()
    )

    sales_points = [
        sales_record.ProductSalesPoint(
            date=row.date,
            quantity=row.quantity_sold,    # 👈 map quantity_sold → quantity
        )
        for row in sales_rows
    ]

    return sales_record.ProductSalesSeries(
        product_id=product.id,
        product_name=product.name,
        sales=sales_points,
    )


