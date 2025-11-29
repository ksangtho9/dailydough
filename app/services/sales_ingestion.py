from __future__ import annotations

import json
from dataclasses import dataclass
from io import StringIO
from typing import Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy.orm import Session

from app.ml.data.schema_inference import infer_column_roles
from app.models import Bakery, Product, SalesRecord

REQUIRED_ROLES = ("date", "product_id", "product_name", "quantity")
OPTIONAL_ROLES = ("bakery_id", "delivery")


class SchemaInferenceError(Exception):
    def __init__(
        self,
        *,
        mapping: Dict[str, Optional[str]],
        missing_roles: List[str],
        available_columns: List[str],
    ):
        super().__init__("Could not infer required columns from CSV.")
        self.mapping = mapping
        self.missing_roles = missing_roles
        self.available_columns = available_columns


@dataclass
class SalesIngestionResult:
    inserted: int
    sales_rows_inserted: int
    skipped_missing_product: int
    created_products: int
    existing_products_used: int
    parse_errors: List[str]
    row_errors: List[str]


def _read_dataframe(content_bytes: bytes) -> pd.DataFrame:
    try:
        content = content_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("CSV must be UTF-8 encoded") from exc

    try:
        df_raw = pd.read_csv(StringIO(content))
    except Exception as exc:
        raise ValueError(f"Unable to parse CSV: {exc}") from exc

    if df_raw.empty:
        raise ValueError("CSV file is empty")

    return df_raw


def _load_column_mapping(
    raw_mapping: Optional[str], columns: List[str]
) -> Optional[Dict[str, str]]:
    if raw_mapping is None:
        return None

    try:
        parsed = json.loads(raw_mapping)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid column_mapping payload: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ValueError("column_mapping must be a JSON object")

    mapping: Dict[str, str] = {}
    for role in REQUIRED_ROLES + OPTIONAL_ROLES:
        value = parsed.get(role)
        if value is None:
            continue
        if value not in columns:
            raise ValueError(
                f"column_mapping[{role}] references unknown column '{value}'"
            )
        mapping[role] = value

    if len(set(mapping.values())) != len(mapping.values()):
        raise ValueError("column_mapping values must be unique per role")

    return mapping


def _dataframe_to_rows(
    df: pd.DataFrame, forced_bakery_id: Optional[int] = None
) -> Tuple[List[dict], List[str]]:
    rows: List[dict] = []
    errors: List[str] = []

    has_bakery_column = "bakery_id" in df.columns

    for line_no, record in enumerate(df.itertuples(index=False), start=2):
        try:
            raw_date = getattr(record, "date")
            sale_date = pd.to_datetime(raw_date, errors="raise").date()

            raw_quantity = getattr(record, "quantity")
            quantity = float(raw_quantity)

            identifier_raw = getattr(record, "product_id")
            csv_product_id: Optional[int] = None
            csv_product_sku: Optional[str] = None
            if identifier_raw is not None and not pd.isna(identifier_raw):
                identifier_str = str(identifier_raw).strip()
                if identifier_str:
                    try:
                        numeric_val = float(identifier_str)
                        if numeric_val.is_integer():
                            csv_product_id = int(numeric_val)
                        else:
                            csv_product_sku = identifier_str
                    except ValueError:
                        csv_product_sku = identifier_str

            product_name_raw = getattr(record, "product_name")
            if product_name_raw is None or pd.isna(product_name_raw):
                raise ValueError("product_name is required")
            product_name = str(product_name_raw).strip()
            if not product_name:
                raise ValueError("product_name is required")

            bakery_id: Optional[int] = forced_bakery_id
            if bakery_id is None and has_bakery_column:
                raw_bakery = getattr(record, "bakery_id")
                if raw_bakery is not None and not pd.isna(raw_bakery):
                    bakery_id = int(float(raw_bakery))

            # Parse delivery quantity if available
            quantity_delivered: Optional[float] = None
            if hasattr(record, "delivery"):
                raw_delivery = getattr(record, "delivery")
                if raw_delivery is not None and not pd.isna(raw_delivery):
                    try:
                        quantity_delivered = float(raw_delivery)
                    except (ValueError, TypeError):
                        pass  # Keep as None if parsing fails

            rows.append(
                {
                    "line_number": line_no,
                    "product_id": csv_product_id,
                    "product_sku": csv_product_sku,
                    "product_name": product_name,
                    "bakery_id": bakery_id,
                    "date": sale_date,
                    "quantity_sold": quantity,
                    "quantity_delivered": quantity_delivered,
                }
            )
        except Exception as exc:
            errors.append(f"Line {line_no}: {exc}")

    return rows, errors


