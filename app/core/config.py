from __future__ import annotations
import os
import json
from typing import Optional
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Note: .env file is optional for local development. Production must use environment variables.
    # .env is gitignored and should not be committed.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "BAKEZY API"
    database_url: str = Field(default="", alias="DATABASE_URL")

    environment: str = Field(default="development", alias="ENVIRONMENT")

    # Supabase Auth — JWT secret for verifying Supabase-issued tokens
    supabase_jwt_secret: str = Field(default="", alias="SUPABASE_JWT_SECRET")
    supabase_url: str = Field(default="", alias="SUPABASE_URL")
    supabase_anon_key: str = Field(default="", alias="SUPABASE_ANON_KEY")
    supabase_service_role_key: str = Field(default="", alias="SUPABASE_SERVICE_ROLE_KEY")

    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"],
        alias="CORS_ORIGINS",
    )

    max_upload_size_mb: int = Field(default=10, alias="MAX_UPLOAD_SIZE_MB")
    max_upload_size_bytes: Optional[int] = Field(default=None, alias="MAX_UPLOAD_SIZE_BYTES")

    # When true, analytics endpoints avoid triggering on-demand forecasts.
    disable_on_demand_analytics_forecasts: bool = Field(
        default=False, alias="DISABLE_ON_DEMAND_ANALYTICS_FORECASTS"
    )

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

    # How many days to reuse cached hyperparameters before re-tuning
    hyperparam_reuse_days: int = 7

    debug_zero_forecasts: bool = os.getenv("DEBUG_ZERO_FORECASTS", "false").lower() == "true"

    @field_validator("environment")
    @classmethod
    def _normalize_env(cls, v: str) -> str:
        return (v or "development").lower().strip()

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, v):
        if v is None:
            return v
        if isinstance(v, str):
            s = v.strip()
            if s.startswith("["):
                try:
                    return json.loads(s)
                except (json.JSONDecodeError, ValueError):
                    return [o.strip() for o in s.split(",") if o.strip()]
            return [o.strip() for o in s.split(",") if o.strip()]
        return v

    @model_validator(mode="after")
    def _fail_fast_prod_jwt(self):
        if self.environment in ("production", "prod", "staging") and not self.supabase_jwt_secret:
            raise ValueError("SUPABASE_JWT_SECRET must be set in production.")
        return self

    @model_validator(mode="after")
    def _compute_upload_size_bytes(self):
        if self.max_upload_size_bytes is None:
            self.max_upload_size_bytes = self.max_upload_size_mb * 1024 * 1024
        return self


settings = Settings()
