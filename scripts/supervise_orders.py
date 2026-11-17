#!/usr/bin/env python3
"""Lightweight deterministic order/position/fill/risk supervision.

This script is designed to run frequently with minimal LLM involvement.
It expects current MCP responses to be provided as JSON files:
  --positions data/mcp_positions.json   (from sim_trade_position_list)
  --orders    data/mcp_orders.json      (from sim_trade_history_order_list)
  --cash      data/mcp_cash.json        (from sim_trade_cash_info)

It compares against the previous supervision snapshot, updates persisted
state (intents.jsonl, risk_state.json), and posts to Slack only when a
material event occurs (new fill, rejected order, expiring position, risk
halt, or MCP error).
"""

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from post_to_slack import load_webhook, post_message

INTENTS_FILE = "data/intents.jsonl"
RISK_STATE_FILE = "data/risk_state.json"
PREV_STATE_FILE = "data/supervision_state.json"


def load_json(path: str):
    with open(path, "r") as f:
        return json.load(f)


def load_jsonl(path: str):
    records = []
    if not Path(path).exists():
        return records
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


def save_jsonl(path: str, records):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r, default=str) + "\n")


def load_prev_state():
    if Path(PREV_STATE_FILE).exists():
        try:
            with open(PREV_STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"positions": [], "orders": [], "cash": {}, "events": []}


