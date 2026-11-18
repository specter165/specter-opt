"""Tests for deterministic risk controls and reservations."""

import os
import sys
import tempfile
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from specter_opt.config import AgentConfig
from specter_opt.fees import option_fees
from specter_opt.risk import RiskGuard


def make_guard():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    cfg = AgentConfig()
    return RiskGuard(cfg, state_file=path), path


def test_daily_loss_block():
    guard, path = make_guard()
    d = date(2026, 11, 17)
    guard.reset_day(100000.0, d)
    ok, reason = guard.update_equity(97000.0, d)
    assert not ok
    assert "daily_loss" in reason
    os.remove(path)


def test_peak_drawdown_halt():
    guard, path = make_guard()
    d = date(2026, 11, 17)
    guard.reset_day(100000.0, d)
    guard.update_equity(106000.0, d)  # push peak 6% above day-start
    ok, reason = guard.update_equity(98400.0, d)  # daily loss 1.6%, peak drawdown 7.2%
    assert not ok
    assert "peak_drawdown" in reason
    assert guard.state.halted
    os.remove(path)


def test_can_enter_respects_budget():
    guard, path = make_guard()
    d = date(2026, 11, 17)
    guard.reset_day(100000.0, d)
    cfg = AgentConfig()
    fee = option_fees(1, 2.0, 100, cfg.fees)
    allowed, reason, qty = guard.can_enter(
        equity=100000.0,
        quantity=3,
        ask=2.0,
        multiplier=100,
        fee_result=fee,
        existing_positions_premium=0.0,
        pending_order_premium=0.0,
        ny_date=d,
    )
    assert allowed
    assert qty > 0
    os.remove(path)


def test_aggregate_premium_limit():
    guard, path = make_guard()
    d = date(2026, 11, 17)
    guard.reset_day(100000.0, d)
    cfg = AgentConfig()
    fee = option_fees(1, 0.5, 100, cfg.fees)
    allowed, reason, qty = guard.can_enter(
        equity=100000.0,
        quantity=1,
        ask=0.5,
        multiplier=100,
        fee_result=fee,
        existing_positions_premium=4960.0,
        pending_order_premium=0.0,
        ny_date=d,
    )
    assert not allowed
    assert reason == "aggregate_premium_limit"
    os.remove(path)


def test_persistence():
    guard, path = make_guard()
    d = date(2026, 11, 17)
    guard.reset_day(100000.0, d)
    guard.save_state()

    guard2 = RiskGuard(AgentConfig(), state_file=path)
    assert guard2.state.day_start_equity == 100000.0
    os.remove(path)


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
