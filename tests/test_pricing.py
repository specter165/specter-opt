"""Tests for BSM reference and American tree pricing."""

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from specter_opt.pricing import bsm_price, american_tree_raw, implied_volatility, american_tree


TOL = 1e-3


def test_bsm_call_matches_known_value():
    # S=100, K=100, tau=1, r=0.05, q=0, sigma=0.2
    price = bsm_price(100, 100, 1.0, 0.05, 0.0, 0.2, "CALL")
    # Known approx value ~10.45
    assert 10.0 < price < 11.0


def test_bsm_put_call_parity_european():
    S, K, tau, r, q, sigma = 100, 100, 0.5, 0.05, 0.02, 0.2
    c = bsm_price(S, K, tau, r, q, sigma, "CALL")
    p = bsm_price(S, K, tau, r, q, sigma, "PUT")
    fwd = S * np.exp(-q * tau) - K * np.exp(-r * tau)
    assert abs(c - p - fwd) < TOL


def test_american_tree_converges_to_bsm_for_european_like_case():
    # For non-dividend American call, early exercise is suboptimal -> equals BSM
    S, K, tau, r, q, sigma = 100, 100, 0.25, 0.05, 0.0, 0.2
    euro = bsm_price(S, K, tau, r, q, sigma, "CALL")
    amer = american_tree_raw(S, K, tau, r, q, sigma, "CALL", n_steps=100)
    assert abs(amer - euro) < 0.05


def test_american_put_exceeds_european_put():
    S, K, tau, r, q, sigma = 100, 100, 0.5, 0.05, 0.02, 0.25
    euro = bsm_price(S, K, tau, r, q, sigma, "PUT")
    amer = american_tree_raw(S, K, tau, r, q, sigma, "PUT", n_steps=80)
    assert amer >= euro - TOL


def test_implied_volatility_inverts_bsm():
    S, K, tau, r, q = 100, 105, 0.4, 0.03, 0.01
    true_sigma = 0.22
    market_price = bsm_price(S, K, tau, r, q, true_sigma, "CALL")
    iv, status = implied_volatility(market_price, S, K, tau, r, q, "CALL", american=False)
    assert status == "ok"
    assert abs(iv - true_sigma) < 1e-4


def test_pricing_handles_expiry():
    assert bsm_price(100, 90, 0.0, 0.05, 0.0, 0.2, "CALL") == 10.0
    assert american_tree_raw(100, 90, 0.0, 0.05, 0.0, 0.2, "CALL") == 10.0


def test_american_tree_invalid_discretization():
    # Very high dividend yield can break CRR probability; should not crash
    pr = american_tree(100, 100, 0.25, 0.05, 0.5, 0.2, "CALL", n_steps=10)
    assert pr.price >= 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
