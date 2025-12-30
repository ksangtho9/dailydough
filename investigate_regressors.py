"""Investigate future regressor values vs training for product 156"""
from app.database.database import SessionLocal
from app.models import Product, SalesRecord
from app.ml.forecast_service import ForecastService
from app.ml.preprocessing import SalesPreprocessor, RawSalesRecord
from app.ml.features import FeatureEngineer
from datetime import date, timedelta
import pandas as pd
import numpy as np

db = SessionLocal()

# Get product 156
product = db.query(Product).filter(Product.id == 156).first()
if not product:
    print("Product 156 not found")
    db.close()
    exit(1)

print(f"Product 156: {product.name}, bakery_id={product.bakery_id}\n")

# Load sales data
sales_rows = (
    db.query(SalesRecord)
    .filter(
        SalesRecord.product_id == 156,
        SalesRecord.bakery_id == product.bakery_id,
    )
    .order_by(SalesRecord.date.asc())
    .all()
)

raw_records = [
    RawSalesRecord(
        date=row.date,
        product_id=row.product_id,
        quantity=row.quantity_sold,
        quantity_delivered=row.quantity_delivered,
    )
    for row in sales_rows
]

# Preprocess
preprocessor = SalesPreprocessor()
cleaned = preprocessor.preprocess(raw_records, product_id=156)

if cleaned.df.empty:
    print("No training data")
    db.close()
    exit(1)

# Get training data up to Oct 31, 2025
train_df = cleaned.df.copy()
train_df["ds"] = pd.to_datetime(train_df["ds"])
last_train_date = train_df["ds"].max().date()

print(f"Training data range: {train_df['ds'].min().date()} to {last_train_date}")
print(f"Total training days: {len(train_df)}")

# Get last 30 days of training for comparison
train_tail_30 = train_df[train_df["ds"] >= (pd.Timestamp(last_train_date) - pd.Timedelta(days=30))].copy()
print(f"Last 30 training days: {len(train_tail_30)} days\n")

# Generate future dates (Nov 1-10, 2025)
future_dates = pd.date_range(
    start=pd.Timestamp(date(2025, 11, 1)),
    end=pd.Timestamp(date(2025, 11, 10)),
    freq="D"
)
future_df = pd.DataFrame({"ds": future_dates})

# Apply feature engineering to both training and future
feature_engineer = FeatureEngineer()
product_info = {
    "category": product.category,
    "shelf_life_days": getattr(product, "shelf_life_days", 1) or 1,
    "price": product.price,
    "cost_per_unit": product.cost_per_unit,
}

# Load feature data
forecast_service = ForecastService()
start_date = train_df["ds"].min().date()
end_date = date(2025, 11, 10)
holidays_df, weather_df, promotions_df, events_df = forecast_service._load_feature_data(
    db, product, start_date, end_date
)

# Apply feature engineering to training data
train_df_enhanced = feature_engineer.transform(
    train_df.copy(),
    holidays_df=holidays_df,
    weather_df=weather_df,
    promotions_df=promotions_df,
    events_df=events_df,
    product_info=product_info,
)

# Apply feature engineering to future dates
future_df_enhanced = feature_engineer.transform(
    future_df.copy(),
    holidays_df=holidays_df,
    weather_df=weather_df,
    promotions_df=promotions_df,
    events_df=events_df,
    product_info=product_info,
)

# Check regressor values
print("=== REGRESSOR COMPARISON: Training (last 30 days) vs Future (Nov 1-10) ===\n")

# Identify regressors (numeric columns that Prophet might use)
regressor_candidates = [
    "delivery", "lag_1", "lag_7", "lag_14", "lag_30",
    "rolling_mean_7", "rolling_mean_30", "rolling_std_7", "rolling_std_30",
    "ewma_7", "ewma_30",
    "month", "quarter", "day_of_month", "week_of_year", "day_of_year",
    "is_month_start", "is_month_end", "days_until_weekend", "days_since_weekend",
    "is_fall", "days_before_holiday", "holiday_proximity",
    "promotion_multiplier", "event_multiplier",
    "spike_probability", "spike_severity", "days_since_last_spike", "spike_seasonality"
]

