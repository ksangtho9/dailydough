from pydantic_settings import BaseSettings


class Settings(BaseSettings):
	app_name: str = "BAKEZY API"
	database_url: str = "sqlite:///./bakezy.db"

	class Config:
		env_file = ".env"


settings = Settings()


