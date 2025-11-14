from fastapi import APIRouter

from .routes import product, sales, forecast

from app.models import User

api_router = APIRouter()

api_router.include_router(product.router)
api_router.include_router(sales.router)
api_router.include_router(forecast.router)
