from fastapi import APIRouter

from .auth import router as auth_router
from .bakery import router as bakery_router
from .product import router as product_router

api_router = APIRouter()

# Auth routes under /api/auth/...
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])

# Bakery routes under /api/bakeries/...
api_router.include_router(bakery_router, prefix="/bakeries", tags=["bakeries"])

# Product routes under /api/products/...
api_router.include_router(product_router, prefix="/products", tags=["products"])


@api_router.get("/health", tags=["health"])
async def health_check():
    return {"status": "ok"}
