from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import List, Optional

import pandas as pd


@dataclass
class RawSalesRecord:
    """Single raw sales record for a product on a given date."""
    date: date
    product_id: int
    quantity: float


@dataclass
class CleanedTimeSeries:
    """Normalized time series ready for modeling."""
    product_id: int
    df: pd.DataFrame  # columns: ["ds", "y"] (Prophet-friendly)


class SalesPreprocessor:
    """
    Handles:
    - Loading raw records (from DB or CSV)
    - Sorting & deduplicating
    - Filling missing dates
    - Basic outlier handling hooks
    """

    def __init__(self, min_date: Optional[date] = None):
        self.min_date = min_date

    def to_dataframe(self, records: List[RawSalesRecord]) -> pd.DataFrame:
        """Convert list of RawSalesRecord → pandas DataFrame."""
        if not records:
            return pd.DataFrame(columns=["ds", "y", "product_id"])

        df = pd.DataFrame(
            [
                {
                    "ds": r.date,
                    "y": r.quantity,
                    "product_id": r.product_id,
                }
                for r in records
            ]
        )

        # 🔹 IMPORTANT: aggregate duplicates (same product_id + ds)
        df = (
            df.groupby(["product_id", "ds"], as_index=False)["y"]
              .sum()
              .sort_values(["product_id", "ds"])
              .reset_index(drop=True)
        )

        return df

    def fill_missing_dates(self, df: pd.DataFrame, product_id: int) -> pd.DataFrame:
        """
        Ensure a continuous daily index with 0 quantity for missing days.
        Prophet likes continuous timelines.

        Also guarantees ONE row per day per product.
        """
        if df.empty:
            return df

        # Filter to this product
        df_prod = df[df["product_id"] == product_id].copy()
        if df_prod.empty:
            # nothing for this product
            return pd.DataFrame(columns=["ds", "y", "product_id"])

        # 🔹 ds is already unique per product_id thanks to to_dataframe(),
        # but we sort to be safe.
        df_prod = df_prod.sort_values("ds")

        start = self.min_date or df_prod["ds"].min()
        end = df_prod["ds"].max()

        all_days = pd.date_range(start=start, end=end, freq="D", name="ds")

        df_full = (
            df_prod.set_index("ds")
            .reindex(all_days)
            .reset_index()
        )
        df_full.rename(columns={"index": "ds"}, inplace=True)

        # fill missing
        df_full["product_id"] = df_full["product_id"].fillna(product_id)
        df_full["y"] = df_full["y"].fillna(0.0)

        return df_full[["ds", "y", "product_id"]]

    def preprocess(
        self,
        records: List[RawSalesRecord],
        product_id: int,
    ) -> CleanedTimeSeries:
        """Main entrypoint: raw records → CleanedTimeSeries."""
        df = self.to_dataframe(records)
        df_full = self.fill_missing_dates(df, product_id)
        # Hook for future steps (outlier removal, smoothing, etc.)
        return CleanedTimeSeries(product_id=product_id, df=df_full[["ds", "y"]])

