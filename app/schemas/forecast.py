from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class ProductForecastPoint(BaseModel):
    date: date
    quantity: float


class ProductForecastResponse(BaseModel):
    product_id: int
    points: list[ProductForecastPoint]


class ForecastMetricsSchema(BaseModel):
    product_id: int
    mape: Optional[float] = None
    rmse: Optional[float] = None
    n_points: int
    model_type: str
    status: str
    last_trained_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ProductTrainingResult(BaseModel):
    product_id: int
    product_name: Optional[str] = None
    status: str
    model_type: str
    n_points: int
    mape: Optional[float] = None
    rmse: Optional[float] = None
    last_trained_at: Optional[datetime] = None
    error: Optional[str] = None


class TrainAllProductsResult(BaseModel):
    trained_products: int
    failed_products: List[int]
    avg_mape: Optional[float]
    results: List[ProductTrainingResult]
