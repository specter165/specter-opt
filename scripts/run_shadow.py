#!/usr/bin/env python3
"""Standalone shadow-mode run using mock broker and synthetic option data."""

import json
import os
import sys
from datetime import date, timedelta

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from specter_opt.broker import MockBroker, OptionContract
from specter_opt.config import AgentConfig
from specter_opt.agent import SpecterAgent


def make_synthetic_chain(underlying: str, spot: float, expiry: str) -> list:
    """Build a small synthetic option chain for shadow testing."""
    contracts = []
    for right in ("CALL", "PUT"):
        for offset in (-0.05, -0.02, 0.0, 0.02, 0.05):
            strike = round(spot * (1 + offset), 2)
            intrinsic = max(spot - strike, 0.0) if right == "CALL" else max(strike - spot, 0.0)
            time_value = max(2.0 - abs(offset) * 10, 0.10)
            mid = max(intrinsic + time_value, 0.05)
            bid = round(mid * 0.98, 2)
            ask = round(mid * 1.02, 2)
            iv = 0.20 + abs(offset) * 0.3
            delta = 0.6 if right == "CALL" else -0.6
            contracts.append(
                OptionContract(
                    symbol=f"{underlying}{expiry.replace('-', '')}{right[0]}{int(strike*1000)}",
                    underlying=underlying,
                    right=right,
                    strike=strike,
                    expiry=expiry,
                    multiplier=100,
                    bid=bid,
                    ask=ask,
                    open_interest=1000,
                    volume=100,
                    iv=iv,
                    delta=delta,
                    quote_age_seconds=1.0,
                )
            )
    return contracts


def main():
    config = AgentConfig(mode="shadow")
    broker = MockBroker(
        initial_equity=100000.0,
        account_title="Moomoo x Qoder AI Paper Trading Agent Challenge",
        market_id=100,
    )

    # Seed synthetic data into mock broker
    expiry = (date.today() + timedelta(days=14)).isoformat()
    broker.option_chains = {
        "SPY": make_synthetic_chain("SPY", 590.0, expiry),
        "QQQ": make_synthetic_chain("QQQ", 505.0, expiry),
    }
    broker.underlying_quotes = {
        "SPY": {"last": 590.0, "bid": 589.95, "ask": 590.05, "iv": 0.18},
        "QQQ": {"last": 505.0, "bid": 504.95, "ask": 505.05, "iv": 0.20},
    }

    # Mock historical returns for EWMA
    np.random.seed(42)
    returns_cache = {
        "SPY": np.random.normal(0, 0.01, size=60),
        "QQQ": np.random.normal(0, 0.012, size=60),
    }

    agent = SpecterAgent(config, broker)
    result = agent.run(returns_cache=returns_cache)

    print(json.dumps(result.__dict__, indent=2, default=str))


if __name__ == "__main__":
    main()
