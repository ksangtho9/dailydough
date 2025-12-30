"""Manually trigger forecast generation and check raw predictions for product 156"""
from app.database.database import SessionLocal
from app.models import Product
from app.ml.forecast_service import ForecastService
from datetime import date
import numpy as np

db = SessionLocal()

# Get product 156
product = db.query(Product).filter(Product.id == 156).first()
if not product:
    print("Product 156 not found")
    db.close()
    exit(1)

print(f"Product 156: {product.name}, bakery_id={product.bakery_id}")

# Generate forecast directly to get raw predictions
forecast_service = ForecastService()
try:
    forecast_result = forecast_service.generate_prophet_forecast_for_product(
        db=db,
        product_id=156,
        horizon_days=60,
    )
    
    print(f"\nForecast generated:")
    print(f"  Model: {forecast_result.model_name}")
    print(f"  Points: {len(forecast_result.points)}")
    print(f"  Has raw_yhat_values: {forecast_result.raw_yhat_values is not None}")
    
    if forecast_result.raw_yhat_values is not None:
        raw_yhat = forecast_result.raw_yhat_values
        print(f"\n=== RAW PREDICTIONS (before clamping) ===")
        print(f"  Count: {len(raw_yhat)}")
        print(f"  Min: {np.min(raw_yhat):.6f}")
        print(f"  Mean: {np.mean(raw_yhat):.6f}")
        print(f"  Max: {np.max(raw_yhat):.6f}")
        print(f"  Negative count: {(raw_yhat < 0).sum()} ({(raw_yhat < 0).sum() / len(raw_yhat) * 100:.1f}%)")
        print(f"  Zero count: {(raw_yhat == 0.0).sum()} ({(raw_yhat == 0.0).sum() / len(raw_yhat) * 100:.1f}%)")
        print(f"  First 10 values: {raw_yhat[:10].tolist()}")
        
        # Check Nov 1-10 specifically
        print(f"\n=== NOV 1-10, 2025 FORECASTS ===")
        nov_dates = [date(2025, 11, d) for d in range(1, 11)]
        for i, point in enumerate(forecast_result.points):
            point_date = date.fromisoformat(point.date)
            if point_date in nov_dates:
                # Find corresponding raw prediction
                raw_idx = i if i < len(raw_yhat) else None
                raw_val = raw_yhat[raw_idx] if raw_idx is not None else None
                raw_str = "N/A" if raw_val is None else f"{raw_val:.6f}"
                print(f"  {point_date}: yhat={point.yhat}, raw_yhat={raw_str}")
    else:
        print("\n  No raw_yhat_values available")
        
    # Check clamped vs raw for first few points
    print(f"\n=== FIRST 5 POINTS (clamped vs raw) ===")
    for i in range(min(5, len(forecast_result.points))):
        point = forecast_result.points[i]
        raw_val = forecast_result.raw_yhat_values[i] if forecast_result.raw_yhat_values is not None and i < len(forecast_result.raw_yhat_values) else None
        raw_str = "N/A" if raw_val is None else f"{raw_val:.6f}"
        print(f"  {point.date}: clamped_yhat={point.yhat}, raw_yhat={raw_str}")

except Exception as e:
    print(f"Error generating forecast: {e}")
    import traceback
    traceback.print_exc()

db.close()

