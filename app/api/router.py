from fastapi import APIRouter


api_router = APIRouter()

from .auth import router as auth_router
from .sales import router as sales_router

api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(sales_router, tags=["sales"])


@api_router.get("/health", tags=["health"])
async def health_check():
	return {"status": "ok"}


