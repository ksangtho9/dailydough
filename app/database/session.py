from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from typing import Generator

from ..core.config import settings


DATABASE_URL = settings.database_url

# For SQLite, check_same_thread should be False. For other DBs, remove connect_args.
engine = create_engine(
	DATABASE_URL,
	connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator:
	db = SessionLocal()
	try:
		yield db
	finally:
		db.close()


