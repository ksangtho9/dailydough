from __future__ import annotations

from dataclasses import dataclass
from typing import List

from sqlalchemy.orm import Session

from app.models import SalesRecord, Product
from .preprocessing import SalesPreprocessor, RawSalesRecord
from .forecaster import ProductForecaster, ForecastResult


@dataclass
class ForecastPoint:
    """Single forecasted point for a given date."""
    date: str          # ISO date string, e.g. "2025-01-01"
    yhat: float        # point forecast
    yhat_lower: float  # lower bound
    yhat_upper: float  # upper bound


@dataclass
class ProductForecast:
    """DTO (data transfer object) that the API can easily return as JSON later."""
    product_id: int
    product_name: str
    horizon_days: int
    points: List[ForecastPoint]


class ForecastService:
    """
    High-level service that connects:
    - DB (SalesRecord)
    - preprocessing
    - Prophet forecaster
    """

    def __init__(self):
        self.preprocessor = SalesPreprocessor()
        self.forecaster = ProductForecaster()

    def _load_sales_for_product(
        self,
        db: Session,
        product_id: int,
    ) -> tuple[Product, list[RawSalesRecord]]:
        """
        Load raw SalesRecord rows from the DB and convert to RawSalesRecord list.
        """
        product = db.query(Product).filter(Product.id == product_id).first()
        if product is None:
            raise ValueError("Product not found")

        sales_rows = (
            db.query(SalesRecord)
            .filter(SalesRecord.product_id == product_id)
            .order_by(SalesRecord.date.asc())
            .all()
        )

        if not sales_rows:
            raise ValueError("No sales data for this product")

        raw_records: list[RawSalesRecord] = [
            RawSalesRecord(
                date=row.date,
                product_id=row.product_id,
                quantity=row.quantity_sold,
            )
            for row in sales_rows
        ]

        return product, raw_records

    def generate_prophet_forecast_for_product(
        self,
        db: Session,
        product_id: int,
        horizon_days: int = 14,
    ) -> ProductForecast:
        """
        Main entrypoint for Step 2.3 & 2.4.

        Usage:
            service = ForecastService()
            forecast = service.generate_prophet_forecast_for_product(db, product_id=1)
        """
        # 1) Load raw sales from DB
        product, raw_records = self._load_sales_for_product(db, product_id)

        # 2) Preprocess → CleanedTimeSeries (fill missing days, sort, etc.)
        cleaned_ts = self.preprocessor.preprocess(
            records=raw_records,
            product_id=product_id,
        )

        # 3) Forecast via Prophet
        forecast_result: ForecastResult = self.forecaster.forecast(
            ts=cleaned_ts,
            horizon_days=horizon_days,
            model_name="prophet",
        )

        df = forecast_result.forecast_df

        # 4) Convert Prophet output → list of ForecastPoint
        points: list[ForecastPoint] = []

        df_future = df.copy()
        if "ds" not in df_future.columns:
            raise RuntimeError("Prophet forecast missing 'ds' column")

        # Expect columns: ds, yhat, yhat_lower, yhat_upper
        for _, row in df_future.iterrows():
            # ds is a Timestamp/ datetime; convert to ISO date string
            ds_value = row["ds"]
            date_str = ds_value.date().isoformat()

            # Raw Prophet outputs
            yhat = float(row["yhat"])
            yhat_lower = float(row["yhat_lower"])
            yhat_upper = float(row["yhat_upper"])

            # 🔒 Clamp to non-negative (no negative sales)
            yhat = max(0.0, yhat)
            yhat_lower = max(0.0, yhat_lower)
            yhat_upper = max(0.0, yhat_upper)

            # 💅 Optional: round to 2 decimals for cleaner JSON
            yhat = round(yhat, 2)
            yhat_lower = round(yhat_lower, 2)
            yhat_upper = round(yhat_upper, 2)

            points.append(
                ForecastPoint(
                    date=date_str,
                    yhat=yhat,
                    yhat_lower=yhat_lower,
                    yhat_upper=yhat_upper,
                )
            )

        return ProductForecast(
            product_id=product.id,
            product_name=product.name,
            horizon_days=horizon_days,
            points=points,
        )