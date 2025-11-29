from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from app.models import Bakery, Product, SalesRecord, ForecastMetrics
from app.ml.inference.forecast_service import get_forecast_for_product


def build_bakery_context(
    bakery_id: int,
    db: Session,
) -> Dict[str, Any]:
    """
    Gather comprehensive context about a bakery for AI assistant.
    Returns a dictionary with structured data that can be formatted into a prompt.
    """
    bakery = db.query(Bakery).filter(Bakery.id == bakery_id).first()
    if not bakery:
        return {}

    # Calculate dashboard summary metrics
    summary = None
    try:
        products_for_summary = (
            db.query(Product)
            .filter(Product.bakery_id == bakery_id)
            .all()
        )
        tomorrow = date.today() + timedelta(days=1)
        recommended_bake = 0
        for product in products_for_summary:
            try:
                forecast = get_forecast_for_product(
                    product_id=product.id,
                    days_ahead=14,
                    db=db,
                )
                points = getattr(forecast, "points", [])
                match = next(
                    (p for p in points if str(getattr(p, "date", None)) == tomorrow.isoformat()),
                    None,
                )
                if match:
                    yhat = getattr(match, "yhat", None)
                    if yhat is not None:
                        recommended_bake += max(0, int(round(float(yhat))))
            except Exception:
                continue

        # Calculate expected waste
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
        if recommended_bake > 0 and actual_rows:
            total_actual = sum(float(row.qty or 0.0) for row in actual_rows)
            avg_actual = total_actual / len(actual_rows) if actual_rows else 0
            if avg_actual > 0:
                surplus = max(recommended_bake - avg_actual, 0)
                expected_waste_pct = surplus / recommended_bake

        # Calculate forecast accuracy
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
            [row for row in metrics_rows if row.mape is not None and row.mape > 0.25]
        )

        summary = {
            "recommended_bake": recommended_bake if recommended_bake > 0 else None,
            "expected_waste_pct": expected_waste_pct,
            "forecast_accuracy_pct": forecast_accuracy_pct,
            "high_risk_items": high_risk_items,
        }
    except Exception:
        pass

    # Get products
    products = (
        db.query(Product)
        .filter(Product.bakery_id == bakery_id)
        .order_by(Product.name.asc())
        .all()
    )

    # Get top products by sales (last 30 days)
    thirty_days_ago = date.today() - timedelta(days=30)
    top_products = (
        db.query(
            Product.id,
            Product.name,
            func.sum(SalesRecord.quantity_sold).label("total_sold"),
        )
        .join(SalesRecord, SalesRecord.product_id == Product.id)
        .filter(
            SalesRecord.bakery_id == bakery_id,
            SalesRecord.date >= thirty_days_ago,
        )
        .group_by(Product.id, Product.name)
        .order_by(desc("total_sold"))
        .limit(5)
        .all()
    )

    # Get recent sales trend (last 7 days)
    seven_days_ago = date.today() - timedelta(days=7)
    recent_sales = (
        db.query(
            SalesRecord.date,
            func.sum(SalesRecord.quantity_sold).label("daily_total"),
        )
        .filter(
            SalesRecord.bakery_id == bakery_id,
            SalesRecord.date >= seven_days_ago,
        )
        .group_by(SalesRecord.date)
        .order_by(SalesRecord.date.asc())
        .all()
    )

    # Get forecast accuracy metrics
    accuracy_metrics = (
        db.query(ForecastMetrics)
        .filter(ForecastMetrics.product_id.in_([p.id for p in products]))
        .all()
    )

    # Get tomorrow's bake plan
    bake_plan = None
    try:
        plan_date = date.today() + timedelta(days=1)
        plan_products = (
            db.query(Product)
            .filter(Product.bakery_id == bakery_id)
            .order_by(Product.name.asc())
            .all()
        )
        plan_items = []
        for product in plan_products:
            try:
                forecast = get_forecast_for_product(
                    product_id=product.id,
                    days_ahead=14,
                    db=db,
                )
                points = getattr(forecast, "points", [])
                match = next(
                    (p for p in points if str(getattr(p, "date", None)) == plan_date.isoformat()),
                    None,
                )
                if match:
                    qty = getattr(match, "yhat", 0)
                    forecast_qty = max(0, int(round(qty)))
                    if forecast_qty > 0:
                        plan_items.append({
                            "product_name": product.name,
                            "forecast_quantity": forecast_qty,
                        })
            except Exception:
                continue
        plan_items.sort(key=lambda x: x["forecast_quantity"], reverse=True)
        bake_plan = {
            "date": str(plan_date),
            "items": plan_items,
        }
    except Exception:
        pass

    return {
        "bakery": {
            "id": bakery.id,
            "name": bakery.name,
            "location": bakery.location,
        },
        "summary": summary,
        "products": [
            {"id": p.id, "name": p.name, "sku": p.sku} for p in products
        ],
        "top_products": [
            {
                "name": row.name,
                "total_sold": float(row.total_sold),
            }
            for row in top_products
        ],
        "recent_sales": [
            {
                "date": str(row.date),
                "daily_total": float(row.daily_total),
            }
            for row in recent_sales
        ],
        "forecast_accuracy": [
            {
                "product_id": m.product_id,
                "mape": m.mape,
                "rmse": m.rmse,
            }
            for m in accuracy_metrics
        ],
        "bake_plan": bake_plan,
    }


