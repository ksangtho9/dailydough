from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.database.database import get_db
from app.models import Product, WalkForwardResult
from app.ml.validation.walk_forward_validator import WalkForwardValidator
from app.schemas.walk_forward import (
    WalkForwardResultOut,
    WalkForwardPredictionRequest,
    WalkForwardPredictionResponse,
    WalkForwardUpdateActualRequest,
    WalkForwardStatusOut,
    WalkForwardMetricsOut,
    WalkForwardReportOut,
)

router = APIRouter(tags=["walk-forward-validation"])


@router.post(
    "/products/{product_id}/walk-forward/predict",
    response_model=WalkForwardPredictionResponse,
    status_code=status.HTTP_201_CREATED,
)
def predict_next_day(
    product_id: int,
    request: WalkForwardPredictionRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Make a 1-day-ahead prediction for walk-forward validation.
    
    This creates a prediction for the specified test_date using training data
    up to training_end_date. The prediction is stored in the database.
    """
    # Verify product exists and user has access
    product = db.query(Product).filter(Product.id == product_id).one_or_none()
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    # Validate dates
    if request.test_date <= request.training_end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="test_date must be after training_end_date",
        )

    # Check if prediction already exists
    existing = (
        db.query(WalkForwardResult)
        .filter(
            WalkForwardResult.product_id == product_id,
            WalkForwardResult.test_date == request.test_date,
        )
        .one_or_none()
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Prediction for {request.test_date} already exists",
        )

    try:
        validator = WalkForwardValidator(db)
        prediction = validator.predict_next_day(
            product_id=product_id,
            test_date=request.test_date,
            training_end_date=request.training_end_date,
            model_name=request.model_name,
        )

        # Store prediction in database
        result = WalkForwardResult(
            product_id=product_id,
            test_date=request.test_date,
            predicted_quantity=prediction["predicted_quantity"],
        )
        db.add(result)
        db.commit()
        db.refresh(result)

        return WalkForwardPredictionResponse(
            product_id=product_id,
            test_date=request.test_date,
            predicted_quantity=prediction["predicted_quantity"],
            training_end_date=prediction["training_end_date"],
            n_training_days=prediction["n_training_days"],
            walk_forward_result_id=result.id,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error making prediction: {str(e)}",
        ) from e


@router.post(
    "/products/{product_id}/walk-forward/update-actual",
    response_model=WalkForwardResultOut,
    status_code=status.HTTP_200_OK,
)
def update_actual_sales(
    product_id: int,
    request: WalkForwardUpdateActualRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Update a prediction with actual sales data.
    
    This updates the walk-forward result with actual sales, calculates error metrics,
    and marks it as complete. After this, you can proceed to predict the next day.
    """
    # Verify product exists
    product = db.query(Product).filter(Product.id == product_id).one_or_none()
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    try:
        validator = WalkForwardValidator(db)
        result = validator.update_with_actual(
            product_id=product_id,
            test_date=request.test_date,
            actual_quantity=request.actual_quantity,
        )

        return WalkForwardResultOut.model_validate(result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating actual sales: {str(e)}",
        ) from e


@router.get(
    "/products/{product_id}/walk-forward/status",
    response_model=WalkForwardStatusOut,
    status_code=status.HTTP_200_OK,
)
def get_validation_status(
    product_id: int,
    test_period_start: date,
    test_period_end: date,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get the current status of walk-forward validation for a product.
    
    Returns information about predictions made, pending actuals, next date to predict,
    and current metrics.
    """
    # Verify product exists
    product = db.query(Product).filter(Product.id == product_id).one_or_none()
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    if test_period_start > test_period_end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="test_period_start must be before test_period_end",
        )

    validator = WalkForwardValidator(db)
    status_info = validator.get_validation_status(
        product_id=product_id,
        test_period_start=test_period_start,
        test_period_end=test_period_end,
    )

    return WalkForwardStatusOut(**status_info)


@router.get(
    "/products/{product_id}/walk-forward/results",
    response_model=list[WalkForwardResultOut],
    status_code=status.HTTP_200_OK,
)
def get_validation_results(
    product_id: int,
    test_period_start: Optional[date] = None,
    test_period_end: Optional[date] = None,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get all walk-forward validation results for a product.
    
    Optionally filter by test period dates.
    """
    # Verify product exists
    product = db.query(Product).filter(Product.id == product_id).one_or_none()
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    query = db.query(WalkForwardResult).filter(WalkForwardResult.product_id == product_id)

    if test_period_start is not None:
        query = query.filter(WalkForwardResult.test_date >= test_period_start)
    if test_period_end is not None:
        query = query.filter(WalkForwardResult.test_date <= test_period_end)

    results = query.order_by(WalkForwardResult.test_date.asc()).all()

    return [WalkForwardResultOut.model_validate(r) for r in results]


@router.get(
    "/products/{product_id}/walk-forward/metrics",
    response_model=WalkForwardMetricsOut,
    status_code=status.HTTP_200_OK,
)
def get_validation_metrics(
    product_id: int,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get validation metrics (MAPE, RMSE, WAPE) for walk-forward validation.
    
    Returns cumulative and rolling metrics.
    """
    # Verify product exists
    product = db.query(Product).filter(Product.id == product_id).one_or_none()
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    validator = WalkForwardValidator(db)
    metrics = validator.get_validation_metrics(
        product_id=product_id,
        start_date=start_date,
        end_date=end_date,
    )

    return WalkForwardMetricsOut(**metrics)


@router.get(
    "/products/{product_id}/walk-forward/report",
    response_model=WalkForwardReportOut,
    status_code=status.HTTP_200_OK,
)
def get_validation_report(
    product_id: int,
    test_period_start: date,
    test_period_end: date,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get a comprehensive validation report with results, metrics, and daily error breakdown.
    
    Useful for visualization and analysis.
    """
    # Verify product exists
    product = db.query(Product).filter(Product.id == product_id).one_or_none()
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    if test_period_start > test_period_end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="test_period_start must be before test_period_end",
        )

    # Get all results
    results = (
        db.query(WalkForwardResult)
        .filter(
            WalkForwardResult.product_id == product_id,
            WalkForwardResult.test_date >= test_period_start,
            WalkForwardResult.test_date <= test_period_end,
        )
        .order_by(WalkForwardResult.test_date.asc())
        .all()
    )

    # Get metrics
    validator = WalkForwardValidator(db)
    metrics = validator.get_validation_metrics(
        product_id=product_id,
        start_date=test_period_start,
        end_date=test_period_end,
    )

    # Build daily error breakdown for visualization
    daily_errors = []
    for result in results:
        if result.actual_quantity is not None:
            daily_errors.append({
                "date": result.test_date.isoformat(),
                "predicted": result.predicted_quantity,
                "actual": result.actual_quantity,
                "absolute_error": result.absolute_error,
                "percentage_error": result.percentage_error,
            })

    return WalkForwardReportOut(
        product_id=product_id,
        product_name=product.name,
        test_period_start=test_period_start,
        test_period_end=test_period_end,
        results=[WalkForwardResultOut.model_validate(r) for r in results],
        metrics=WalkForwardMetricsOut(**metrics),
        daily_errors=daily_errors,
    )


@router.delete(
    "/products/{product_id}/walk-forward/reset",
    status_code=status.HTTP_204_NO_CONTENT,
)
def reset_validation(
    product_id: int,
    test_period_start: date,
    test_period_end: date,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Delete all walk-forward validation results for a product in the specified period.
    
    Useful for starting over or cleaning up.
    """
    # Verify product exists
    product = db.query(Product).filter(Product.id == product_id).one_or_none()
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    results = (
        db.query(WalkForwardResult)
        .filter(
            WalkForwardResult.product_id == product_id,
            WalkForwardResult.test_date >= test_period_start,
            WalkForwardResult.test_date <= test_period_end,
        )
        .all()
    )

    for result in results:
        db.delete(result)

    db.commit()
