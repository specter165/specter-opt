"""Closed positions and terminal orders must not consume position slots.

The paper API keeps CLOSED rows in sim_trade_position_list (qty "0") and
returns cancelled/filled orders from the order list. Counting either toward
max_concurrent_positions made the agent report 3/3 live with zero real
exposure, blocking every entry.
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

from build_snapshot import parse_orders, parse_positions  # noqa: E402
from specter_opt.agents.base import AgentContext  # noqa: E402
from specter_opt.agents.research_agent import ResearchAgent  # noqa: E402


POSITIONS = {
    "ret_code": 0,
    "data": {
        "positions": [
            {"symbol": "SPY261120C740000", "qty": "0", "cost_price": "0"},
            {"symbol": "QQQ261120C650000", "qty": "2", "cost_price": "3.10"},
        ]
    },
}

ORDERS = {
    "ret_code": 0,
    "data": {
        "orders": [
            {"order_id": "1", "status": 5, "qty": "1", "cum_qty": "0"},   # cancelled
            {"order_id": "2", "status": 4, "qty": "1", "cum_qty": "1"},   # filled
            {"order_id": "3", "status": 3, "qty": "1", "cum_qty": "0"},   # working
        ]
    },
}


def test_closed_position_is_dropped():
    parsed = parse_positions(POSITIONS)
    assert [p["symbol"] for p in parsed] == ["QQQ261120C650000"]


def test_only_working_orders_survive_and_numeric_status_is_understood():
    parsed = parse_orders(ORDERS)
    assert [o["order_id"] for o in parsed] == ["3"]
    assert parsed[0]["status"] == "PARTIAL_FILLED"


def test_research_agent_counts_no_phantom_exposure(tmp_path):
    paths = {}
    for name, payload in (("cash", {"data": {"total_asset": "100000"}}),
                          ("positions", POSITIONS),
                          ("orders", ORDERS)):
        p = tmp_path / f"{name}.json"
        p.write_text(json.dumps(payload))
        paths[name] = str(p)

    ctx = AgentContext(
        mcp_cash_path=paths["cash"],
        mcp_positions_path=paths["positions"],
        mcp_orders_path=paths["orders"],
    )
    result = ResearchAgent().run(ctx)
    assert result.success
    assert result.output["position_count"] == 1
    assert result.output["open_order_count"] == 1
