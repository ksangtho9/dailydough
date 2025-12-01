from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import pandas as pd

from app.models import Product, SalesRecord
from app.services.inventory_tracker import compute_inventory_timeseries


@dataclass
class ProfitMetrics:
    """Profit calculation results for a single day or forecast period."""
    revenue: float
    cost: float
    waste_cost: float
    profit: float
    waste_quantity: float
    has_delivery_data: bool


@dataclass
class HistoricalProfitSummary:
    """Summary of profit metrics over a historical period."""
    total_revenue: float
    total_cost: float
    total_waste_cost: float
    total_profit: float
    total_waste_quantity: float
    average_daily_profit: float
    profit_margin_percent: float
    waste_percent: float
    has_delivery_data: bool
    days_with_data: int


class ProfitCalculator:
    """
    Calculates profit metrics for bakery products.
    
    Profit = Revenue - Cost - Waste Cost
    - Revenue = quantity_sold * price
    - Cost = quantity_delivered * cost_per_unit (or quantity_sold * cost_per_unit if no delivery)
    - Waste = max(0, quantity_delivered - quantity_sold) * cost_per_unit
    """

    @staticmethod
    def calculate_daily_profit(
        quantity_sold: float,
        quantity_delivered: Optional[float],
        price: Optional[float],
        cost_per_unit: Optional[float],
    ) -> ProfitMetrics:
        """
        Calculate profit metrics for a single day.
        
        Args:
            quantity_sold: Units sold
            quantity_delivered: Units produced/delivered (optional)
            price: Selling price per unit (optional)
            cost_per_unit: Production cost per unit (optional)
        
        Returns:
            ProfitMetrics with all calculated values
        """
        has_delivery_data = quantity_delivered is not None
        
        # Default to 0 if price/cost not set
        price = price or 0.0
        cost_per_unit = cost_per_unit or 0.0
        
        # Revenue = sales * price
        revenue = quantity_sold * price
        
        # Cost calculation:
        # - If delivery data exists: cost = delivered * cost_per_unit
        # - Otherwise: cost = sold * cost_per_unit (assume we only produce what we sell)
        if has_delivery_data:
            cost = quantity_delivered * cost_per_unit
            waste_quantity = max(0.0, quantity_delivered - quantity_sold)
        else:
            # Without delivery data, assume no waste (we only produce what we sell)
            cost = quantity_sold * cost_per_unit
            waste_quantity = 0.0
        
        waste_cost = waste_quantity * cost_per_unit
        profit = revenue - cost - waste_cost
        
        return ProfitMetrics(
            revenue=revenue,
            cost=cost,
            waste_cost=waste_cost,
            profit=profit,
            waste_quantity=waste_quantity,
            has_delivery_data=has_delivery_data,
        )

    @staticmethod
    def calculate_historical_profit(
        sales_records: List[SalesRecord],
        product: Product,
    ) -> HistoricalProfitSummary:
        """
        Calculate profit summary for historical sales records.
        
        Args:
            sales_records: List of sales records for the product
            product: Product with price and cost_per_unit
        
        Returns:
            HistoricalProfitSummary with aggregated metrics
        """
        if not sales_records:
            return HistoricalProfitSummary(
                total_revenue=0.0,
                total_cost=0.0,
                total_waste_cost=0.0,
                total_profit=0.0,
                total_waste_quantity=0.0,
                average_daily_profit=0.0,
                profit_margin_percent=0.0,
                waste_percent=0.0,
                has_delivery_data=False,
                days_with_data=0,
            )
        
        # Decide whether to use shelf-life-aware inventory tracking.
        shelf_life_days = getattr(product, "shelf_life_days", 1) or 1
        has_delivery_data = any(
            record.quantity_delivered is not None for record in sales_records
        )

        total_revenue = 0.0
        total_cost = 0.0
        total_waste_cost = 0.0
        total_waste_quantity = 0.0

        if shelf_life_days > 1:
            # Use shelf-life-aware inventory tracking for multi-day products.
            inv_states = compute_inventory_timeseries(
                sales_records, shelf_life_days=shelf_life_days
            )

            for state in inv_states:
                # Revenue is based on units actually sold that day.
                metrics_revenue = (state.quantity_sold * (product.price or 0.0))

                # Production cost is based on units delivered (or inferred from sales
                # when delivery is missing).
                unit_cost = product.cost_per_unit or 0.0
                metrics_cost = state.quantity_delivered * unit_cost

                # Waste cost only counts items that have exceeded shelf life.
                metrics_waste_cost = state.waste_quantity * unit_cost

                total_revenue += metrics_revenue
                total_cost += metrics_cost
                total_waste_cost += metrics_waste_cost
                total_waste_quantity += state.waste_quantity

            days_with_data = len(inv_states)
        else:
            # Original per-day calculation for 1-day shelf life (backwards compatible).
            for record in sales_records:
                metrics = ProfitCalculator.calculate_daily_profit(
                    quantity_sold=record.quantity_sold,
                    quantity_delivered=record.quantity_delivered,
                    price=product.price,
                    cost_per_unit=product.cost_per_unit,
                )
                total_revenue += metrics.revenue
                total_cost += metrics.cost
                total_waste_cost += metrics.waste_cost
                total_waste_quantity += metrics.waste_quantity

            days_with_data = len(sales_records)
        total_profit = total_revenue - total_cost - total_waste_cost
        average_daily_profit = total_profit / days_with_data if days_with_data > 0 else 0.0
        
        # Calculate percentages
        profit_margin_percent = (
            (total_profit / total_revenue * 100) if total_revenue > 0 else 0.0
        )
        
        if shelf_life_days > 1 and has_delivery_data:
            total_produced = sum(
                r.quantity_delivered or 0.0 for r in sales_records
            )
        elif has_delivery_data:
            total_produced = sum(
                r.quantity_delivered or 0.0 for r in sales_records
            )
        else:
            total_produced = sum(r.quantity_sold for r in sales_records)
        waste_percent = (
            (total_waste_quantity / total_produced * 100) if total_produced > 0 else 0.0
        )
        
        return HistoricalProfitSummary(
            total_revenue=total_revenue,
            total_cost=total_cost,
            total_waste_cost=total_waste_cost,
            total_profit=total_profit,
            total_waste_quantity=total_waste_quantity,
            average_daily_profit=average_daily_profit,
            profit_margin_percent=profit_margin_percent,
            waste_percent=waste_percent,
            has_delivery_data=has_delivery_data,
            days_with_data=days_with_data,
        )

    @staticmethod
    def calculate_forecast_profit(
        forecast_quantity: float,
        price: Optional[float],
        cost_per_unit: Optional[float],
        production_quantity: Optional[float] = None,
        shelf_life_days: int = 1,
    ) -> ProfitMetrics:
        """
        Calculate projected profit for a forecast period.
        
        Args:
            forecast_quantity: Forecasted demand (yhat)
            price: Selling price per unit
            cost_per_unit: Production cost per unit
            production_quantity: Optional production quantity (if different from forecast)
        
        Returns:
            ProfitMetrics for the forecast period
        """
        # If production_quantity not provided, assume we produce exactly the forecast
        # (ideal scenario - no waste, but also no buffer for stockouts)
        if production_quantity is None:
            production_quantity = forecast_quantity

        # For 1-day shelf life, treat any overproduction as waste (original behavior).
        # For multi-day shelf life, we treat overproduction as carryover (no immediate waste)
        # in this single-period profit view, since those units can be sold on subsequent days.
        shelf_life_days = shelf_life_days or 1
        if shelf_life_days <= 1:
            return ProfitCalculator.calculate_daily_profit(
                quantity_sold=forecast_quantity,  # Assume we sell what we forecast
                quantity_delivered=production_quantity,
                price=price,
                cost_per_unit=cost_per_unit,
            )

        # Multi-day shelf life: no same-day waste penalty for producing above forecast.
        has_delivery_data = True
        price = price or 0.0
        cost_per_unit = cost_per_unit or 0.0

        revenue = forecast_quantity * price
        cost = production_quantity * cost_per_unit
        waste_quantity = 0.0
        waste_cost = 0.0
        profit = revenue - cost - waste_cost

        return ProfitMetrics(
            revenue=revenue,
            cost=cost,
            waste_cost=waste_cost,
            profit=profit,
            waste_quantity=waste_quantity,
            has_delivery_data=has_delivery_data,
        )