for regressor in regressor_candidates:
    if regressor not in train_df_enhanced.columns and regressor not in future_df_enhanced.columns:
        continue
    
    # Training stats (last 30 days)
    train_vals = None
    if regressor in train_tail_30.columns:
        train_vals = pd.to_numeric(train_tail_30[regressor], errors='coerce').dropna()
    
    # Future values (Nov 1-10)
    future_vals = None
    if regressor in future_df_enhanced.columns:
        future_vals = pd.to_numeric(future_df_enhanced[regressor], errors='coerce')
    
    if train_vals is not None and len(train_vals) > 0:
        train_min = float(train_vals.min())
        train_mean = float(train_vals.mean())
        train_max = float(train_vals.max())
        train_nan_pct = (train_vals.isna().sum() / len(train_vals) * 100) if len(train_vals) > 0 else 0.0
    else:
        train_min = train_mean = train_max = None
        train_nan_pct = 100.0
    
    if future_vals is not None and len(future_vals) > 0:
        future_min = float(future_vals.min()) if pd.notna(future_vals.min()) else None
        future_mean = float(future_vals.mean()) if pd.notna(future_vals.mean()) else None
        future_max = float(future_vals.max()) if pd.notna(future_vals.max()) else None
        future_nan_pct = (future_vals.isna().sum() / len(future_vals) * 100) if len(future_vals) > 0 else 0.0
        future_nan_count = future_vals.isna().sum()
    else:
        future_min = future_mean = future_max = None
        future_nan_pct = 100.0
        future_nan_count = len(future_df_enhanced) if regressor in future_df_enhanced.columns else 0
    
    # Check for imputation (all same value or all zero)
    is_imputed = False
    imputation_type = None
    if future_vals is not None and len(future_vals) > 0:
        valid_future = future_vals.dropna()
        if len(valid_future) > 0:
            if valid_future.nunique() == 1:
                is_imputed = True
                imputation_type = "constant"
            elif (valid_future == 0.0).all():
                is_imputed = True
                imputation_type = "zero"
            # Check if matches last training value (forward-fill)
            if train_vals is not None and len(train_vals) > 0:
                last_train_val = float(train_vals.iloc[-1])
                if (valid_future == last_train_val).all():
                    is_imputed = True
                    imputation_type = "forward_fill"
    
    # Print comparison
    print(f"Regressor: {regressor}")
    if train_vals is not None and len(train_vals) > 0:
        print(f"  Training (last 30d): min={train_min:.6f}, mean={train_mean:.6f}, max={train_max:.6f}, NaN%={train_nan_pct:.1f}%")
    else:
        print(f"  Training (last 30d): NOT PRESENT")
    
    if future_vals is not None and len(future_vals) > 0:
        future_min_str = f"{future_min:.6f}" if future_min is not None else "None"
        future_mean_str = f"{future_mean:.6f}" if future_mean is not None else "None"
        future_max_str = f"{future_max:.6f}" if future_max is not None else "None"
        print(f"  Future (Nov 1-10): min={future_min_str}, mean={future_mean_str}, max={future_max_str}, NaN%={future_nan_pct:.1f}% ({future_nan_count}/{len(future_vals)})")
    else:
        print(f"  Future (Nov 1-10): NOT PRESENT")
    
    if is_imputed:
        print(f"  ⚠️  IMPUTED: {imputation_type}")
    
    # Check for distribution mismatch
    if (train_vals is not None and len(train_vals) > 0 and 
        future_vals is not None and len(future_vals) > 0 and
        future_mean is not None and train_mean is not None):
        # Check if future values are way off
        if abs(future_mean - train_mean) > abs(train_mean) * 0.5:  # More than 50% difference
            print(f"  ⚠️  DISTRIBUTION MISMATCH: Future mean ({future_mean:.6f}) differs significantly from training mean ({train_mean:.6f})")
        if future_min is not None and train_min is not None and future_min < train_min * 0.5:
            print(f"  ⚠️  DISTRIBUTION MISMATCH: Future min ({future_min:.6f}) is much lower than training min ({train_min:.6f})")
    
    print()

# Check specific dates
print("\n=== DETAILED VALUES FOR NOV 1-10, 2025 ===\n")
for idx, row in future_df_enhanced.iterrows():
    date_str = row["ds"].strftime("%Y-%m-%d")
    print(f"Date: {date_str}")
    for regressor in ["delivery", "lag_1", "lag_7", "rolling_mean_7", "rolling_mean_30"]:
        if regressor in row.index:
            val = row[regressor]
            if pd.notna(val):
                print(f"  {regressor}: {float(val):.6f}")
            else:
                print(f"  {regressor}: NaN")
        else:
            print(f"  {regressor}: MISSING")
    print()

db.close()

