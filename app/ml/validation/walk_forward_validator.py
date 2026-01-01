from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Dict, Any, List, Tuple

import pandas as pd
from sqlalchemy.orm import Session

from app.models import Product, SalesRecord, WalkForwardResult
from app.ml.preprocessing import SalesPreprocessor, RawSalesRecord, CleanedTimeSeries
from app.ml.trainer import ModelTrainer
from app.ml.forecaster import ProductForecaster
from app.ml.metrics import calculate_wape

logger = logging.getLogger("bakezy.walk_forward_validation")


class WalkForwardValidator:
    """
    Performs walk-forward validation for forecasting models.
    
    Process:
    1. Split data at cutoff date (e.g., end of month 11)
    2. For each day in test period (month 12):
       - Train model on expanding window (starts at 11 months, grows day by day)
       - Make 1-day-ahead prediction
       - Store prediction
       - When actual data available, calculate metrics and expand training window
    """

    def __init__(self, db: Session):
        self.db = db
        self.preprocessor = SalesPreprocessor()
        self.trainer = ModelTrainer()
        self.forecaster = ProductForecaster(trainer=self.trainer)

    def _load_sales_records(
        self,
        product_id: int,
        end_date: Optional[date] = None,
    ) -> List[RawSalesRecord]:
        """Load sales records for a product up to a given date."""
        product = self.db.query(Product).filter(Product.id == product_id).one_or_none()
        if product is None:
            raise ValueError(f"Product {product_id} not found")

        query = (
            self.db.query(SalesRecord)
            .filter(
                SalesRecord.product_id == product_id,
                SalesRecord.bakery_id == product.bakery_id,
            )
            .order_by(SalesRecord.date.asc())
        )

        if end_date is not None:
            query = query.filter(SalesRecord.date <= end_date)

        sales_rows = query.all()

        return [
            RawSalesRecord(
                date=row.date,
                product_id=row.product_id,
                quantity=row.quantity_sold,
                quantity_delivered=row.quantity_delivered,
            )
            for row in sales_rows
        ]

    def _calculate_error_metrics(
        self,
        predicted: float,
        actual: float,
    ) -> Tuple[float, float]:
        """
        Calculate absolute error and percentage error.
        
        Returns:
            Tuple of (absolute_error, percentage_error)
        """
        absolute_error = abs(predicted - actual)
        if actual != 0:
            percentage_error = (absolute_error / actual) * 100
        else:
            percentage_error = 0.0 if predicted == 0 else float('inf')
        
        return absolute_error, percentage_error

    def predict_next_day(
        self,
        product_id: int,
        test_date: date,
        training_end_date: date,
        model_name: str = "prophet",
    ) -> Dict[str, Any]:
        """
        Make a prediction for a specific test date using training data up to training_end_date.
        
        Args:
            product_id: Product ID to forecast
            test_date: Date to predict (should be training_end_date + 1 day)
            training_end_date: Last date to include in training data
            model_name: Model type to use ("prophet", "xgboost", or "ensemble")
        
        Returns:
            Dict with prediction information
        """
        # Load training data up to training_end_date
        training_records = self._load_sales_records(product_id, end_date=training_end_date)
        
        if not training_records:
            raise ValueError(f"No training data available for product {product_id} up to {training_end_date}")

        # Preprocess training data
        cleaned = self.preprocessor.preprocess(training_records, product_id=product_id)
        if cleaned.df.empty:
            raise ValueError(f"Preprocessed training data is empty for product {product_id}")

        # Get product info for feature engineering
        product = self.db.query(Product).filter(Product.id == product_id).one_or_none()
        product_info = None
        if product:
            product_info = {
                "product_id": product.id,
                "category": product.category,
                "shelf_life_days": product.shelf_life_days,
            }

        # Make 1-day-ahead forecast
        forecast_result = self.forecaster.forecast(
            ts=cleaned,
            horizon_days=1,
            model_name=model_name,
            product_info=product_info,
        )

        # Extract prediction for the test_date
        forecast_df = forecast_result.forecast_df
        if forecast_df.empty:
            raise ValueError(f"No forecast generated for product {product_id} on {test_date}")

        # Convert test_date to datetime for comparison
        test_datetime = pd.to_datetime(test_date)

        # Find matching row in forecast
        forecast_df["ds"] = pd.to_datetime(forecast_df["ds"])
        matching_rows = forecast_df[forecast_df["ds"].dt.date == test_date]

        if matching_rows.empty:
            # If exact match not found, take first row (should be next day)
            predicted_quantity = float(forecast_df.iloc[0]["yhat"])
        else:
            predicted_quantity = float(matching_rows.iloc[0]["yhat"])

        return {
            "product_id": product_id,
            "test_date": test_date,
            "predicted_quantity": predicted_quantity,
            "training_end_date": training_end_date,
            "n_training_days": len(cleaned.df),
        }

    def update_with_actual(
        self,
        product_id: int,
        test_date: date,
        actual_quantity: float,
    ) -> WalkForwardResult:
        """
        Update a walk-forward result with actual sales data and calculate metrics.
        
        Args:
            product_id: Product ID
            test_date: Date of the prediction
            actual_quantity: Actual sales quantity
        
        Returns:
            Updated WalkForwardResult
        """
        # Find existing prediction
        result = (
            self.db.query(WalkForwardResult)
            .filter(
                WalkForwardResult.product_id == product_id,
                WalkForwardResult.test_date == test_date,
            )
            .one_or_none()
        )

        if result is None:
            raise ValueError(
                f"No prediction found for product {product_id} on date {test_date}. "
                "Call predict_next_day first."
            )

        # Update with actual
        result.actual_quantity = actual_quantity
        result.updated_at = datetime.now(timezone.utc)

        # Calculate error metrics
        absolute_error, percentage_error = self._calculate_error_metrics(
            result.predicted_quantity,
            actual_quantity,
        )
        result.absolute_error = absolute_error
        result.percentage_error = percentage_error

        self.db.commit()
        self.db.refresh(result)

        logger.info(
            f"Updated walk-forward result for product {product_id} on {test_date}: "
            f"predicted={result.predicted_quantity:.2f}, actual={actual_quantity:.2f}, "
            f"error={absolute_error:.2f}, pct_error={percentage_error:.2f}%"
        )

        return result

    def get_validation_metrics(
        self,
        product_id: int,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        """
        Calculate cumulative and rolling metrics for walk-forward validation.
        
        Args:
            product_id: Product ID
            start_date: Optional start date for filtering
            end_date: Optional end date for filtering
        
        Returns:
            Dict with metrics (MAPE, RMSE, WAPE) and trend information
        """
        query = (
            self.db.query(WalkForwardResult)
            .filter(WalkForwardResult.product_id == product_id)
            .filter(WalkForwardResult.actual_quantity.isnot(None))
        )

        if start_date is not None:
            query = query.filter(WalkForwardResult.test_date >= start_date)
        if end_date is not None:
            query = query.filter(WalkForwardResult.test_date <= end_date)

        results = query.order_by(WalkForwardResult.test_date.asc()).all()

        if not results:
            return {
                "n_points": 0,
                "cumulative_mape": None,
                "cumulative_rmse": None,
                "cumulative_wape": None,
                "rolling_7d_mape": None,
                "rolling_7d_rmse": None,
                "rolling_7d_wape": None,
                "trend": "no_data",
            }

        # Extract actual and predicted values
        actuals = [r.actual_quantity for r in results]
        predictions = [r.predicted_quantity for r in results]

        # Calculate cumulative metrics
        actuals_array = pd.Series(actuals)
        predictions_array = pd.Series(predictions)

        # MAPE (Mean Absolute Percentage Error)
        non_zero_mask = actuals_array != 0
        if non_zero_mask.any():
            mape_values = (predictions_array[non_zero_mask] - actuals_array[non_zero_mask]).abs() / actuals_array[non_zero_mask] * 100
            cumulative_mape = float(mape_values.mean())
        else:
            cumulative_mape = None

        # RMSE (Root Mean Squared Error)
        errors = predictions_array - actuals_array
        cumulative_rmse = float((errors.pow(2).mean()) ** 0.5)

        # WAPE (Weighted Absolute Percentage Error)
        cumulative_wape = calculate_wape(actuals_array.values, predictions_array.values)
        if cumulative_wape is not None:
            cumulative_wape = float(cumulative_wape) * 100  # Convert to percentage

        # Rolling 7-day metrics (if we have at least 7 days)
        rolling_7d_mape = None
        rolling_7d_rmse = None
        rolling_7d_wape = None

        if len(results) >= 7:
            recent_results = results[-7:]
            recent_actuals = [r.actual_quantity for r in recent_results]
            recent_predictions = [r.predicted_quantity for r in recent_results]
            
            recent_actuals_array = pd.Series(recent_actuals)
            recent_predictions_array = pd.Series(recent_predictions)

            # Rolling MAPE
            non_zero_mask = recent_actuals_array != 0
            if non_zero_mask.any():
                mape_values = (recent_predictions_array[non_zero_mask] - recent_actuals_array[non_zero_mask]).abs() / recent_actuals_array[non_zero_mask] * 100
                rolling_7d_mape = float(mape_values.mean())

            # Rolling RMSE
            errors = recent_predictions_array - recent_actuals_array
            rolling_7d_rmse = float((errors.pow(2).mean()) ** 0.5)

            # Rolling WAPE
            rolling_7d_wape = calculate_wape(recent_actuals_array.values, recent_predictions_array.values)
            if rolling_7d_wape is not None:
                rolling_7d_wape = float(rolling_7d_wape) * 100

        # Determine trend (comparing first half vs second half if we have enough data)
        trend = "stable"
        if len(results) >= 14:
            mid_point = len(results) // 2
            first_half = results[:mid_point]
            second_half = results[mid_point:]

            first_actuals = pd.Series([r.actual_quantity for r in first_half])
            first_predictions = pd.Series([r.predicted_quantity for r in first_half])
            first_errors = (first_predictions - first_actuals).abs()

            second_actuals = pd.Series([r.actual_quantity for r in second_half])
            second_predictions = pd.Series([r.predicted_quantity for r in second_half])
            second_errors = (second_predictions - second_actuals).abs()

            first_mae = float(first_errors.mean())
            second_mae = float(second_errors.mean())

            if second_mae < first_mae * 0.95:  # More than 5% improvement
                trend = "improving"
            elif second_mae > first_mae * 1.05:  # More than 5% deterioration
                trend = "declining"

        return {
            "n_points": len(results),
            "cumulative_mape": cumulative_mape,
            "cumulative_rmse": cumulative_rmse,
            "cumulative_wape": cumulative_wape,
            "rolling_7d_mape": rolling_7d_mape,
            "rolling_7d_rmse": rolling_7d_rmse,
            "rolling_7d_wape": rolling_7d_wape,
            "trend": trend,
        }

    def get_validation_status(
        self,
        product_id: int,
        test_period_start: date,
        test_period_end: date,
    ) -> Dict[str, Any]:
        """
        Get the current status of walk-forward validation for a product.
        
        Args:
            product_id: Product ID
            test_period_start: Start date of test period
            test_period_end: End date of test period
        
        Returns:
            Dict with status information
        """
        # Count predictions made
        all_predictions = (
            self.db.query(WalkForwardResult)
            .filter(
                WalkForwardResult.product_id == product_id,
                WalkForwardResult.test_date >= test_period_start,
                WalkForwardResult.test_date <= test_period_end,
            )
            .order_by(WalkForwardResult.test_date.asc())
            .all()
        )

        predictions_with_actuals = [r for r in all_predictions if r.actual_quantity is not None]
        predictions_pending = [r for r in all_predictions if r.actual_quantity is None]

        # Determine next date to predict
        next_date = None
        if not all_predictions:
            next_date = test_period_start
        else:
            last_prediction_date = max(r.test_date for r in all_predictions)
            if last_prediction_date < test_period_end:
                next_date = last_prediction_date + timedelta(days=1)

        # Get current metrics
        metrics = self.get_validation_metrics(product_id, test_period_start, test_period_end)

        return {
            "product_id": product_id,
            "test_period_start": test_period_start,
            "test_period_end": test_period_end,
            "total_test_days": (test_period_end - test_period_start).days + 1,
            "predictions_made": len(all_predictions),
            "predictions_with_actuals": len(predictions_with_actuals),
            "predictions_pending": len(predictions_pending),
            "next_date_to_predict": next_date,
            "is_complete": next_date is None and len(predictions_pending) == 0,
            "metrics": metrics,
        }





