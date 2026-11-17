"""Research agent: gathers market status, account state, and economic events."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from specter_opt.agents.base import Agent, AgentContext, AgentResult


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
            output["position_count"] = len(positions.get("data", {}).get("positions", []))
            output["open_order_count"] = len(orders.get("data", {}).get("orders", []))
            output["cash_data"] = cash.get("data", {})
            output["positions"] = positions.get("data", {}).get("positions", [])
            output["orders"] = orders.get("data", {}).get("orders", [])

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
