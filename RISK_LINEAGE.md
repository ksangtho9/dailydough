# Bakeplan Risk Lineage Documentation

## Overview

This document explains the data lineage and calculation method for bakeplan "waste risk" and "stockout risk" metrics displayed in the dashboard.

## Current State (After Implementation)

### Data Flow

```
DailyForecast (DB)
  ├── yhat (point forecast)
  ├── yhat_lower (P10, nullable)
  └── yhat_upper (P90, nullable)
        ↓
GET /api/bakeries/{bakery_id}/bake-plan
  ├── Reads DailyForecast for plan_date
  ├── Calls calculate_risk_metrics()
  ├── Returns BakePlanItem with risk fields
  └── Logs per-product risk calculation
        ↓
Frontend Dashboard
  ├── Displays waste_risk_prob * 100 as "Est. waste (%)"
  └── Displays stockout_risk_prob * 100 as "Stockout risk (%)"
```

## Risk Calculation Method

### Formula

For each product in the bakeplan:

1. **Extract forecast data**:
   - `yhat`: Point forecast (mean expected demand)
   - `yhat_lower`: Lower bound (P10 for 80% interval)
   - `yhat_upper`: Upper bound (P90 for 80% interval)
   - `planned_qty`: Planned production quantity (forecast_quantity from bakeplan)

2. **Calculate sigma (standard deviation)**:
   - If `yhat_lower` and `yhat_upper` exist:
     - Assume 80% interval (P10/P90) per schema comments
     - `z = 1.281551565545` (z-score for 80% central interval)
     - `sigma = (yhat_upper - yhat_lower) / (2 * z)`
     - `sigma ≈ (yhat_upper - yhat_lower) / 2.5631`
   - If bounds missing:
     - Fallback: `sigma = max(1.0, 0.2 * yhat)`
   - Clamp: `sigma = max(sigma, 1e-6)` to avoid division by zero

3. **Calculate z-score**:
   ```
   zscore = (planned_qty - yhat) / sigma
   ```

4. **Compute probabilities** (using normal CDF):
   ```
   waste_risk_prob = CDF(zscore)          # P(demand < planned_qty)
   stockout_risk_prob = 1 - CDF(zscore)   # P(demand > planned_qty)
   ```

### Interval Level

The schema comments indicate that `yhat_lower` and `yhat_upper` represent P10/P90 bounds, which corresponds to an 80% central confidence interval. The implementation assumes this interval level when bounds are present.

**Note**: If explicit `interval_level` is provided in the future, the calculation uses:
```python
z = norm.ppf(0.5 + interval_level / 2)
sigma = (upper - lower) / (2 * z)
```

For 95% intervals: `z ≈ 1.96`, divisor ≈ 3.92
For 80% intervals: `z ≈ 1.28155`, divisor ≈ 2.5631

## API Response Schema

Each `BakePlanItem` in the response includes:

```python
{
    "product_id": int,
    "product_name": str,
    "forecast_quantity": int,  # planned_qty
    "sku": str | None,
    
    # Risk metrics (computed)
    "waste_risk_prob": float | None,        # 0-1, P(demand < planned)
    "stockout_risk_prob": float | None,     # 0-1, P(demand > planned)
    "risk_sigma": float | None,             # Standard deviation used
    "interval_level_used": float | str | None,  # 0.8, 0.95, or "fallback"
    "risk_method": str | None,              # "interval_based" | "residual_based" | "fallback"
    "debug_source": str | None,             # "prophet_interval" | "xgb_interval" | "fallback"
    "sigma_clamped": bool | None,           # True if sigma was clamped
}
```

## Logging

### Backend Logging

The bakeplan endpoint logs per-product risk calculations using the centralized logger (`bakezy.bake_plan`):

```
Risk calculation: request_id={request_id}, bakery_id={bakery_id}, product_id={product_id}, 
date={date}, yhat={yhat}, lower={lower}, upper={upper}, planned_qty={planned_qty}, 
waste_risk_prob={waste_risk_prob}, stockout_risk_prob={stockout_risk_prob}, 
risk_method={risk_method}, interval_level_used={interval_level_used}, 
risk_sigma={risk_sigma}, sigma_clamped={sigma_clamped}
```

