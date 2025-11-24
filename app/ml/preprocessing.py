"""
DEPRECATED: logic moved to app/ml/data/sales_preprocessor.py

This file is kept for backward compatibility only.
"""

from app.ml.data.sales_preprocessor import (
    SalesPreprocessor,
    RawSalesRecord,
    CleanedTimeSeries,
)

__all__ = [
    "SalesPreprocessor",
    "RawSalesRecord",
    "CleanedTimeSeries",
]
