"""Investigate future regressor values vs training for product 156 - using actual forecast service"""
from app.database.database import SessionLocal
from app.models import Product
from app.ml.forecast_service import ForecastService
from datetime import date
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

# Use ForecastService to get the actual future_df that Prophet sees
forecast_service = ForecastService()

# Generate forecast to see what regressors are used
# We'll intercept the future_df before it goes to Prophet
# Actually, let's just generate a forecast and check the logs, or better yet,
# let's manually call the internal methods

# Load sales and preprocess (same as forecast_service does)
from app.ml.preprocessing import SalesPreprocessor, RawSalesRecord
from app.models import SalesRecord

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
cleaned = preprocessor.preprocess(raw_records, product_id=156, shelf_life_days=getattr(product, "shelf_life_days", 1) or 1)

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

# Apply feature engineering to training data FIRST (before getting tail)
df = train_df.copy()
df["ds"] = pd.to_datetime(df["ds"])
start_date = df["ds"].min().date()
end_date = date(2025, 11, 10)

holidays_df, weather_df, promotions_df, events_df = forecast_service._load_feature_data(
    db, product, start_date, end_date
)

product_info = {
    "category": product.category,
    "shelf_life_days": getattr(product, "shelf_life_days", 1) or 1,
    "price": product.price,
    "cost_per_unit": product.cost_per_unit,
}

# Apply feature engineering to historical data
df = forecast_service.feature_engineer.transform(
    df,
    holidays_df=holidays_df,
    weather_df=weather_df,
    promotions_df=promotions_df,
    events_df=events_df,
    product_info=product_info,
)

# Get last 30 days of training for comparison (AFTER feature engineering)
train_tail_30 = df[df["ds"] >= (pd.Timestamp(last_train_date) - pd.Timedelta(days=30))].copy()
print(f"Last 30 training days: {len(train_tail_30)} days\n")

# df is already feature-engineered above

# Generate future dates (Nov 1-10, 2025)
from datetime import timedelta
future_dates = pd.date_range(
    start=pd.Timestamp(last_train_date) + pd.Timedelta(days=1),
    end=pd.Timestamp(date(2025, 11, 10)),
    freq="D",
)
future_df = pd.DataFrame({"ds": future_dates})

# Apply feature engineering to future dates
future_df = forecast_service.feature_engineer.transform(
    future_df,
    holidays_df=holidays_df,
    weather_df=weather_df,
    promotions_df=promotions_df,
    events_df=events_df,
    product_info=product_info,
)

# Now apply the regressor filling logic (this is what we need to check)
# This replicates lines 538-577 from forecast_service.py
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
for col in future_df.columns:
    if col != "ds":
        try:
            future_df[col] = pd.to_numeric(future_df[col], errors='coerce').fillna(0.0)
        except (ValueError, TypeError):
            pass

# Print what columns exist
print("=== COLUMNS IN TRAINING DATA (last 30 days) ===")
print(f"Columns: {sorted([c for c in train_tail_30.columns if c not in ['ds', 'y']])}\n")

print("=== COLUMNS IN FUTURE DATA (Nov 1-10) ===")
print(f"Columns: {sorted([c for c in future_df.columns if c != 'ds'])}\n")

# Check regressor values
print("=== REGRESSOR COMPARISON: Training (last 30 days) vs Future (Nov 1-10) ===\n")

regressor_candidates = [
    "delivery", "lag_1", "lag_7", "lag_14", "lag_30",
    "rolling_mean_7", "rolling_mean_30", "rolling_std_7", "rolling_std_30",
    "ewma_7", "ewma_30",
]

for regressor in regressor_candidates:
    # Training stats (last 30 days)
    train_vals = None
    if regressor in train_tail_30.columns:
        train_vals = pd.to_numeric(train_tail_30[regressor], errors='coerce').dropna()
    
    # Future values (Nov 1-10) - check AFTER regressor filling
    future_vals = None
    if regressor in future_df.columns:
        future_vals = pd.to_numeric(future_df[regressor], errors='coerce')
        # Debug: print first few values
        if len(future_vals) > 0:
            print(f"  DEBUG: {regressor} first 3 values: {future_vals.head(3).tolist()}")
    
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
        future_nan_count = len(future_df) if regressor in future_df.columns else 0
    
    # Check if constant
    is_constant = False
    if future_vals is not None and len(future_vals) > 0:
        valid_future = future_vals.dropna()
        if len(valid_future) > 0 and valid_future.nunique() == 1:
            is_constant = True
    
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
        if is_constant:
            print(f"  WARNING: CONSTANT across horizon: {valid_future.iloc[0]:.6f}")
    else:
        print(f"  Future (Nov 1-10): NOT PRESENT")
    
    # Check for distribution mismatch
    if (train_vals is not None and len(train_vals) > 0 and 
        future_vals is not None and len(future_vals) > 0 and
        future_mean is not None and train_mean is not None):
        if abs(future_mean - train_mean) > abs(train_mean) * 0.5:
            print(f"  WARNING: DISTRIBUTION MISMATCH: Future mean ({future_mean:.6f}) differs significantly from training mean ({train_mean:.6f})")
    
    print()

# Check specific dates
print("\n=== DETAILED VALUES FOR NOV 1-10, 2025 ===\n")
for idx, row in future_df.iterrows():
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

