"""Check diagnostic data after retraining product 156"""
from app.database.database import SessionLocal
from app.models import ModelRun, DailyForecast
from datetime import date, datetime, timedelta
import json

db = SessionLocal()

# Check for ModelRuns created in the last hour
one_hour_ago = datetime.now() - timedelta(hours=1)
recent_runs = db.query(ModelRun).filter(
    ModelRun.product_id == 156,
    ModelRun.created_at >= one_hour_ago
).order_by(ModelRun.created_at.desc()).all()

print(f"ModelRuns for product 156 in last hour: {len(recent_runs)}")
for run in recent_runs:
    print(f"\n  Created: {run.created_at}")
    print(f"  Active: {run.is_active}")
    print(f"  Model: {run.selected_model_type}")
    if run.metrics_json:
        print(f"  Metrics keys: {list(run.metrics_json.keys())}")
        
        future_stats = run.metrics_json.get('raw_prediction_summary_future', {})
        eval_stats = run.metrics_json.get('raw_prediction_summary_eval', {})
        training_summary = run.metrics_json.get('training_data_summary', {})
        
        print(f"\n  === FUTURE SLICE STATS ===")
        if future_stats:
            print(f"    raw_neg_pct: {future_stats.get('raw_neg_pct', 'N/A')}%")
            print(f"    clamped_zero_pct: {future_stats.get('clamped_zero_pct', 'N/A')}%")
            print(f"    raw_mean: {future_stats.get('raw_mean', 'N/A')}")
            print(f"    raw_min: {future_stats.get('raw_min', 'N/A')}")
            print(f"    raw_max: {future_stats.get('raw_max', 'N/A')}")
            print(f"    n_points_future: {future_stats.get('n_points_future', 'N/A')}")
        else:
            print("    EMPTY - Future stats not computed/stored")
        
        print(f"\n  === EVAL SLICE STATS ===")
        if eval_stats:
            print(f"    raw_neg_pct: {eval_stats.get('raw_neg_pct', 'N/A')}%")
            print(f"    clamped_zero_pct: {eval_stats.get('clamped_zero_pct', 'N/A')}%")
            print(f"    raw_mean: {eval_stats.get('raw_mean', 'N/A')}")
        else:
            print("    EMPTY - Eval stats not computed/stored")
        
        print(f"\n  === TRAINING DATA SUMMARY ===")
        if training_summary:
            print(f"    mean_y: {training_summary.get('mean_y', 'N/A')}")
            print(f"    zero_rate: {training_summary.get('zero_rate', 'N/A')}%")
            print(f"    total_training_days: {training_summary.get('total_training_days', 'N/A')}")
    else:
        print("  No metrics_json!")

# Check latest active ModelRun
latest_active = db.query(ModelRun).filter(
    ModelRun.product_id == 156,
    ModelRun.is_active == True
).order_by(ModelRun.created_at.desc()).first()

if latest_active:
    print(f"\n=== LATEST ACTIVE ModelRun ===")
    print(f"Created: {latest_active.created_at}")
    print(f"Model: {latest_active.selected_model_type}")

# Check forecasts
print(f"\n=== FORECASTS Nov 1-10, 2025 ===")
nov_forecasts = db.query(DailyForecast).filter(
    DailyForecast.product_id == 156,
    DailyForecast.date >= date(2025, 11, 1),
    DailyForecast.date <= date(2025, 11, 10)
).order_by(DailyForecast.date).all()

if nov_forecasts:
    for f in nov_forecasts:
        print(f"  {f.date}: yhat={f.yhat}")
else:
    print("  No forecasts found")

db.close()



