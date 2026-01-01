"""
Unit tests for risk calculator.

Tests deterministic risk calculations, monotonicity, and edge cases.
"""

import pytest
from app.services.risk_calculator import calculate_risk_metrics


def test_sigma_from_80_percent_interval():
    """Test sigma calculation for 80% interval (P10/P90)."""
    # For 80% interval, z = 1.281551565545
    # sigma = (upper - lower) / (2 * 1.281551565545)
    yhat = 100.0
    yhat_lower = 80.0  # P10
    yhat_upper = 120.0  # P90
    planned_qty = 100.0
    
    result = calculate_risk_metrics(
        yhat=yhat,
        yhat_lower=yhat_lower,
        yhat_upper=yhat_upper,
        planned_qty=planned_qty,
    )
    
    # Expected sigma: (120 - 80) / (2 * 1.281551565545) ≈ 15.598
    expected_sigma = (120.0 - 80.0) / (2.0 * 1.281551565545)
    
    assert result["risk_method"] == "interval_based"
    assert result["interval_level_used"] == 0.8
    assert result["debug_source"] == "prophet_interval"
    assert abs(result["risk_sigma"] - expected_sigma) < 0.01
    assert result["waste_risk_prob"] + result["stockout_risk_prob"] == pytest.approx(1.0, abs=1e-6)


def test_risk_monotonicity():
    """Test that as planned_qty increases, stockout decreases and waste increases."""
    yhat = 100.0
    yhat_lower = 80.0
    yhat_upper = 120.0
    
    planned_qty_values = [50.0, 80.0, 100.0, 120.0, 150.0]
    results = []
    
    for planned_qty in planned_qty_values:
        result = calculate_risk_metrics(
            yhat=yhat,
            yhat_lower=yhat_lower,
            yhat_upper=yhat_upper,
            planned_qty=planned_qty,
        )
        results.append({
            "planned_qty": planned_qty,
            "waste": result["waste_risk_prob"],
            "stockout": result["stockout_risk_prob"],
        })
    
    # Check monotonicity: waste should increase, stockout should decrease
    for i in range(1, len(results)):
        assert results[i]["waste"] >= results[i-1]["waste"], \
            f"Waste should increase as planned_qty increases: {results[i-1]['planned_qty']} -> {results[i]['planned_qty']}"
        assert results[i]["stockout"] <= results[i-1]["stockout"], \
            f"Stockout should decrease as planned_qty increases: {results[i-1]['planned_qty']} -> {results[i]['planned_qty']}"


def test_edge_case_missing_bounds():
    """Test fallback when bounds are missing."""
    yhat = 100.0
    planned_qty = 100.0
    
    result = calculate_risk_metrics(
        yhat=yhat,
        yhat_lower=None,
        yhat_upper=None,
        planned_qty=planned_qty,
    )
    
    assert result["risk_method"] == "fallback"
    assert result["interval_level_used"] == "fallback"
    assert result["debug_source"] == "fallback"
    assert result["risk_sigma"] == pytest.approx(max(1.0, 0.2 * 100.0), abs=0.01)
    assert 0.0 <= result["waste_risk_prob"] <= 1.0
    assert 0.0 <= result["stockout_risk_prob"] <= 1.0
    assert result["waste_risk_prob"] + result["stockout_risk_prob"] == pytest.approx(1.0, abs=1e-6)


def test_edge_case_yhat_zero():
    """Test behavior when yhat is zero."""
    yhat = 0.0
    yhat_lower = 0.0
    yhat_upper = 10.0
    planned_qty = 5.0
    
    result = calculate_risk_metrics(
        yhat=yhat,
        yhat_lower=yhat_lower,
        yhat_upper=yhat_upper,
        planned_qty=planned_qty,
    )
    
    assert result["risk_sigma"] > 0
    assert 0.0 <= result["waste_risk_prob"] <= 1.0
    assert 0.0 <= result["stockout_risk_prob"] <= 1.0
    assert result["waste_risk_prob"] + result["stockout_risk_prob"] == pytest.approx(1.0, abs=1e-6)


