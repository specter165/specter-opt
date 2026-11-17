"""Risk agent: monitors risk state and enforces halt conditions."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from specter_opt.agents.base import Agent, AgentContext, AgentResult


class RiskAgent(Agent):
    """Agent responsible for risk monitoring and halt enforcement."""

    name = "risk"

    def _load_json(self, path: str) -> Dict[str, Any]:
        if not Path(path).exists():
            return {}
        with open(path, "r") as f:
            return json.load(f)

    def run(self, context: AgentContext) -> AgentResult:
        output: Dict[str, Any] = {"timestamp": datetime.utcnow().isoformat()}
        errors: list[str] = []

        try:
            state = self._load_json(context.risk_state_path)
            equity = context.data.get("equity") or state.get("last_equity", 0)
            output["equity"] = equity
            output["halted"] = state.get("halted", False)
            output["halt_reason"] = state.get("halt_reason", "")
            output["day_start_equity"] = state.get("day_start_equity", equity)
            output["peak_equity"] = state.get("peak_equity", equity)

            if output["halted"]:
                context.halt = True
                context.add_event(f"Risk: HALT active — {output['halt_reason']}")
            else:
                # Compute hypothetical halt metrics
                day_start = max(output["day_start_equity"], 1e-9)
                peak = max(output["peak_equity"], 1e-9)
                daily_loss = 1.0 - equity / day_start
                drawdown = 1.0 - equity / peak
                output["daily_loss"] = daily_loss
                output["drawdown"] = drawdown
                context.add_event(
                    f"Risk: ok, daily_loss={daily_loss:.4f}, drawdown={drawdown:.4f}"
                )

            context.data["risk_state"] = state
        except Exception as e:
            errors.append(str(e))
            context.add_event(f"Risk agent error: {e}")

        return AgentResult(
            agent_name=self.name,
            success=len(errors) == 0,
            output=output,
            errors=errors,
        )