def ingest_sales_csv(
    *,
    db: Session,
    file_bytes: bytes,
    column_mapping_json: Optional[str] = None,
    target_bakery: Optional[Bakery] = None,
    context_bakery_id: Optional[int] = None,
    demo_bakery_id: Optional[int] = None,
    replace_mode: bool = False,
) -> SalesIngestionResult:
    df_raw = _read_dataframe(file_bytes)
    explicit_mapping = _load_column_mapping(column_mapping_json, list(df_raw.columns))
    mapping = explicit_mapping or infer_column_roles(df_raw)
    missing_roles = [role for role in REQUIRED_ROLES if not mapping.get(role)]
    if missing_roles:
        raise SchemaInferenceError(
            mapping=mapping,
            missing_roles=missing_roles,
            available_columns=list(df_raw.columns),
        )

    rename_map = {
        source_column: role
        for role, source_column in mapping.items()
        if source_column is not None
    }
    df_internal = df_raw.rename(columns=rename_map)

    # Priority: target_bakery > context_bakery_id > demo_bakery_id
    if target_bakery:
        forced_bakery_id = target_bakery.id
    elif context_bakery_id is not None:
        forced_bakery_id = context_bakery_id
    else:
        forced_bakery_id = demo_bakery_id
    rows, parse_errors = _dataframe_to_rows(df_internal, forced_bakery_id)
    if not rows and parse_errors:
        raise ValueError("; ".join(parse_errors))

    inserted = 0
    skipped_missing_product = 0
    created_products = 0
    existing_products_used: set[int] = set()
    row_errors: List[str] = []

    product_query = db.query(Product)
    if target_bakery:
        product_query = product_query.filter(Product.bakery_id == target_bakery.id)
    existing_products = product_query.all()
    products_by_id = {p.id: p for p in existing_products}
    products_by_sku: Dict[str, Product] = {}
    for product in existing_products:
        if product.sku:
            products_by_sku[product.sku.strip().lower()] = product

    for row in rows:
        idx = row["line_number"]
        csv_product_id: int | None = row.get("product_id")
        csv_product_sku: Optional[str] = row.get("product_sku")
        csv_product_name: Optional[str] = row.get("product_name")
        csv_bakery_id: Optional[int] = row.get("bakery_id")

        # Auto-fill bakery_id from context if missing
        # Priority: CSV bakery_id > forced_bakery_id (from context/demo) > error
        if csv_bakery_id is None:
            if forced_bakery_id is not None:
                csv_bakery_id = forced_bakery_id
            else:
                skipped_missing_product += 1
                row_errors.append(
                    f"Line {idx}: bakery_id missing and no bakery context or demo bakery specified"
                )
                continue

        sku_key = (
            csv_product_sku.strip().lower()
            if isinstance(csv_product_sku, str) and csv_product_sku.strip()
            else None
        )

        product = (
            products_by_id.get(csv_product_id) if csv_product_id is not None else None
        )
        if product is None and sku_key:
            product = products_by_sku.get(sku_key)

        product_was_created = False

        if product is None:
            can_create = csv_product_name and (csv_product_id is not None or sku_key)

            if not can_create:
                skipped_missing_product += 1
                identifier = (
                    csv_product_id
                    if csv_product_id is not None
                    else csv_product_sku
                    or "unknown"
                )
                row_errors.append(
                    f"Line {idx}: product {identifier} not found and missing required columns for auto-creation"
                )
                continue

            product = Product(
                bakery_id=csv_bakery_id,
                name=csv_product_name,
                sku=csv_product_sku
                or (str(csv_product_id) if csv_product_id is not None else None),
            )

            if csv_product_id is not None:
                product.id = csv_product_id

            db.add(product)
            if csv_product_id is not None:
                products_by_id[csv_product_id] = product
            if sku_key:
                products_by_sku[sku_key] = product
            created_products += 1
            product_was_created = True

        # If replace_mode, delete existing record for this (date, product_id, bakery_id) first
        if replace_mode:
            db.query(SalesRecord).filter(
                SalesRecord.bakery_id == (product.bakery_id or csv_bakery_id),
                SalesRecord.product_id == product.id,
                SalesRecord.date == row["date"],
            ).delete(synchronize_session=False)

        try:
            record = SalesRecord(
                bakery_id=product.bakery_id or csv_bakery_id,
                product_id=product.id,
                date=row["date"],
                quantity_sold=row["quantity_sold"],
                quantity_delivered=row.get("quantity_delivered"),
            )
            db.add(record)
            inserted += 1
            if not product_was_created and product.id is not None:
                existing_products_used.add(product.id)
        except Exception as exc:
            row_errors.append(f"Line {idx}: {exc}")
            db.rollback()

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise

    return SalesIngestionResult(
        inserted=inserted,
        sales_rows_inserted=inserted,
        skipped_missing_product=skipped_missing_product,
        created_products=created_products,
        existing_products_used=len(existing_products_used),
        parse_errors=parse_errors,
        row_errors=row_errors,
    )