Each request has a unique `request_id` (8-character hex UUID) for end-to-end tracing.

### Frontend Logging (Dev Mode)

When dev mode is enabled, the dashboard logs:
- API endpoint called
- Response payload shape
- Risk values for first 3 products

Check browser console with dev mode enabled.

## What Was Wrong Before

### Previous Implementation

The dashboard displayed placeholder values:
```typescript
waste = 7 + (index % 3) * 0.6  // Placeholder!
risk  = 10 + (index % 4) * 1.5  // Placeholder!
```

These values were:
- **Not based on forecast data**
- **Deterministic only by array index**, not by actual risk
- **Not connected to forecast uncertainty**
- **Misleading to users**

### New Implementation

- ✅ **Deterministic** and **reproducible** (same inputs → same outputs)
- ✅ **Based on forecast uncertainty intervals** (yhat_lower, yhat_upper)
- ✅ **Properly logged** with request_id for debugging
- ✅ **Includes metadata** (risk_method, interval_level_used) for transparency

## Debugging

### How to Debug Risk Calculations

1. **Check backend logs**:
   - Look for log entries with pattern: `Risk calculation: request_id=...`
   - Filter by `request_id` to trace a specific request
   - Verify `risk_method`, `interval_level_used`, and `risk_sigma` values

2. **Check frontend console** (dev mode):
   - Enable dev mode in dashboard
   - Look for `BAKE_PLAN_API_RESPONSE` and `BAKE_PLAN_RISK_VALUES_FIRST_3` logs
   - Verify risk fields are present in API response

3. **Verify data in database**:
   ```sql
   SELECT product_id, date, yhat, yhat_lower, yhat_upper
   FROM daily_forecasts
   WHERE bakery_id = ? AND date = ?;
   ```
   - If `yhat_lower` or `yhat_upper` are NULL, fallback method is used

4. **Run integration test**:
   ```bash
   python scripts/test_bakeplan_risks.py <bakery_id>
   ```
   - Verifies deterministic behavior (same request → same risk values)

### Example Log Output

```
Bake plan request: request_id=a1b2c3d4, bakery_id=1, plan_date=2025-01-15, products_count=10

Risk calculation: request_id=a1b2c3d4, bakery_id=1, product_id=5, date=2025-01-15, 
yhat=100.00, lower=80.00, upper=120.00, planned_qty=100, 
waste_risk_prob=0.5000, stockout_risk_prob=0.5000, risk_method=interval_based, 
interval_level_used=0.8, risk_sigma=15.60, sigma_clamped=False
```

## Testing

### Unit Tests

Run unit tests:
```bash
pytest tests/test_risk_calculator.py -v
```

Tests cover:
- Sigma derivation from 80% intervals
- Risk monotonicity (waste increases, stockout decreases as planned_qty increases)
- Edge cases (missing bounds, sigma=0, yhat=0, planned=0)
- Deterministic behavior

### Integration Test

Run integration test:
```bash
python scripts/test_bakeplan_risks.py <bakery_id>
```

This test:
- Calls bakeplan API twice
- Asserts risk values are identical (deterministic)
- Shows sample risk values

## Future Improvements

1. **Explicit interval_level storage**: Store interval level in DailyForecast or forecast metadata to avoid assumptions
2. **Residual-based sigma**: Compute sigma from historical forecast residuals when intervals are missing
3. **Product-specific uncertainty**: Track per-product uncertainty characteristics
4. **Confidence intervals in UI**: Display uncertainty intervals alongside risks

## References

- Forecast schema: `app/schemas/sales_record.py` → `ForecastPointOut`
- DailyForecast model: `app/models/daily_forecast.py`
- Risk calculator: `app/services/risk_calculator.py`
- Bakeplan API: `app/api/bake_plan.py`
- Dashboard UI: `frontend/app/dashboard/page.tsx`


