import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
	app_name: str = "BAKEZY API"
	database_url: str = "sqlite:///./bakezy.db"
	# When true, broad analytics endpoints (dashboard summary, bake plan, etc.)
	# avoid triggering new on-demand forecasts and rely solely on precomputed
	# data. Useful in development to keep navigation snappy.
	disable_on_demand_analytics_forecasts: bool = False
	# Admin mode: enables /api/admin/* endpoints
	# Default: True in dev/local, False in prod unless explicitly enabled
	# Set ADMIN_MODE_ENABLED=true in .env to enable in production
	admin_mode_enabled: bool = True
	
	# Prophet eligibility thresholds
	prophet_min_nonzero_days: int = int(os.getenv("PROPHET_MIN_NONZERO_DAYS", "10"))
	prophet_max_zero_rate: float = float(os.getenv("PROPHET_MAX_ZERO_RATE", "0.6"))
	
	# Guardrail thresholds for zero prediction detection
	zero_guardrail_train_max: float = float(os.getenv("ZERO_GUARDRAIL_TRAIN_MAX", "0.3"))
	zero_guardrail_pred_min: float = float(os.getenv("ZERO_GUARDRAIL_PRED_MIN", "0.6"))
	
	# Minimum training window (days)
	min_training_window: int = int(os.getenv("MIN_TRAINING_WINDOW", "14"))
	
	# Evaluation window for validation (last N valid days)
	eval_window_days: int = int(os.getenv("EVAL_WINDOW_DAYS", "14"))

	class Config:
		env_file = ".env"


settings = Settings()


