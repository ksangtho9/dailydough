from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.router import api_router
from .core.config import settings
from .db import Base, engine

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

# Create DB tables
Base.metadata.create_all(bind=engine)


@app.get("/", tags=["root"])
async def read_root() -> dict:
    return {"message": "BAKEZY API is running"}


# Mount all API routes under /api
app.include_router(api_router, prefix="/api")
