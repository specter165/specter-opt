"""The configured concurrent-position cap must actually block new entries."""

from specter_opt.agent import SpecterAgent
from specter_opt.broker import MockBroker, Position
from specter_opt.config import AgentConfig


def _position(i: int) -> Position:
    return Position(
        symbol=f"US.SPY261218C{700 + i}000",
        underlying="SPY",
        right="CALL",
        strike=700.0 + i,
        expiry="2026-12-18",
        quantity=1,
        entry_price=1.0,
        multiplier=100,
        market_price=1.0,
        unrealized_pnl=0.0,
    )


def test_at_cap_blocks_entry():
    config = AgentConfig()
    broker = MockBroker(account_title="Moomoo x Qoder AI Paper Trading Agent Challenge")
    broker.positions = [_position(i) for i in range(config.risk.max_concurrent_positions)]
    agent = SpecterAgent(config, broker, universe=["SPY"])

    result = agent.run()

    assert result.actions[0].action == "HOLD"
    assert any(r.startswith("max_concurrent_positions") for r in result.rejection_reasons)


def test_below_cap_does_not_trigger_cap_reason():
    config = AgentConfig()
    broker = MockBroker(account_title="Moomoo x Qoder AI Paper Trading Agent Challenge")
    broker.positions = [_position(0)]
    agent = SpecterAgent(config, broker, universe=["SPY"])

    result = agent.run()

    assert not any(r.startswith("max_concurrent_positions") for r in result.rejection_reasons)
