from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Dict, Any

import pandas as pd
import numpy as np

try:
    from prophet import Prophet
except ImportError:
    Prophet = None


@dataclass
class ForecastComponent:
    """Component breakdown of a forecast point."""
    date: str
    trend: float
    weekly_seasonality: float
    daily_seasonality: float
    regressor_contributions: Dict[str, float]
    total_forecast: float


@dataclass
class ForecastExplanation:
    """Full explanation of a forecast with component breakdown."""
    product_id: int
    forecast_points: List[ForecastComponent]
    feature_importance: Dict[str, float]
    model_type: str


class ForecastInterpreter:
    """Extracts interpretability information from Prophet forecasts."""

    @staticmethod
    def explain_prophet_forecast(
        model: Prophet,
        forecast_df: pd.DataFrame,
        product_id: int,
    ) -> ForecastExplanation:
        """
        Extract component breakdown from Prophet forecast.

        Args:
            model: Fitted Prophet model
            forecast_df: Forecast DataFrame from Prophet (with components)
            product_id: Product ID for this forecast

        Returns:
            ForecastExplanation with component breakdown
        """
        if model is None:
            raise ValueError("Model is not fitted")

        components = []
        feature_importance = {}

        # Get regressor names from the forecast DataFrame
        # Prophet includes regressor contributions as columns in the forecast
        standard_columns = {
            "ds", "yhat", "yhat_lower", "yhat_upper", "trend", "additive_terms",
            "multiplicative_terms", "weekly", "yearly", "daily", "holidays",
            "zeros", "extra_regressors_additive", "extra_regressors_multiplicative"
        }
        regressor_names = [
            col for col in forecast_df.columns
            if col not in standard_columns and col not in ["y", "cap", "floor"]
        ]

        for _, row in forecast_df.iterrows():
            date_str = row["ds"].date().isoformat() if hasattr(row["ds"], "date") else str(row["ds"])

            # Extract components
            trend = float(row.get("trend", 0.0))
            weekly = float(row.get("weekly", 0.0))
            daily = float(row.get("daily", 0.0))
            yhat = float(row.get("yhat", 0.0))

            # Extract regressor contributions
            regressor_contributions = {}
            for regressor in regressor_names:
                component_name = regressor
                if component_name in row:
                    regressor_contributions[regressor] = float(row[component_name])
                else:
                    regressor_contributions[regressor] = 0.0

            components.append(
                ForecastComponent(
                    date=date_str,
                    trend=trend,
                    weekly_seasonality=weekly,
                    daily_seasonality=daily,
                    regressor_contributions=regressor_contributions,
                    total_forecast=yhat,
                )
            )

        # Calculate feature importance (average absolute contribution)
        if regressor_names:
            for regressor in regressor_names:
                contributions = [
                    abs(comp.regressor_contributions.get(regressor, 0.0))
                    for comp in components
                ]
                if contributions:
                    feature_importance[regressor] = float(np.mean(contributions))

        # Add seasonality importance
        trend_contribs = [abs(comp.trend) for comp in components]
        weekly_contribs = [abs(comp.weekly_seasonality) for comp in components]
        daily_contribs = [abs(comp.daily_seasonality) for comp in components]

        if trend_contribs:
            feature_importance["trend"] = float(np.mean(trend_contribs))
        if weekly_contribs:
            feature_importance["weekly_seasonality"] = float(np.mean(weekly_contribs))
        if daily_contribs:
            feature_importance["daily_seasonality"] = float(np.mean(daily_contribs))

        return ForecastExplanation(
            product_id=product_id,
            forecast_points=components,
            feature_importance=feature_importance,
            model_type="prophet",
        )

    @staticmethod
    def get_top_drivers(explanation: ForecastExplanation, top_n: int = 5) -> List[tuple[str, float]]:
        """
        Get top N features driving the forecast.

        Returns:
            List of (feature_name, importance) tuples, sorted by importance
        """
        sorted_features = sorted(
            explanation.feature_importance.items(),
            key=lambda x: x[1],
            reverse=True,
        )
        return sorted_features[:top_n]

    @staticmethod
    def explain_forecast_point(
        explanation: ForecastExplanation,
        date: str,
    ) -> Optional[ForecastComponent]:
        """Get explanation for a specific forecast date."""
        for comp in explanation.forecast_points:
            if comp.date == date:
                return comp
        return None

