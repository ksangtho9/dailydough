from __future__ import annotations
from typing import Optional
from datetime import date
import logging
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.database.database import get_db
from app.models import Bakery, SalesRecord, Product, ForecastMetrics, DailyForecast, Profile
from app.user_schemas import BakeryCreate, BakeryOut
from app.api.auth import get_current_user
from app.core.config import settings
from app.services.sales_ingestion import (
    SchemaInferenceError,
    ingest_sales_csv,
)
from app.ml.training.train_all_products import train_all_products

logger = logging.getLogger("bakezy.api.bakery")

router = APIRouter(
    prefix="/bakeries",
    tags=["bakeries"],
)


@router.post("/", response_model=BakeryOut, status_code=status.HTTP_201_CREATED)
def create_bakery(
    bakery_in: BakeryCreate,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    bakery = Bakery(
        name=bakery_in.name,
        location=bakery_in.location,
        timezone=bakery_in.timezone or "UTC",
        user_id=current_user.id,
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
def list_bakeries(
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    return db.query(Bakery).filter(Bakery.user_id == current_user.id).all()


@router.delete("/{bakery_id}", status_code=status.HTTP_200_OK)
def delete_bakery(
    bakery_id: int,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    bakery = db.query(Bakery).filter(
        Bakery.id == bakery_id, Bakery.user_id == current_user.id
    ).first()
    if not bakery:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bakery not found",
        )
    
    # Store bakery name for response
    bakery_name = bakery.name
    
    # Delete DailyForecast records (no cascade, so manual delete)
    daily_forecast_count = (
        db.query(DailyForecast)
        .filter(DailyForecast.bakery_id == bakery_id)
        .delete(synchronize_session=False)
    )
    
    # Delete the bakery (cascade will handle products, sales_records, events, promotions, weather_data)
    # Products cascade will handle forecast_metrics, model_runs, walk_forward_results
    db.delete(bakery)
    db.commit()
    
    return {
        "message": f"Bakery '{bakery_name}' and all associated data deleted successfully",
        "bakery_id": bakery_id,
        "bakery_name": bakery_name,
        "daily_forecasts_deleted": daily_forecast_count,
    }


@router.post("/{bakery_id}/sales/upload", status_code=status.HTTP_201_CREATED)
async def upload_sales_for_bakery(
    bakery_id: int,
    file: UploadFile = File(...),
    column_mapping: Optional[str] = Form(None),
    upload_mode: Optional[str] = Form("append", description="Upload mode: 'append' or 'replace'"),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    bakery = db.query(Bakery).filter(
        Bakery.id == bakery_id, Bakery.user_id == current_user.id
    ).first()
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
    
    # Check file size limit
    if len(content_bytes) > settings.max_upload_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File size ({len(content_bytes) / (1024*1024):.1f}MB) exceeds maximum of {settings.max_upload_size_mb}MB",
        )
    
    # Best-effort content-type check (don't rely solely on it)
    if file.content_type and file.content_type not in ["text/csv", "application/csv", "text/plain"]:
        logger.warning(f"Unexpected content-type {file.content_type} for file {file.filename}")

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
    except ValueError:
        logger.exception("ValueError in bakery sales upload")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid data in upload. Please check your CSV format and try again.",
        )
    except Exception:
        logger.exception("Unexpected error in bakery sales upload")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred processing the upload. Please try again later.",
        )

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
    current_user: Profile = Depends(get_current_user),
):
    bakery = db.query(Bakery).filter(
        Bakery.id == bakery_id, Bakery.user_id == current_user.id
    ).first()
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

    # Get affected product IDs before deletion for ForecastMetrics cleanup
    affected_product_ids = set(query.with_entities(SalesRecord.product_id).distinct().all())
    affected_product_ids = {pid[0] for pid in affected_product_ids}

    # Count before deletion
    count = query.count()

    # Delete sales records
    query.delete(synchronize_session=False)

    # Clean up ForecastMetrics for affected products
    # If all sales are deleted (no filters), clean up all ForecastMetrics for this bakery
    if not date_from and not date_to and not product_id:
        # Delete all ForecastMetrics for all products in this bakery
        products_in_bakery = db.query(Product.id).filter(Product.bakery_id == bakery_id).all()
        product_ids_in_bakery = {pid[0] for pid in products_in_bakery}
        if product_ids_in_bakery:
            db.query(ForecastMetrics).filter(
                ForecastMetrics.product_id.in_(product_ids_in_bakery)
            ).delete(synchronize_session=False)
    elif affected_product_ids:
        # Delete ForecastMetrics only for products that had their sales deleted
        db.query(ForecastMetrics).filter(
            ForecastMetrics.product_id.in_(affected_product_ids)
        ).delete(synchronize_session=False)

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


@router.delete("/{bakery_id}/forecast-metrics", status_code=status.HTTP_200_OK)
def delete_forecast_metrics_for_bakery(
    bakery_id: int,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    bakery = db.query(Bakery).filter(
        Bakery.id == bakery_id, Bakery.user_id == current_user.id
    ).first()
    if not bakery:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bakery not found",
        )

    # Get all product IDs for this bakery
    products_in_bakery = db.query(Product.id).filter(Product.bakery_id == bakery_id).all()
    product_ids_in_bakery = [pid[0] for pid in products_in_bakery]

    if not product_ids_in_bakery:
        return {
            "deleted_count": 0,
            "bakery_id": bakery_id,
            "message": "No products found for this bakery",
        }

    # Delete all ForecastMetrics for products in this bakery
    deleted_count = (
        db.query(ForecastMetrics)
        .filter(ForecastMetrics.product_id.in_(product_ids_in_bakery))
        .delete(synchronize_session=False)
    )

    db.commit()

    return {
        "deleted_count": deleted_count,
        "bakery_id": bakery_id,
        "message": f"Deleted forecast metrics for {deleted_count} product(s) in bakery",
    }
