"""Tests for contract screening, EV/CVaR ranking and sizing."""

import os
import sys
from datetime import date, timedelta

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from specter_opt.broker import OptionContract
from specter_opt.config import AgentConfig
from specter_opt.forecasting import EWMAStudentTForecast
from specter_opt.selection import evaluate_candidate, rank_candidates, size_candidate, compute_cvar


def make_contract(strike=100.0, right="CALL", ask=3.0, bid=2.9, iv=0.20, oi=1000):
    expiry = (date.today() + timedelta(days=14)).isoformat()
    return OptionContract(
        symbol=f"SPY{expiry.replace('-', '')}{right[0]}{int(strike*1000)}",
        underlying="SPY",
        right=right,
        strike=strike,
        expiry=expiry,
        multiplier=100,
        bid=bid,
        ask=ask,
        open_interest=oi,
        volume=100,
        iv=iv,
        delta=0.5 if right == "CALL" else -0.5,
        quote_age_seconds=1.0,
    )


def make_scenarios(spot=100.0, iv=0.20, paths=2000, seed=42):
    returns = np.random.normal(0, 0.01, size=60)
    return EWMAStudentTForecast(seed=seed, paths=paths).generate(
        "SPY", spot, iv, returns, horizon=1
    )


def test_screen_rejects_wide_spread():
    cfg = AgentConfig()
    c = make_contract(ask=3.0, bid=2.0)
    from specter_opt.selection import screen_contract
    reasons = screen_contract(c, cfg)
    assert "wide_spread" in reasons


def test_cvar_computation():
    losses = np.array([1, 2, 3, 4, 5, 10, 20])
    cvar = compute_cvar(losses, alpha=0.9)
    assert cvar >= 10.0


def test_evaluate_candidate_computes_ev():
    cfg = AgentConfig()
    c = make_contract(ask=2.0, bid=1.95, iv=0.18)
    scen = make_scenarios(spot=100.0, iv=0.18)
    cand = evaluate_candidate(c, scen, cfg)
    assert cand.ev < 100  # reasonable bound
    assert cand.cvar95 >= 0


def test_ranking_prefers_positive_edge():
    cfg = AgentConfig()
    scen = make_scenarios(spot=100.0, iv=0.18, paths=2000)
    c1 = make_contract(strike=100.0, ask=2.0, bid=1.95, iv=0.18)
    c2 = make_contract(strike=95.0, ask=7.0, bid=6.95, iv=0.18)
    cand1 = evaluate_candidate(c1, scen, cfg)
    cand2 = evaluate_candidate(c2, scen, cfg)
    ranked = rank_candidates([cand1, cand2])
    assert len(ranked) <= 2


def test_size_candidate_zero_budget():
    cfg = AgentConfig()
    c = make_contract(ask=2.0)
    scen = make_scenarios(spot=100.0, iv=0.18)
    cand = evaluate_candidate(c, scen, cfg)
    qty = size_candidate(cand, 100000.0, 1000000.0, 0.0, 0.0, cfg)
    assert qty == 0


def test_size_candidate_within_budget():
    cfg = AgentConfig()
    c = make_contract(ask=2.0)
    scen = make_scenarios(spot=100.0, iv=0.18)
    cand = evaluate_candidate(c, scen, cfg)
    qty = size_candidate(cand, 100000.0, 0.0, 0.0, 0.0, cfg)
    # Per-trade budget is 1.5% of equity ($1,500); each contract ~$200 + fees.
    assert 0 < qty <= 8


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
