from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging
from pathlib import Path

from .api.router import api_router
from app.api.v1.routes import analytics
from app.api.v1 import api as v1_api
from .core.config import settings
from app.database.database import Base, engine

# ---------- Centralized logging configuration ----------
# Configure forecast-related loggers to write to forecast.log
# This ensures bakezy.forecast.api logs are written even if app/api/forecast.py
# is imported before app/ml/forecast_service.py sets up bakezy.forecast logger
LOG_DIR = Path("logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "forecast.log"

# Get or create the file handler for forecast.log
# Check if bakezy.forecast logger already has handlers (from app/ml/forecast_service.py)
forecast_logger = logging.getLogger("bakezy.forecast")
file_handler = None

if forecast_logger.handlers:
    # Reuse existing FileHandler if available (from app/ml/forecast_service.py)
    log_file_path = LOG_FILE.resolve()
    for handler in forecast_logger.handlers:
        if isinstance(handler, logging.FileHandler):
            # Check if it's writing to the same file
            handler_path = Path(handler.baseFilename).resolve()
            if handler_path == log_file_path:
                file_handler = handler
                break

# If no handler found, create a new one
if file_handler is None:
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(formatter)
    # Add to bakezy.forecast logger if it doesn't have handlers yet
    if not forecast_logger.handlers:
        forecast_logger.setLevel(logging.INFO)
        forecast_logger.addHandler(file_handler)

# Configure bakezy.forecast.api logger to use the same handler
forecast_api_logger = logging.getLogger("bakezy.forecast.api")
if not forecast_api_logger.handlers:
    forecast_api_logger.setLevel(logging.INFO)
    # Use the same handler as bakezy.forecast to write to the same file
    forecast_api_logger.addHandler(file_handler)
    # Don't propagate to root to avoid duplicate logs
    forecast_api_logger.propagate = False

app = FastAPI(title=settings.app_name)

# CORS configuration
# For local development, we want the Next.js frontend at
# http://localhost:3000 or http://127.0.0.1:3000 to call the API without
# \"Failed to fetch\" / CORS issues. This is intentionally permissive for dev.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create DB tables (using the same Base/engine as all models)
Base.metadata.create_all(bind=engine)


@app.get("/", tags=["root"])
async def read_root() -> dict:
    return {"message": "BAKEZY API is running"}


# Security headers middleware
from fastapi import Request

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Add security headers to all responses."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # HSTS only in production/staging
    if settings.environment in ("production", "prod", "staging"):
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


# Mount all API routes under /api
app.include_router(api_router, prefix="/api")
app.include_router(v1_api.api_router, prefix="/api/v1")
app.include_router(analytics.router, prefix="/api/v1")
