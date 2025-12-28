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

	class Config:
		env_file = ".env"


settings = Settings()


