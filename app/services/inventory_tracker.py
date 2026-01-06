from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import List

from app.models import SalesRecord


@dataclass
class DailyInventoryState:
    """Represents inventory flow for a single day for one product."""

    date: date
    quantity_sold: float
    quantity_delivered: float
    starting_inventory: float
    available_inventory: float
    leftover: float
    waste_quantity: float
    carryover_quantity: float


def compute_inventory_timeseries(
    sales_records: List[SalesRecord],
    *,
    shelf_life_days: int,
) -> List[DailyInventoryState]:
    """
    Compute per-day inventory, leftovers, and waste with shelf-life-aware carryover.

    - Shelf life is in whole days (currently 1–2).
    - Items are assumed to be sold FIFO (oldest stock first).
    - For shelf_life_days == 1:
        * Any unsold inventory at end of day is waste.
    - For shelf_life_days == 2:
        * Unsold inventory from day 0 can be sold on day 1.
        * Unsold inventory that is 2 days old at the END of the day is treated as waste.

    If quantity_delivered is missing for a day, we conservatively assume
    production equals sales (no waste or carryover for that day).
    """
    if not sales_records:
        return []

    # Clamp to supported range for safety
    if shelf_life_days < 1:
        shelf_life_days = 1
    if shelf_life_days > 2:
        shelf_life_days = 2

    # Sort by date to ensure chronological processing
    sorted_records = sorted(sales_records, key=lambda r: r.date)

    states: List[DailyInventoryState] = []

    # Buckets indexed by "age in days".
    # bucket[0] => produced today
    # bucket[1] => produced yesterday (for shelf_life_days == 2)
    age_buckets = [0.0 for _ in range(shelf_life_days)]

    for record in sorted_records:
        qty_sold = float(record.quantity_sold or 0.0)
        # If no delivery is recorded, assume we only produced what we sold.
        # This matches the old semantics (no waste when delivery is unknown).
        qty_delivered = (
            float(record.quantity_delivered)
            if record.quantity_delivered is not None
            else qty_sold
        )

        # Starting inventory is everything in buckets before today's production.
        starting_inventory = sum(age_buckets)

        # Add today's production as age 0 inventory.
        age_buckets[0] += qty_delivered

        # Available inventory after production, before sales.
        available_inventory = sum(age_buckets)

        # Sell using FIFO: consume from oldest stock first.
        remaining_demand = qty_sold
        for age in reversed(range(shelf_life_days)):
            if remaining_demand <= 0:
                break
            stock_at_age = age_buckets[age]
            if stock_at_age <= 0:
                continue
            used = min(stock_at_age, remaining_demand)
            age_buckets[age] -= used
            remaining_demand -= used

        # Anything left in the oldest bucket at the END of the day has reached
        # the end of its shelf life and is considered waste.
        waste_quantity = 0.0
        if shelf_life_days == 1:
            # All leftovers are waste when shelf life is 1 day.
            leftover = sum(age_buckets)
            waste_quantity = leftover
            carryover = 0.0
            age_buckets = [0.0 for _ in range(shelf_life_days)]
        else:
            # shelf_life_days == 2 (by clamping above)
            oldest_age_index = shelf_life_days - 1
            waste_quantity = age_buckets[oldest_age_index]
            age_buckets[oldest_age_index] = 0.0
            leftover = sum(age_buckets)
            carryover = leftover

        states.append(
            DailyInventoryState(
                date=record.date,
                quantity_sold=qty_sold,
                quantity_delivered=qty_delivered,
                starting_inventory=starting_inventory,
                available_inventory=available_inventory,
                leftover=leftover,
                waste_quantity=waste_quantity,
                carryover_quantity=carryover,
            )
        )

    return states









