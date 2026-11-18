#!/usr/bin/env python3
"""Generate SPECTER-OPT daily summary and post to Slack.

Usage:
  python scripts/daily_slack_update.py [--env data/.slack_webhook.env]
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from post_to_slack import load_webhook, post_message


def load_json(path: str):
    with open(path, "r") as f:
        return json.load(f)


def load_jsonl(path: str):
    if not Path(path).exists():
        return []
    records = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def _qty(row: dict) -> int:
    return int(row.get("qty", row.get("quantity", 0)) or 0)


def load_mcp_summary() -> Dict[str, Any]:
    """Fallback summary from MCP data when no run_result exists."""
    cash = load_json("data/mcp_cash.json") if Path("data/mcp_cash.json").exists() else {}
    positions = load_json("data/mcp_positions.json") if Path("data/mcp_positions.json").exists() else {}
    orders = load_json("data/mcp_orders.json") if Path("data/mcp_orders.json").exists() else {}

    cash_data = cash.get("data", {}) if isinstance(cash, dict) else {}
    pos_data = positions.get("data", {}) if isinstance(positions, dict) else {}
    order_data = orders.get("data", {}) if isinstance(orders, dict) else {}

    raw_positions = pos_data.get("positions", [])
    live_positions = [p for p in raw_positions if _qty(p) > 0]
    live_orders = order_data.get("orders", [])

    total_profit = sum(float(p.get("profit", 0) or 0) for p in live_positions)
    # Use profit_ratio from first position if only one, else aggregate roughly.
    profit_ratio = 0.0
    if len(live_positions) == 1:
        profit_ratio = float(live_positions[0].get("profit_ratio", 0) or 0)
    elif live_positions:
        costs = sum(float(p.get("cost_price", 0) or 0) * _qty(p) for p in live_positions)
        profit_ratio = total_profit / max(costs, 1e-9)

    return {
        "equity": float(cash_data.get("total_asset", cash_data.get("balance", 0))),
        "position_count": len(live_positions),
        "open_order_count": len(live_orders),
        "position_profit": total_profit,
        "position_profit_ratio": profit_ratio,
        "positions": live_positions,
    }


def generate_summary(result_path: str = "data/run_result_fresh.json", mcp_fallback: bool = False) -> str:
    cfg_path = Path(result_path)
    if not cfg_path.exists():
        cfg_path = Path("data/run_result_20261117_b.json")
    if not cfg_path.exists():
        cfg_path = Path("data/run_result_20261117_a.json")

    result = load_json(cfg_path) if cfg_path.exists() and not mcp_fallback else {}
    mcp = load_mcp_summary()
    decisions = load_jsonl("decision-logs/decisions.jsonl")
    state = load_json("data/risk_state.json") if Path("data/risk_state.json").exists() else {}

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    action = "HOLD"
    reason = "unknown"
    actions = result.get("actions", [])
    if actions and isinstance(actions, list):
        first = actions[0]
        if isinstance(first, str):
            # Handles repr like "AgentAction(action='HOLD', reason='no_candidate', ...)"
            if "action='" in first:
                action = first.split("action='")[1].split("'")[0]
            if "reason='" in first:
                reason = first.split("reason='")[1].split("'")[0]
        else:
            action = str(first.get("action", "HOLD"))
            reason = str(first.get("reason", "unknown"))
    if not reason or reason == "unknown":
        reasons = result.get("rejection_reasons", [])
        if reasons:
            reason = str(reasons[0])

    equity = result.get("equity") if result else None
    if equity is None:
        equity = mcp.get("equity", state.get("last_equity", 0.0))
    halted = result.get("halted", state.get("halted", False)) if result else state.get("halted", False)

    lines = [
        f"*SPECTER-OPT Daily Update — {today}*",
        f"Mode: `{result.get('mode', 'paper') if result else 'paper'}`",
        f"Account: `{result.get('account_title', 'Moomoo x Qoder AI Paper Trading Agent Challenge') if result else 'Moomoo x Qoder AI Paper Trading Agent Challenge'}`",
        f"Equity: `${equity:,.2f}`",
        f"Positions: {mcp.get('position_count', 0)}",
    ]

    if mcp.get("position_count", 0) > 0:
        lines.append(
            f"Open P&L: `${mcp.get('position_profit', 0):,.2f}` "
            f"({mcp.get('position_profit_ratio', 0) * 100:.2f}%)"
        )

    lines.append(f"Open orders: {mcp.get('open_order_count', 0)}")
    lines.append(f"Halted: `{halted}`")
    if result:
        lines.append(f"Today's action: `{action}` (reason: `{reason}`)")
    lines.append(f"Total decisions logged: {len(decisions)}")

    if halted and state.get("halt_reason"):
        lines.append(f"*Halt reason:* {state['halt_reason']}")

    top = result.get("top_candidate") if result else None
    if top:
        lines.append(
            f"Top candidate: `{top.get('symbol')}` {top.get('right')} "
            f"strike={top.get('strike')} expiry={top.get('expiry')} "
            f"score={top.get('score', 0):.4f} edge={top.get('robust_edge', 0):.2f}"
        )

    mode = result.get("mode", "paper") if result else "paper"
    if mode == "paper":
        lines.append("_Paper trading is active. Pending intents, if any, are submitted via MCP._")
    else:
        lines.append("_Paper orders remain disabled until explicit user approval._")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Post daily SPECTER-OPT update to Slack")
    parser.add_argument("--env", default="data/.slack_webhook.env", help="Path to env file with SLACK_WEBHOOK_URL")
    parser.add_argument("--result", default="data/run_result_fresh.json", help="Path to run result JSON")
    parser.add_argument("--mcp-fallback", action="store_true", help="Ignore run result and build summary from MCP data")
    parser.add_argument("--dry-run", action="store_true", help="Print message instead of posting")
    args = parser.parse_args()

    summary = generate_summary(args.result, args.mcp_fallback)
    if args.dry_run:
        print(summary)
        return

    url = load_webhook(args.env)
    result = post_message(url, summary)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
