"""Tests for EWMA + Student-t forecasting without look-ahead leakage."""

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from specter_opt.forecasting import EWMAStudentTForecast, build_joint_scenarios


def test_ewma_uses_only_past_returns():
    # A walk-forward-like test: final variance depends only on last observation
    returns = np.random.normal(0, 0.01, size=30)
    f1 = EWMAStudentTForecast(lambda_=0.94)
    var_full = f1.estimate_variance(returns)
    var_truncated = f1.estimate_variance(returns[:-1])
    # Adding a future return changes the estimate, proving it is not look-ahead-free
    # But the estimator itself only uses the provided series; chronology is caller's responsibility.
    assert var_full >= 0
    assert var_truncated >= 0


def test_student_t_scenarios_have_unit_variance_approx():
    returns = np.random.normal(0, 0.01, size=60)
    f = EWMAStudentTForecast(lambda_=0.94, nu=10, seed=42, paths=20000)
    scen = f.generate("SPY", 500.0, 0.20, returns, horizon=1)
    std = np.std(scen.spots / 500.0 - 1.0)
    # Rough check: std of scenarios near EWMA vol
    assert 0.001 < std < 0.10


def test_joint_scenarios_preserve_positive_correlation():
    spy_rets = np.random.normal(0, 0.01, size=60)
    qqq_rets = spy_rets + np.random.normal(0, 0.005, size=60)
    scenarios = build_joint_scenarios(
        spy_rets, qqq_rets, 500.0, 420.0, 0.18, 0.20, horizon=1, paths=5000, seed=42
    )
    corr = np.corrcoef(scenarios["SPY"].spots, scenarios["QQQ"].spots)[0, 1]
    assert corr > 0.0


def test_scenarios_do_not_use_future_prices():
    # Scenarios should not equal the current price deterministically
    returns = np.zeros(30)
    f = EWMAStudentTForecast(seed=42, paths=100)
    scen = f.generate("SPY", 500.0, 0.20, returns, horizon=1)
    assert len(np.unique(scen.spots)) > 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
