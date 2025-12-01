import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Dict, Optional

from app.database.database import get_db
from app.models import Product
from app.ml.forecast_service import ForecastService
from app.ml.interpretability import ForecastInterpreter

logger = logging.getLogger("bakezy.forecast.explain")

router = APIRouter(
    prefix="/forecast",
    tags=["forecast"],
)


class ForecastComponentOut(BaseModel):
    date: str
    trend: float
    weekly_seasonality: float
    daily_seasonality: float
    regressor_contributions: Dict[str, float]
    total_forecast: float


class TopDriverOut(BaseModel):
    feature: str
    importance: float


class ForecastExplanationOut(BaseModel):
    product_id: int
    product_name: str
    forecast_points: List[ForecastComponentOut]
    feature_importance: Dict[str, float]
    top_drivers: List[TopDriverOut]
    model_type: str


@router.get(
    "/product/{product_id}/explain",
    response_model=ForecastExplanationOut,
    status_code=status.HTTP_200_OK,
)
def explain_forecast(
    product_id: int,
    horizon_days: int = 14,
    db: Session = Depends(get_db),
):
    """
    Generate forecast explanation with component breakdown.

    Shows what's driving the forecast: trend, seasonality, and regressor contributions.
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    try:
        # Generate forecast
        forecast_service = ForecastService()
        forecast_result = forecast_service.generate_prophet_forecast_for_product(
            db=db,
            product_id=product_id,
            horizon_days=horizon_days,
        )

        # Get the trained model to extract components
        # We need to access the model from the forecaster
        # For now, we'll regenerate to get the model
        # In a production system, you'd cache the model
        from app.ml.forecaster import ProductForecaster
        from app.ml.trainer import ModelTrainer

        # Load data and train model to get access to it
        product, raw_records = forecast_service._load_sales_for_product(db, product_id)
        cleaned_ts = forecast_service.preprocessor.preprocess(
            records=raw_records,
            product_id=product_id,
            shelf_life_days=getattr(product, "shelf_life_days", 1) or 1,
        )

        # Load feature data
        import pandas as pd
        from datetime import timedelta
        df = cleaned_ts.df.copy()
        df["ds"] = pd.to_datetime(df["ds"])
        start_date = df["ds"].min().date()
        end_date = df["ds"].max().date() + timedelta(days=horizon_days)

        holidays_df, weather_df, promotions_df, events_df = forecast_service._load_feature_data(
            db, product, start_date, end_date
        )

        product_info = {
            "category": product.category,
            "shelf_life_days": getattr(product, "shelf_life_days", 1) or 1,
            "price": product.price,
            "cost_per_unit": product.cost_per_unit,
        }

        # Apply feature engineering
        df = forecast_service.feature_engineer.transform(
            df,
            holidays_df=holidays_df,
            weather_df=weather_df,
            promotions_df=promotions_df,
            events_df=events_df,
            product_info=product_info,
        )
        cleaned_ts.df = df

        # Train model to get access to it
        trainer = ModelTrainer(feature_engineer=forecast_service.feature_engineer)
        train_result = trainer.train(
            cleaned_ts,
            model_name="prophet",
            holidays_df=holidays_df,
            weather_df=weather_df,
            promotions_df=promotions_df,
            events_df=events_df,
            product_info=product_info,
        )

        # Generate full forecast with components
        if train_result.model_name == "prophet":
            historical_delivery = None
            if "delivery" in cleaned_ts.df.columns:
                historical_delivery = cleaned_ts.df["delivery"]

            # Generate future regressors
            last_date = cleaned_ts.df["ds"].max()
            future_dates = pd.date_range(
                start=last_date + timedelta(days=1),
                periods=horizon_days,
                freq="D",
            )
            future_df = pd.DataFrame({"ds": future_dates})
            future_df = forecast_service.feature_engineer.transform(
                future_df,
                holidays_df=holidays_df,
                weather_df=weather_df,
                promotions_df=promotions_df,
                events_df=events_df,
                product_info=product_info,
            )

            # Fill lag features
            if "lag_1" in cleaned_ts.df.columns:
                last_y = cleaned_ts.df["y"].iloc[-1] if len(cleaned_ts.df) > 0 else 0.0
                future_df["lag_1"] = last_y
            for col in ["rolling_mean_7", "rolling_mean_30", "rolling_std_7", "rolling_std_30"]:
                if col in cleaned_ts.df.columns:
                    last_val = cleaned_ts.df[col].iloc[-1] if len(cleaned_ts.df) > 0 else 0.0
                    future_df[col] = last_val

            full_forecast_df = train_result.model.predict(
                horizon_days,
                historical_delivery=historical_delivery,
                future_regressors=future_df,
            )

            # Extract explanation
            explanation = ForecastInterpreter.explain_prophet_forecast(
                model=train_result.model.model,  # ProphetSalesModel.model is the Prophet instance
                forecast_df=full_forecast_df[full_forecast_df["ds"] > last_date],
                product_id=product_id,
            )

            # Get top drivers and convert to list of dicts for JSON serialization
            top_drivers_tuples = ForecastInterpreter.get_top_drivers(explanation, top_n=5)
            top_drivers = [{"feature": name, "importance": importance} for name, importance in top_drivers_tuples]

            # Convert to output format
            forecast_points_out = [
                ForecastComponentOut(
                    date=comp.date,
                    trend=comp.trend,
                    weekly_seasonality=comp.weekly_seasonality,
                    daily_seasonality=comp.daily_seasonality,
                    regressor_contributions=comp.regressor_contributions,
                    total_forecast=comp.total_forecast,
                )
                for comp in explanation.forecast_points
            ]

            return ForecastExplanationOut(
                product_id=product_id,
                product_name=product.name,
                forecast_points=forecast_points_out,
                feature_importance=explanation.feature_importance,
                top_drivers=top_drivers,
                model_type=explanation.model_type,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Forecast explanation only available for Prophet model",
            )

    except Exception as e:
        logger.exception("Error explaining forecast for product_id=%d", product_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating forecast explanation: {str(e)}",
        ) from e

