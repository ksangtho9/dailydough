from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import List, Optional

import pandas as pd

from .spike_detector import SpikeDetector, SpikeConfig


@dataclass
class RawSalesRecord:
    """Single raw sales record for a product on a given date."""
    date: date
    product_id: int
    quantity: float
    quantity_delivered: Optional[float] = None


@dataclass
class CleanedTimeSeries:
    """Normalized time series ready for modeling."""
    product_id: int
    df: pd.DataFrame  # columns: ["ds", "y"] and optionally ["delivery"] (Prophet-friendly)
    # Static product-level metadata that models or downstream services can use.
    shelf_life_days: int = 1


class SalesPreprocessor:
    """
    Handles:
    - Loading raw records (from DB or CSV)
    - Sorting & deduplicating
    - Filling missing dates
    - Spike detection and handling
    """

    def __init__(self, min_date: Optional[date] = None, spike_config: Optional[SpikeConfig] = None):
        self.min_date = min_date
        self.spike_detector = SpikeDetector(config=spike_config) if spike_config else None

    def to_dataframe(self, records: List[RawSalesRecord]) -> pd.DataFrame:
        """Convert list of RawSalesRecord → pandas DataFrame."""
        if not records:
            return pd.DataFrame(columns=["ds", "y", "product_id", "delivery"])

        df = pd.DataFrame(
            [
                {
                    "ds": r.date,
                    "y": r.quantity,
                    "product_id": r.product_id,
                    "delivery": r.quantity_delivered if r.quantity_delivered is not None else 0.0,
                }
                for r in records
            ]
        )

        # 🔹 IMPORTANT: aggregate duplicates (same product_id + ds)
        # IMPORTANT: CSV rows may be arbitrarily sorted by the user.
        # Always sort by product_id then date so the model sees a proper chronological series per product.
        # This ensures training works correctly regardless of CSV row order.
        df = (
            df.groupby(["product_id", "ds"], as_index=False)
              .agg({"y": "sum", "delivery": "sum"})
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
            return pd.DataFrame(columns=["ds", "y", "product_id", "delivery"])

        # IMPORTANT: CSV rows may be arbitrarily sorted by the user.
        # Always sort by date so the model sees a proper chronological series.
        df_prod = df_prod.sort_values("ds").reset_index(drop=True)

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
        # For delivery, fill with 0.0 if missing (treat as no delivery)
        if "delivery" in df_full.columns:
            df_full["delivery"] = df_full["delivery"].fillna(0.0)
        else:
            df_full["delivery"] = 0.0

        return df_full[["ds", "y", "product_id", "delivery"]]

    def preprocess(
        self,
        records: List[RawSalesRecord],
        product_id: int,
        shelf_life_days: int = 1,
    ) -> CleanedTimeSeries:
        """Main entrypoint: raw records → CleanedTimeSeries."""
        df = self.to_dataframe(records)
        df_full = self.fill_missing_dates(df, product_id)
        
        # Spike detection and handling
        if self.spike_detector is not None and not df_full.empty and "y" in df_full.columns:
            # Detect spikes
            spike_result = self.spike_detector.detect(df_full, value_col="y")
            
            # Add spike flags and severity
            df_full["is_spike"] = spike_result.is_spike.astype(int)
            df_full["spike_severity"] = spike_result.severity_score
            
            # Preserve original values in a separate column
            df_full["y_original"] = spike_result.original_values
            
            # Use smoothed values for training (replace y with smoothed values)
            df_full["y"] = spike_result.smoothed_values
            
            # Handle NaN values if spikes were removed
            if df_full["y"].isna().any():
                df_full["y"] = df_full["y"].bfill().ffill().fillna(0.0)
        else:
            # No spike detection - initialize spike columns with zeros
            df_full["is_spike"] = 0
            df_full["spike_severity"] = 0.0
            df_full["y_original"] = df_full["y"] if "y" in df_full.columns else 0.0
        
        # Include delivery column if present
        columns = ["ds", "y"]
        if "delivery" in df_full.columns:
            columns.append("delivery")
        # Always include spike-related columns for analysis
        if "is_spike" in df_full.columns:
            columns.extend(["is_spike", "spike_severity", "y_original"])
        
        return CleanedTimeSeries(
            product_id=product_id,
            df=df_full[columns],
            shelf_life_days=shelf_life_days or 1,
        )

