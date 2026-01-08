import os
import json
from typing import Optional
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DEV_JWT = "CHANGE_ME_TO_A_LONG_RANDOM_STRING_DEV_ONLY"


class Settings(BaseSettings):
	# Note: .env file is optional for local development. Production must use environment variables.
	# .env is gitignored and should not be committed.
	model_config = SettingsConfigDict(env_file=".env", extra="ignore")
	
	app_name: str = "BAKEZY API"
	database_url: str = "sqlite:///./bakezy.db"
	
	# Environment detection
	environment: str = Field(default="development", alias="ENVIRONMENT")
	
	# Admin mode: default to False for security (must explicitly enable)
	# Set ADMIN_MODE_ENABLED=true in .env or environment to enable
	admin_mode_enabled: bool = Field(default=False, alias="ADMIN_MODE_ENABLED")
	
	# JWT secret key for token signing
	# In production, MUST be set via JWT_SECRET_KEY environment variable
	jwt_secret_key: str = Field(default=DEFAULT_DEV_JWT, alias="JWT_SECRET_KEY")
	
	# CORS origins (comma-separated string or JSON array in env)
	cors_origins: list[str] = Field(
		default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"],
		alias="CORS_ORIGINS",
	)
	
	# File upload size limit
	max_upload_size_mb: int = Field(default=10, alias="MAX_UPLOAD_SIZE_MB")
	max_upload_size_bytes: Optional[int] = Field(default=None, alias="MAX_UPLOAD_SIZE_BYTES")
	
	# When true, broad analytics endpoints (dashboard summary, bake plan, etc.)
	# avoid triggering new on-demand forecasts and rely solely on precomputed
	# data. Useful in development to keep navigation snappy.
	disable_on_demand_analytics_forecasts: bool = False
	
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
	
	# Hyperparameter reuse settings
	hyperparam_reuse_days: int = int(os.getenv("HYPERPARAM_REUSE_DAYS", "7"))
	
	# Reduced optimization settings for retraining (configurable, not hard-coded)
	prophet_opt_max_iter_retrain: int = int(os.getenv("PROPHET_OPT_MAX_ITER_RETRAIN", "4"))
	xgb_opt_max_iter_retrain: int = int(os.getenv("XGB_OPT_MAX_ITER_RETRAIN", "9"))
	cv_splits_retrain: int = int(os.getenv("CV_SPLITS_RETRAIN", "2"))
	
	# Zero forecast investigation: enable deep diagnostic logging
	debug_zero_forecasts: bool = os.getenv("DEBUG_ZERO_FORECASTS", "false").lower() == "true"
	
	# Product IDs for which to enable deep diagnostic logging (comma-separated, e.g., "194,156")
	debug_forecast_product_ids: list[int] = [
		int(pid.strip()) 
		for pid in os.getenv("DEBUG_FORECAST_PRODUCT_IDS", "").split(",") 
		if pid.strip().isdigit()
	]
	
	@field_validator("environment")
	@classmethod
	def _normalize_env(cls, v: str) -> str:
		"""Normalize environment to lowercase."""
		return (v or "development").lower().strip()
	
	@field_validator("cors_origins", mode="before")
	@classmethod
	def _parse_cors_origins(cls, v):
		"""Parse CORS_ORIGINS from env (comma-separated string or JSON array)."""
		if v is None:
			return v
		if isinstance(v, str):
			s = v.strip()
			if s.startswith("["):
				# Try JSON array first, fall back to comma-splitting if it fails
				try:
					return json.loads(s)
				except (json.JSONDecodeError, ValueError):
					# If JSON parsing fails, treat as comma-separated string
					return [o.strip() for o in s.split(",") if o.strip()]
			return [o.strip() for o in s.split(",") if o.strip()]
		return v
	
	@model_validator(mode="after")
	def _fail_fast_prod_jwt(self):
		"""Fail fast if production uses default JWT secret."""
		if self.environment in ("production", "prod", "staging") and self.jwt_secret_key == DEFAULT_DEV_JWT:
			raise ValueError("JWT_SECRET_KEY must be set in production.")
		return self
	
	@model_validator(mode="after")
	def _compute_upload_size_bytes(self):
		"""Compute bytes from MB setting if not explicitly set."""
		if self.max_upload_size_bytes is None:
			self.max_upload_size_bytes = self.max_upload_size_mb * 1024 * 1024
		return self


settings = Settings()


