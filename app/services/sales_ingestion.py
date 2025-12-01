from __future__ import annotations

import json
from dataclasses import dataclass
from io import StringIO
from typing import Dict, List, Optional, Tuple
import logging

import pandas as pd
from sqlalchemy.orm import Session

from app.ml.data.schema_inference import infer_column_roles
from app.models import Bakery, Product, SalesRecord

REQUIRED_ROLES = ("date", "product_id", "product_name", "quantity")
# Optional roles include bakery_id & delivery quantity; we now also support an
# optional shelf_life column for per-product shelf life configuration.
OPTIONAL_ROLES = ("bakery_id", "delivery", "shelf_life")


logger = logging.getLogger("bakezy.sales_ingestion")


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
    has_shelf_life_column = "shelf_life" in df.columns

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

            # Parse shelf life in days if available. This is product-level metadata
            # but we capture it per-row and later only apply it when auto-creating
            # new products.
            #
            # Supported formats:
            # - Numeric shelf_life column (e.g. 1 or 2): values >1 → 2, values <=1 → 1
            # - Boolean-ish \"More than 1 Day Shelf Life\" style column:
            #     * TRUE/Yes/Y/1 → 2 days
            #     * anything else non-empty → 1 day
            shelf_life_days: Optional[int] = None
            if has_shelf_life_column and hasattr(record, "shelf_life"):
                raw_shelf_life = getattr(record, "shelf_life")
                if raw_shelf_life is not None and not pd.isna(raw_shelf_life):
                    try:
                        # First try numeric interpretation. We support both:
                        # - Boolean-style 0/1 flags (1 → 2 days, 0 → 1 day)
                        # - Direct numeric shelf-life in days (1 or 2)
                        numeric_val = float(raw_shelf_life)
                        if numeric_val in (0.0, 1.0):
                            # Treat as boolean flag: 1 means \"more than 1 day\"
                            value = 2 if numeric_val >= 1.0 else 1
                        else:
                            # Treat as direct shelf-life days: >1 → 2 days
                            value = 2 if numeric_val > 1 else 1
                        value = max(1, min(2, int(value)))
                        shelf_life_days = value
                    except (ValueError, TypeError):
                        # Fallback: treat as string/boolean-style flag
                        text = str(raw_shelf_life).strip().lower()
                        if text:
                            true_like = {"true", "yes", "y", "t"}
                            shelf_life_days = 2 if text in true_like else 1

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
                    "shelf_life_days": shelf_life_days,
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

    # --- Column role mapping (supports optional roles like shelf_life) ---
    columns_list = list(df_raw.columns)
    explicit_mapping = _load_column_mapping(column_mapping_json, columns_list)

    if explicit_mapping is not None:
        # Run auto-inference as a baseline so we can preserve optional roles
        # (e.g., shelf_life) even when the UI only sends required roles.
        auto_mapping = infer_column_roles(df_raw)

        mapping: Dict[str, Optional[str]] = {}
        # Merge explicit + auto:
        # - required roles: always take explicit when provided
        # - optional roles: take explicit when provided, otherwise fall back
        #   to auto-inferred column if present.
        for role in REQUIRED_ROLES + OPTIONAL_ROLES:
            if role in explicit_mapping:
                mapping[role] = explicit_mapping[role]
            else:
                # For optional roles only, preserve auto inference
                if role in OPTIONAL_ROLES:
                    mapping[role] = auto_mapping.get(role)
                else:
                    mapping[role] = auto_mapping.get(role)
    else:
        mapping = infer_column_roles(df_raw)

    # Dev/diagnostic logging to help verify how shelf life is wired up.
    try:
        logger.info(
            "Sales CSV column-role mapping: %s",
            {role: col for role, col in mapping.items() if col is not None},
        )
    except Exception:
        # Never break ingestion because of logging issues.
        pass
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

    # More detailed diagnostics for shelf_life_days parsing to help debug issues
    # like \"all products appearing as same-day\" after uploads. This keeps the
    # logging lightweight and safe for production.
    try:
        sample = rows[:10]
        shelf_values = [row.get("shelf_life_days") for row in sample]
        logger.info(
            "Parsed shelf_life_days for first %d rows: %s",
            len(sample),
            shelf_values,
        )
    except Exception:
        pass
    if not rows and parse_errors:
        raise ValueError("; ".join(parse_errors))

    inserted = 0
    skipped_missing_product = 0
    created_products = 0
    existing_products_used: set[int] = set()
    row_errors: List[str] = []

    # Filter products by bakery_id to scope lookup to the current bakery
    # This prevents matching products from other bakeries
    product_query = db.query(Product)
    if target_bakery:
        product_query = product_query.filter(Product.bakery_id == target_bakery.id)
    elif forced_bakery_id is not None:
        # When using context_bakery_id or demo_bakery_id, also filter by bakery_id
        product_query = product_query.filter(Product.bakery_id == forced_bakery_id)
    existing_products = product_query.all()
    # Build lookup dictionaries scoped to this bakery
    # Only use SKU and name for matching - CSV product_id should NOT be used as DB primary key
    products_by_sku: Dict[str, Product] = {}
    products_by_name: Dict[str, Product] = {}
    for product in existing_products:
        if product.sku:
            products_by_sku[product.sku.strip().lower()] = product
        if product.name:
            # Use lowercase for case-insensitive matching
            products_by_name[product.name.strip().lower()] = product

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
        
        # Try to match by SKU first (most reliable), then by name
        # Do NOT match by csv_product_id as database ID - it can collide across bakeries
        product = None
        if sku_key:
            product = products_by_sku.get(sku_key)
        
        if product is None and csv_product_name:
            name_key = csv_product_name.strip().lower()
            product = products_by_name.get(name_key)

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

            shelf_life_days = row.get("shelf_life_days") or 1
            if shelf_life_days < 1 or shelf_life_days > 2:
                shelf_life_days = 1

            product = Product(
                bakery_id=csv_bakery_id,
                name=csv_product_name,
                sku=csv_product_sku
                or (str(csv_product_id) if csv_product_id is not None else None),
                shelf_life_days=shelf_life_days,
            )
            
            # Do NOT set product.id = csv_product_id
            # Let the database auto-generate unique IDs to prevent collisions across bakeries

            db.add(product)
            db.flush()  # Flush to get the auto-generated ID before adding to lookup dicts
            
            # Update lookup dictionaries with the newly created product
            if sku_key:
                products_by_sku[sku_key] = product
            if csv_product_name:
                products_by_name[csv_product_name.strip().lower()] = product
            created_products += 1
            product_was_created = True
        else:
            # Existing product: if we have a non-default shelf_life_days from the CSV,
            # allow it to upgrade products from 1 → 2 days (but never beyond 2).
            row_shelf_life = row.get("shelf_life_days")
            if row_shelf_life is not None:
                try:
                    new_value = int(row_shelf_life)
                except (TypeError, ValueError):
                    new_value = None

                if new_value is not None:
                    if new_value < 1:
                        new_value = 1
                    if new_value > 2:
                        new_value = 2

                    if (
                        getattr(product, "shelf_life_days", 1) == 1
                        and new_value > 1
                    ):
                        product.shelf_life_days = new_value

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



