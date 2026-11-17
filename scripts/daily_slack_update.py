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


def generate_summary(result_path: str = "data/run_result_fresh.json") -> str:
    cfg_path = Path(result_path)
    if not cfg_path.exists():
        cfg_path = Path("data/run_result_20261117_b.json")
    if not cfg_path.exists():
        cfg_path = Path("data/run_result_20261117_a.json")

    result = load_json(cfg_path) if cfg_path.exists() else {}
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
    equity = result.get("equity", state.get("last_equity", 0.0))
    halted = result.get("halted", state.get("halted", False))

    lines = [
        f"*SPECTER-OPT Daily Update — {today}*",
        f"Mode: `{result.get('mode', 'shadow')}`",
        f"Account: `{result.get('account_title', 'unknown')}`",
        f"Equity: `${equity:,.2f}`",
        f"Halted: `{halted}`",
        f"Today's action: `{action}` (reason: `{reason}`)",
        f"Total decisions logged: {len(decisions)}",
    ]

    if halted and state.get("halt_reason"):
        lines.append(f"*Halt reason:* {state['halt_reason']}")

    top = result.get("top_candidate")
    if top:
        lines.append(
            f"Top candidate: `{top.get('symbol')}` {top.get('right')} "
            f"strike={top.get('strike')} expiry={top.get('expiry')} "
            f"score={top.get('score', 0):.4f} edge={top.get('robust_edge', 0):.2f}"
        )

    mode = result.get("mode", "shadow")
    if mode == "paper":
        lines.append("_Paper trading is active. Pending intents, if any, are submitted via MCP._")
    else:
        lines.append("_Paper orders remain disabled until explicit user approval._")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Post daily SPECTER-OPT update to Slack")
    parser.add_argument("--env", default="data/.slack_webhook.env", help="Path to env file with SLACK_WEBHOOK_URL")
    parser.add_argument("--result", default="data/run_result_fresh.json", help="Path to run result JSON")
    parser.add_argument("--dry-run", action="store_true", help="Print message instead of posting")
    args = parser.parse_args()

    summary = generate_summary(args.result)
    if args.dry_run:
        print(summary)
        return

    url = load_webhook(args.env)
    result = post_message(url, summary)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
