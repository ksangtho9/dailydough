from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Product, SalesRecord, WalkForwardResult
from app.ml.validation.walk_forward_validator import WalkForwardValidator

logger = logging.getLogger("bakezy.walk_forward_scheduler")


class WalkForwardScheduler:
    """
    Background service for semi-automated walk-forward validation.
    
    Responsibilities:
    - Check for new actual sales data daily
    - Automatically update validation results when actuals become available
    - Optionally auto-advance to next day if accuracy passes threshold
    - Log validation progress for manual review
    """

    def __init__(self, db: Session):
        self.db = db
        self.validator = WalkForwardValidator(db)

    def check_and_update_pending_actuals(
        self,
        product_id: int,
        test_period_start: date,
        test_period_end: date,
    ) -> dict[str, int]:
        """
        Check for pending predictions that now have actual sales data available,
        and update them automatically.
        
        Args:
            product_id: Product ID to check
            test_period_start: Start of test period
            test_period_end: End of test period
        
        Returns:
            Dict with counts of updated and still-pending predictions
        """
        # Find pending predictions (have prediction but no actual)
        pending_results = (
            self.db.query(WalkForwardResult)
            .filter(
                WalkForwardResult.product_id == product_id,
                WalkForwardResult.test_date >= test_period_start,
                WalkForwardResult.test_date <= test_period_end,
                WalkForwardResult.actual_quantity.is_(None),
            )
            .order_by(WalkForwardResult.test_date.asc())
            .all()
        )

        updated_count = 0
        still_pending_count = 0

        for result in pending_results:
            # Check if actual sales data is available for this date
            product = self.db.query(Product).filter(Product.id == product_id).one_or_none()
            if product is None:
                continue

            sales_record = (
                self.db.query(SalesRecord)
                .filter(
                    SalesRecord.product_id == product_id,
                    SalesRecord.bakery_id == product.bakery_id,
                    SalesRecord.date == result.test_date,
                )
                .one_or_none()
            )

            if sales_record is not None:
                # Actual data is available, update the result
                try:
                    self.validator.update_with_actual(
                        product_id=product_id,
                        test_date=result.test_date,
                        actual_quantity=sales_record.quantity_sold,
                    )
                    updated_count += 1
                    logger.info(
                        f"Auto-updated walk-forward result for product {product_id} "
                        f"on {result.test_date} with actual quantity {sales_record.quantity_sold}"
                    )
                except Exception as e:
                    logger.error(
                        f"Error updating walk-forward result for product {product_id} "
                        f"on {result.test_date}: {e}"
                    )
            else:
                still_pending_count += 1

        return {
            "updated": updated_count,
            "still_pending": still_pending_count,
        }

    def auto_predict_next_day(
        self,
        product_id: int,
        test_period_start: date,
        test_period_end: date,
        model_name: str = "prophet",
        min_accuracy_threshold: Optional[float] = None,
    ) -> Optional[dict]:
        """
        Automatically predict the next day if all previous days have actuals.
        
        Args:
            product_id: Product ID
            test_period_start: Start of test period
            test_period_end: End of test period
            model_name: Model type to use
            min_accuracy_threshold: Optional MAPE threshold. If provided and current
                                   MAPE is above threshold, don't auto-predict.
        
        Returns:
            Dict with prediction info if made, None otherwise
        """
        # Get current status
        status = self.validator.get_validation_status(
            product_id=product_id,
            test_period_start=test_period_start,
            test_period_end=test_period_end,
        )

        # Check if there's a next date to predict
        if status["next_date_to_predict"] is None:
            logger.info(f"No more days to predict for product {product_id}")
            return None

        # Check if there are pending actuals (need manual review first)
        if status["predictions_pending"] > 0:
            logger.info(
                f"Cannot auto-predict for product {product_id}: "
                f"{status['predictions_pending']} predictions still pending actuals"
            )
            return None

        # Check accuracy threshold if provided
        if min_accuracy_threshold is not None:
            metrics = status["metrics"]
            if metrics["cumulative_mape"] is not None:
                if metrics["cumulative_mape"] > min_accuracy_threshold:
                    logger.info(
                        f"Cannot auto-predict for product {product_id}: "
                        f"MAPE {metrics['cumulative_mape']:.2f}% exceeds threshold "
                        f"{min_accuracy_threshold:.2f}%"
                    )
                    return None

        # Calculate training end date (day before next prediction date)
        next_date = status["next_date_to_predict"]
        training_end_date = next_date - timedelta(days=1)

        # Make prediction
        try:
            prediction = self.validator.predict_next_day(
                product_id=product_id,
                test_date=next_date,
                training_end_date=training_end_date,
                model_name=model_name,
            )

            # Store in database
            result = WalkForwardResult(
                product_id=product_id,
                test_date=next_date,
                predicted_quantity=prediction["predicted_quantity"],
            )
            self.db.add(result)
            self.db.commit()
            self.db.refresh(result)

            logger.info(
                f"Auto-predicted next day for product {product_id}: "
                f"date={next_date}, predicted={prediction['predicted_quantity']:.2f}"
            )

            return {
                "product_id": product_id,
                "test_date": next_date,
                "predicted_quantity": prediction["predicted_quantity"],
                "training_end_date": training_end_date,
                "n_training_days": prediction["n_training_days"],
                "walk_forward_result_id": result.id,
            }
        except Exception as e:
            logger.error(
                f"Error auto-predicting next day for product {product_id}: {e}"
            )
            return None

    def process_product_daily(
        self,
        product_id: int,
        test_period_start: date,
        test_period_end: date,
        model_name: str = "prophet",
        auto_advance: bool = False,
        min_accuracy_threshold: Optional[float] = None,
    ) -> dict:
        """
        Daily processing routine for a product's walk-forward validation.
        
        This method:
        1. Checks for and updates pending predictions with actual sales
        2. Optionally auto-predicts next day if auto_advance is True
        
        Args:
            product_id: Product ID
            test_period_start: Start of test period
            test_period_end: End of test period
            model_name: Model type to use
            auto_advance: If True, automatically predict next day after updating actuals
            min_accuracy_threshold: Optional MAPE threshold for auto-advance
        
        Returns:
            Dict with processing results
        """
        # Step 1: Update pending actuals
        update_results = self.check_and_update_pending_actuals(
            product_id=product_id,
            test_period_start=test_period_start,
            test_period_end=test_period_end,
        )

        # Step 2: Optionally auto-predict next day
        prediction_result = None
        if auto_advance:
            prediction_result = self.auto_predict_next_day(
                product_id=product_id,
                test_period_start=test_period_start,
                test_period_end=test_period_end,
                model_name=model_name,
                min_accuracy_threshold=min_accuracy_threshold,
            )

        # Get current status
        status = self.validator.get_validation_status(
            product_id=product_id,
            test_period_start=test_period_start,
            test_period_end=test_period_end,
        )

        return {
            "product_id": product_id,
            "updated_predictions": update_results["updated"],
            "still_pending": update_results["still_pending"],
            "auto_prediction_made": prediction_result is not None,
            "auto_prediction": prediction_result,
            "current_status": status,
        }







