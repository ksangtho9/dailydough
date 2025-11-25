from typing import Optional
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.database.database import get_db
from app.models import Bakery
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

    try:
        ingestion_result = ingest_sales_csv(
            db=db,
            file_bytes=content_bytes,
            column_mapping_json=column_mapping,
            context_bakery_id=bakery_id,
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
