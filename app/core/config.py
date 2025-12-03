from pydantic_settings import BaseSettings


class Settings(BaseSettings):
	app_name: str = "BAKEZY API"
	database_url: str = "sqlite:///./bakezy.db"
	# When true, broad analytics endpoints (dashboard summary, bake plan, etc.)
	# avoid triggering new on-demand forecasts and rely solely on precomputed
	# data. Useful in development to keep navigation snappy.
	disable_on_demand_analytics_forecasts: bool = False

	class Config:
		env_file = ".env"


settings = Settings()