def test_edge_case_planned_zero():
    """Test behavior when planned_qty is zero."""
    yhat = 100.0
    yhat_lower = 80.0
    yhat_upper = 120.0
    planned_qty = 0.0
    
    result = calculate_risk_metrics(
        yhat=yhat,
        yhat_lower=yhat_lower,
        yhat_upper=yhat_upper,
        planned_qty=planned_qty,
    )
    
    # When planned_qty = 0 and yhat > 0, waste risk should be very low, stockout very high
    assert result["waste_risk_prob"] < 0.01  # Almost no waste (can't go below 0)
    assert result["stockout_risk_prob"] > 0.99  # Almost certain stockout
    assert result["waste_risk_prob"] + result["stockout_risk_prob"] == pytest.approx(1.0, abs=1e-6)


def test_edge_case_sigma_clamped():
    """Test that sigma is clamped when interval width is very small."""
    yhat = 100.0
    yhat_lower = 99.9  # Very narrow interval
    yhat_upper = 100.1
    planned_qty = 100.0
    
    result = calculate_risk_metrics(
        yhat=yhat,
        yhat_lower=yhat_lower,
        yhat_upper=yhat_upper,
        planned_qty=planned_qty,
    )
    
    # Sigma should be clamped to at least 1e-6
    assert result["risk_sigma"] >= 1e-6
    assert 0.0 <= result["waste_risk_prob"] <= 1.0
    assert 0.0 <= result["stockout_risk_prob"] <= 1.0


def test_explicit_interval_level():
    """Test with explicit interval_level parameter."""
    yhat = 100.0
    yhat_lower = 85.0
    yhat_upper = 115.0
    planned_qty = 100.0
    interval_level = 0.95  # 95% interval
    
    result = calculate_risk_metrics(
        yhat=yhat,
        yhat_lower=yhat_lower,
        yhat_upper=yhat_upper,
        planned_qty=planned_qty,
        interval_level=interval_level,
    )
    
    # For 95% interval, z = norm.ppf(0.5 + 0.95/2) = norm.ppf(0.975) ≈ 1.96
    from scipy.stats import norm
    z = norm.ppf(0.5 + 0.95 / 2.0)
    expected_sigma = (115.0 - 85.0) / (2.0 * z)
    
    assert result["risk_method"] == "interval_based"
    assert result["interval_level_used"] == 0.95
    assert abs(result["risk_sigma"] - expected_sigma) < 0.01


def test_probabilities_sum_to_one():
    """Test that waste and stockout probabilities always sum to 1.0."""
    test_cases = [
        (100.0, 80.0, 120.0, 50.0),
        (100.0, 80.0, 120.0, 100.0),
        (100.0, 80.0, 120.0, 150.0),
        (0.0, None, None, 10.0),
        (50.0, 40.0, 60.0, 0.0),
    ]
    
    for yhat, lower, upper, planned in test_cases:
        result = calculate_risk_metrics(
            yhat=yhat,
            yhat_lower=lower,
            yhat_upper=upper,
            planned_qty=planned,
        )
        total = result["waste_risk_prob"] + result["stockout_risk_prob"]
        assert total == pytest.approx(1.0, abs=1e-6), \
            f"Probabilities should sum to 1.0, got {total} for yhat={yhat}, planned={planned}"


def test_deterministic_results():
    """Test that identical inputs produce identical outputs."""
    yhat = 100.0
    yhat_lower = 80.0
    yhat_upper = 120.0
    planned_qty = 100.0
    
    result1 = calculate_risk_metrics(
        yhat=yhat,
        yhat_lower=yhat_lower,
        yhat_upper=yhat_upper,
        planned_qty=planned_qty,
    )
    
    result2 = calculate_risk_metrics(
        yhat=yhat,
        yhat_lower=yhat_lower,
        yhat_upper=yhat_upper,
        planned_qty=planned_qty,
    )
    
    assert result1["waste_risk_prob"] == result2["waste_risk_prob"]
    assert result1["stockout_risk_prob"] == result2["stockout_risk_prob"]
    assert result1["risk_sigma"] == result2["risk_sigma"]
    assert result1["risk_method"] == result2["risk_method"]
    assert result1["interval_level_used"] == result2["interval_level_used"]

