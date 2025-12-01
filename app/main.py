from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.router import api_router
from app.api.v1.routes import analytics
from app.api.v1 import api as v1_api
from .core.config import settings
from app.database.database import Base, engine

app = FastAPI(title=settings.app_name)

origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create DB tables (using the same Base/engine as all models)
Base.metadata.create_all(bind=engine)


@app.get("/", tags=["root"])
async def read_root() -> dict:
    return {"message": "BAKEZY API is running"}


# Mount all API routes under /api
app.include_router(api_router, prefix="/api")
app.include_router(v1_api.api_router, prefix="/api/v1")
app.include_router(analytics.router, prefix="/api/v1")