def format_context_for_prompt(context: Dict[str, Any]) -> str:
    """
    Format the context dictionary into a readable text prompt for the AI.
    """
    lines = []

    bakery = context.get("bakery", {})
    lines.append(f"BAKERY INFORMATION:")
    lines.append(f"- Name: {bakery.get('name', 'Unknown')}")
    lines.append(f"- Location: {bakery.get('location', 'Unknown')}")
    lines.append("")

    summary = context.get("summary")
    if summary:
        lines.append("KEY METRICS:")
        if summary.get("recommended_bake") is not None:
            lines.append(f"- Recommended bake (tomorrow): {summary['recommended_bake']:,} units")
        if summary.get("expected_waste_pct") is not None:
            lines.append(f"- Expected waste: {summary['expected_waste_pct']*100:.1f}%")
        if summary.get("forecast_accuracy_pct") is not None:
            lines.append(f"- Forecast accuracy: {summary['forecast_accuracy_pct']:.1f}%")
        lines.append(f"- High risk items (MAPE > 25%): {summary.get('high_risk_items', 0)}")
        lines.append("")

    top_products = context.get("top_products", [])
    if top_products:
        lines.append("TOP SELLING PRODUCTS (last 30 days):")
        for i, product in enumerate(top_products[:5], 1):
            lines.append(f"{i}. {product['name']}: {product['total_sold']:,.0f} units")
        lines.append("")

    recent_sales = context.get("recent_sales", [])
    if recent_sales:
        lines.append("RECENT SALES TREND (last 7 days):")
        for sale in recent_sales:
            lines.append(f"- {sale['date']}: {sale['daily_total']:,.0f} units")
        avg_recent = sum(s["daily_total"] for s in recent_sales) / len(recent_sales) if recent_sales else 0
        lines.append(f"- Average daily sales: {avg_recent:,.0f} units")
        lines.append("")

    bake_plan = context.get("bake_plan")
    if bake_plan and bake_plan.get("items"):
        lines.append(f"TOMORROW'S BAKE PLAN ({bake_plan.get('date', 'N/A')}):")
        for item in bake_plan["items"][:10]:  # Limit to top 10
            lines.append(f"- {item['product_name']}: {item['forecast_quantity']} units")
        if len(bake_plan["items"]) > 10:
            lines.append(f"- ... and {len(bake_plan['items']) - 10} more products")
        lines.append("")

    products = context.get("products", [])
    if products:
        lines.append(f"TOTAL PRODUCTS: {len(products)}")
        lines.append("")

    return "\n".join(lines)

