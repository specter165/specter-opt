"""Underlying-quote IV is not always present; the agent must not crash on it."""

import numpy as np

from specter_opt.agent import SpecterAgent
from specter_opt.broker import MockBroker, OptionContract
from specter_opt.config import AgentConfig


def _contract(strike: float, iv: float) -> OptionContract:
    return OptionContract(
        symbol=f"US.SPY261218C{int(strike * 1000)}000",
        underlying="SPY",
        right="CALL",
        strike=strike,
        expiry="2026-12-18",
        multiplier=100,
        bid=1.0,
        ask=1.2,
        open_interest=5000,
        iv=iv,
    )


def test_missing_iv_is_imputed_from_near_money_chain():
    agent = SpecterAgent(AgentConfig(), MockBroker(), universe=["SPY"])
    chain = [_contract(700.0, 0.21), _contract(750.0, 0.25), _contract(800.0, 0.30)]
    quotes = {"SPY": {"last": 752.0}}

    agent._impute_underlying_iv(["SPY"], quotes, {"SPY": chain})

    assert quotes["SPY"]["iv"] == 0.25


def test_existing_iv_is_left_alone():
    agent = SpecterAgent(AgentConfig(), MockBroker(), universe=["SPY"])
    quotes = {"SPY": {"last": 752.0, "iv": 0.18}}

    agent._impute_underlying_iv(["SPY"], quotes, {"SPY": [_contract(750.0, 0.25)]})

    assert quotes["SPY"]["iv"] == 0.18


def test_none_iv_does_not_crash_forecast_build():
    agent = SpecterAgent(AgentConfig(), MockBroker(), universe=["SPY"])
    quotes = {"SPY": {"last": 752.0, "iv": None}}
    chains = {"SPY": [_contract(750.0, 0.25)]}

    agent._impute_underlying_iv(["SPY"], quotes, chains)
    scenarios = agent._build_forecasts(["SPY"], quotes, {"SPY": np.zeros(60)})

    assert (("SPY", 1) in scenarios) is True


def test_no_chain_data_falls_back_to_default_vol():
    agent = SpecterAgent(AgentConfig(), MockBroker(), universe=["SPY"])
    quotes = {"SPY": {"last": 752.0, "iv": None}}

    agent._impute_underlying_iv(["SPY"], quotes, {"SPY": []})
    scenarios = agent._build_forecasts(["SPY"], quotes, {"SPY": np.zeros(60)})

    assert ("SPY", 1) in scenarios
