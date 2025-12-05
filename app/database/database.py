from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker


SQLALCHEMY_DATABASE_URL = "sqlite:///./bakezy.db"

# For SQLite, check_same_thread should be False.
# Note: SQLite doesn't support connection pooling in the traditional sense,
# but we can configure it for better concurrency handling.
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={
        "check_same_thread": False,
        # Wait up to 30 seconds for a locked database before failing.
        "timeout": 30,
    },
    # Enable connection pool pre-ping to detect stale connections
    pool_pre_ping=True,
    # For SQLite, pool_size and max_overflow don't apply, but we set them
    # for consistency and in case we switch to a different database later
    pool_size=5,
    max_overflow=10,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """
    Enable WAL mode for better concurrency with SQLite.
    This is safe to run on every new connection.
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL;")
    finally:
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
