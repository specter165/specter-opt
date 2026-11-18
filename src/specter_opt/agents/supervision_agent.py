"""Supervision agent: monitors open positions and submits protective exits."""

import json
import os
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from specter_opt.agents.base import Agent, AgentContext, AgentResult


def _load_json(path: str) -> Dict[str, Any]:
    if not Path(path).exists():
        return {}
    with open(path, "r") as f:
        return json.load(f)


def _qty(row: dict) -> int:
    return int(row.get("qty", row.get("quantity", 0)) or 0)


def _parse_date(s: str) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except Exception:
        return None


class SupervisionAgent(Agent):
    """Agent responsible for monitoring open positions and exiting losers/expiring contracts."""

    name = "supervision"

    def _run_subprocess(self, cmd: list[str]) -> Dict[str, Any]:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[3],
        )
        if result.returncode != 0:
            raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{result.stderr}")
        return json.loads(result.stdout)

    def _detect_exits(self, positions: List[dict]) -> List[dict]:
        exits = []
        today = datetime.now(timezone.utc).date()
        for p in positions:
            qty = _qty(p)
            if qty <= 0:
                continue
            symbol = p.get("symbol", "")
            profit_ratio = float(p.get("profit_ratio", 0) or 0)
            cost = float(p.get("cost_price", 0) or p.get("buy_avg_price", 0) or 0)
            cur = float(p.get("cur_price", 0) or 0)
            # 30% premium stop: if unrealized loss >= 30% of cost basis.
            stop_triggered = profit_ratio <= -0.30 or (cost > 0 and cur > 0 and (cost - cur) / cost >= 0.30)
            expiry_str = p.get("expiry_date") or p.get("strike_time") or p.get("maturity_date") or ""
            expiry = _parse_date(expiry_str)
            expiring_soon = expiry is not None and (expiry - today).days <= 1

            if stop_triggered or expiring_soon:
                reason = []
                if stop_triggered:
                    reason.append(f"stop_loss_{profit_ratio:.2%}")
                if expiring_soon:
                    reason.append(f"expiry_{expiry_str}")
                exits.append({
                    "symbol": symbol,
                    "side": 2,
                    "quantity": qty,
                    "price": cur if cur > 0 else cost,
                    "order_type": 1,
                    "reason": ",".join(reason),
                })
        return exits

    def run(self, context: AgentContext) -> AgentResult:
        output: Dict[str, Any] = {"timestamp": datetime.utcnow().isoformat()}
        errors: list[str] = []

        try:
            result = self._run_subprocess(
                [
                    sys.executable,
                    "scripts/supervise_orders.py",
                    "--positions", context.mcp_positions_path,
                    "--orders", context.mcp_orders_path,
                    "--cash", context.mcp_cash_path,
                ]
            )
            output["supervision_events"] = result.get("events", [])
            output["position_count"] = result.get("position_count", 0)
            output["open_order_count"] = result.get("open_order_count", 0)
            output["equity"] = result.get("equity", 0)
            output["halted"] = result.get("halted", False)
            context.data["risk_halted"] = output["halted"]
            context.halt = bool(output["halted"])

            positions = _load_json(context.mcp_positions_path).get("data", {}).get("positions", [])
            live_positions = [p for p in positions if _qty(p) > 0]
            exits = self._detect_exits(live_positions)
            output["exit_intents"] = exits
            context.data["exit_intents"] = exits

            if exits:
                context.add_event(f"Supervision: {len(exits)} position(s) need exit ({', '.join(e['symbol'] for e in exits)})")
            else:
                context.add_event("Supervision: no protective exits needed")
        except Exception as e:
            errors.append(str(e))
            context.add_event(f"Supervision agent error: {e}")

        return AgentResult(
            agent_name=self.name,
            success=len(errors) == 0,
            output=output,
            errors=errors,
        )
