from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.ml.inference.forecast_service import get_forecast_for_product
from app.models import Bakery, Product, ForecastMetrics, SalesRecord
from app.schemas.dashboard_summary import DashboardSummaryResponse

router = APIRouter(tags=["dashboard-summary"])


@router.get(
    "/bakeries/{bakery_id}/dashboard-summary",
    response_model=DashboardSummaryResponse,
)
def get_dashboard_summary(
    bakery_id: int,
    db: Session = Depends(get_db),
):
    bakery = db.query(Bakery).filter(Bakery.id == bakery_id).one_or_none()
    if bakery is None:
        raise HTTPException(status_code=404, detail="Bakery not found")

    products = (
        db.query(Product)
        .filter(Product.bakery_id == bakery_id)
        .all()
    )

    tomorrow = date.today() + timedelta(days=1)
    recommended_bake = 0
    for product in products:
        try:
            forecast = get_forecast_for_product(
                product_id=product.id,
                days_ahead=14,
                db=db,
            )
        except Exception:
            continue

        points = getattr(forecast, "points", forecast.get("points", []))
        match = next(
            (
                p
                for p in points
                if str(getattr(p, "date", p.get("date"))) == tomorrow.isoformat()
            ),
            None,
        )
        if match is None:
            continue
        yhat = getattr(match, "yhat", match.get("yhat"))
        if yhat is None:
            continue
        recommended_bake += max(0, int(round(float(yhat))))

    if recommended_bake == 0:
        recommended_bake_value = None
    else:
        recommended_bake_value = recommended_bake

    lookback_days = 7
    lookback_start = date.today() - timedelta(days=lookback_days)
    actual_rows = (
        db.query(
            SalesRecord.date.label("day"),
            func.sum(SalesRecord.quantity_sold).label("qty"),
        )
        .filter(
            SalesRecord.bakery_id == bakery_id,
            SalesRecord.date >= lookback_start,
            SalesRecord.date <= date.today(),
        )
        .group_by(SalesRecord.date)
        .all()
    )

    expected_waste_pct = None
    if recommended_bake_value and actual_rows:
        total_actual = sum(float(row.qty or 0.0) for row in actual_rows)
        avg_actual = total_actual / len(actual_rows) if actual_rows else 0
        if avg_actual > 0:
            surplus = max(recommended_bake_value - avg_actual, 0)
            if recommended_bake_value > 0:
                expected_waste_pct = surplus / recommended_bake_value

    metrics_rows = (
        db.query(ForecastMetrics)
        .join(Product, ForecastMetrics.product_id == Product.id)
        .filter(Product.bakery_id == bakery_id)
        .all()
    )

    mape_values = [row.mape for row in metrics_rows if row.mape is not None]
    forecast_accuracy_pct = (
        (sum(mape_values) / len(mape_values)) * 100 if mape_values else None
    )

    high_risk_items = len(
        [
            row
            for row in metrics_rows
            if row.mape is not None and row.mape > 0.25
        ]
    )

    return DashboardSummaryResponse(
        bakery_id=bakery.id,
        bakery_name=bakery.name,
        as_of=date.today(),
        recommended_bake=recommended_bake_value,
        expected_waste_pct=expected_waste_pct,
        forecast_accuracy_pct=forecast_accuracy_pct,
        high_risk_items=high_risk_items,
    )




