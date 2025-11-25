from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Dict, Any

from sqlalchemy.orm import Session

from app.database.database import SessionLocal
from app.models import Product, SalesRecord, ForecastMetrics
from app.ml.preprocessing import SalesPreprocessor, RawSalesRecord
from app.ml.trainer import ModelTrainer


def _compute_metrics(train_result, cleaned_df) -> tuple[Optional[float], Optional[float]]:
    try:
        forecast_df = train_result.model.predict(0)  # includes training range
        merged = forecast_df.merge(cleaned_df, on="ds", how="inner")
        if merged.empty:
            return None, None
        actual = merged["y"]
        predicted = merged["yhat"]
        error = predicted - actual
        rmse = float((error.pow(2).mean()) ** 0.5)

        non_zero_actual = actual.replace(0, None)
        ape = (predicted - actual).abs() / non_zero_actual
        ape = ape.dropna()
        mape = float(ape.mean()) if not ape.empty else None
        return mape, rmse
    except Exception:
        return None, None


def train_product(
    *,
    product_id: int,
    db: Optional[Session] = None,
    model_name: str = "prophet",
) -> Dict[str, Any]:
    owns_session = False
    if db is None:
        db = SessionLocal()
        owns_session = True

    try:
        product = (
            db.query(Product)
            .filter(Product.id == product_id)
            .one_or_none()
        )
        if product is None:
            raise ValueError(f"Product {product_id} not found")

        sales_rows = (
            db.query(SalesRecord)
            .filter(SalesRecord.product_id == product_id)
            .order_by(SalesRecord.date.asc())
            .all()
        )

        if not sales_rows:
            return {
                "product_id": product_id,
                "product_name": product.name,
                "status": "skipped_no_data",
                "model_type": model_name,
                "n_points": 0,
                "mape": None,
                "rmse": None,
                "last_trained_at": None,
            }

        raw_records = [
            RawSalesRecord(
                date=row.date,
                product_id=row.product_id,
                quantity=row.quantity_sold,
            )
            for row in sales_rows
        ]

        preprocessor = SalesPreprocessor()
        cleaned = preprocessor.preprocess(raw_records, product_id=product_id)
        if cleaned.df.empty:
            return {
                "product_id": product_id,
                "product_name": product.name,
                "status": "skipped_no_timeseries",
                "model_type": model_name,
                "n_points": 0,
                "mape": None,
                "rmse": None,
                "last_trained_at": None,
            }

        trainer = ModelTrainer()
        train_result = trainer.train(cleaned, model_name=model_name)

        mape, rmse = _compute_metrics(train_result, cleaned.df)
        trained_at = datetime.now(timezone.utc)

        metrics = (
            db.query(ForecastMetrics)
            .filter(ForecastMetrics.product_id == product_id)
            .one_or_none()
        )
        if metrics is None:
            metrics = ForecastMetrics(product_id=product_id)
            db.add(metrics)

        metrics.mape = mape
        metrics.rmse = rmse
        metrics.n_points = len(cleaned.df)
        metrics.model_type = train_result.model_name
        metrics.status = "ok"
        metrics.last_trained_at = trained_at

        db.commit()
        db.refresh(metrics)

        return {
            "product_id": product_id,
            "product_name": product.name,
            "status": "ok",
            "model_type": train_result.model_name,
            "n_points": len(cleaned.df),
            "mape": mape,
            "rmse": rmse,
            "last_trained_at": trained_at,
        }
    finally:
        if owns_session:
            db.close()

