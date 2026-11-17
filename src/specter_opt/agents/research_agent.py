"""Research agent: gathers market status, account state, and economic events."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from specter_opt.agents.base import Agent, AgentContext, AgentResult

# sim_trade_* numeric order statuses (4=filled and beyond are terminal).
_LIVE_ORDER_STATUS = {1, 2, 3}
_LIVE_ORDER_NAMES = {"NEW", "SUBMITTED", "PARTIAL_FILLED", "PENDING_NEW"}


def _qty(row: dict) -> int:
    return int(row.get("qty", row.get("quantity", 0)) or 0)


def _is_live_order(order: dict) -> bool:
    raw = order.get("order_status", order.get("status"))
    if isinstance(raw, int):
        status = raw in _LIVE_ORDER_STATUS
    else:
        status = str(raw).upper() in _LIVE_ORDER_NAMES
    if not status:
        return False
    return _qty(order) > int(order.get("cum_qty", order.get("dealt_qty", 0)) or 0)


class ResearchAgent(Agent):
    """Agent responsible for market research and account-state collection."""

    name = "research"

    def _load_json(self, path: str) -> Dict[str, Any]:
        if not Path(path).exists():
            return {}
        with open(path, "r") as f:
            return json.load(f)

    def run(self, context: AgentContext) -> AgentResult:
        output: Dict[str, Any] = {"timestamp": datetime.utcnow().isoformat()}
        errors: list[str] = []

        try:
            cash = self._load_json(context.mcp_cash_path)
            positions = self._load_json(context.mcp_positions_path)
            orders = self._load_json(context.mcp_orders_path)

            output["equity"] = float(
                cash.get("data", {}).get("total_asset", cash.get("data", {}).get("balance", 0))
            )
            raw_positions = positions.get("data", {}).get("positions", [])
            raw_orders = orders.get("data", {}).get("orders", [])
            # sim_trade_position_list keeps CLOSED rows with qty "0", and the
            # order list includes cancelled/filled history. Neither is live
            # exposure; counting them exhausts max_concurrent_positions.
            live_positions = [p for p in raw_positions if _qty(p) > 0]
            live_orders = [o for o in raw_orders if _is_live_order(o)]
            output["position_count"] = len(live_positions)
            output["open_order_count"] = len(live_orders)
            output["cash_data"] = cash.get("data", {})
            output["positions"] = live_positions
            output["orders"] = live_orders

            context.data["equity"] = output["equity"]
            context.data["position_count"] = output["position_count"]
            context.data["open_order_count"] = output["open_order_count"]
            context.data["positions"] = output["positions"]
            context.data["orders"] = output["orders"]

            context.add_event(
                f"Research: equity=${output['equity']:,.2f}, "
                f"positions={output['position_count']}, orders={output['open_order_count']}"
            )
        except Exception as e:
            errors.append(str(e))
            context.add_event(f"Research agent error: {e}")

        return AgentResult(
            agent_name=self.name,
            success=len(errors) == 0,
            output=output,
            errors=errors,
        )
