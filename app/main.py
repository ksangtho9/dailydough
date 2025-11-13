from fastapi import FastAPI

from .api.router import api_router
from .core.config import settings


app = FastAPI(title=settings.app_name)


@app.get("/", tags=["root"])
async def read_root():
	return {"message": "BAKEZY API is running"}


app.include_router(api_router, prefix="/api")


