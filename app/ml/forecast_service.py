from __future__ import annotations

import logging
import os
from pathlib import Path


from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from datetime import date, datetime, timedelta, timezone
from sqlalchemy.orm import Session
import pandas as pd
import numpy as np

from app.models import SalesRecord, Product, Event, Promotion, WeatherData
from app.services.profit_calculator import ProfitCalculator
try:
    from app.services.production_optimizer import ProductionOptimizer
    HAS_PRODUCTION_OPTIMIZER = True
except ImportError:
    HAS_PRODUCTION_OPTIMIZER = False
    ProductionOptimizer = None  # type: ignore
from .preprocessing import SalesPreprocessor, RawSalesRecord
from .forecaster import ProductForecaster, ForecastResult
from .features import FeatureEngineer
from .spike_detector import SpikeConfig

# ---------- Logging setup for forecasting ----------

LOG_DIR = Path("logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)  # ensure logs/ exists

LOG_FILE = LOG_DIR / "forecast.log"

logger = logging.getLogger("bakezy.forecast")

if not logger.handlers:
    logger.setLevel(logging.INFO)
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)


@dataclass
class ForecastPoint:
    """Single forecasted point for a given date."""
    date: str          # ISO date string, e.g. "2025-01-01"
    yhat: float        # point forecast
    yhat_lower: float  # lower bound
    yhat_upper: float  # upper bound
    # Profit metrics (optional - only included if product has price/cost)
    revenue: float | None = None
    cost: float | None = None
    waste_cost: float | None = None
    profit: float | None = None
    waste_quantity: float | None = None
    # Cost-optimized production recommendation
    optimal_quantity: float | None = None
    expected_stockout_cost: float | None = None
    expected_waste_cost: float | None = None
    expected_total_cost: float | None = None
    # Spike prediction
    is_predicted_spike: bool = False
    spike_probability: float | None = None
    spike_magnitude: float | None = None
    spike_confidence: float | None = None


@dataclass
class ProductForecast:
    """DTO (data transfer object) that the API can easily return as JSON later."""
    product_id: int
    product_name: str
    horizon_days: int
    points: List[ForecastPoint]


