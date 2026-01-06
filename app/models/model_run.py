from sqlalchemy import (
    Column,
    Integer,
    ForeignKey,
    DateTime,
    String,
    JSON,
    Boolean,
    Date,
    func,
)
from sqlalchemy.orm import relationship

from app.database.database import Base


class ModelRun(Base):
    """
    Stores model training runs with hyperparameters and metadata.
    
    Separates model state/config from evaluation metrics (ForecastMetrics).
    Allows multiple runs per product, versioning, and tracking best vs most recent runs.
    """
    __tablename__ = "model_runs"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(
        Integer,
        ForeignKey("products.id"),
        nullable=False,
        index=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    model_type = Column(String, nullable=False)  # Requested model: "prophet", "xgboost", "ensemble", etc.
    selected_model_type = Column(String, nullable=False)  # Actual model used after gating/fallback
    hyperparameters_json = Column(JSON, nullable=True)  # Model-specific hyperparameters
    training_window_end = Column(Date, nullable=True)  # Last date in training data
    feature_version = Column(String, nullable=True)  # Hash/version of feature engineering
    metrics_json = Column(JSON, nullable=True)  # Optional: wape, wape_adjusted, etc.
    is_active = Column(Boolean, default=True, nullable=False)  # Latest run for this product
    is_best = Column(Boolean, default=False, nullable=False)  # Best performing run (for future use)
    forecast_model_override_reason = Column(String, nullable=True)  # If gating forced different model at forecast time

    product = relationship("Product", back_populates="model_runs")



