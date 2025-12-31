"""Test forecast generation for product 194 with enhanced logging"""
import logging
from app.database.database import SessionLocal
from app.models import Product
from app.ml.forecast_service import ForecastService
from datetime import date

# Enable debug logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bakezy")

db = SessionLocal()
product = db.query(Product).filter(Product.id == 194).first()
if not product:
    print("Product 194 not found")
    db.close()
    exit(1)

print(f"Testing forecast for product 194: {product.name}, bakery_id={product.bakery_id}")
print("=" * 80)

fs = ForecastService()
result = fs.generate_prophet_forecast_for_product(db=db, product_id=194, horizon_days=14)

print("=" * 80)
print(f'Generated forecast for product 194:')
print(f'  Total points: {len(result.points)}')
print(f'  Model: {result.model_name}')
print(f'  Has raw_yhat_values: {result.raw_yhat_values is not None}')

if result.raw_yhat_values is not None:
    import numpy as np
    print(f'  Raw predictions: count={len(result.raw_yhat_values)}, '
          f'neg_count={(result.raw_yhat_values < 0).sum()}, '
          f'mean={result.raw_yhat_values.mean():.2f}')

nov1_point = next((p for p in result.points if p.date == '2025-11-01'), None)
print(f'  Nov 1 forecast: yhat={nov1_point.yhat if nov1_point else None}')

if len(result.points) > 0:
    print(f'  First 5 dates:')
    for p in result.points[:5]:
        print(f'    {p.date}: yhat={p.yhat}')
else:
    print('  WARNING: No forecast points returned - all predictions were invalid/None')

db.close()

