from __future__ import annotations

import re
from typing import Dict, Optional

import pandas as pd


def normalize_column_name(name: str) -> str:
    """
    Normalize a column name for fuzzy matching.

    Lowercase, trim, and remove whitespace, underscores, and hyphens so we can
    compare user-provided headers against our aliases.
    """
    normalized = name.strip().lower()
    normalized = re.sub(r"[\s_\-]+", "", normalized)
    return normalized


ALIASES = {
    "date": ["date", "saledate", "orderdate", "day", "transactiondate"],
    "product_id": [
        "productid",
        "sku",
        "itemid",
        "productcode",
        "product code",
        "externalid",
    ],
    "product_name": [
        "productname",
        "product name",
        "product",
        "item",
        "itemname",
        "sku_name",
    ],
    "quantity": [
        "qty",
        "quantity",
        "units",
        "unitssold",
        "quantitysold",
        "salesunits",
        "qtysold",
        "sales qty",
        "salesqty",
    ],
    "delivery": [
        "delivery",
        "production",
        "productionqty",
        "production qty",
        "delivered",
        "deliveryqty",
        "delivery qty",
        "prod qty",
        "prodqty",
    ],
    # Optional but helpful when auto-creating products
    "bakery_id": ["bakeryid", "locationid", "storeid"],
    # Optional per-product shelf life metadata. This can come from a numeric
    # column like `shelf_life` (values 1 or 2) or from a boolean-style flag
    # such as `More than 1 Day Shelf Life`.
    "shelf_life": [
        "shelflife",
        "shelf_life",
        "shelf life",
        "morethan1dayshelflife",
        "morethan1dayshelflife?",
        "morethanonedayshelflife",
        "morethanonedayshelflife?",
        "morethan1dayshelf",
        "more than 1 day shelf life",
        "more than one day shelf life",
    ],
}

NORMALIZED_ALIASES = {
    role: [normalize_column_name(alias) for alias in aliases]
    for role, aliases in ALIASES.items()
}


def infer_column_roles(df: pd.DataFrame) -> Dict[str, Optional[str]]:
    """
    Inspect df.columns and return a mapping from our internal roles to the actual
    CSV column names.

    Example:
        {
            "date": "Sale Date",
            "product_id": "SKU",
            "product_name": "Item",
            "quantity": "Qty Sold",
            "delivery": "Production qty",
            "bakery_id": None,
        }
    """
    columns = list(df.columns)
    norm_cols = {col: normalize_column_name(str(col)) for col in columns}

    role_to_column: Dict[str, Optional[str]] = {
        "date": None,
        "product_id": None,
        "product_name": None,
        "quantity": None,
        "delivery": None,
        "bakery_id": None,
        "shelf_life": None,
    }
    role_scores = {role: -1.0 for role in role_to_column}

    for col in columns:
        norm = norm_cols[col]
        series = df[col]

        for role, aliases in NORMALIZED_ALIASES.items():
            score = 0.0

            if norm in aliases:
                score += 10.0
            elif any(alias in norm or norm in alias for alias in aliases):
                score += 5.0

            if role == "date":
                try:
                    parsed = pd.to_datetime(
                        series, errors="coerce", infer_datetime_format=True
                    )
                    non_null_ratio = parsed.notna().mean()
                    if non_null_ratio > 0.8:
                        score += 5.0
                except Exception:
                    pass

            if role == "quantity":
                numeric = pd.to_numeric(series, errors="coerce")
                non_null_ratio = numeric.notna().mean()
                if non_null_ratio > 0.8:
                    score += 3.0
                    non_negative_ratio = (numeric >= 0).mean()
                    if non_negative_ratio > 0.9:
                        score += 2.0

            if role == "delivery":
                numeric = pd.to_numeric(series, errors="coerce")
                non_null_ratio = numeric.notna().mean()
                if non_null_ratio > 0.8:
                    score += 3.0
                    non_negative_ratio = (numeric >= 0).mean()
                    if non_negative_ratio > 0.9:
                        score += 2.0

            if role == "product_id":
                # Prefer columns that look categorical / stringy with few uniques
                unique_ratio = series.astype(str).nunique(dropna=True) / max(
                    len(series), 1
                )
                if unique_ratio > 0.1:
                    score += 1.0

            if role == "product_name":
                # Text columns with more than trivial unique values
                unique_ratio = series.astype(str).nunique(dropna=True) / max(
                    len(series), 1
                )
                if unique_ratio > 0.3:
                    score += 1.5

            if score > role_scores[role]:
                role_scores[role] = score
                role_to_column[role] = col

    MIN_SCORE = 4.0
    for role, score in role_scores.items():
        if score < MIN_SCORE:
            role_to_column[role] = None

    return role_to_column