def save_prev_state(state):
    os.makedirs(os.path.dirname(PREV_STATE_FILE), exist_ok=True)
    with open(PREV_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def today_ny_date():
    try:
        import pytz
        ny = pytz.timezone("America/New_York")
        return datetime.now(ny).date()
    except Exception:
        return datetime.now(timezone.utc).date()


def update_intents_for_fills(orders):
    """Reconcile intents.jsonl with current order statuses."""
    if not Path(INTENTS_FILE).exists():
        return
    intents = load_jsonl(INTENTS_FILE)
    order_map = {o["order_id"]: o for o in orders if o.get("order_id")}
    updated = []
    for intent in intents:
        oid = intent.get("order_id")
        if oid and oid in order_map:
            o = order_map[oid]
            status_map = {
                1: "NEW",
                2: "SUBMITTED",
                3: "PARTIAL_FILLED",
                4: "FILLED",
                5: "CANCELLED",
                6: "REJECTED",
                7: "EXPIRED",
            }
            intent["status"] = status_map.get(o.get("status"), str(o.get("status")))
            intent["fill_qty"] = int(o.get("cum_qty", 0))
            intent["avg_fill_price"] = float(o.get("avg_fill_price") or 0) or None
            intent["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
        updated.append(intent)
    save_jsonl(INTENTS_FILE, updated)


def update_risk_state(cash_data, positions):
    """Update risk_state equity and check halt conditions."""
    state = {}
    if Path(RISK_STATE_FILE).exists():
        try:
            with open(RISK_STATE_FILE, "r") as f:
                state = json.load(f)
        except Exception:
            pass

    equity = float(cash_data.get("total_asset", cash_data.get("balance", 0)))
    state["last_equity"] = equity
    peak = state.get("peak_equity", equity) or equity
    if equity > peak:
        state["peak_equity"] = equity
    day_start = state.get("day_start_equity", equity) or equity

    daily_loss = 1.0 - equity / max(day_start, 1e-9)
    drawdown = 1.0 - equity / max(peak, 1e-9)

    if state.get("halted"):
        state["halt_reason"] = state.get("halt_reason", "manual")
    elif daily_loss >= 0.02:
        state["halted"] = True
        state["halt_reason"] = f"daily_loss_{daily_loss:.4f}"
    elif drawdown >= 0.05:
        state["halted"] = True
        state["halt_reason"] = f"peak_drawdown_{drawdown:.4f}"

    state["open_position_count"] = len(positions)
    os.makedirs(os.path.dirname(RISK_STATE_FILE), exist_ok=True)
    with open(RISK_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)

    return state


def detect_events(prev, current_orders, current_positions, cash_data, risk_state):
    events = []

    prev_order_ids = {o.get("order_id"): o for o in prev.get("orders", [])}
    for o in current_orders:
        oid = o.get("order_id")
        status = o.get("status")
        prev_o = prev_order_ids.get(oid)
        prev_status = prev_o.get("status") if prev_o else None
        if prev_status is None:
            events.append(f"New order {oid}: status {status}")
        elif status != prev_status:
            events.append(f"Order {oid} status changed: {prev_status} -> {status}")
        if status == 6 and prev_status != 6:
            events.append(f"Order {oid} REJECTED")
        if int(o.get("cum_qty", 0)) > 0 and (not prev_o or int(prev_o.get("cum_qty", 0)) < int(o.get("cum_qty", 0))):
            events.append(
                f"Fill on {oid}: cum_qty {o.get('cum_qty')} avg_fill_price {o.get('avg_fill_price')}"
            )

    prev_pos_keys = {(p.get("symbol"), p.get("code")) for p in prev.get("positions", [])}
    for p in current_positions:
        key = (p.get("symbol"), p.get("code"))
        if key not in prev_pos_keys:
            events.append(f"New position: {p.get('symbol')} qty={p.get('quantity')}")

    # Expiry check (simplified: if position has expiry_date within 1 day)
    ny_today = today_ny_date()
    for p in current_positions:
        expiry_str = p.get("expiry_date") or p.get("strike_time") or p.get("maturity_date")
        if expiry_str:
            try:
                expiry = datetime.strptime(expiry_str[:10], "%Y-%m-%d").date()
                delta = (expiry - ny_today).days
                if delta <= 1:
                    events.append(f"Expiring position {p.get('symbol')} expiry={expiry_str}")
            except Exception:
                pass

    if risk_state.get("halted") and not prev.get("risk_halted"):
        events.append(f"Risk halt triggered: {risk_state.get('halt_reason')}")

    equity = float(cash_data.get("total_asset", cash_data.get("balance", 0)))
    prev_equity = float(prev.get("cash", {}).get("total_asset", prev.get("cash", {}).get("balance", equity)))
    if abs(equity - prev_equity) > 0.01:
        events.append(f"Equity updated: ${prev_equity:,.2f} -> ${equity:,.2f}")

    return events


def post_slack(events, webhook_url):
    if not events:
        return
    if not webhook_url:
        print("No Slack webhook configured; events:", events)
        return
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    msg = "*SPECTER-OPT Supervision Alert — " + today + "*\n" + "\n".join(f"- {e}" for e in events)
    try:
        result = post_message(webhook_url, msg)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(f"Slack post failed: {e}")


def main():
    parser = argparse.ArgumentParser(description="Lightweight order/position supervision")
    parser.add_argument("--positions", default="data/mcp_positions.json", help="sim_trade_position_list JSON")
    parser.add_argument("--orders", default="data/mcp_orders.json", help="sim_trade_history_order_list JSON")
    parser.add_argument("--cash", default="data/mcp_cash.json", help="sim_trade_cash_info JSON")
    parser.add_argument("--env", default="data/.slack_webhook.env", help="Slack webhook env file")
    parser.add_argument("--dry-run", action="store_true", help="Print events instead of posting")
    args = parser.parse_args()

    current_positions = load_json(args.positions).get("data", {}).get("positions", [])
    current_orders = load_json(args.orders).get("data", {}).get("orders", [])
    cash_data = load_json(args.cash).get("data", {})

    prev = load_prev_state()

    update_intents_for_fills(current_orders)
    risk_state = update_risk_state(cash_data, current_positions)

    events = detect_events(prev, current_orders, current_positions, cash_data, risk_state)

    output = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "events": events,
        "position_count": len(current_positions),
        "open_order_count": len(current_orders),
        "equity": float(cash_data.get("total_asset", cash_data.get("balance", 0))),
        "halted": risk_state.get("halted", False),
    }
    print(json.dumps(output, indent=2, default=str))

    if args.dry_run:
        return

    webhook_url = None
    try:
        webhook_url = load_webhook(args.env)
    except Exception:
        pass

    post_slack(events, webhook_url)

    # Save current state for next run
    save_prev_state({
        "positions": current_positions,
        "orders": current_orders,
        "cash": cash_data,
        "risk_halted": risk_state.get("halted", False),
        "last_run_utc": datetime.now(timezone.utc).isoformat(),
    })


if __name__ == "__main__":
    main()
