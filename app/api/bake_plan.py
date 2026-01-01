from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import exc as sa_exc
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models import Bakery, Product, DailyForecast
from app.ml.inference.forecast_service import get_forecast_for_product
from app.services.daily_forecast_service import upsert_product_daily_forecasts
from app.services.risk_calculator import calculate_risk_metrics
from app.core.config import settings
from app.schemas.bake_plan import BakePlanItem, BakePlanResponse

logger = logging.getLogger("bakezy.bake_plan")

router = APIRouter(tags=["bake-plan"])


@router.get(
    "/bakeries/{bakery_id}/bake-plan",
    response_model=BakePlanResponse,
)
def get_bake_plan(
    bakery_id: int,
    target_date: date | None = Query(
        default=None,
        description="ISO date. Defaults to tomorrow.",
    ),
    db: Session = Depends(get_db),
):
    bakery = db.query(Bakery).filter(Bakery.id == bakery_id).one_or_none()
    if bakery is None:
        raise HTTPException(status_code=404, detail="Bakery not found")

    plan_date = target_date or (date.today() + timedelta(days=1))

    # Generate request_id for end-to-end tracing
    request_id = uuid.uuid4().hex[:8]

    products = (
        db.query(Product)
        .filter(Product.bakery_id == bakery_id)
        .order_by(Product.name.asc())
        .all()
    )

    items: List[BakePlanItem] = []
    
    logger.info(
        "Bake plan request: request_id=%s, bakery_id=%d, plan_date=%s, products_count=%d",
        request_id,
        bakery_id,
        plan_date.isoformat(),
        len(products),
    )

    # Try to use precomputed daily forecasts for the plan date, falling back
    # to on-demand forecasting only for products that are missing rows.
    precomputed_rows = (
        db.query(DailyForecast)
        .filter(
            DailyForecast.bakery_id == bakery_id,
            DailyForecast.date == plan_date,
        )
        .all()
    )
    precomputed_by_product = {row.product_id: row for row in precomputed_rows}
    
    # #region agent log
    import json
    import time
    try:
        log_entry = {
            "sessionId": "debug-session",
            "runId": "run1",
            "hypothesisId": "F",
            "location": "bake_plan.py:67",
            "message": "Bake plan forecast query",
            "data": {
                "bakery_id": bakery_id,
                "plan_date": plan_date.isoformat(),
                "total_products": len(products),
                "precomputed_count": len(precomputed_rows),
                "precomputed_product_ids": [r.product_id for r in precomputed_rows],
                "missing_product_ids": [p.id for p in products if p.id not in precomputed_by_product]
            },
            "timestamp": int(time.time() * 1000)
        }
        with open(r"c:\Users\forfl\Documents\dailydough-1\.cursor\debug.log", "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")
    except Exception:
        pass
    # #endregion

    for product in products:
        # Extract all ORM attributes before any database operations that might fail
        # This prevents PendingRollbackError when accessing attributes after rollback
        product_id = product.id
        product_name = product.name
        product_sku = product.sku
        
        # #region agent log
        try:
            import json
            import time
            log_entry = {
                "sessionId": "debug-session",
                "runId": "run1",
                "hypothesisId": "J",
                "location": "bake_plan.py:95",
                "message": "Processing product for bake plan",
                "data": {
                    "product_id": product_id,
                    "product_name": product_name,
                    "plan_date": plan_date.isoformat(),
                    "today": today.isoformat()
                },
                "timestamp": int(time.time() * 1000)
            }
            with open(r"c:\Users\forfl\Documents\dailydough-1\.cursor\debug.log", "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry) + "\n")
        except Exception:
            pass
        # #endregion
        
        row = precomputed_by_product.get(product_id)

        if row is None and not settings.disable_on_demand_analytics_forecasts:
            # Fallback: run a single on-demand forecast for this product,
            # then store its daily points for future requests.
            # Generate 60 days ahead (same as training) to ensure we cover any reasonable plan_date.
            # Forecasts start from last_train_date + 1, not today, so we need a large enough horizon.
            days_needed = 60
            today = date.today()
            try:
                # #region agent log
                try:
                    import json
                    import time
                    log_entry = {
                        "sessionId": "debug-session",
                        "runId": "run1",
                        "hypothesisId": "G",
                        "location": "bake_plan.py:104",
                        "message": "Attempting on-demand forecast",
                        "data": {
                            "product_id": product_id,
                            "product_name": product_name,
                            "plan_date": plan_date.isoformat(),
                            "today": today.isoformat(),
                            "days_needed": days_needed,
                            "disable_on_demand": settings.disable_on_demand_analytics_forecasts
                        },
                        "timestamp": int(time.time() * 1000)
                    }
                    with open(r"c:\Users\forfl\Documents\dailydough-1\.cursor\debug.log", "a", encoding="utf-8") as f:
                        f.write(json.dumps(log_entry) + "\n")
                except Exception:
                    pass
                # #endregion
                # Retry forecast generation up to 2 times if it fails
                forecast_attempts = 0
                max_attempts = 2
                forecast = None
                
                while forecast_attempts < max_attempts and forecast is None:
                    try:
                        forecast_attempts += 1
                        forecast = get_forecast_for_product(
                            product_id=product_id,
                            days_ahead=days_needed,
                            db=db,
                        )
                        
                        # Validate forecast has points
                        if not forecast or not forecast.points:
                            raise ValueError(f"Forecast returned empty points for product_id={product_id}")
                            
                    except Exception as forecast_error:
                        if forecast_attempts >= max_attempts:
                            # Final attempt failed - log error but continue to show product with 0 forecast
                            logger.error(
                                f"Failed to generate on-demand forecast for product_id={product_id}, "
                                f"product_name={product_name} after {max_attempts} attempts: {forecast_error}",
                                exc_info=True
                            )
                            # #region agent log
                            try:
                                log_entry = {
                                    "sessionId": "debug-session",
                                    "runId": "run1",
                                    "hypothesisId": "H",
                                    "location": "bake_plan.py:136",
                                    "message": "On-demand forecast generation failed after retries",
                                    "data": {
                                        "product_id": product_id,
                                        "product_name": product_name,
                                        "error": str(forecast_error),
                                        "error_type": type(forecast_error).__name__,
                                        "attempts": forecast_attempts
                                    },
                                    "timestamp": int(time.time() * 1000)
                                }
                                with open(r"c:\Users\forfl\Documents\dailydough-1\.cursor\debug.log", "a", encoding="utf-8") as f:
                                    f.write(json.dumps(log_entry) + "\n")
                            except Exception:
                                pass
                            # #endregion
                            forecast = None  # Will show product with 0 forecast
                        else:
                            logger.warning(
                                f"On-demand forecast attempt {forecast_attempts}/{max_attempts} failed for "
                                f"product_id={product_id}, product_name={product_name}: {forecast_error}. Retrying...",
                                exc_info=True
                            )
                
                if forecast is not None:
                    # #region agent log
                    try:
                        forecast_dates = [p.date.isoformat() if hasattr(p.date, 'isoformat') else str(p.date) for p in forecast.points] if forecast and forecast.points else []
                        plan_date_in_forecast = any(
                            (p.date == plan_date if hasattr(p.date, '__eq__') else str(p.date) == plan_date.isoformat())
                            for p in (forecast.points if forecast else [])
                        )
                        log_entry = {
                            "sessionId": "debug-session",
                            "runId": "run1",
                            "hypothesisId": "G",
                            "location": "bake_plan.py:120",
                            "message": "Forecast generated successfully",
                            "data": {
                                "product_id": product_id,
                                "forecast_points_count": len(forecast.points) if forecast else 0,
                                "plan_date": plan_date.isoformat(),
                                "plan_date_in_forecast": plan_date_in_forecast,
                                "forecast_date_range": f"{forecast_dates[0]} to {forecast_dates[-1]}" if forecast_dates else "none",
                                "sample_forecast_dates": forecast_dates[:5]
                            },
                            "timestamp": int(time.time() * 1000)
                        }
                        with open(r"c:\Users\forfl\Documents\dailydough-1\.cursor\debug.log", "a", encoding="utf-8") as f:
                            f.write(json.dumps(log_entry) + "\n")
                    except Exception:
                        pass
                    # #endregion
                    try:
                        upsert_product_daily_forecasts(
                            db,
                            product=product,
                            forecast=forecast,
                        )
                    except Exception as storage_error:
                        logger.error(
                            f"Failed to store forecast for product_id={product_id}, product_name={product_name}: {storage_error}",
                            exc_info=True
                        )
                        # Continue anyway - we'll try to query the row, and if it's not there, show 0
                    
                    # #region agent log
                    try:
                        log_entry = {
                            "sessionId": "debug-session",
                            "runId": "run1",
                            "hypothesisId": "G",
                            "location": "bake_plan.py:130",
                            "message": "Forecast stored, querying back",
                            "data": {
                                "product_id": product_id,
                                "plan_date": plan_date.isoformat()
                            },
                            "timestamp": int(time.time() * 1000)
                        }
                        with open(r"c:\Users\forfl\Documents\dailydough-1\.cursor\debug.log", "a", encoding="utf-8") as f:
                            f.write(json.dumps(log_entry) + "\n")
                    except Exception:
                        pass
                    # #endregion
                    row = (
                        db.query(DailyForecast)
                        .filter(
                            DailyForecast.bakery_id == bakery_id,
                            DailyForecast.product_id == product_id,
                            DailyForecast.date == plan_date,
                        )
                        .one_or_none()
                    )
                    # #region agent log
                    try:
                        log_entry = {
                            "sessionId": "debug-session",
                            "runId": "run1",
                            "hypothesisId": "G",
                            "location": "bake_plan.py:140",
                            "message": "Row query result",
                            "data": {
                                "product_id": product_id,
                                "plan_date": plan_date.isoformat(),
                                "row_found": row is not None,
                                "row_yhat": float(row.yhat) if row and row.yhat else None
                            },
                            "timestamp": int(time.time() * 1000)
                        }
                        with open(r"c:\Users\forfl\Documents\dailydough-1\.cursor\debug.log", "a", encoding="utf-8") as f:
                            f.write(json.dumps(log_entry) + "\n")
                    except Exception:
                        pass
                    # #endregion
            
            except sa_exc.OperationalError as e:
                # Handle SQLite "database is locked" errors gracefully by rolling
                # back the current transaction and skipping this product.
                msg = str(e.orig) if getattr(e, "orig", None) is not None else str(e)
                if "database is locked" in msg.lower():
                    logger.warning(
                        "Bake plan: database is locked while upserting daily forecasts for "
                        "product_id=%d, skipping this product for bakery_id=%d, plan_date=%s",
                        product_id,
                        bakery_id,
                        plan_date.isoformat(),
                        exc_info=True,
                    )
                    try:
                        db.rollback()
                    except Exception as rollback_error:
                        logger.warning(
                            f"Error during rollback: {rollback_error}. "
                            "Session may already be in a bad state."
                        )
                    continue
                # Re-raise other OperationalError instances
                raise
            except sa_exc.PendingRollbackError as e:
                # Handle case where session is already in a bad state
                logger.warning(
                    "Session in bad state for product_id=%d, rolling back and skipping: %s",
                    product_id,
                    str(e),
                    exc_info=True,
                )
                try:
                    db.rollback()
                except Exception:
                    # Ignore errors during rollback of already-bad session
                    pass
                continue
            except Exception as e:
                # #region agent log
                try:
                    import json
                    import time
                    log_entry = {
                        "sessionId": "debug-session",
                        "runId": "run1",
                        "hypothesisId": "G",
                        "location": "bake_plan.py:164",
                        "message": "Forecast generation failed",
                        "data": {
                            "product_id": product_id,
                            "product_name": product_name,
                            "error": str(e),
                            "error_type": type(e).__name__
                        },
                        "timestamp": int(time.time() * 1000)
                    }
                    with open(r"c:\Users\forfl\Documents\dailydough-1\.cursor\debug.log", "a", encoding="utf-8") as f:
                        f.write(json.dumps(log_entry) + "\n")
                except Exception:
                    pass
                # #endregion
                logger.warning(
                    "Failed to generate forecast for product_id=%d, product_name=%s: %s",
                    product_id,
                    product_name,
                    str(e),
                    exc_info=True,
                )
                try:
                    db.rollback()
                except Exception as rollback_error:
                    logger.warning(
                        f"Error during rollback: {rollback_error}. "
                        "Session may already be in a bad state."
                    )
                continue

        # Show all products, even if they don't have forecasts
        # Products without forecasts will show 0 forecast_quantity
        if row is None:
            # #region agent log
            try:
                import json
                import time
                log_entry = {
                    "sessionId": "debug-session",
                    "runId": "run1",
                    "hypothesisId": "G",
                    "location": "bake_plan.py:181",
                    "message": "Product has no forecast - using 0",
                    "data": {
                        "product_id": product_id,
                        "product_name": product_name,
                        "plan_date": plan_date.isoformat(),
                        "disable_on_demand": settings.disable_on_demand_analytics_forecasts
                    },
                    "timestamp": int(time.time() * 1000)
                }
                with open(r"c:\Users\forfl\Documents\dailydough-1\.cursor\debug.log", "a", encoding="utf-8") as f:
                    f.write(json.dumps(log_entry) + "\n")
            except Exception:
                pass
            # #endregion
            # Product has no forecast - show it with 0 quantity instead of skipping
            forecast_qty = 0
        else:
            qty = float(row.yhat or 0.0)
            forecast_qty = max(0, int(round(qty)))
            # #region agent log
            try:
                log_entry = {
                    "sessionId": "debug-session",
                    "runId": "run1",
                    "hypothesisId": "J",
                    "location": "bake_plan.py:392",
                    "message": "Forecast quantity calculated",
                    "data": {
                        "product_id": product_id,
                        "product_name": product_name,
                        "plan_date": plan_date.isoformat(),
                        "yhat": qty,
                        "forecast_qty": forecast_qty
                    },
                    "timestamp": int(time.time() * 1000)
                }
                with open(r"c:\Users\forfl\Documents\dailydough-1\.cursor\debug.log", "a", encoding="utf-8") as f:
                    f.write(json.dumps(log_entry) + "\n")
            except Exception:
                pass
            # #endregion
        
        # Include products even with zero forecast (they might have been skipped during training)
        # Only skip if explicitly requested to hide zero forecasts
        # if forecast_qty <= 0:
        #     logger.debug(
        #         "Forecast quantity is zero or negative for product_id=%d (yhat=%.2f)",
        #         product_id,
        #         qty,
        #     )
        #     continue

        logger.debug(
            "Adding product to bake plan: product_id=%d, forecast_quantity=%d",
            product_id,
            forecast_qty,
        )

        # Calculate risk metrics if we have forecast data
        risk_metrics = None
        if row is not None:
            yhat = float(row.yhat or 0.0)
            yhat_lower = float(row.yhat_lower) if row.yhat_lower is not None else None
            yhat_upper = float(row.yhat_upper) if row.yhat_upper is not None else None
            
            risk_metrics = calculate_risk_metrics(
                yhat=yhat,
                yhat_lower=yhat_lower,
                yhat_upper=yhat_upper,
                planned_qty=float(forecast_qty),
                interval_level=None,  # Assume 0.8 (P10/P90) per schema
            )

            # Log risk calculation per product
            logger.info(
                "Risk calculation: request_id=%s, bakery_id=%d, product_id=%d, date=%s, "
                "yhat=%.2f, lower=%s, upper=%s, planned_qty=%d, "
                "waste_risk_prob=%.4f, stockout_risk_prob=%.4f, risk_method=%s, "
                "interval_level_used=%s, risk_sigma=%.4f, sigma_clamped=%s",
                request_id,
                bakery_id,
                product_id,
                plan_date.isoformat(),
                yhat,
                f"{yhat_lower:.2f}" if yhat_lower is not None else "None",
                f"{yhat_upper:.2f}" if yhat_upper is not None else "None",
                forecast_qty,
                risk_metrics["waste_risk_prob"],
                risk_metrics["stockout_risk_prob"],
                risk_metrics["risk_method"],
                risk_metrics["interval_level_used"],
                risk_metrics["risk_sigma"],
                risk_metrics["sigma_clamped"],
            )
        else:
            # No forecast data - risk metrics remain None
            logger.debug(
                "No forecast row for product_id=%d, date=%s - skipping risk calculation",
                product_id,
                plan_date.isoformat(),
            )

        items.append(
            BakePlanItem(
                product_id=product_id,
                product_name=product_name,
                forecast_quantity=forecast_qty,
                sku=product_sku,
                waste_risk_prob=risk_metrics["waste_risk_prob"] if risk_metrics else None,
                stockout_risk_prob=risk_metrics["stockout_risk_prob"] if risk_metrics else None,
                risk_sigma=risk_metrics["risk_sigma"] if risk_metrics else None,
                interval_level_used=risk_metrics["interval_level_used"] if risk_metrics else None,
                risk_method=risk_metrics["risk_method"] if risk_metrics else None,
                debug_source=risk_metrics["debug_source"] if risk_metrics else None,
                sigma_clamped=risk_metrics["sigma_clamped"] if risk_metrics else None,
            )
        )

    items.sort(key=lambda x: x.forecast_quantity, reverse=True)

    logger.info(
        "Bake plan generated successfully: bakery_id=%d, plan_date=%s, items_count=%d",
        bakery.id,
        plan_date.isoformat(),
        len(items),
    )

    return BakePlanResponse(
        bakery_id=bakery.id,
        bakery_name=bakery.name,
        date=plan_date,
        items=items,
    )




