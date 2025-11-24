from fastapi import APIRouter

from .auth import router as auth_router
from .bakery import router as bakery_router
from .product import router as product_router
from .sales import router as sales_router
from .forecast import router as forecast_router
from .debug import router as debug_router

api_router = APIRouter()

api_router.include_router(auth_router)
api_router.include_router(bakery_router)
api_router.include_router(product_router)
api_router.include_router(sales_router)
api_router.include_router(forecast_router)
api_router.include_router(debug_router) 
