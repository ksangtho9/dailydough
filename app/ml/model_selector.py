from __future__ import annotations

from typing import Literal, Optional
import logging

import pandas as pd
import numpy as np

from .preprocessing import CleanedTimeSeries
from .trainer import ModelTrainer
from .hyperparameter_optimization import (
    optimize_prophet_hyperparameters,
    optimize_xgboost_hyperparameters,
    time_series_cv_splits,
)
from .metrics import calculate_wape

logger = logging.getLogger("bakezy.model_selector")

ModelName = Literal["prophet", "xgboost", "ensemble"]


class ModelSelector:
    """
    Automatically selects the best model for a product based on:
    - Data characteristics (amount of history, seasonality strength, volatility)
    - Historical performance metrics
    - Product type (high volatility vs stable)
    """
    
    def __init__(self):
        self.trainer = ModelTrainer()
    
    def analyze_data_characteristics(self, ts: CleanedTimeSeries) -> dict:
        """
        Analyze time series characteristics to inform model selection.
        
        Returns:
            Dictionary with characteristics:
            - days_of_data: Number of days of historical data
            - has_seasonality: Whether strong seasonality is detected
            - volatility: Coefficient of variation
            - trend_strength: Strength of trend (if any)
            - spike_frequency: Frequency of spikes
        """
        df = ts.df.copy()
        df["ds"] = pd.to_datetime(df["ds"])
        
        if "y" not in df.columns or len(df) == 0:
            return {
                "days_of_data": 0,
                "has_seasonality": False,
                "volatility": 0.0,
                "trend_strength": 0.0,
                "spike_frequency": 0.0,
            }
        
        values = df["y"].values
        
        # Days of data
        date_range = df["ds"].max() - df["ds"].min()
        days_of_data = date_range.days
        
        # Volatility (coefficient of variation)
        mean_val = np.mean(values)
        std_val = np.std(values)
        volatility = std_val / mean_val if mean_val > 0 else 0.0
        
        # Seasonality detection (check for weekly patterns)
        if len(values) >= 14:
            # Calculate day-of-week averages
            df["dow"] = df["ds"].dt.dayofweek
            dow_means = df.groupby("dow")["y"].mean()
            dow_std = dow_means.std()
            dow_mean = dow_means.mean()
            # Strong seasonality if day-of-week variation is >20% of mean
            has_seasonality = (dow_std / dow_mean > 0.2) if dow_mean > 0 else False
        else:
            has_seasonality = False
        
        # Trend strength (simple linear regression slope normalized by mean)
        if len(values) >= 7:
            x = np.arange(len(values))
            slope = np.polyfit(x, values, 1)[0]
            trend_strength = abs(slope) / mean_val if mean_val > 0 else 0.0
        else:
            trend_strength = 0.0
        
        # Spike frequency
        if "is_spike" in df.columns:
            spike_frequency = df["is_spike"].sum() / len(df)
        else:
            # Estimate based on outliers
            q1 = np.percentile(values, 25)
            q3 = np.percentile(values, 75)
            iqr = q3 - q1
            outliers = ((values < q1 - 1.5 * iqr) | (values > q3 + 1.5 * iqr)).sum()
            spike_frequency = outliers / len(values) if len(values) > 0 else 0.0
        
        return {
            "days_of_data": days_of_data,
            "has_seasonality": has_seasonality,
            "volatility": volatility,
            "trend_strength": trend_strength,
            "spike_frequency": spike_frequency,
        }
    
    def evaluate_model_performance(
        self,
        ts: CleanedTimeSeries,
        model_name: ModelName,
        holidays_df: Optional[pd.DataFrame] = None,
        weather_df: Optional[pd.DataFrame] = None,
        promotions_df: Optional[pd.DataFrame] = None,
        events_df: Optional[pd.DataFrame] = None,
        product_info: Optional[dict] = None,
        n_splits: int = 3,
    ) -> Optional[float]:
        """
        Evaluate model performance using cross-validation.
        
        Returns:
            Average WAPE across CV folds, or None if evaluation fails
        """
        try:
            df = ts.df.copy()
            df["ds"] = pd.to_datetime(df["ds"])
            
            # Feature engineering
            df = self.trainer.feature_engineer.transform(
                df,
                holidays_df=holidays_df,
                weather_df=weather_df,
                promotions_df=promotions_df,
                events_df=events_df,
                product_info=product_info,
            )
            
            # Generate CV splits
            cv_splits = time_series_cv_splits(df, n_splits=n_splits, test_size=14, gap=0)
            
            if not cv_splits:
                return None
            
            wapes = []
            
            for train_idx, test_idx in cv_splits:
                try:
                    train_df = df.iloc[train_idx].copy()
                    test_df = df.iloc[test_idx].copy()
                    
                    # Create training time series
                    train_ts = CleanedTimeSeries(
                        product_id=ts.product_id,
                        df=train_df,
                        shelf_life_days=ts.shelf_life_days,
                    )
                    
                    # Train model
                    train_result = self.trainer.train(
                        train_ts,
                        model_name=model_name,
                        holidays_df=holidays_df,
                        weather_df=weather_df,
                        promotions_df=promotions_df,
                        events_df=events_df,
                        product_info=product_info,
                        optimize_with_wape=False,  # Fast evaluation
                    )
                    
                    # Predict on test set
                    if model_name == "prophet":
                        horizon = len(test_df)
                        historical_delivery = None
                        if "delivery" in train_df.columns:
                            historical_delivery = train_df["delivery"]
                        forecast_df = train_result.model.predict(horizon, historical_delivery=historical_delivery)
                        # Get only future rows
                        last_train_date = train_df["ds"].max()
                        forecast_df = forecast_df[forecast_df["ds"] > last_train_date]
                        
                    elif model_name == "xgboost":
                        from app.ml.features import FeatureEngineer
                        feature_engineer = FeatureEngineer()
                        future_df = test_df[["ds"]].copy()
                        future_df = feature_engineer.transform(
                            future_df,
                            holidays_df=holidays_df,
                            weather_df=weather_df,
                            promotions_df=promotions_df,
                            events_df=events_df,
                            product_info=product_info,
                        )
                        forecast_df = train_result.model.predict_future(
                            historical_df=train_df,
                            future_df=future_df,
                            feature_engineer=feature_engineer,
                            holidays_df=holidays_df,
                            weather_df=weather_df,
                            promotions_df=promotions_df,
                            events_df=events_df,
                            product_info=product_info,
                        )
                    elif model_name == "ensemble":
                        from app.ml.features import FeatureEngineer
                        feature_engineer = FeatureEngineer()
                        future_df = test_df[["ds"]].copy()
                        future_df = feature_engineer.transform(
                            future_df,
                            holidays_df=holidays_df,
                            weather_df=weather_df,
                            promotions_df=promotions_df,
                            events_df=events_df,
                            product_info=product_info,
                        )
                        historical_delivery = None
                        if "delivery" in train_df.columns:
                            historical_delivery = train_df["delivery"]
                        forecast_df = train_result.model.predict(
                            historical_df=train_df,
                            future_df=future_df,
                            horizon_days=len(test_df),
                            holidays_df=holidays_df,
                            weather_df=weather_df,
                            promotions_df=promotions_df,
                            events_df=events_df,
                            product_info=product_info,
                            future_regressors=future_df,
                            historical_delivery=historical_delivery,
                        )
                    else:
                        continue
                    
                    # Merge with actuals
                    forecast_df["ds"] = pd.to_datetime(forecast_df["ds"])
                    test_df["ds"] = pd.to_datetime(test_df["ds"])
                    merged = forecast_df.merge(test_df[["ds", "y"]], on="ds", how="inner")
                    
                    if len(merged) == 0:
                        continue
                    
                    # Calculate WAPE
                    actual = merged["y"].values
                    predicted = merged["yhat"].values
                    
                    # Ensure numeric types
                    actual = pd.to_numeric(actual, errors='coerce')
                    predicted = pd.to_numeric(predicted, errors='coerce')
                    
                    wape = calculate_wape(actual, predicted)
                    
                    # Safe NaN check using pandas
                    if wape is not None and pd.notna(wape):
                        try:
                            wapes.append(float(wape))
                        except (ValueError, TypeError):
                            pass
                        
                except Exception as e:
                    logger.warning(f"Error in CV fold for {model_name}: {e}")
                    continue
            
            if wapes:
                return np.mean(wapes)
            else:
                return None
                
        except Exception as e:
            logger.warning(f"Error evaluating {model_name}: {e}")
            return None
    
    def select_best_model(
        self,
        ts: CleanedTimeSeries,
        holidays_df: Optional[pd.DataFrame] = None,
        weather_df: Optional[pd.DataFrame] = None,
        promotions_df: Optional[pd.DataFrame] = None,
        events_df: Optional[pd.DataFrame] = None,
        product_info: Optional[dict] = None,
        evaluate_all: bool = True,
    ) -> ModelName:
        """
        Select the best model for a given time series.
        
        Args:
            ts: CleanedTimeSeries to analyze
            holidays_df: Optional holidays DataFrame
            weather_df: Optional weather DataFrame
            promotions_df: Optional promotions DataFrame
            events_df: Optional events DataFrame
            product_info: Optional product metadata
            evaluate_all: If True, evaluate all models. If False, use heuristics only.
            
        Returns:
            Best model name
        """
        # Analyze data characteristics
        characteristics = self.analyze_data_characteristics(ts)
        
        logger.info(
            f"Data characteristics for product {ts.product_id}: "
            f"days={characteristics['days_of_data']}, "
            f"seasonality={characteristics['has_seasonality']}, "
            f"volatility={characteristics['volatility']:.2f}"
        )
        
        # Heuristic-based selection for quick decisions
        if not evaluate_all:
            # Use heuristics
            if characteristics["days_of_data"] < 60:
                # Not enough data for complex models
                return "prophet"
            elif characteristics["has_seasonality"] and characteristics["days_of_data"] > 365:
                # Strong seasonality with enough data - Prophet excels
                return "prophet"
            elif characteristics["volatility"] > 0.5 and characteristics["spike_frequency"] > 0.1:
                # High volatility and spikes - XGBoost may handle better
                return "xgboost"
            elif characteristics["days_of_data"] > 180:
                # Enough data for ensemble
                return "ensemble"
            else:
                return "prophet"
        
        # Evaluate all models
        models_to_evaluate = ["prophet", "xgboost"]
        
        # Only evaluate ensemble if we have enough data
        if characteristics["days_of_data"] > 90:
            models_to_evaluate.append("ensemble")
        
        best_model = "prophet"  # Default
        best_wape = float("inf")
        
        for model_name in models_to_evaluate:
            logger.info(f"Evaluating {model_name} for product {ts.product_id}")
            wape = self.evaluate_model_performance(
                ts=ts,
                model_name=model_name,
                holidays_df=holidays_df,
                weather_df=weather_df,
                promotions_df=promotions_df,
                events_df=events_df,
                product_info=product_info,
                n_splits=2,  # Use fewer splits for faster evaluation
            )
            
            if wape is not None and wape < best_wape:
                best_wape = wape
                best_model = model_name
                logger.info(f"{model_name} WAPE: {wape:.4f} (new best)")
            elif wape is not None:
                logger.info(f"{model_name} WAPE: {wape:.4f}")
        
        logger.info(f"Selected {best_model} for product {ts.product_id} (WAPE: {best_wape:.4f})")
        return best_model

