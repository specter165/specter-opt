"""Tests for the multi-underlying universe: liquidity gates, dividends,
earnings blackout and correlated-cluster caps."""

import importlib.util
import os
import sys
import tempfile
from dataclasses import replace
from datetime import date, timedelta
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from specter_opt.agent import SpecterAgent
from specter_opt.broker import MockBroker, OptionContract
from specter_opt.config import AgentConfig
from specter_opt.risk import cluster_headroom, compute_cluster_premium
from specter_opt.selection import screen_contract

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_module(name, relpath):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, relpath))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _contract(underlying, *, spread=0.01, oi=2000, dte=14, right="CALL", strike=None, iv=0.25):
    expiry = (date.today() + timedelta(days=dte)).isoformat()
    strike = strike if strike is not None else 100.0
    return OptionContract(
        symbol=f"{underlying}{expiry.replace('-', '')}{right[0]}{int(strike * 1000)}",
        underlying=underlying,
        right=right,
        strike=strike,
        expiry=expiry,
        multiplier=100,
        bid=2.0,
        ask=2.0 * (1 + spread),
        open_interest=oi,
        iv=iv,
        delta=0.5 if right == "CALL" else -0.5,
        quote_age_seconds=1.0,
    )


def _agent(tmp_path, earnings_dates=None, cfg=None):
    cfg = cfg or AgentConfig(mode="shadow")
    cfg = replace(
        cfg,
        execution=replace(
            cfg.execution,
            state_file=str(tmp_path / "risk_state.json"),
            intent_file=str(tmp_path / "intents.jsonl"),
            decision_log=str(tmp_path / "decisions.jsonl"),
        ),
    )
    return SpecterAgent(cfg, MockBroker(), earnings_dates=earnings_dates)


def test_option_code_parsing_handles_four_char_tickers():
    mod = _load_module("build_snapshot_test", "scripts/build_snapshot.py")
    assert mod._underlying_from_code("US.NVDA260123C500000") == "NVDA"
    assert mod._underlying_from_code("US.AAPL261218P200000") == "AAPL"
    assert mod._underlying_from_code("US.SPY260123C500000") == "SPY"
    assert mod._underlying_from_code("US.SPY") == "SPY"


def test_iv_percent_is_normalised_to_decimal():
    mod = _load_module("build_snapshot_iv_test", "scripts/build_snapshot.py")
    # Moomoo reports option IV in percent; the engine expects a decimal.
    assert mod.normalize_iv(23.65) == 0.2365
    assert abs(mod.normalize_iv("27.7") - 0.277) < 1e-12
    # Already-decimal values pass through unchanged.
    assert mod.normalize_iv(0.24) == 0.24
    assert mod.normalize_iv(0) is None
    assert mod.normalize_iv(None) is None

    quote_map = mod.build_quote_map(
        {"data": {"snapshot_list": [{"code": "US.SPY260123C500000", "option_implied_volatility": 23.65}]}}
    )
    assert quote_map["US.SPY260123C500000"]["iv"] == 0.2365


def test_single_names_get_stricter_liquidity_gates():
    cfg = AgentConfig()
    wide = _contract("NVDA", spread=0.04, oi=700)
    assert "wide_spread" in screen_contract(wide, cfg)
    assert "low_oi" in screen_contract(wide, cfg)
    # The same contract would clear the index-level thresholds.
    index_wide = _contract("SPY", spread=0.04, oi=700)
    assert screen_contract(index_wide, cfg) == []


def test_per_symbol_dividend_yield(tmp_path):
    agent = _agent(tmp_path)
    nvda_yield = AgentConfig().dividend_yields["NVDA"]
    assert agent._div_yield("NVDA") == nvda_yield
    assert nvda_yield != AgentConfig().pricing.dividend_yield
    # Unknown symbol falls back to the index-level yield.
    fallback = AgentConfig().pricing.dividend_yield
    assert agent._div_yield("UNKNOWN") == fallback


def test_earnings_blackout_drops_contracts_spanning_earnings(tmp_path):
    earnings = (date.today() + timedelta(days=10)).isoformat()
    agent = _agent(tmp_path, earnings_dates={"NVDA": [earnings]})
    spanning = _contract("NVDA", dte=14)  # expiry after earnings -> dropped
    before = _contract("NVDA", dte=7)     # expires before earnings -> kept
    kept = agent._filter_chain([spanning], 100.0, "NVDA")
    assert kept == []
    assert agent._filter_chain([before], 100.0, "NVDA") != []


def test_missing_earnings_calendar_fails_closed(tmp_path):
    agent = _agent(tmp_path, earnings_dates={})
    blocked, reason = agent._earnings_blocked("NVDA")
    assert blocked is True
    assert reason == "missing_earnings_calendar"
    assert agent._earnings_blocked("SPY") == (False, "")
    # With a calendar present the symbol is allowed again.
    future = (date.today() + timedelta(days=40)).isoformat()
    agent2 = _agent(tmp_path, earnings_dates={"AAPL": [future]})
    assert agent2._earnings_blocked("AAPL") == (False, "")


def test_cluster_exposure_counts_multi_membership():
    membership = AgentConfig().cluster_membership
    positions = [
        SimpleNamespace(underlying="QQQ", quantity=2, entry_price=5.0, multiplier=100),
        SimpleNamespace(underlying="NVDA", quantity=1, entry_price=5.0, multiplier=100),
        SimpleNamespace(underlying="SPY", quantity=1, entry_price=8.0, multiplier=100),
    ]
    current = compute_cluster_premium(positions, membership)
    assert current["index"] == 2 * 5.0 * 100 + 8.0 * 100  # 1800
    assert current["megacap_tech"] == 2 * 5.0 * 100 + 5.0 * 100  # 1500

    equity = 100_000.0
    cap_pct = 0.02  # 2000 per cluster
    # QQQ belongs to both clusters: the tighter remaining budget wins (200).
    assert cluster_headroom(equity, cap_pct, current, "QQQ", membership) == 200.0
    # SPY is index-only.
    assert cluster_headroom(equity, cap_pct, current, "SPY", membership) == 200.0
    # AAPL is megacap-only, so it sees that cluster's larger headroom.
    assert cluster_headroom(equity, cap_pct, current, "AAPL", membership) == 500.0


def test_universe_includes_requested_symbols():
    assert AgentConfig().universe == ["SPY", "QQQ", "NVDA", "AAPL"]
