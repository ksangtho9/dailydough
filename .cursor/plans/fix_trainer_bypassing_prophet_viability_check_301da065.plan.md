# Fix Prophet Viability Gate Being Bypassed by Trainer

## Problem

The `ModelTrainer.train()` method has early eligibility and viability checks (lines 730-782) that run BEFORE Prophet is trained. When these checks fail, the trainer skips Prophet and returns XGBoost instead. This means:

1. When `forecaster.forecast()` calls `trainer.train(model_name="prophet")`, the trainer may return `TrainResult(model_name="xgboost")`
2. The forecaster's Prophet viability gate (lines 196-198 in `forecaster.py`) never runs because it only executes when `train_result.model_name == "prophet"`
3. The requested "fail fast" approach (Prophet → generate predictions → check viability → fallback) is bypassed

**Current flow (broken)**:
```
forecaster.forecast(model_name="prophet")
  → trainer.train(model_name="prophet")
    → trainer eligibility check fails
    → trainer returns TrainResult(model_name="xgboost")
  → forecaster checks: if train_result.model_name == "prophet" ❌ (it's "xgboost")
  → Prophet viability gate never runs
```

**Desired flow**:
```
forecaster.forecast(model_name="prophet")
  → trainer.train(model_name="prophet", force_model=True)
    → bypass eligibility/viability gates
    → train Prophet
    → return TrainResult(model_name="prophet")
  → forecaster checks: if requested_model == "prophet" ✅
  → run _check_prophet_viability() on raw predictions
  → if fails, fallback to XGBoost/seasonal_naive/rolling_mean
```

## Solution

1. Add `force_model: bool = False` parameter to `ModelTrainer.train()` that, when `True` and `model_name=="prophet"`, bypasses ONLY the early pre-training gates (eligibility + quick viability checks) that would switch away from Prophet.
2. Still perform normal data validation, feature generation, and other safety checks.
3. In `forecaster.py`, when explicitly attempting Prophet, pass `force_model=True`.
4. Change the viability gate logic to check the REQUESTED model name, not the returned model name.

## Implementation

### 1. Update `ModelTrainer.train()` to add `force_model` parameter

**File**: `app/ml/trainer.py`

- Add `force_model: bool = False` parameter to method signature (around line 410)
- When `force_model=True` and `model_name=="prophet"`:
  - Skip the eligibility check (lines 730-757) that checks `nonzero_days` and `zero_rate`
  - Skip the quick viability check (lines 759-782) that runs `_quick_prophet_viability_check()`
  - Add logging: `TRAIN_FORCE_MODEL: product_id=..., model=prophet, bypassed_prechecks=True`
- **Important**: Still perform all other checks:
  - Data validity checks
  - Leakage checks
  - Schema validation
  - Cancellation checks
  - Feature generation
  - Normal Prophet training

### 2. Update `ProductForecaster.forecast()` to use force_model and check requested model

**File**: `app/ml/forecaster.py`

- Store the requested `model_name` in a variable before calling trainer
- Pass `force_model=True` when calling `trainer.train()` if `model_name == "prophet"` (around line 167)
- Change the viability gate logic (around line 179) to check the REQUESTED model name:
  ```python
  requested_model = model_name  # Store original request
  train_result = self.trainer.train(..., model_name=model_name, force_model=(model_name=="prophet"))
  
  if requested_model == "prophet":  # Check requested, not result
      # Always attempt Prophet viability check
      if train_result.model_name != "prophet":
          # Prophet was skipped/failed - treat as viability failure
          logger.warning("Prophet training failed or was skipped, treating as viability failure")
          # Fallback logic...
      else:
          # Prophet trained successfully - check viability on predictions
          forecast_df = train_result.model.predict(...)
          is_prophet_viable, prophet_diagnostics = self._check_prophet_viability(...)
          # Existing fallback logic...
  ```

### 3. Handle Prophet training failures

- If `train_result.model_name != "prophet"` but we requested Prophet, treat this as a viability failure and trigger the fallback chain immediately
- Log the reason (e.g., "Prophet training failed, falling back to XGBoost")

## Files to Modify

- `app/ml/trainer.py`: Add `force_model` parameter and bypass early gates when True
- `app/ml/forecaster.py`: Pass `force_model=True` for Prophet requests, check requested model name instead of result model name

## Acceptance Criteria

1. When forecast requests Prophet, logs show `TRAIN_FORCE_MODEL: product_id=..., model=prophet, bypassed_prechecks=True`
2. Logs show `PROPHET_VIABILITY_CHECK` for that product
3. If Prophet horizon predictions are mostly negative, forecaster falls back and stores only fallback forecasts (no all-zero clamped Prophet output)
4. The viability gate runs based on the requested model, not the returned model name

