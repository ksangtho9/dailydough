from __future__ import annotations

import logging
import os
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional

import pandas as pd
from sqlalchemy.orm import Session

from app.models import SalesRecord, Product
from ..data.sales_preprocessor import SalesPreprocessor, RawSalesRecord, CleanedTimeSeries, build_base_timeseries
from ..registry.file_registry import load_model, model_exists
from ..training.train_product import train_product
from ..models.prophet_model import ProphetForecastModel, ProphetModel

# ---------- Logging setup for forecasting ----------

LOG_DIR = Path("logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)  # ensure logs/ exists

LOG_FILE = LOG_DIR / "forecast.log"

logger = logging.getLogger("bakezy.forecast")

if not logger.handlers:
    logger.setLevel(logging.INFO)
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)


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


def get_forecast_for_product(
    db: Session,
    product_id: int,
    horizon_days: int = 14,
    use_cached_model: bool = True,
) -> ProductForecast:
    """
    Generate forecast for a product.
    
    This is the main entrypoint for inference. It:
    1. Loads or trains a model (using registry if available)
    2. Generates predictions
    3. Returns formatted forecast
    
    Args:
        db: Database session
        product_id: Product ID to forecast
        horizon_days: Number of days to forecast
        use_cached_model: Whether to use cached model from registry
    
    Returns:
        ProductForecast with predictions
    """
    logger.info(
        "Starting forecast: product_id=%d horizon_days=%d",
        product_id,
        horizon_days,
    )

    # 1) Load product
    product = db.query(Product).filter(Product.id == product_id).first()
    if product is None:
        logger.warning(f"Forecast failed: product_id={product_id} not found")
        raise ValueError("Product not found")

    # 2) Load sales data
    sales_rows = (
        db.query(SalesRecord)
        .filter(SalesRecord.product_id == product_id)
        .order_by(SalesRecord.date.asc())
        .all()
    )

    if not sales_rows:
        logger.warning(
            f"Forecast failed: no sales data for product_id={product_id}"
        )
        raise ValueError("No sales data for this product")

    raw_records: list[RawSalesRecord] = [
        RawSalesRecord(
            date=row.date,
            product_id=row.product_id,
            quantity=row.quantity_sold,
        )
        for row in sales_rows
    ]

    logger.info(
        "Loaded %d sales records for product_id=%d (from %s to %s)",
        len(raw_records),
        product_id,
        raw_records[0].date.isoformat(),
        raw_records[-1].date.isoformat(),
    )

    # 3) Preprocess
    preprocessor = SalesPreprocessor()
    cleaned_ts = preprocessor.preprocess(
        records=raw_records,
        product_id=product_id,
    )

    # 4) Load or train model
    model = None
    if use_cached_model and model_exists(product_id):
        try:
            model = load_model(product_id)
            logger.info(f"Loaded cached model for product_id={product_id}")
        except Exception as e:
            logger.warning(f"Failed to load cached model: {e}, training new model")
    
    if model is None:
        # Train new model on the fly if needed
        logger.info(f"Training new model for product_id={product_id}")
        train_result = train_product(db, product_id, model_name="prophet")
        model = train_result.model
        logger.info(f"Trained new model for product_id={product_id}")

    # 5) Generate forecast
    # For Prophet, we need to create future dataframe
    if isinstance(model, (ProphetForecastModel, ProphetModel)):
        # Get last date from training data
        last_date = cleaned_ts.df["ds"].max()
        if isinstance(last_date, pd.Timestamp):
            last_date = last_date.to_pydatetime().date()
        elif hasattr(last_date, 'date'):
            last_date = last_date.date()
        
        # Create future dates
        future_dates = pd.date_range(
            start=last_date + pd.Timedelta(days=1),
            periods=horizon_days,
            freq="D"
        )
        future_df = pd.DataFrame({"ds": future_dates})
        
        # Use the convenience method for backward compatibility
        forecast_df = model.predict_with_horizon(horizon_days)
        
        # Filter to only future dates
        forecast_df = forecast_df[forecast_df["ds"] > pd.Timestamp(last_date)].reset_index(drop=True)
    else:
        # For other models, create future dataframe
        last_date = cleaned_ts.df["ds"].max()
        if isinstance(last_date, pd.Timestamp):
            last_date = last_date.to_pydatetime().date()
        elif hasattr(last_date, 'date'):
            last_date = last_date.date()
        
        future_dates = pd.date_range(
            start=last_date + pd.Timedelta(days=1),
            periods=horizon_days,
            freq="D"
        )
        future_df = pd.DataFrame({"ds": future_dates})
        forecast_df = model.predict(future_df)

    # 6) Convert to ForecastPoint list
    points: list[ForecastPoint] = []

    if "ds" not in forecast_df.columns:
        logger.error("Forecast failed: 'ds' column missing in forecast output")
        raise RuntimeError("Forecast missing 'ds' column")

    for _, row in forecast_df.iterrows():
        ds_value = row["ds"]
        if isinstance(ds_value, pd.Timestamp):
            date_str = ds_value.date().isoformat()
        else:
            date_str = str(ds_value)

        # Extract predictions
        yhat = float(row.get("yhat", 0.0))
        yhat_lower = float(row.get("yhat_lower", yhat))
        yhat_upper = float(row.get("yhat_upper", yhat))

        # Clamp non-negative
        yhat = max(0.0, yhat)
        yhat_lower = max(0.0, yhat_lower)
        yhat_upper = max(0.0, yhat_upper)

        # Round nicely
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

    logger.info(
        "Forecast complete: product_id=%d horizon_days=%d points=%d",
        product_id,
        horizon_days,
        len(points),
    )

    return ProductForecast(
        product_id=product.id,
        product_name=product.name,
        horizon_days=horizon_days,
        points=points,
    )


# Backward compatibility: ForecastService class
class ForecastService:
    """
    High-level service that connects:
    - DB (SalesRecord)
    - preprocessing
    - Model registry
    - Forecasting
    
    Maintains backward compatibility with existing API.
    """

    def __init__(self):
        pass

    def generate_prophet_forecast_for_product(
        self,
        db: Session,
        product_id: int,
        horizon_days: int = 14,
    ) -> ProductForecast:
        """
        Main entrypoint for forecasting (backward compatibility).
        """
        return get_forecast_for_product(
            db=db,
            product_id=product_id,
            horizon_days=horizon_days,
            use_cached_model=True,
        )

