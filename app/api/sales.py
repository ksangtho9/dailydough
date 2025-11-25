from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models import SalesRecord, Bakery, Product
from app.user_schemas import SalesRecordCreate, SalesRecordOut
from app.api.auth import get_current_user          # ✅ import from auth.py
from app.schemas import sales_record               # ✅ our sales-series schemas
from app.services.sales_ingestion import (
    SchemaInferenceError,
    ingest_sales_csv,
)
from app.ml.training.train_all_products import train_all_products


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


@router.post("/upload-csv", status_code=status.HTTP_201_CREATED)
async def upload_sales(
    file: UploadFile = File(...),
    column_mapping: Optional[str] = Form(None),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: Session = Depends(get_db),
):
    """
    Upload sales CSV. If bakery_id is provided in the URL path, it will be used
    as the context bakery for rows that don't have bakery_id in the CSV.
    """
    if not file.filename.endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .csv files are accepted",
        )

    content_bytes = await file.read()

    try:
        ingestion_result = ingest_sales_csv(
            db=db,
            file_bytes=content_bytes,
            column_mapping_json=column_mapping,
            context_bakery_id=None,
        )
    except SchemaInferenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "schema_inference_failed",
                "message": "Could not infer all required columns from CSV.",
                "inferred_mapping": exc.mapping,
                "missing_roles": exc.missing_roles,
                "available_columns": exc.available_columns,
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    # Trigger automatic training in the background after successful upload
    # Models will retrain for all products that may have been affected
    # Pass db=None so train_all_products creates its own session (BackgroundTasks runs after request completes)
    background_tasks.add_task(train_all_products, db=None)

    return {
        "filename": file.filename,
        "inserted": ingestion_result.inserted,
        "sales_rows_inserted": ingestion_result.sales_rows_inserted,
        "skipped_missing_product": ingestion_result.skipped_missing_product,
        "created_products": ingestion_result.created_products,
        "existing_products_used": ingestion_result.existing_products_used,
        "parse_errors": ingestion_result.parse_errors,
        "row_errors": ingestion_result.row_errors,
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


