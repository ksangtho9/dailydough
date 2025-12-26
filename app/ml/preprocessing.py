from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import List, Optional

import numpy as np
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

        # Add is_valid_day flag after aggregation
        # Set is_valid_day = 0 when: delivery == 0 AND y == 0 (closed/no-op days)
        # Also set to 0 if y is null (missing sales data)
        df["is_valid_day"] = 1
        df.loc[(df["delivery"] == 0) & (df["y"] == 0), "is_valid_day"] = 0
        df.loc[df["y"].isna(), "is_valid_day"] = 0

        return df

    def fill_missing_dates(self, df: pd.DataFrame, product_id: int) -> pd.DataFrame:
        """
        Ensure a continuous daily index for missing days.
        Prophet likes continuous timelines.

        Also guarantees ONE row per day per product.
        For missing dates: set y = NaN (NOT 0.0), delivery = NaN or 0.0, is_valid_day = 0
        """
        if df.empty:
            return df

        # Filter to this product
        df_prod = df[df["product_id"] == product_id].copy()
        if df_prod.empty:
            # nothing for this product
            return pd.DataFrame(columns=["ds", "y", "product_id", "delivery", "is_valid_day"])

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

        # Fill missing values
        df_full["product_id"] = df_full["product_id"].fillna(product_id)
        # For missing dates: y = NaN (NOT 0.0), delivery = NaN or 0.0, is_valid_day = 0
        # Don't fill y with 0.0 - keep as NaN for missing dates
        if "y" not in df_full.columns:
            df_full["y"] = np.nan
        
        # For delivery, use NaN for missing (or 0.0 if preferred)
        if "delivery" in df_full.columns:
            df_full["delivery"] = df_full["delivery"].fillna(0.0)
        else:
            df_full["delivery"] = 0.0
        
        # Set is_valid_day = 0 for missing dates (where y is NaN)
        if "is_valid_day" not in df_full.columns:
            df_full["is_valid_day"] = 1
        # Missing dates (y is NaN) should be invalid
        df_full.loc[df_full["y"].isna(), "is_valid_day"] = 0
        # Also check delivery == 0 AND y == 0 (or NaN) for missing dates
        df_full.loc[(df_full["delivery"] == 0) & (df_full["y"].isna()), "is_valid_day"] = 0

        return df_full[["ds", "y", "product_id", "delivery", "is_valid_day"]]

    def preprocess(
        self,
        records: List[RawSalesRecord],
        product_id: int,
        shelf_life_days: int = 1,
    ) -> CleanedTimeSeries:
        """Main entrypoint: raw records → CleanedTimeSeries."""
        df = self.to_dataframe(records)
        df_full = self.fill_missing_dates(df, product_id)
        
        # Spike detection: run on valid-only series (is_valid_day == 1)
        # Compute spike features on filtered valid days only, then merge back
        if self.spike_detector is not None and not df_full.empty and "y" in df_full.columns:
            # Filter to valid days only for spike detection
            valid_df = df_full[df_full["is_valid_day"] == 1].copy()
            
            if not valid_df.empty and len(valid_df) > 0:
                # Detect spikes on valid days only
                # Reset index to ensure continuous indexing for spike detector
                valid_df_reset = valid_df.reset_index(drop=True)
                spike_result = self.spike_detector.detect(valid_df_reset, value_col="y")
                
                # Create spike columns in valid_df_reset (with reset index)
                valid_df_reset["is_spike"] = spike_result.is_spike.astype(int)
                valid_df_reset["spike_severity"] = spike_result.severity_score
                valid_df_reset["y_original"] = spike_result.original_values
                # Use smoothed values for training
                valid_df_reset["y"] = spike_result.smoothed_values
                
                # Map back to original valid_df using ds column (since index was reset)
                valid_df = valid_df_reset.copy()
                
                # Merge spike features back to full dataset
                # Invalid days get default spike values (0 for is_spike, 0.0 for severity)
                spike_cols = valid_df[["ds", "is_spike", "spike_severity", "y_original", "y"]].copy()
                spike_cols = spike_cols.rename(columns={"y": "y_smoothed"})
                
                df_full = df_full.merge(
                    spike_cols[["ds", "is_spike", "spike_severity", "y_original", "y_smoothed"]],
                    on="ds",
                    how="left",
                    suffixes=("", "_spike")
                )
                
                # Update y with smoothed values from spike detection (only for valid days)
                df_full.loc[df_full["is_valid_day"] == 1, "y"] = df_full.loc[df_full["is_valid_day"] == 1, "y_smoothed"]
                df_full = df_full.drop(columns=["y_smoothed"], errors="ignore")
                
                # Fill default values for invalid days
                df_full["is_spike"] = df_full["is_spike"].fillna(0).astype(int)
                df_full["spike_severity"] = df_full["spike_severity"].fillna(0.0)
                # For y_original, use original y value if available, otherwise use current y
                df_full["y_original"] = df_full["y_original"].fillna(df_full["y"])
            else:
                # No valid days - initialize spike columns with zeros
                df_full["is_spike"] = 0
                df_full["spike_severity"] = 0.0
                df_full["y_original"] = df_full["y"] if "y" in df_full.columns else np.nan
        else:
            # No spike detection - initialize spike columns with zeros
            df_full["is_spike"] = 0
            df_full["spike_severity"] = 0.0
            df_full["y_original"] = df_full["y"] if "y" in df_full.columns else np.nan
        
        # Include all columns: ds, y, delivery, is_valid_day, and spike-related columns
        columns = ["ds", "y", "is_valid_day"]
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

