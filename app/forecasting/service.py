from __future__ import annotations
from datetime import date, timedelta
from collections import defaultdict
from sqlalchemy.orm import Session

from app.models.sales_record import SalesRecord


class ForecastService:
    """
    Simple baseline forecaster:
    - Uses recent history for (bakery_id, product_id)
    - Averages quantity per weekday (Mon–Sun)
    """

    def __init__(self, db: Session):
        self.db = db

    def _get_history(
        self,
        bakery_id: int,
        product_id: int,
        days_back: int = 90,
    ):
        cutoff = date.today() - timedelta(days=days_back)
        q = (
            self.db.query(SalesRecord)
            .filter(
                SalesRecord.bakery_id == bakery_id,
                SalesRecord.product_id == product_id,
                SalesRecord.date >= cutoff,
            )
            .order_by(SalesRecord.date)
        )
        return q.all()

    def forecast_product(
        self,
        bakery_id: int,
        product_id: int,
        horizon_days: int = 7,
    ) -> list[dict]:
        history = self._get_history(bakery_id, product_id)
        today = date.today()

        if not history:
            # No data → zeros
            return [
                {"date": today + timedelta(days=i), "quantity": 0.0}
                for i in range(1, horizon_days + 1)
            ]

        weekday_totals = defaultdict(float)
        weekday_counts = defaultdict(int)

        for record in history:
            wd = record.date.weekday()
            weekday_totals[wd] += record.quantity_sold
            weekday_counts[wd] += 1

        total_qty = sum(weekday_totals.values())
        total_cnt = sum(weekday_counts.values()) or 1
        global_avg = total_qty / total_cnt

        weekday_avg = {}
        for wd in range(7):
            if weekday_counts[wd] > 0:
                weekday_avg[wd] = weekday_totals[wd] / weekday_counts[wd]
            else:
                weekday_avg[wd] = global_avg

        forecasts: list[dict] = []
        for i in range(1, horizon_days + 1):
            d = today + timedelta(days=i)
            wd = d.weekday()
            qty = weekday_avg[wd]
            forecasts.append({"date": d, "quantity": qty})

        return forecasts
