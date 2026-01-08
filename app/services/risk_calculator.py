"""
Risk calculator for bakeplan waste and stockout risk metrics.

Computes deterministic risk probabilities based on forecast uncertainty intervals.
"""

from typing import Optional
from scipy.stats import norm
import math


def calculate_risk_metrics(
    yhat: float,
    yhat_lower: Optional[float],
    yhat_upper: Optional[float],
    planned_qty: float,
    interval_level: Optional[float] = None,
) -> dict:
    """
    Calculate waste and stockout risk probabilities from forecast intervals.

    Args:
        yhat: Point forecast (mean expected demand)
        yhat_lower: Lower bound of forecast interval (P10 for 80% interval)
        yhat_upper: Upper bound of forecast interval (P90 for 80% interval)
        planned_qty: Planned production quantity (the decision variable)
        interval_level: Explicit interval level (e.g., 0.8 for 80%, 0.95 for 95%)
                        If None, assumes 0.8 (P10/P90) when bounds exist.

    Returns:
        Dictionary with:
        - waste_risk_prob: float (0-1) - P(demand < planned_qty)
        - stockout_risk_prob: float (0-1) - P(demand > planned_qty)
        - risk_sigma: float - Standard deviation used in calculation
        - interval_level_used: float | str - 0.8, 0.95, or "fallback"
        - risk_method: str - "interval_based" | "residual_based" | "fallback"
        - debug_source: str - "prophet_interval" | "xgb_interval" | "fallback"
        - sigma_clamped: bool - True if sigma was clamped to avoid division by zero
    """
    # Default values for fallback case
    waste_risk_prob = 0.5
    stockout_risk_prob = 0.5
    risk_sigma = None
    interval_level_used = "fallback"
    risk_method = "fallback"
    debug_source = "fallback"
    sigma_clamped = False

    # Case 1: Explicit interval_level provided
    if interval_level is not None:
        if yhat_lower is None or yhat_upper is None:
            # Can't compute sigma without bounds, use fallback
            risk_method = "fallback"
            debug_source = "fallback"
        else:
            z = norm.ppf(0.5 + interval_level / 2.0)
            sigma = (yhat_upper - yhat_lower) / (2.0 * z)
            interval_level_used = interval_level
            risk_method = "interval_based"
            debug_source = "prophet_interval"  # Assume Prophet, can be made configurable
            risk_sigma = sigma

    # Case 2: Bounds exist, assume 0.8 (P10/P90) per schema comments
    elif yhat_lower is not None and yhat_upper is not None:
        z = 1.281551565545  # For 80% interval (P10/P90)
        sigma = (yhat_upper - yhat_lower) / (2.0 * z)
        interval_level_used = 0.8
        risk_method = "interval_based"
        debug_source = "prophet_interval"
        risk_sigma = sigma

    # Case 3: No bounds or interval_level - use fallback
    else:
        # Fallback sigma = max(1.0, 0.2 * yhat)
        risk_sigma = max(1.0, 0.2 * max(yhat, 0.0))
        interval_level_used = "fallback"
        risk_method = "fallback"
        debug_source = "fallback"

    # Validate and clamp sigma to avoid division by zero or invalid values
    if risk_sigma is None or not math.isfinite(risk_sigma) or risk_sigma <= 0:
        risk_sigma = max(1.0, 0.2 * max(yhat, 0.0))
        sigma_clamped = True
    else:
        # Clamp to minimum to avoid numerical issues
        MIN_SIGMA = 1e-6
        if risk_sigma < MIN_SIGMA:
            risk_sigma = MIN_SIGMA
            sigma_clamped = True

    # Compute z-score: (planned_qty - mean) / sigma
    zscore = (planned_qty - yhat) / risk_sigma

    # Compute probabilities using normal CDF
    waste_risk_prob = norm.cdf(zscore)  # P(demand < planned_qty)
    stockout_risk_prob = 1.0 - norm.cdf(zscore)  # P(demand > planned_qty)

    # Ensure probabilities are valid (0-1 range) and sum to 1
    waste_risk_prob = max(0.0, min(1.0, waste_risk_prob))
    stockout_risk_prob = max(0.0, min(1.0, stockout_risk_prob))

    # Normalize to ensure they sum to 1 (handle floating point issues)
    total = waste_risk_prob + stockout_risk_prob
    if total > 0:
        waste_risk_prob = waste_risk_prob / total
        stockout_risk_prob = stockout_risk_prob / total

    return {
        "waste_risk_prob": waste_risk_prob,
        "stockout_risk_prob": stockout_risk_prob,
        "risk_sigma": risk_sigma,
        "interval_level_used": interval_level_used,
        "risk_method": risk_method,
        "debug_source": debug_source,
        "sigma_clamped": sigma_clamped,
    }



