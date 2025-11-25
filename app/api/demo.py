from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.database.database import get_db
from app.demo.seed_demo_data import DEMO_BAKERY_NAME, seed_demo_data
from app.models import Bakery, SalesRecord
from app.services.sales_ingestion import (
    SchemaInferenceError,
    ingest_sales_csv,
)

router = APIRouter(prefix="/demo", tags=["demo"])


def _get_demo_bakery(db: Session) -> Bakery:
    bakery = db.query(Bakery).filter(Bakery.name == DEMO_BAKERY_NAME).one_or_none()
    if bakery is None:
        seed_demo_data()
        bakery = db.query(Bakery).filter(Bakery.name == DEMO_BAKERY_NAME).one()
    return bakery


@router.post("/seed", status_code=status.HTTP_200_OK)
def seed_demo_endpoint(current_user=Depends(get_current_user)):
    """
    Seed the database with demo bakery, product, and sales data.
    Limited to authenticated users to avoid anonymous abuse.
    """
    try:
        seed_demo_data()
        return {"status": "ok", "message": "Demo data seeded."}
    except Exception as exc:  # pragma: no cover - surfaced to client
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


@router.post("/import-sales", status_code=status.HTTP_200_OK)
async def import_demo_sales(
    mode: str = Query("append", regex="^(append|replace)$"),
    file: UploadFile = File(...),
    column_mapping: Optional[str] = Form(None),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Import a user-provided CSV into the Demo Bakery.

    mode:
      - append (default) keeps existing demo sales
      - replace clears existing demo sales first
    """
    demo_bakery = _get_demo_bakery(db)

    if mode == "replace":
        db.query(SalesRecord).filter(SalesRecord.bakery_id == demo_bakery.id).delete(
            synchronize_session=False
        )
        db.commit()

    content_bytes = await file.read()

    try:
        result = ingest_sales_csv(
            db=db,
            file_bytes=content_bytes,
            column_mapping_json=column_mapping,
            target_bakery=demo_bakery,
        )
    except SchemaInferenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "schema_inference_failed",
                "message": "Could not infer columns for demo import.",
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

    return {
        "status": "ok",
        "mode": mode,
        "demo_bakery_id": demo_bakery.id,
        "demo_bakery_name": demo_bakery.name,
        "created_products": result.created_products,
        "existing_products_used": result.existing_products_used,
        "sales_rows_inserted": result.sales_rows_inserted,
        "parse_errors": result.parse_errors,
        "row_errors": result.row_errors,
    }