class ForecastService:
    """
    High-level service that connects:
    - DB (SalesRecord)
    - preprocessing
    - Prophet forecaster
    """

    # ------------------------------------------------------------------
    # Simple in-process forecast cache
    #
    # This keeps recently computed forecasts in memory so that repeated
    # calls for the same product / horizon can be served instantly
    # without re-running the full Prophet / cmdstanpy pipeline.
    #
    # Cache key:
    #   (product_id, bakery_id, horizon_days, last_trained_at_iso)
    #
    # We include `last_trained_at` so that whenever a model is retrained
    # (or metrics are updated), the cache automatically invalidates.
    # ------------------------------------------------------------------

    # Max age for cache entries in seconds (default: 1 hour)
    _CACHE_TTL_SECONDS: int = 60 * 60
    # Soft limit on number of entries; if exceeded we evict the oldest.
    _CACHE_MAX_ENTRIES: int = 512
    # Internal cache storage
    _forecast_cache: Dict[
        Tuple[int, int, int, Optional[str]],
        Tuple[datetime, "ProductForecast"],
    ] = {}

    def __init__(self):
        # Enable spike detection by default
        spike_config = SpikeConfig()
        self.preprocessor = SalesPreprocessor(spike_config=spike_config)
        self.feature_engineer = FeatureEngineer()
        self.forecaster = ProductForecaster()
    
    def _predict_spikes(
        self,
        historical_df: pd.DataFrame,
        forecast_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Predict spikes for forecast dates based on historical patterns.
        
        Args:
            historical_df: Historical data with spike information
            forecast_df: Future dates to predict spikes for
            
        Returns:
            DataFrame with spike predictions added
        """
        forecast_df = forecast_df.copy()
        
        # Initialize spike prediction columns
        forecast_df["is_predicted_spike"] = False
        forecast_df["spike_probability"] = 0.0
        forecast_df["spike_magnitude"] = 0.0
        forecast_df["spike_confidence"] = 0.0
        
        if historical_df.empty or "is_spike" not in historical_df.columns:
            return forecast_df
        
        # Analyze historical spike patterns
        spike_mask = historical_df["is_spike"] == 1
        historical_spikes = historical_df[spike_mask]
        
        if len(historical_spikes) == 0:
            return forecast_df
        
        # Calculate historical spike statistics
        spike_values = historical_spikes["y_original"] if "y_original" in historical_spikes.columns else historical_spikes["y"]
        avg_spike_magnitude = spike_values.mean() if len(spike_values) > 0 else 0.0
        baseline_mean = historical_df["y"].mean() if len(historical_df) > 0 else 0.0
        
        # Calculate spike probability by day of week
        historical_df["dow"] = pd.to_datetime(historical_df["ds"]).dt.dayofweek
        spike_by_dow = historical_df[spike_mask].groupby("dow").size() / historical_df.groupby("dow").size()
        spike_by_dow = spike_by_dow.fillna(0.0)
        
        # Calculate spike probability by month
        historical_df["month"] = pd.to_datetime(historical_df["ds"]).dt.month
        spike_by_month = historical_df[spike_mask].groupby("month").size() / historical_df.groupby("month").size()
        spike_by_month = spike_by_month.fillna(0.0)
        
        # Calculate proximity to events/promotions (if available)
        event_proximity_factor = 1.0
        if "is_event" in historical_df.columns or "is_promotion" in historical_df.columns:
            event_spikes = historical_df[
                ((historical_df.get("is_event", 0) == 1) | (historical_df.get("is_promotion", 0) == 1)) & spike_mask
            ]
            if len(event_spikes) > 0:
                event_spike_rate = len(event_spikes) / len(historical_df[
                    (historical_df.get("is_event", 0) == 1) | (historical_df.get("is_promotion", 0) == 1)
                ])
                event_proximity_factor = event_spike_rate if event_spike_rate > 0 else 1.0
        
        # Predict spikes for each forecast date
        for idx, row in forecast_df.iterrows():
            forecast_date = pd.to_datetime(row["ds"])
            dow = forecast_date.dayofweek
            month = forecast_date.month
            
            # Base probability from day of week
            dow_prob = spike_by_dow.get(dow, 0.0)
            
            # Month adjustment
            month_prob = spike_by_month.get(month, 0.0)
            
            # Combined probability
            base_prob = (dow_prob + month_prob) / 2.0 if (dow_prob > 0 or month_prob > 0) else 0.0
            
            # Check if there's an event/promotion on this date
            if "is_event" in forecast_df.columns and row.get("is_event", 0) == 1:
                base_prob = max(base_prob, event_proximity_factor * 0.3)  # Boost probability if event
            if "is_promotion" in forecast_df.columns and row.get("is_promotion", 0) == 1:
                base_prob = max(base_prob, event_proximity_factor * 0.3)  # Boost probability if promotion
            
            # Use spike_probability from features if available
            if "spike_probability" in row and pd.notna(row["spike_probability"]):
                feature_prob = float(row["spike_probability"])
                base_prob = max(base_prob, feature_prob)
            
            # Calculate spike magnitude (relative to baseline)
            if baseline_mean > 0:
                magnitude_multiplier = avg_spike_magnitude / baseline_mean if baseline_mean > 0 else 1.5
                predicted_magnitude = baseline_mean * magnitude_multiplier
            else:
                predicted_magnitude = avg_spike_magnitude
            
            # Confidence based on historical data quality
            confidence = min(1.0, len(historical_spikes) / 10.0)  # More spikes = higher confidence, cap at 1.0
            
            # Threshold for considering it a predicted spike
            is_spike = base_prob > 0.2  # 20% threshold
            
            forecast_df.loc[idx, "is_predicted_spike"] = is_spike
            forecast_df.loc[idx, "spike_probability"] = round(base_prob, 3)
            forecast_df.loc[idx, "spike_magnitude"] = round(predicted_magnitude, 2) if is_spike else 0.0
            forecast_df.loc[idx, "spike_confidence"] = round(confidence, 3)
        
        return forecast_df

    def _load_sales_for_product(
        self,
        db: Session,
        product_id: int,
    ) -> tuple[Product, list[RawSalesRecord]]:
        """
        Load raw SalesRecord rows from the DB and convert to RawSalesRecord list.
        """
        product = db.query(Product).filter(Product.id == product_id).first()
        if product is None:
            logger.warning(f"Forecast failed: product_id={product_id} not found")
            raise ValueError("Product not found")

        # Load sales records for this product.
        #
        # We *prefer* filtering by both product_id and bakery_id to enforce bakery
        # isolation. However, some historical imports may have inconsistent
        # bakery_id values on SalesRecord rows (for example, if data was migrated
        # before bakery support was added). In those cases we fall back to
        # product_id-only filtering so that genuine historical data is not
        # mistakenly treated as “no sales”.
        sales_query = (
            db.query(SalesRecord)
            .filter(
                SalesRecord.product_id == product_id,
                SalesRecord.bakery_id == product.bakery_id,
            )
            .order_by(SalesRecord.date.asc())
        )
        sales_rows = sales_query.all()

        if not sales_rows:
            # Fallback: re-query by product_id only. We log this so we can
            # diagnose any data-quality issues while still serving forecasts.
            logger.warning(
                "No sales rows found for product_id=%d with bakery_id=%d; "
                "falling back to product_id-only sales lookup",
                product_id,
                product.bakery_id,
            )
            sales_rows = (
                db.query(SalesRecord)
                .filter(SalesRecord.product_id == product_id)
                .order_by(SalesRecord.date.asc())
                .all()
            )

        if not sales_rows:
            logger.warning(
                f"Forecast failed: no sales data for product_id={product_id}"
            )
            raise ValueError("No sales data for this product")

        raw_records: list[RawSalesRecord] = [
            RawSalesRecord(
                date=row.date,
                product_id=row.product_id,
                quantity=row.quantity_sold,
                quantity_delivered=row.quantity_delivered,
            )
            for row in sales_rows
        ]
        logger.info(
            "Loaded %d sales records for product_id=%d (from %s to %s)",
            len(raw_records),
            product_id,
            raw_records[0].date.isoformat(),
            raw_records[-1].date.isoformat(),
        )

        return product, raw_records

    def _load_feature_data(
        self,
        db: Session,
        product: Product,
        start_date: date,
        end_date: date,
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """
        Load feature data (holidays, weather, promotions, events) for date range.

        Returns:
            Tuple of (holidays_df, weather_df, promotions_df, events_df)
        """
        bakery_id = product.bakery_id

        # Load events
        events_rows = (
            db.query(Event)
            .filter(
                Event.bakery_id == bakery_id,
                Event.date >= start_date,
                Event.date <= end_date,
            )
            .all()
        )
        events_data = []
        for event in events_rows:
            events_data.append({
                "ds": event.date,
                "is_event": 1,
                "sales_multiplier": float(event.sales_multiplier) if event.sales_multiplier else 1.0,
            })
        events_df = pd.DataFrame(events_data) if events_data else pd.DataFrame(columns=["ds", "is_event", "sales_multiplier"])

        # Load promotions
        promotions_rows = (
            db.query(Promotion)
            .filter(
                Promotion.bakery_id == bakery_id,
                Promotion.is_active == True,
                Promotion.start_date <= end_date,
                Promotion.end_date >= start_date,
            )
            .all()
        )
        promotions_data = []
        for promo in promotions_rows:
            # Check if promotion applies to this product (or all products)
            if promo.product_id is None or promo.product_id == product.id:
                # Generate dates in the promotion range that overlap with our date range
                promo_start = max(promo.start_date, start_date)
                promo_end = min(promo.end_date, end_date)
                current_date = promo_start
                while current_date <= promo_end:
                    promotions_data.append({
                        "ds": current_date,
                        "product_id": product.id,
                        "is_promotion": 1,
                        "sales_multiplier": promo.sales_multiplier or 1.0,
                    })
                    current_date += timedelta(days=1)
        promotions_df = pd.DataFrame(promotions_data) if promotions_data else pd.DataFrame(columns=["ds", "product_id", "is_promotion", "sales_multiplier"])

        # Load weather data
        weather_rows = (
            db.query(WeatherData)
            .filter(
                WeatherData.bakery_id == bakery_id,
                WeatherData.date >= start_date,
                WeatherData.date <= end_date,
            )
            .all()
        )
        weather_data = []
        for weather in weather_rows:
            weather_data.append({
                "ds": weather.date,
                "temperature": weather.temperature,
                "precipitation": weather.precipitation or 0.0,
                "condition": weather.condition,
            })
        weather_df = pd.DataFrame(weather_data) if weather_data else pd.DataFrame(columns=["ds", "temperature", "precipitation", "condition"])

        # Generate US holidays (using a simple approach - can be enhanced)
        holidays_data = []
        try:
            import holidays
            us_holidays = holidays.UnitedStates(years=range(start_date.year, end_date.year + 2))
            current_date = start_date
            while current_date <= end_date:
                if current_date in us_holidays:
                    holidays_data.append({
                        "ds": current_date,
                        "is_holiday": 1,
                        "holiday_name": us_holidays[current_date],
                    })
                current_date += timedelta(days=1)
        except ImportError:
            logger.warning("holidays library not installed, skipping US holidays")
        holidays_df = pd.DataFrame(holidays_data) if holidays_data else pd.DataFrame(columns=["ds", "is_holiday", "holiday_name"])

        return holidays_df, weather_df, promotions_df, events_df

    def generate_prophet_forecast_for_product(
        self,
        db: Session,
        product_id: int,
        horizon_days: int = 14,
    ) -> ProductForecast:
        """
        Main entrypoint for forecasting.
        
        Uses ALL available historical data for maximum model accuracy.
        
        Args:
            db: Database session
            product_id: Product ID to forecast
            horizon_days: Number of days to forecast ahead
        """
        logger.info(
            "Starting forecast: product_id=%d horizon_days=%d",
            product_id,
            horizon_days,
        )

        # 0) Load raw sales from DB (and product meta for cache key)
        product, raw_records = self._load_sales_for_product(db, product_id)

        # Build a cache key that is stable for a given product / bakery /
        # horizon and invalidates automatically when the model is
        # retrained (via ForecastMetrics.last_trained_at).
        last_trained_at_iso: Optional[str] = None
        try:
            metrics = getattr(product, "forecast_metrics", None)
            if metrics is not None and getattr(metrics, "last_trained_at", None) is not None:
                # Normalise to an ISO string so it is hashable and stable
                last_trained_at_iso = metrics.last_trained_at.isoformat()
        except Exception:
            # If anything goes wrong while reading metrics, we simply
            # skip the cache key extension; correctness matters more
            # than caching in this edge case.
            last_trained_at_iso = None

        cache_key: Tuple[int, int, int, Optional[str]] = (
            product.id,
            getattr(product, "bakery_id", 0) or 0,
            int(horizon_days),
            last_trained_at_iso,
        )

        # Look for a fresh cached forecast
        now = datetime.now(timezone.utc)
        cached = self._forecast_cache.get(cache_key)
        if cached is not None:
            created_at, cached_forecast = cached
            age_seconds = (now - created_at).total_seconds()
            if age_seconds <= self._CACHE_TTL_SECONDS:
                logger.info(
                    "Forecast cache hit: product_id=%d bakery_id=%d horizon_days=%d age=%.1fs",
                    product.id,
                    getattr(product, "bakery_id", 0) or 0,
                    horizon_days,
                    age_seconds,
                )
                return cached_forecast
            else:
                # Expired entry – remove it so the cache doesn't grow without bound.
                self._forecast_cache.pop(cache_key, None)

        logger.info(
            "Forecast cache miss: product_id=%d bakery_id=%d horizon_days=%d last_trained_at=%s",
            product.id,
            getattr(product, "bakery_id", 0) or 0,
            horizon_days,
            last_trained_at_iso,
        )

        # 2) Preprocess → CleanedTimeSeries (fill missing days, sort, etc.)
        cleaned_ts = self.preprocessor.preprocess(
            records=raw_records,
            product_id=product_id,
            shelf_life_days=getattr(product, "shelf_life_days", 1) or 1,
        )

        # 2.5) Load feature data
        df = cleaned_ts.df.copy()
        df["ds"] = pd.to_datetime(df["ds"])
        start_date = df["ds"].min().date()
        end_date = df["ds"].max().date() + timedelta(days=horizon_days)

        holidays_df, weather_df, promotions_df, events_df = self._load_feature_data(
            db, product, start_date, end_date
        )

        # 2.6) Prepare product info
        product_info = {
            "category": product.category,
            "shelf_life_days": getattr(product, "shelf_life_days", 1) or 1,
            "price": product.price,
            "cost_per_unit": product.cost_per_unit,
        }

        # 2.7) Apply feature engineering to historical data
        df = self.feature_engineer.transform(
            df,
            holidays_df=holidays_df,
            weather_df=weather_df,
            promotions_df=promotions_df,
            events_df=events_df,
            product_info=product_info,
        )

        # Update cleaned_ts with enhanced features
        # All historical data is used for maximum model accuracy
        cleaned_ts.df = df

        # 2.8) Generate future regressor values for forecast period
        last_date = df["ds"].max()
        future_dates = pd.date_range(
            start=last_date + timedelta(days=1),
            periods=horizon_days,
            freq="D",
        )
        future_df = pd.DataFrame({"ds": future_dates})

        # Apply feature engineering to future dates
        future_df = self.feature_engineer.transform(
            future_df,
            holidays_df=holidays_df,
            weather_df=weather_df,
            promotions_df=promotions_df,
            events_df=events_df,
            product_info=product_info,
        )

        # Fill lag features with last known values or rolling means
        # Ensure all values are numeric
        if "lag_1" in df.columns:
            last_y = pd.to_numeric(df["y"].iloc[-1], errors='coerce') if len(df) > 0 else 0.0
            future_df["lag_1"] = float(last_y) if pd.notna(last_y) else 0.0
        if "lag_7" in df.columns:
            y_series = pd.to_numeric(df["y"], errors='coerce')
            last_7_avg = float(y_series.tail(7).mean()) if len(df) >= 7 else (float(y_series.mean()) if len(df) > 0 and pd.notna(y_series.mean()) else 0.0)
            future_df["lag_7"] = last_7_avg
        if "lag_14" in df.columns:
            y_series = pd.to_numeric(df["y"], errors='coerce')
            last_14_avg = float(y_series.tail(14).mean()) if len(df) >= 14 else (float(y_series.mean()) if len(df) > 0 and pd.notna(y_series.mean()) else 0.0)
            future_df["lag_14"] = last_14_avg
        if "lag_30" in df.columns:
            y_series = pd.to_numeric(df["y"], errors='coerce')
            last_30_avg = float(y_series.tail(30).mean()) if len(df) >= 30 else (float(y_series.mean()) if len(df) > 0 and pd.notna(y_series.mean()) else 0.0)
            future_df["lag_30"] = last_30_avg

        # Fill rolling features with last known values
        for col in ["rolling_mean_7", "rolling_mean_30", "rolling_std_7", "rolling_std_30"]:
            if col in df.columns:
                last_val = pd.to_numeric(df[col].iloc[-1], errors='coerce') if len(df) > 0 else 0.0
                future_df[col] = float(last_val) if pd.notna(last_val) else 0.0
        
        # Ensure all columns in future_df are numeric (except 'ds')
        # Remove any non-numeric columns that might have been added by feature engineering
        cols_to_remove = []
        for col in future_df.columns:
            if col != "ds":
                try:
                    # Try to convert to numeric
                    future_df[col] = pd.to_numeric(future_df[col], errors='coerce').fillna(0.0)
                except (ValueError, TypeError):
                    # If conversion fails, remove the column
                    cols_to_remove.append(col)
        
        # Remove non-numeric columns
        for col in cols_to_remove:
            if col in future_df.columns:
                future_df = future_df.drop(columns=[col])

        # 3) Forecast via Prophet
        forecast_result: ForecastResult = self.forecaster.forecast(
            ts=cleaned_ts,
            horizon_days=horizon_days,
            model_name="prophet",
            holidays_df=holidays_df,
            weather_df=weather_df,
            promotions_df=promotions_df,
            events_df=events_df,
            product_info=product_info,
            future_regressors=future_df,
        )

        df = forecast_result.forecast_df

        # 4) Predict spikes for forecast period
        # Use historical data with spike information for prediction
        historical_with_spikes = cleaned_ts.df.copy()
        df_future = df.copy()
        
        # Add spike predictions to forecast dataframe
        df_future = self._predict_spikes(historical_with_spikes, df_future)

        # 5) Convert Prophet output → list of ForecastPoint
        points: list[ForecastPoint] = []

        if "ds" not in df_future.columns:
            logger.error("Forecast failed: 'ds' column missing in Prophet output")
            raise RuntimeError("Prophet forecast missing 'ds' column")

        # Calculate profit metrics if product has price/cost
        has_profit_data = product.price is not None and product.cost_per_unit is not None
        
        for _, row in df_future.iterrows():
            ds_value = row["ds"]
            date_str = ds_value.date().isoformat()

            # Raw Prophet outputs - ensure numeric conversion
            try:
                yhat = float(pd.to_numeric(row["yhat"], errors='coerce')) if pd.notna(row.get("yhat")) else 0.0
                yhat_lower = max(0.0, float(pd.to_numeric(row["yhat_lower"], errors='coerce'))) if pd.notna(row.get("yhat_lower")) else 0.0
                yhat_upper = max(0.0, float(pd.to_numeric(row["yhat_upper"], errors='coerce'))) if pd.notna(row.get("yhat_upper")) else 0.0
            except (ValueError, TypeError) as e:
                logger.warning(f"Error converting forecast values to numeric: {e}")
                yhat = 0.0
                yhat_lower = 0.0
                yhat_upper = 0.0

            # Clamp non-negative
            yhat = max(0.0, yhat)

            # Round nicely
            yhat = round(yhat, 2)
            yhat_lower = round(yhat_lower, 2)
            yhat_upper = round(yhat_upper, 2)

            # Calculate profit metrics if available
            revenue = None
            cost = None
            waste_cost = None
            profit = None
            waste_quantity = None
            
            # Calculate optimal production quantity
            optimal_quantity = None
            expected_stockout_cost = None
            expected_waste_cost = None
            expected_total_cost = None
            
            if has_profit_data:
                # Use forecast quantity as production quantity (ideal scenario).
                # For multi-day shelf life products, overproduction is treated as
                # carryover rather than same-day waste in this single-day view.
                profit_metrics = ProfitCalculator.calculate_forecast_profit(
                    forecast_quantity=yhat,
                    price=product.price,
                    cost_per_unit=product.cost_per_unit,
                    production_quantity=yhat,  # Produce exactly what we forecast
                    shelf_life_days=getattr(product, "shelf_life_days", 1) or 1,
                )
                revenue = round(profit_metrics.revenue, 2)
                cost = round(profit_metrics.cost, 2)
                waste_cost = round(profit_metrics.waste_cost, 2)
                profit = round(profit_metrics.profit, 2)
                waste_quantity = round(profit_metrics.waste_quantity, 2)
                
                # Calculate cost-optimized production quantity
                optimal_quantity = None
                expected_stockout_cost = None
                expected_waste_cost = None
                expected_total_cost = None
                
                if HAS_PRODUCTION_OPTIMIZER and ProductionOptimizer is not None:
                    try:
                        stockout_cost_ratio = getattr(product, "stockout_cost_ratio", 2.0) or 2.0
                        shelf_life_days = getattr(product, "shelf_life_days", 1) or 1
                        
                        optimization_result = ProductionOptimizer.optimize_production_quantity(
                            forecast_p50=yhat,
                            forecast_p10=yhat_lower,
                            forecast_p90=yhat_upper,
                            price=product.price,
                            cost_per_unit=product.cost_per_unit,
                            stockout_cost_ratio=stockout_cost_ratio,
                            shelf_life_days=shelf_life_days,
                        )
                        
                        optimal_quantity = round(optimization_result.optimal_quantity, 2)
                        expected_stockout_cost = round(optimization_result.expected_stockout_cost, 2)
                        expected_waste_cost = round(optimization_result.expected_waste_cost, 2)
                        expected_total_cost = round(optimization_result.expected_total_cost, 2)
                    except Exception as e:
                        # If optimization fails, log but don't break the forecast
                        logger.warning(
                            "Failed to calculate optimal production quantity for product_id=%d: %s",
                            product.id,
                            str(e),
                        )
            
            # Extract spike prediction information
            is_predicted_spike = bool(row.get("is_predicted_spike", False)) if "is_predicted_spike" in row.index else False
            spike_probability = None
            if "spike_probability" in row.index and pd.notna(row["spike_probability"]):
                spike_probability = float(row["spike_probability"])
            spike_magnitude = None
            if "spike_magnitude" in row.index and pd.notna(row["spike_magnitude"]):
                mag_val = float(row["spike_magnitude"])
                if mag_val > 0:
                    spike_magnitude = mag_val
            spike_confidence = None
            if "spike_confidence" in row.index and pd.notna(row["spike_confidence"]):
                spike_confidence = float(row["spike_confidence"])

            points.append(
                ForecastPoint(
                    date=date_str,
                    yhat=yhat,
                    yhat_lower=yhat_lower,
                    yhat_upper=yhat_upper,
                    revenue=revenue,
                    cost=cost,
                    waste_cost=waste_cost,
                    profit=profit,
                    waste_quantity=waste_quantity,
                    optimal_quantity=optimal_quantity,
                    expected_stockout_cost=expected_stockout_cost,
                    expected_waste_cost=expected_waste_cost,
                    expected_total_cost=expected_total_cost,
                    is_predicted_spike=is_predicted_spike,
                    spike_probability=spike_probability,
                    spike_magnitude=spike_magnitude,
                    spike_confidence=spike_confidence,
                )
            )

        logger.info(
            "Forecast complete: product_id=%d horizon_days=%d points=%d",
            product_id,
            horizon_days,
            len(points),
        )
        result = ProductForecast(
            product_id=product.id,
            product_name=product.name,
            horizon_days=horizon_days,
            points=points,
        )

        # Store in cache for subsequent requests.
        try:
            # Simple size-based eviction: if we exceed the soft limit,
            # drop the oldest entry (by created_at).
            if len(self._forecast_cache) >= self._CACHE_MAX_ENTRIES:
                oldest_key = None
                oldest_time = now
                for k, (created_at, _) in self._forecast_cache.items():
                    if created_at <= oldest_time:
                        oldest_time = created_at
                        oldest_key = k
                if oldest_key is not None:
                    self._forecast_cache.pop(oldest_key, None)

            self._forecast_cache[cache_key] = (now, result)
            logger.info(
                "Stored forecast in cache: product_id=%d bakery_id=%d horizon_days=%d",
                product.id,
                getattr(product, "bakery_id", 0) or 0,
                horizon_days,
            )
        except Exception as e:
            # Cache must never break the main forecast path.
            logger.warning(
                "Failed to store forecast in cache for product_id=%d: %s",
                product.id,
                str(e),
            )

        return result
