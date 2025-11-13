from fastapi import APIRouter

from .auth import router as auth_router

api_router = APIRouter()

# Auth routes under /api/auth/...
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])


@api_router.get("/health", tags=["health"])
async def health_check():
    return {"status": "ok"}