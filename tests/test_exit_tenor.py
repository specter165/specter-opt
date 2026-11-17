"""The exit leg must be repriced at the contract's remaining life.

evaluate_candidate used to start from the *horizon* rather than the contract's
DTE, so the exit tenor collapsed to zero and every exit was valued at expiry
(intrinsic only). That made every long-premium trade look catastrophic and was
one of the reasons the agent never traded.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from specter_opt.broker import OptionContract  # noqa: E402
from specter_opt.config import AgentConfig  # noqa: E402
from specter_opt.forecasting import ScenarioSet  # noqa: E402
from specter_opt.selection import evaluate_candidate  # noqa: E402


def _atm_contract(dte: int) -> OptionContract:
    expiry = (date.today() + timedelta(days=dte)).isoformat()
    return OptionContract(
        symbol=f"SPY{expiry.replace('-', '')}C100000",
        underlying="SPY",
        right="CALL",
        strike=100.0,
        expiry=expiry,
        multiplier=100,
        bid=2.00,
        ask=2.10,
        open_interest=5000,
        iv=0.25,
        delta=0.5,
        quote_age_seconds=0.0,
    )


def _scenarios(spot: float, n: int = 200) -> ScenarioSet:
    return ScenarioSet(
        underlying="SPY",
        horizon=1,
        as_of=date.today().isoformat(),
        model="M0",
        spots=np.full(n, spot),
        ivs=np.full(n, 0.25),
        params={},
        seed=42,
    )


def test_one_day_exit_keeps_time_value():
    # Spot sits exactly at the strike, so intrinsic is zero. A 14-DTE contract
    # exited after one day still has 13 days of time value left.
    cand = evaluate_candidate(_atm_contract(dte=14), _scenarios(100.0), AgentConfig(), horizon=1)
    assert np.median(cand.exit_bids) > 1.0


def test_exit_value_decays_as_expiry_approaches():
    near = np.median(evaluate_candidate(_atm_contract(dte=7), _scenarios(100.0), AgentConfig(), horizon=3).exit_bids)
    far = np.median(evaluate_candidate(_atm_contract(dte=30), _scenarios(100.0), AgentConfig(), horizon=3).exit_bids)
    assert near < far
