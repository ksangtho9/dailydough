from typing import Optional
from datetime import date
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.database.database import get_db
from app.models import Bakery, SalesRecord
from app.user_schemas import BakeryCreate, BakeryOut
from app.services.sales_ingestion import (
    SchemaInferenceError,
    ingest_sales_csv,
)
from app.ml.training.train_all_products import train_all_products

router = APIRouter(
    prefix="/bakeries",
    tags=["bakeries"],
)


@router.post("/", response_model=BakeryOut, status_code=status.HTTP_201_CREATED)
def create_bakery(
    bakery_in: BakeryCreate,
    db: Session = Depends(get_db),
):
    bakery = Bakery(
        name=bakery_in.name,
        location=bakery_in.location,
        timezone=bakery_in.timezone or "UTC",
    )
    db.add(bakery)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # name is UNIQUE, so this happens if the name already exists
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A bakery with this name already exists",
        )
    db.refresh(bakery)
    return bakery



@router.get("/", response_model=list[BakeryOut])
def list_bakeries(db: Session = Depends(get_db)):
    return db.query(Bakery).all()


@router.post("/{bakery_id}/sales/upload", status_code=status.HTTP_201_CREATED)
async def upload_sales_for_bakery(
    bakery_id: int,
    file: UploadFile = File(...),
    column_mapping: Optional[str] = Form(None),
    upload_mode: Optional[str] = Form("append", description="Upload mode: 'append' or 'replace'"),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: Session = Depends(get_db),
):
    """
    Upload sales CSV for a specific bakery. The bakery_id from the URL will be
    used as the context bakery for rows that don't have bakery_id in the CSV.
    """
    # Verify bakery exists
    bakery = db.query(Bakery).filter(Bakery.id == bakery_id).first()
    if not bakery:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bakery not found",
        )

    if not file.filename.endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .csv files are accepted",
        )

    content_bytes = await file.read()

    # Validate upload_mode
    if upload_mode not in ["append", "replace"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="upload_mode must be 'append' or 'replace'",
        )

    try:
        ingestion_result = ingest_sales_csv(
            db=db,
            file_bytes=content_bytes,
            column_mapping_json=column_mapping,
            context_bakery_id=bakery_id,
            replace_mode=(upload_mode == "replace"),
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
    background_tasks.add_task(train_all_products, db=None, bakery_id=bakery_id)

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


@router.delete("/{bakery_id}/sales", status_code=status.HTTP_200_OK)
def delete_sales_for_bakery(
    bakery_id: int,
    date_from: Optional[date] = Query(None, description="Delete records from this date (inclusive)"),
    date_to: Optional[date] = Query(None, description="Delete records up to this date (inclusive)"),
    product_id: Optional[int] = Query(None, description="Delete records for this product only"),
    db: Session = Depends(get_db),
):
    """
    Delete sales records for a bakery. Supports optional filters:
    - date_from/date_to: Delete records within date range
    - product_id: Delete records for a specific product
    - If no filters provided, deletes all sales for the bakery
    """
    # Verify bakery exists
    bakery = db.query(Bakery).filter(Bakery.id == bakery_id).first()
    if not bakery:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bakery not found",
        )

    # Build query
    query = db.query(SalesRecord).filter(SalesRecord.bakery_id == bakery_id)

    if date_from:
        query = query.filter(SalesRecord.date >= date_from)
    if date_to:
        query = query.filter(SalesRecord.date <= date_to)
    if product_id:
        query = query.filter(SalesRecord.product_id == product_id)

    # Count before deletion
    count = query.count()

    # Delete records
    query.delete(synchronize_session=False)
    db.commit()

    return {
        "deleted_count": count,
        "bakery_id": bakery_id,
        "filters": {
            "date_from": str(date_from) if date_from else None,
            "date_to": str(date_to) if date_to else None,
            "product_id": product_id,
        },
    }
