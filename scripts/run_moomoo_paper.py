#!/usr/bin/env python3
"""Run SPECTER-OPT against a Moomoo snapshot file in paper or shadow mode.

The snapshot JSON must contain keys:
  account: dict with account_id, account_title, market_id, equity, cash, buying_power, is_paper
  positions: list[dict]
  open_orders: list[dict]
  option_chains: dict[underlying -> list[dict]]
  underlying_quotes: dict[underlying -> dict]
  returns_cache: optional dict[underlying -> list[float]]
  earnings_dates: optional dict[underlying -> list["YYYY-MM-DD"]]

Example:
  python scripts/run_moomoo_paper.py --snapshot data/snapshot.json --mode shadow
"""

import argparse
import json
import os
import sys
from typing import Optional

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from specter_opt.agent import SpecterAgent
from specter_opt.broker import BrokerOrder, OrderIntent
from specter_opt.config import AgentConfig
from specter_opt.moomoo_broker import MoomooPaperBroker


def load_snapshot(path: str) -> dict:
    with open(path, "r") as f:
        return json.load(f)


PENDING_ORDERS_FILE = "data/pending_paper_orders.jsonl"


def build_broker(snapshot: dict, mode: str, assistant_submits: bool):
    def order_placer(intent: OrderIntent) -> BrokerOrder:
        if assistant_submits:
            # Persist intent for the assistant to submit via MCP sim_trade_input_order.
            os.makedirs(os.path.dirname(PENDING_ORDERS_FILE), exist_ok=True)
            with open(PENDING_ORDERS_FILE, "a") as f:
                f.write(
                    json.dumps(
                        {
                            "intent_id": intent.intent_id,
                            "symbol": intent.symbol,
                            "side": intent.side,
                            "quantity": intent.quantity,
                            "price": intent.price,
                            "order_type": intent.order_type,
                            "expected_premium": intent.expected_premium,
                            "reason": intent.reason,
                            "timestamp_utc": intent.timestamp_utc.isoformat() if intent.timestamp_utc else None,
                        },
                        default=str,
                    )
                    + "\n"
                )
            return BrokerOrder(
                order_id="PENDING_ASSISTANT_SUBMIT",
                intent_id=intent.intent_id,
                symbol=intent.symbol,
                side=intent.side,
                quantity=intent.quantity,
                price=intent.price,
                order_type=intent.order_type,
                status="PENDING_NEW",
            )
        # Offline-testable simulated acknowledgment.
        return BrokerOrder(
            order_id="SIMULATED",
            intent_id=intent.intent_id,
            symbol=intent.symbol,
            side=intent.side,
            quantity=intent.quantity,
            price=intent.price,
            order_type=intent.order_type,
            status="NEW",
        )

    return MoomooPaperBroker(
        account=snapshot["account"],
        positions=snapshot.get("positions", []),
        open_orders=snapshot.get("open_orders", []),
        option_chains=snapshot.get("option_chains", {}),
        underlying_quotes=snapshot.get("underlying_quotes", {}),
        order_placer=order_placer if mode == "paper" else None,
        order_canceller=None,
    )


def main():
    parser = argparse.ArgumentParser(description="Run SPECTER-OPT from Moomoo snapshot")
    parser.add_argument("--snapshot", required=True, help="Path to snapshot JSON")
    parser.add_argument("--mode", choices=["shadow", "paper"], default="shadow")
    parser.add_argument("--assistant-submits", action="store_true", help="In paper mode, write intents to pending file for assistant to submit via MCP")
    parser.add_argument("--out", default="data/run_result.json", help="Result output path")
    args = parser.parse_args()

    snapshot = load_snapshot(args.snapshot)
    config = AgentConfig(mode=args.mode)
    assistant_submits = args.assistant_submits or (args.mode == "paper")
    broker = build_broker(snapshot, args.mode, assistant_submits)

    returns_cache = None
    if "returns_cache" in snapshot:
        returns_cache = {
            k: np.array(v, dtype=float) for k, v in snapshot["returns_cache"].items()
        }

    agent = SpecterAgent(
        config,
        broker,
        earnings_dates=snapshot.get("earnings_dates", {}),
        universe=snapshot.get("universe"),
    )
    result = agent.run(returns_cache=returns_cache)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(result.__dict__, f, indent=2, default=str)
    print(json.dumps(result.__dict__, indent=2, default=str))


if __name__ == "__main__":
    main()
