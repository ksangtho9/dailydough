from fastapi import FastAPI

from .api.router import api_router
from .core.config import settings
from .db import Base, engine

app = FastAPI(title=settings.app_name)

# Create DB tables
Base.metadata.create_all(bind=engine)


@app.get("/", tags=["root"])
async def read_root() -> dict:
    return {"message": "BAKEZY API is running"}


# Mount all API routes under /api
app.include_router(api_router, prefix="/api")
