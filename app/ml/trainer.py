from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

import pandas as pd

from .preprocessing import CleanedTimeSeries
from .features import FeatureEngineer
from .models.prophet_model import ProphetSalesModel
from .models.xgboost_model import XGBoostSalesModel


ModelName = Literal["prophet", "xgboost"]


@dataclass
class TrainResult:
    model_name: ModelName
    # In MLOps v2, you might store metrics here (MAE, MAPE, etc.)
    # For now this is a simple placeholder.
    model: object


class ModelTrainer:
    def __init__(self, feature_engineer: Optional[FeatureEngineer] = None):
        self.feature_engineer = feature_engineer or FeatureEngineer()

    def train(
        self,
        ts: CleanedTimeSeries,
        model_name: ModelName = "prophet",
        holidays_df: Optional[pd.DataFrame] = None,
        weather_df: Optional[pd.DataFrame] = None,
        promotions_df: Optional[pd.DataFrame] = None,
        events_df: Optional[pd.DataFrame] = None,
        product_info: Optional[dict] = None,
    ) -> TrainResult:
        """
        High-level training routine for a single product time series.
        """
        df = ts.df.copy()

        # Feature engineering
        df["ds"] = pd.to_datetime(df["ds"])
        df = self.feature_engineer.transform(
            df,
            holidays_df=holidays_df,
            weather_df=weather_df,
            promotions_df=promotions_df,
            events_df=events_df,
            product_info=product_info,
        )

        if model_name == "prophet":
            # Prophet needs ds, y, and optionally delivery as regressor
            model = ProphetSalesModel()
            model.fit(df)
            return TrainResult(model_name="prophet", model=model)

        elif model_name == "xgboost":
            model = XGBoostSalesModel()
            model.fit(df)
            return TrainResult(model_name="xgboost", model=model)

        else:
            raise ValueError(f"Unsupported model: {model_name}")
