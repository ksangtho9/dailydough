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
import time

from app.models import SalesRecord, Product, Event, Promotion, WeatherData, ModelRun
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
    yhat: float | None  # point forecast (None if invalid/missing)
    yhat_lower: float | None  # lower bound (None if invalid/missing)
    yhat_upper: float | None  # upper bound (None if invalid/missing)
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
    # Optional fields for future stats computation (used by train_all_products.py)
    raw_yhat_values: Optional[np.ndarray] = None
    model_name: Optional[str] = None
    # Source metadata for tracing (cache|db|fresh_generate)
    source: Optional[str] = None
    forecast_run_id: Optional[str] = None


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
        forecast_run_id: Optional[str] = None,
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
        
        # Log cache key inputs
        logger.info(
            f"CACHE_KEY_INPUTS: forecast_run_id={forecast_run_id}, product_id={product.id}, "
            f"bakery_id={getattr(product, 'bakery_id', 0) or 0}, horizon_days={horizon_days}, "
            f"last_trained_at={last_trained_at_iso}, key={cache_key}"
        )

        # Look for a fresh cached forecast
        now = datetime.now(timezone.utc)
        cached = self._forecast_cache.get(cache_key)
        if cached is not None:
            created_at, cached_forecast, cached_source = cached
            age_seconds = (now - created_at).total_seconds()
            if age_seconds <= self._CACHE_TTL_SECONDS:
                # Log cache hit with values
                if cached_forecast.points:
                    first_3_yhat = [p.yhat for p in cached_forecast.points[:3]]
                    last_3_yhat = [p.yhat for p in cached_forecast.points[-3:]]
                    logger.info(
                        f"CACHE_HIT: forecast_run_id={forecast_run_id}, key={cache_key}, age_seconds={age_seconds:.1f}, "
                        f"source={cached_source}, points_count={len(cached_forecast.points)}, "
                        f"first_3_yhat={first_3_yhat}, last_3_yhat={last_3_yhat}"
                    )
                else:
                    logger.info(
                        f"CACHE_HIT: forecast_run_id={forecast_run_id}, key={cache_key}, age_seconds={age_seconds:.1f}, "
                        f"source={cached_source}, points_count=0"
                    )
                # Set source and forecast_run_id on returned forecast
                cached_forecast.source = cached_source
                cached_forecast.forecast_run_id = forecast_run_id
                return cached_forecast
            else:
                # Expired entry – remove it so the cache doesn't grow without bound.
                logger.info(
                    f"CACHE_MISS: forecast_run_id={forecast_run_id}, key={cache_key}, reason=expired, age_seconds={age_seconds:.1f}"
                )
                self._forecast_cache.pop(cache_key, None)
        
        logger.info(
            f"CACHE_MISS: forecast_run_id={forecast_run_id}, key={cache_key}, reason=not_found"
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

        # CRITICAL: Remove delivery from training data BEFORE training
        # Delivery is unknown for future dates, so we shouldn't train with it
        # This prevents Prophet from expecting delivery in future_df
        if "delivery" in df.columns:
            delivery_training = pd.to_numeric(df["delivery"], errors='coerce').dropna()
            if len(delivery_training) > 0:
                logger.info(
                    f"Removing delivery regressor from training data for product {product_id} "
                    f"(training mean: {delivery_training.mean():.2f}) - unknown for future dates"
                )
                df = df.drop(columns=["delivery"])
        
        # Update cleaned_ts with enhanced features
        # All historical data is used for maximum model accuracy
        cleaned_ts.df = df
        
        # Fix 3: Verify delivery is not in cleaned_ts.df before training
        from app.core.config import settings
        if settings.debug_zero_forecasts or (product_id is not None and product_id in settings.debug_forecast_product_ids):
            if "delivery" in cleaned_ts.df.columns:
                logger.error(
                    f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                    f"step=training_data_check, ERROR: delivery still in cleaned_ts.df!"
                )
            else:
                logger.info(
                    f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                    f"step=training_data_check, delivery correctly removed from cleaned_ts.df"
                )

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

        # CRITICAL FIX: Iterative future feature generation for lag/rolling/EWMA
        # Feature engineering doesn't create lag/rolling features for future_df (no "y" column)
        # So we need to create them manually and populate them iteratively
        
        # Ensure lag/rolling/EWMA columns exist in future_df (create if missing)
        lag_rolling_cols = ["lag_1", "lag_7", "lag_14", "lag_30",
                           "rolling_mean_7", "rolling_mean_30", "rolling_std_7", "rolling_std_30",
                           "ewma_7", "ewma_30", "ewma_7_halflife_3", "ewma_30_halflife_14"]
        for col in lag_rolling_cols:
            if col not in future_df.columns:
                future_df[col] = np.nan  # Initialize as NaN, will be filled below
        
        # Seed history series with actual training data
        y_hist = pd.to_numeric(df["y"], errors='coerce').dropna().tolist()
        if len(y_hist) == 0:
            y_hist = [0.0]  # Fallback if no valid data
        
        # For Prophet (which predicts all dates at once), we need to estimate future values
        # to compute evolving lag/rolling features. Use a simple approach:
        # - For first date: use training history
        # - For subsequent dates: use training history + estimated predictions based on trend/seasonality
        # This ensures regressors evolve rather than being constant
        
        # Compute simple trend from last 30 days for estimation
        # For new products, ensure we have a reasonable baseline to avoid all-zero features
        if len(y_hist) >= 30:
            recent_y = y_hist[-30:]
            trend_slope = (recent_y[-1] - recent_y[0]) / 30.0 if len(recent_y) > 1 else 0.0
            base_level = recent_y[-1]
        else:
            trend_slope = 0.0
            base_level = y_hist[-1] if len(y_hist) > 0 else 0.0
        
        # CRITICAL FIX: For new products with limited/zero history, use mean of non-zero values
        # This ensures lag/rolling features have variation instead of being all zero/constant
        if base_level == 0.0 and len(y_hist) > 0:
            non_zero_values = [y for y in y_hist if y > 0]
            if len(non_zero_values) > 0:
                base_level = np.mean(non_zero_values)
                logger.info(
                    f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                    f"step=baseline_adjustment, base_level was 0, using mean of non-zero values: {base_level:.2f}"
                )
            elif len(y_hist) > 0:
                # If all zeros, use a small positive baseline to ensure features vary
                # Use 1.0 as minimum to ensure lag/rolling features aren't all zero
                base_level = 1.0
                logger.info(
                    f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                    f"step=baseline_adjustment, all training values are zero, using minimum baseline: {base_level:.2f}"
                )
        
        # Iteratively generate regressors for each future date
        from app.core.config import settings
        should_log_iterative = settings.debug_zero_forecasts or (product_id is not None and product_id in settings.debug_forecast_product_ids)
        
        if should_log_iterative:
            logger.info(
                f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                f"step=iterative_generation_start, total_iterations={len(future_dates)}, "
                f"y_hist_length={len(y_hist)}, base_level={base_level:.2f}, trend_slope={trend_slope:.4f}"
            )
        
        for i, future_date in enumerate(future_dates):
            # Estimate y for this date (for computing lag/rolling)
            # Use base level + trend, clamped to non-negative
            # Add small random variation to prevent all features from being exactly constant
            # This helps Prophet when training data is limited
            estimated_y = max(0.0, base_level + trend_slope * (i + 1))
            
            # For very new products, add small variation to prevent all-zero/constant features
            # This is a heuristic to ensure lag/rolling features have some variation
            if base_level > 0 and base_level < 5.0:  # Small baseline
                # Add small day-of-week variation (0-10% variation)
                day_of_week = future_date.dayofweek
                variation_factor = 1.0 + (day_of_week % 3) * 0.05  # 0%, 5%, 10% variation
                estimated_y = estimated_y * variation_factor
            
            # Build extended history: training + estimated future values so far
            # For iterative building, we need to accumulate: [y_hist] + [est_0, est_1, ..., est_i]
            if i == 0:
                extended_y_hist = y_hist + [estimated_y]
            else:
                # Get previous estimated values from future_df if available, or use current estimate
                extended_y_hist = y_hist + [estimated_y] * (i + 1)
            
            # Enhanced debug logging for first 3 iterations
            if should_log_iterative and i < 3:
                logger.info(
                    f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                    f"step=iterative_generation, iteration={i}, "
                    f"future_date={future_date.strftime('%Y-%m-%d')}, estimated_y={estimated_y:.2f}, "
                    f"extended_y_hist_length={len(extended_y_hist)}"
                )
            
            # Compute lag features from extended history
            # Columns are guaranteed to exist (created above if missing)
            if "lag_1" in future_df.columns:
                lag_1_val = extended_y_hist[-1] if len(extended_y_hist) >= 1 else 0.0
                future_df.loc[i, "lag_1"] = lag_1_val
                # Enhanced debug logging for first 3 iterations
                if should_log_iterative and i < 3:
                    logger.info(
                        f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                        f"step=iterative_generation, iteration={i}, "
                        f"lag_1_val={lag_1_val:.6f}, set_in_future_df={future_df.loc[i, 'lag_1']:.6f}"
                    )
            
            if "lag_7" in future_df.columns:
                lag_7_val = np.mean(extended_y_hist[-7:]) if len(extended_y_hist) >= 7 else (np.mean(extended_y_hist) if len(extended_y_hist) > 0 else 0.0)
                future_df.loc[i, "lag_7"] = lag_7_val
                if should_log_iterative and i < 3:
                    logger.info(
                        f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                        f"step=iterative_generation, iteration={i}, lag_7_val={lag_7_val:.6f}"
                    )
            
            if "lag_14" in future_df.columns:
                lag_14_val = np.mean(extended_y_hist[-14:]) if len(extended_y_hist) >= 14 else (np.mean(extended_y_hist) if len(extended_y_hist) > 0 else 0.0)
                future_df.loc[i, "lag_14"] = lag_14_val
            
            if "lag_30" in future_df.columns:
                lag_30_val = np.mean(extended_y_hist[-30:]) if len(extended_y_hist) >= 30 else (np.mean(extended_y_hist) if len(extended_y_hist) > 0 else 0.0)
                future_df.loc[i, "lag_30"] = lag_30_val
            
            # Compute rolling features from extended history
            if "rolling_mean_7" in future_df.columns:
                rolling_mean_7_val = np.mean(extended_y_hist[-7:]) if len(extended_y_hist) >= 7 else (np.mean(extended_y_hist) if len(extended_y_hist) > 0 else 0.0)
                future_df.loc[i, "rolling_mean_7"] = rolling_mean_7_val
                if should_log_iterative and i < 3:
                    logger.info(
                        f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                        f"step=iterative_generation, iteration={i}, rolling_mean_7_val={rolling_mean_7_val:.6f}"
                    )
            
            if "rolling_mean_30" in future_df.columns:
                rolling_mean_30_val = np.mean(extended_y_hist[-30:]) if len(extended_y_hist) >= 30 else (np.mean(extended_y_hist) if len(extended_y_hist) > 0 else 0.0)
                future_df.loc[i, "rolling_mean_30"] = rolling_mean_30_val
                if should_log_iterative and i < 3:
                    logger.info(
                        f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                        f"step=iterative_generation, iteration={i}, rolling_mean_30_val={rolling_mean_30_val:.6f}"
                    )
            
            if "rolling_std_7" in future_df.columns:
                rolling_std_7_val = np.std(extended_y_hist[-7:]) if len(extended_y_hist) >= 7 else 0.0
                future_df.loc[i, "rolling_std_7"] = rolling_std_7_val
            
            if "rolling_std_30" in future_df.columns:
                rolling_std_30_val = np.std(extended_y_hist[-30:]) if len(extended_y_hist) >= 30 else 0.0
                future_df.loc[i, "rolling_std_30"] = rolling_std_30_val
            
            # Compute EWMA features (evolving)
            # Use halflife-based EWMA calculation (matches feature engineering)
            if "ewma_7_halflife_3" in future_df.columns:
                if len(extended_y_hist) >= 7:
                    # EWMA with halflife=3 (alpha = 1 - exp(-ln(2)/halflife))
                    halflife = 3.0
                    alpha = 1.0 - np.exp(-np.log(2.0) / halflife)
                    ewma_val = extended_y_hist[-1]
                    for val in reversed(extended_y_hist[-7:-1]):
                        ewma_val = alpha * val + (1 - alpha) * ewma_val
                else:
                    ewma_val = np.mean(extended_y_hist) if len(extended_y_hist) > 0 else 0.0
                future_df.loc[i, "ewma_7_halflife_3"] = ewma_val
            
            if "ewma_30_halflife_14" in future_df.columns:
                if len(extended_y_hist) >= 30:
                    # EWMA with halflife=14
                    halflife = 14.0
                    alpha = 1.0 - np.exp(-np.log(2.0) / halflife)
                    ewma_val = extended_y_hist[-1]
                    for val in reversed(extended_y_hist[-30:-1]):
                        ewma_val = alpha * val + (1 - alpha) * ewma_val
                else:
                    ewma_val = np.mean(extended_y_hist) if len(extended_y_hist) > 0 else 0.0
                future_df.loc[i, "ewma_30_halflife_14"] = ewma_val
            
            # Also set legacy ewma_7/ewma_30 if they exist
            if "ewma_7" in future_df.columns:
                # Use same calculation as ewma_7_halflife_3
                if len(extended_y_hist) >= 7:
                    halflife = 3.0
                    alpha = 1.0 - np.exp(-np.log(2.0) / halflife)
                    ewma_val = extended_y_hist[-1]
                    for val in reversed(extended_y_hist[-7:-1]):
                        ewma_val = alpha * val + (1 - alpha) * ewma_val
                else:
                    ewma_val = np.mean(extended_y_hist) if len(extended_y_hist) > 0 else 0.0
                future_df.loc[i, "ewma_7"] = ewma_val
            
            if "ewma_30" in future_df.columns:
                # Use same calculation as ewma_30_halflife_14
                if len(extended_y_hist) >= 30:
                    halflife = 14.0
                    alpha = 1.0 - np.exp(-np.log(2.0) / halflife)
                    ewma_val = extended_y_hist[-1]
                    for val in reversed(extended_y_hist[-30:-1]):
                        ewma_val = alpha * val + (1 - alpha) * ewma_val
                else:
                    ewma_val = np.mean(extended_y_hist) if len(extended_y_hist) > 0 else 0.0
                future_df.loc[i, "ewma_30"] = ewma_val
        
        # Enhanced logging: Log summary statistics after iterative loop completes
        if should_log_iterative:
            logger.info(
                f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                f"step=iterative_generation_complete, total_iterations={len(future_dates)}"
            )
            
            # Log summary statistics for critical lag/rolling features
            critical_features = ["lag_1", "lag_7", "rolling_mean_7", "rolling_mean_30"]
            for feat in critical_features:
                if feat in future_df.columns:
                    feat_data = pd.to_numeric(future_df[feat], errors='coerce')
                    feat_valid = feat_data.dropna()
                    nan_count = feat_data.isna().sum()
                    nan_pct = (nan_count / len(feat_data) * 100) if len(feat_data) > 0 else 0.0
                    
                    if len(feat_valid) > 0:
                        min_val = float(feat_valid.min())
                        max_val = float(feat_valid.max())
                        mean_val = float(feat_valid.mean())
                        unique_count = feat_valid.nunique()
                        is_constant = unique_count == 1
                        
                        logger.info(
                            f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                            f"step=iterative_generation_summary, feature={feat}, "
                            f"min={min_val:.6f}, max={max_val:.6f}, mean={mean_val:.6f}, "
                            f"nan_count={int(nan_count)}, nan_pct={nan_pct:.1f}%, "
                            f"unique_values={unique_count}, is_constant={is_constant}"
                        )
                    else:
                        logger.warning(
                            f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                            f"step=iterative_generation_summary, feature={feat}, "
                            f"ERROR: All values are NaN!"
                        )
        
        # Add validation after iterative loop: Check critical features
        critical_features = ["lag_1", "lag_7", "rolling_mean_7", "rolling_mean_30"]
        validation_failed = False
        for feat in critical_features:
            if feat in future_df.columns:
                feat_data = pd.to_numeric(future_df[feat], errors='coerce')
                nan_count = feat_data.isna().sum()
                nan_pct = (nan_count / len(feat_data) * 100) if len(feat_data) > 0 else 0.0
                
                if nan_pct > 50.0:  # More than 50% NaN
                    logger.warning(
                        f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                        f"step=feature_validation, WARNING: {feat} has {nan_pct:.1f}% NaN values"
                    )
                    validation_failed = True
                
                # Check if constant (all same value)
                feat_valid = feat_data.dropna()
                if len(feat_valid) > 0 and feat_valid.nunique() == 1:
                    logger.warning(
                        f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                        f"step=feature_validation, WARNING: {feat} is CONSTANT (value={feat_valid.iloc[0]:.6f})"
                    )
                    validation_failed = True
        
        if validation_failed:
            logger.warning(
                f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                f"step=feature_validation, WARNING: Some critical features failed validation. "
                f"This may cause zero forecasts."
            )
        else:
            logger.info(
                f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                f"step=feature_validation, All critical features passed validation"
            )
        
        # B) Delivery regressor handling: Remove it (unknown for future dates)
        # Delivery is a cause (supply/production plan input), not a feature we can forecast
        if "delivery" in future_df.columns:
            if "delivery" in df.columns:
                delivery_training = pd.to_numeric(df["delivery"], errors='coerce').dropna()
                if len(delivery_training) > 0:
                    # Option A: Remove from future_df (recommended)
                    future_df = future_df.drop(columns=["delivery"])
                    logger.warning(
                        f"Delivery regressor removed from future_df for product {product_id} - "
                        f"unknown for future dates (training mean: {delivery_training.mean():.2f})"
                    )
                else:
                    # Delivery was always NaN in training - remove it
                    future_df = future_df.drop(columns=["delivery"])
            else:
                # Delivery not in training - remove it
                future_df = future_df.drop(columns=["delivery"])
        
        # C) Feature-type aware NaN handling
        # For lag/rolling/EWMA: Should be computed from history, avoid NaN by design
        # For unknown future inputs: Use scenario default (median) + log warning
        # Only use 0 if the feature is structurally binary and 0 is valid
        for col in future_df.columns:
            if col != "ds":
                if col in ["lag_1", "lag_7", "lag_14", "lag_30", 
                          "rolling_mean_7", "rolling_mean_30", "rolling_std_7", "rolling_std_30",
                          "ewma_7", "ewma_30", "ewma_7_halflife_3", "ewma_30_halflife_14"]:
                    # These should be computed from history - NaN means computation failed
                    # Fill with training mean/median as fallback
                    if col in df.columns:
                        training_vals = pd.to_numeric(df[col], errors='coerce').dropna()
                        if len(training_vals) > 0:
                            fill_val = float(training_vals.mean())
                            nan_count = future_df[col].isna().sum()
                            if nan_count > 0:
                                future_df[col] = future_df[col].fillna(fill_val)
                                logger.warning(
                                    f"Regressor {col} had {nan_count} NaN values in future_df - "
                                    f"filled with training mean ({fill_val:.2f})"
                                )
                        else:
                            future_df[col] = future_df[col].fillna(0.0)
                    else:
                        future_df[col] = future_df[col].fillna(0.0)
                elif col == "delivery":
                    # Already handled above - should be removed
                    pass
                else:
                    # Other regressors: Try forward-fill from training, then median, then 0
                    try:
                        future_df[col] = pd.to_numeric(future_df[col], errors='coerce')
                        nan_count = future_df[col].isna().sum()
                        if nan_count > 0:
                            if col in df.columns:
                                training_vals = pd.to_numeric(df[col], errors='coerce').dropna()
                                if len(training_vals) > 0:
                                    # Forward-fill from last training value
                                    last_val = float(training_vals.iloc[-1])
                                    future_df[col] = future_df[col].fillna(last_val)
                                else:
                                    future_df[col] = future_df[col].fillna(0.0)
                            else:
                                future_df[col] = future_df[col].fillna(0.0)
                    except (ValueError, TypeError):
                        # If conversion fails, remove the column
                        if col in future_df.columns:
                            future_df = future_df.drop(columns=[col])
        
        # D) Add validation logging (Fix 4: comprehensive diagnostics)
        from app.core.config import settings
        if settings.debug_zero_forecasts or (product_id is not None and product_id in settings.debug_forecast_product_ids):
            sample_indices = [0, 1, 2] + [len(future_df) - 3, len(future_df) - 2, len(future_df) - 1]
            sample_indices = [i for i in sample_indices if 0 <= i < len(future_df)]
            
            logger.info(
                f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                f"step=future_regressor_validation, future_df_shape={future_df.shape}, "
                f"future_df_columns_count={len(future_df.columns)}, "
                f"future_df_columns={list(future_df.columns)[:20]}"  # First 20 columns
            )
            
            # Log all regressor columns and their NaN counts (Fix 4)
            regressor_cols = [col for col in future_df.columns if col != "ds"]
            for col in regressor_cols[:30]:  # First 30 regressors
                nan_count = future_df[col].isna().sum()
                nan_pct = (nan_count / len(future_df) * 100) if len(future_df) > 0 else 0.0
                if nan_pct > 50.0:  # Log if more than 50% NaN
                    logger.warning(
                        f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                        f"step=regressor_nan_check, regressor={col}, "
                        f"nan_count={nan_count}, nan_pct={nan_pct:.1f}%"
                    )
            
            for regressor in ["lag_1", "lag_7", "rolling_mean_7", "rolling_mean_30", "delivery"]:
                if regressor in future_df.columns:
                    values = pd.to_numeric(future_df[regressor], errors='coerce')
                    if len(values) > 0:
                        # Check if constant
                        valid_values = values.dropna()
                        if len(valid_values) > 0:
                            if valid_values.nunique() == 1:
                                logger.warning(
                                    f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                                    f"step=regressor_check, regressor={regressor} is CONSTANT: {valid_values.iloc[0]:.6f}"
                                )
                            
                            # Log sample values
                            sample_values = []
                            for i in sample_indices:
                                if i < len(future_df):
                                    date_str = future_df.iloc[i]["ds"].strftime("%Y-%m-%d")
                                    val = values.iloc[i] if i < len(values) else None
                                    if pd.notna(val):
                                        sample_values.append(f"{date_str}:{val:.6f}")
                            if sample_values:
                                logger.info(
                                    f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                                    f"step=regressor_check, regressor={regressor}, sample_values={sample_values}"
                                )
                        else:
                            logger.warning(
                                f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                                f"step=regressor_check, regressor={regressor} has NO VALID VALUES (all NaN)"
                            )
                else:
                    logger.warning(
                        f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                        f"step=regressor_check, regressor={regressor} NOT IN future_df.columns"
                    )

        # 3) Load ModelRun to get stored hyperparameters and selected model type
        model_run = (
            db.query(ModelRun)
            .filter(
                ModelRun.product_id == product_id,
                ModelRun.is_active == True
            )
            .first()
        )
        
        # Determine model type and hyperparameters to use
        requested_model = "prophet"  # Default
        hyperparameters = None
        forecast_model_override_reason = None
        
        if model_run:
            # Use stored selected_model_type
            requested_model = model_run.selected_model_type
            hyperparameters = model_run.hyperparameters_json or {}
            logger.info(
                f"Using stored ModelRun for product {product_id}: "
                f"selected_model_type={requested_model}, has_hyperparams={bool(hyperparameters)}"
            )
        else:
            logger.info(
                f"No active ModelRun found for product {product_id}, using defaults"
            )
        
        # Final delivery check: Ensure cleaned_ts.df doesn't contain delivery before forecast
        from app.core.config import settings
        if settings.debug_zero_forecasts or (product_id is not None and product_id in settings.debug_forecast_product_ids):
            if "delivery" in cleaned_ts.df.columns:
                logger.error(
                    f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                    f"step=final_delivery_check, ERROR: delivery still in cleaned_ts.df before forecaster.forecast()!"
                )
            else:
                logger.info(
                    f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                    f"step=final_delivery_check, delivery correctly removed from cleaned_ts.df before forecast"
                )
        
        # 4) Forecast via selected model (gating will still run in trainer.train())
        forecast_result: ForecastResult = self.forecaster.forecast(
            ts=cleaned_ts,
            horizon_days=horizon_days,
            model_name=requested_model,
            hyperparameters=hyperparameters,  # Pass stored hyperparameters as warm-start
            holidays_df=holidays_df,
            weather_df=weather_df,
            promotions_df=promotions_df,
            events_df=events_df,
            product_info=product_info,
            future_regressors=future_df,
        )
        
        # Check if gating forced a different model (compare requested vs actual)
        if forecast_result.model_name != requested_model:
            forecast_model_override_reason = (
                f"Gating selected {forecast_result.model_name} instead of {requested_model}"
            )
            logger.warning(
                f"Model override for product {product_id}: {forecast_model_override_reason}"
            )
            # Update ModelRun with override reason if it exists
            if model_run:
                model_run.forecast_model_override_reason = forecast_model_override_reason
                db.commit()
        
        # Phase 2: Log model/hyperparams used in forecasting (gated by debug_zero_forecasts)
        from app.core.config import settings
        if settings.debug_zero_forecasts or (product_id is not None and product_id in settings.debug_forecast_product_ids):
            final_model = forecast_result.model_name
            model_run_id = model_run.id if model_run else None
            trained_at = model_run.created_at.isoformat() if model_run and model_run.created_at else None
            hyperparams_source = "stored" if (model_run and hyperparameters) else "defaults"
            hyperparams_summary = {}
            if hyperparameters:
                # Log key hyperparameters (avoid logging full dict if too large)
                for key in ["changepoint_prior_scale", "seasonality_prior_scale", "holidays_prior_scale", 
                           "n_estimators", "max_depth", "learning_rate"]:
                    if key in hyperparameters:
                        hyperparams_summary[key] = hyperparameters[key]
            
            logger.info(
                f"FORECAST_MODEL_INFO: product_id={product_id}, "
                f"final_model={final_model}, "
                f"model_run_id={model_run_id}, "
                f"trained_at={trained_at}, "
                f"hyperparams_source={hyperparams_source}, "
                f"hyperparams_summary={hyperparams_summary}, "
                f"requested_model={requested_model}, "
                f"model_override={forecast_result.model_name != requested_model}"
            )

        df = forecast_result.forecast_df
        
        # Fix 4: Check if forecast_df is empty or has invalid yhat values
        from app.core.config import settings
        if settings.debug_zero_forecasts or (product_id is not None and product_id in settings.debug_forecast_product_ids):
            if df.empty:
                logger.error(
                    f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                    f"step=forecast_df_check, ERROR: forecast_df is EMPTY!"
                )
            elif "yhat" not in df.columns:
                logger.error(
                    f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                    f"step=forecast_df_check, ERROR: 'yhat' column missing in forecast_df! "
                    f"Columns: {list(df.columns)}"
                )
            else:
                yhat_nan_count = df["yhat"].isna().sum()
                yhat_valid_count = df["yhat"].notna().sum()
                logger.info(
                    f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                    f"step=forecast_df_check, forecast_df_rows={len(df)}, "
                    f"yhat_valid={yhat_valid_count}, yhat_nan={yhat_nan_count}"
                )
                if yhat_valid_count > 0:
                    sample_yhat = df["yhat"].dropna().head(5).tolist()
                    yhat_min = float(df["yhat"].min()) if yhat_valid_count > 0 else None
                    yhat_max = float(df["yhat"].max()) if yhat_valid_count > 0 else None
                    yhat_mean = float(df["yhat"].mean()) if yhat_valid_count > 0 else None
                    negative_count = (df["yhat"] < 0).sum() if yhat_valid_count > 0 else 0
                    zero_count = (df["yhat"] == 0.0).sum() if yhat_valid_count > 0 else 0
                    
                    logger.info(
                        f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                        f"step=forecast_df_check, sample_yhat_values={sample_yhat}, "
                        f"yhat_min={yhat_min}, yhat_max={yhat_max}, yhat_mean={yhat_mean}, "
                        f"negative_count={negative_count}, zero_count={zero_count}"
                    )
                    
                    if negative_count > 0:
                        logger.warning(
                            f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                            f"step=forecast_df_check, WARNING: {negative_count} negative predictions "
                            f"will be clamped to zero!"
                        )
                    if zero_count == yhat_valid_count:
                        logger.warning(
                            f"ZERO_FORECAST_INVESTIGATION: product_id={product_id}, "
                            f"step=forecast_df_check, WARNING: ALL predictions are zero! "
                            f"This suggests Prophet failed or predicted all negatives."
                        )
        
        # Extract raw predictions before clamping for future stats computation
        raw_yhat_values = None
        if not df.empty and "yhat" in df.columns:
            raw_yhat_values = df["yhat"].values.copy()

        # #region agent log
        try:
            import json
            import time
            from datetime import date as date_type
            last_train_date = cleaned_ts.df["ds"].max().date() if not cleaned_ts.df.empty else None
            today = date_type.today()
            forecast_date_range = f"{df['ds'].min().date() if not df.empty else 'none'} to {df['ds'].max().date() if not df.empty else 'none'}"
            sample_yhat_values = df["yhat"].head(5).tolist() if not df.empty and "yhat" in df.columns else []
            zero_forecast_count = (df["yhat"] == 0.0).sum() if not df.empty and "yhat" in df.columns else 0
            total_forecast_count = len(df) if not df.empty else 0
            log_entry = {
                "sessionId": "debug-session",
                "runId": "run1",
                "hypothesisId": "I",
                "location": "forecast_service.py:589",
                "message": "Forecast generated - checking values",
                "data": {
                    "product_id": product_id,
                    "last_train_date": last_train_date.isoformat() if last_train_date else None,
                    "today": today.isoformat(),
                    "horizon_days": horizon_days,
                    "forecast_date_range": forecast_date_range,
                    "total_forecast_count": total_forecast_count,
                    "zero_forecast_count": int(zero_forecast_count),
                    "sample_yhat_values": sample_yhat_values,
                    "forecast_df_columns": list(df.columns) if not df.empty else []
                },
                "timestamp": int(time.time() * 1000)
            }
            with open(r"c:\Users\forfl\Documents\dailydough-1\.cursor\debug.log", "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry) + "\n")
        except Exception:
            pass
        # #endregion

        # 4) Predict spikes for forecast period
        # Use historical data with spike information for prediction
        historical_with_spikes = cleaned_ts.df.copy()
        df_future = df.copy()
        
        # Add spike predictions to forecast dataframe
        df_future = self._predict_spikes(historical_with_spikes, df_future)

        # 5) Convert Prophet output → list of ForecastPoint
        points: list[ForecastPoint] = []
        
        # Diagnostic: Log before conversion (STORAGE_PRE_WRITE)
        # Log the forecast_df values before conversion
        if not df_future.empty and "yhat" in df_future.columns:
            yhat_values = df_future["yhat"].values
            first_3_yhat = yhat_values[:3].tolist() if len(yhat_values) >= 3 else yhat_values.tolist()
            last_3_yhat = yhat_values[-3:].tolist() if len(yhat_values) >= 3 else yhat_values.tolist()
            logger.info(
                f"STORAGE_PRE_WRITE: forecast_run_id={forecast_run_id}, product_id={product_id}, "
                f"points_count={len(df_future)}, first_3_yhat={first_3_yhat}, last_3_yhat={last_3_yhat}"
            )

        if "ds" not in df_future.columns:
            logger.error("Forecast failed: 'ds' column missing in Prophet output")
            raise RuntimeError("Prophet forecast missing 'ds' column")

        # Calculate profit metrics if product has price/cost
        has_profit_data = product.price is not None and product.cost_per_unit is not None
        
        for _, row in df_future.iterrows():
            ds_value = row["ds"]
            date_str = ds_value.date().isoformat()

            # Raw Prophet outputs - ensure numeric conversion
            # Don't default NaN to 0.0 - use None to indicate invalid/missing forecasts
            try:
                yhat_raw = row.get("yhat")
                if pd.notna(yhat_raw):
                    yhat_numeric = pd.to_numeric(yhat_raw, errors='coerce')
                    if pd.notna(yhat_numeric):
                        yhat_before_clamp = float(yhat_numeric)
                        yhat = max(0.0, yhat_before_clamp)  # Clamp non-negative
                        # #region agent log
                        if yhat == 0.0 and yhat_before_clamp < 0:
                            try:
                                import json
                                import time
                                log_entry = {
                                    "sessionId": "debug-session",
                                    "runId": "run1",
                                    "hypothesisId": "K",
                                    "location": "forecast_service.py:656",
                                    "message": "Zero forecast from negative prediction",
                                    "data": {
                                        "product_id": product_id,
                                        "date": date_str,
                                        "yhat_before_clamp": yhat_before_clamp,
                                        "yhat_after_clamp": yhat
                                    },
                                    "timestamp": int(time.time() * 1000)
                                }
                                with open(r"c:\Users\forfl\Documents\dailydough-1\.cursor\debug.log", "a", encoding="utf-8") as f:
                                    f.write(json.dumps(log_entry) + "\n")
                            except Exception:
                                pass
                        # #endregion
                    else:
                        yhat = None  # Invalid conversion
                else:
                    yhat = None  # Missing value
                
                yhat_lower_raw = row.get("yhat_lower")
                if pd.notna(yhat_lower_raw):
                    yhat_lower_numeric = pd.to_numeric(yhat_lower_raw, errors='coerce')
                    if pd.notna(yhat_lower_numeric):
                        yhat_lower = max(0.0, float(yhat_lower_numeric))
                    else:
                        yhat_lower = None
                else:
                    yhat_lower = None
                
                yhat_upper_raw = row.get("yhat_upper")
                if pd.notna(yhat_upper_raw):
                    yhat_upper_numeric = pd.to_numeric(yhat_upper_raw, errors='coerce')
                    if pd.notna(yhat_upper_numeric):
                        yhat_upper = max(0.0, float(yhat_upper_numeric))
                    else:
                        yhat_upper = None
                else:
                    yhat_upper = None
            except (ValueError, TypeError) as e:
                logger.warning(f"Error converting forecast values to numeric for date {date_str}: {e}")
                yhat = None
                yhat_lower = None
                yhat_upper = None
            
            # Skip this point if yhat is invalid (None)
            if yhat is None:
                logger.warning(f"Skipping forecast point for {date_str} - invalid yhat value")
                continue

            # Round nicely (only if values are not None)
            yhat = round(yhat, 2)
            if yhat_lower is not None:
                yhat_lower = round(yhat_lower, 2)
            if yhat_upper is not None:
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
        
        # Store raw predictions as an attribute for future stats computation
        # This is used by train_all_products.py to compute raw_prediction_summary_future
        result.raw_yhat_values = raw_yhat_values
        result.model_name = forecast_result.model_name
        result.source = "fresh_generate"
        result.forecast_run_id = forecast_run_id

        # Store in cache for subsequent requests.
        try:
            # Simple size-based eviction: if we exceed the soft limit,
            # drop the oldest entry (by created_at).
            if len(self._forecast_cache) >= self._CACHE_MAX_ENTRIES:
                oldest_key = None
                oldest_time = now
                for k, (created_at, _, _) in self._forecast_cache.items():
                    if created_at <= oldest_time:
                        oldest_time = created_at
                        oldest_key = k
                if oldest_key is not None:
                    self._forecast_cache.pop(oldest_key, None)

            self._forecast_cache[cache_key] = (now, result, result.source)
            
            # Log cache storage with values
            if result.points:
                first_3_yhat = [p.yhat for p in result.points[:3]]
                last_3_yhat = [p.yhat for p in result.points[-3:]]
                logger.info(
                    f"CACHE_STORE: forecast_run_id={forecast_run_id}, key={cache_key}, "
                    f"source={result.source}, points_count={len(result.points)}, "
                    f"first_3_yhat={first_3_yhat}, last_3_yhat={last_3_yhat}"
                )
            else:
                logger.info(
                    f"CACHE_STORE: forecast_run_id={forecast_run_id}, key={cache_key}, "
                    f"source={result.source}, points_count=0"
                )
            
            # Diagnostic: Read back from cache and log (STORAGE_POST_READ)
            cached_result = self._forecast_cache.get(cache_key)
            if cached_result and cached_result[1] and cached_result[1].points:
                cached_points = cached_result[1].points
                first_3_yhat = [p.yhat for p in cached_points[:3]] if len(cached_points) >= 3 else [p.yhat for p in cached_points]
                last_3_yhat = [p.yhat for p in cached_points[-3:]] if len(cached_points) >= 3 else [p.yhat for p in cached_points]
                logger.info(
                    f"STORAGE_POST_READ: forecast_run_id={forecast_run_id}, product_id={product_id}, "
                    f"rows_read={len(cached_points)}, first_3_yhat={first_3_yhat}, last_3_yhat={last_3_yhat}"
                )
        except Exception as e:
            # Cache must never break the main forecast path.
            logger.warning(
                "Failed to store forecast in cache for product_id=%d: %s",
                product.id,
                str(e),
            )

        return result
