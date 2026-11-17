"""Tests for execution supervisor and agent integration."""

import os
import sys
import tempfile
from datetime import date, timedelta

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dataclasses import replace

from specter_opt.agent import AgentConfig, SpecterAgent
from specter_opt.broker import MockBroker, OptionContract
from specter_opt.execution import ExecutionSupervisor


def make_chain(underlying: str, spot: float, expiry: str):
    contracts = []
    for right in ("CALL", "PUT"):
        for offset in (-0.03, 0.0, 0.03):
            strike = round(spot * (1 + offset), 2)
            mid = max(1.0, abs(strike - spot) * 0.05)
            contracts.append(
                OptionContract(
                    symbol=f"{underlying}{expiry.replace('-', '')}{right[0]}{int(strike*1000)}",
                    underlying=underlying,
                    right=right,
                    strike=strike,
                    expiry=expiry,
                    multiplier=100,
                    bid=round(mid * 0.99, 2),
                    ask=round(mid * 1.01, 2),
                    open_interest=1000,
                    iv=0.18,
                    delta=0.5 if right == "CALL" else -0.5,
                    quote_age_seconds=1.0,
                )
            )
    return contracts


def test_execution_supervisor_prevents_duplicate():
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    sup = ExecutionSupervisor(path)
    sup.new_intent("SPY123C100", "BUY", 1, 2.0, "LIMIT", "test", 200.0)
    assert sup.duplicate_exists("SPY123C100", "BUY", 2.0, within_seconds=60)
    assert not sup.duplicate_exists("SPY123C100", "SELL", 2.0, within_seconds=60)
    os.remove(path)


def test_agent_hold_when_no_account_match(tmp_path):
    broker = MockBroker()
    broker.option_chains = {}
    broker.underlying_quotes = {}
    cfg = AgentConfig(mode="shadow")
    cfg = replace(
        cfg,
        execution=replace(
            cfg.execution,
            state_file=str(tmp_path / "risk_state.json"),
            intent_file=str(tmp_path / "intents.jsonl"),
            decision_log=str(tmp_path / "decisions.jsonl"),
        ),
    )
    agent = SpecterAgent(cfg, broker)
    result = agent.run()
    assert result.actions[0].action == "HOLD"
    assert any("account_identity_mismatch" in r for r in result.rejection_reasons)


def test_agent_shadow_run_no_crash(tmp_path):
    broker = MockBroker(account_title="Moomoo x Qoder AI Paper Trading Agent Challenge")
    expiry = (date.today() + timedelta(days=14)).isoformat()
    broker.option_chains = {
        "SPY": make_chain("SPY", 590.0, expiry),
        "QQQ": make_chain("QQQ", 505.0, expiry),
    }
    broker.underlying_quotes = {
        "SPY": {"last": 590.0, "bid": 589.95, "ask": 590.05, "iv": 0.18},
        "QQQ": {"last": 505.0, "bid": 504.95, "ask": 505.05, "iv": 0.20},
    }
    cfg = AgentConfig(mode="shadow")
    cfg = replace(
        cfg,
        execution=replace(
            cfg.execution,
            state_file=str(tmp_path / "risk_state.json"),
            intent_file=str(tmp_path / "intents.jsonl"),
            decision_log=str(tmp_path / "decisions.jsonl"),
        ),
    )
    agent = SpecterAgent(cfg, broker)
    returns_cache = {
        "SPY": np.random.normal(0, 0.01, size=60),
        "QQQ": np.random.normal(0, 0.012, size=60),
    }
    result = agent.run(returns_cache=returns_cache)
    assert result.mode == "shadow"
    assert len(result.actions) >= 1


def test_execution_supervisor_restart_loads_intents(tmp_path):
    intent_file = str(tmp_path / "intents.jsonl")
    sup = ExecutionSupervisor(intent_file)
    intent = sup.new_intent("SPY123C100", "BUY", 10, 2.0, "LIMIT", "test", 2000.0)
    # Simulate process restart by creating a new supervisor instance
    sup2 = ExecutionSupervisor(intent_file)
    assert intent.intent_id in sup2.intents
    active = sup2.active_intents()
    assert len(active) == 1
    assert active[0].symbol == "SPY123C100"


def test_execution_supervisor_reconcile_partial_fill():
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    sup = ExecutionSupervisor(path)
    intent = sup.new_intent("SPY123C100", "BUY", 10, 2.0, "LIMIT", "test", 2000.0)
    from specter_opt.broker import BrokerOrder

    order = BrokerOrder(
        order_id="O1",
        intent_id=intent.intent_id,
        symbol="SPY123C100",
        side="BUY",
        quantity=10,
        price=2.0,
        order_type="LIMIT",
        status="PARTIAL_FILLED",
        filled_qty=5,
        avg_fill_price=2.0,
    )
    sup.reconcile_order(order)
    loaded = sup.intents[intent.intent_id]
    assert loaded.status == "PARTIAL_FILLED"
    assert loaded.fill_qty == 5
    assert loaded.avg_fill_price == 2.0
    os.remove(path)


def test_agent_logs_place_order_exception(tmp_path):
    broker = MockBroker(account_title="Moomoo x Qoder AI Paper Trading Agent Challenge")
    expiry = (date.today() + timedelta(days=14)).isoformat()
    broker.option_chains = {
        "SPY": [
            OptionContract(
                symbol=f"SPY{expiry.replace('-', '')}C590000",
                underlying="SPY",
                right="CALL",
                strike=590.0,
                expiry=expiry,
                multiplier=100,
                bid=4.90,
                ask=5.00,
                open_interest=1000,
                iv=0.50,
                delta=0.50,
                quote_age_seconds=1.0,
            )
        ]
    }
    broker.underlying_quotes = {
        "SPY": {"last": 590.0, "bid": 589.95, "ask": 590.05, "iv": 0.50},
    }

    cfg = AgentConfig(mode="paper")
    cfg = replace(
        cfg,
        risk=replace(cfg.risk, min_score_threshold=-1.0, per_trade_premium_pct=0.02),
        execution=replace(
            cfg.execution,
            state_file=str(tmp_path / "risk_state.json"),
            intent_file=str(tmp_path / "intents.jsonl"),
            decision_log=str(tmp_path / "decisions.jsonl"),
        ),
    )

    def raise_timeout(intent):
        raise TimeoutError("submit_timeout")

    broker.place_order = raise_timeout

    agent = SpecterAgent(cfg, broker)
    # High-volatility returns cache inflates scenario option value above cheap ask
    returns_cache = {"SPY": np.full(60, 0.05), "QQQ": np.full(60, 0.05)}
    result = agent.run(returns_cache=returns_cache)

    assert result.mode == "paper"
    assert any(a.action == "ENTER" for a in result.actions)
    decision_file = tmp_path / "decisions.jsonl"
    raw = decision_file.read_text()
    assert "ORDER_SUBMIT_ERROR" in raw
    assert "submit_timeout" in raw


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
