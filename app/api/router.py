from fastapi import APIRouter

from .auth import router as auth_router
from .bakery import router as bakery_router
from .product import router as product_router
from .sales import router as sales_router
from .forecast import router as forecast_router
from .debug import router as debug_router
from .demo import router as demo_router
from .forecast_training import router as forecast_training_router
from .bake_plan import router as bake_plan_router
from .top_products import router as top_products_router
from .weekday_pattern import router as weekday_pattern_router
from .forecast_vs_actual import router as forecast_vs_actual_router
from .dashboard_summary import router as dashboard_summary_router

api_router = APIRouter()

api_router.include_router(auth_router)
api_router.include_router(bakery_router)
api_router.include_router(product_router)
api_router.include_router(sales_router)
api_router.include_router(forecast_router)
api_router.include_router(debug_router)
api_router.include_router(demo_router)
api_router.include_router(forecast_training_router)
api_router.include_router(bake_plan_router)
api_router.include_router(top_products_router)
api_router.include_router(weekday_pattern_router)
api_router.include_router(forecast_vs_actual_router)
api_router.include_router(dashboard_summary_router)
